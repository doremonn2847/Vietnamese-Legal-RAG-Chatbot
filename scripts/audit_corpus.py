"""Pre-article audit. Never emits a searchable release or infers legal validity."""
import collections
import csv
import datetime
import hashlib
import html
import json
from pathlib import Path
import re
import unicodedata

import pyarrow
import pyarrow.parquet as pq

from download_snapshot import ROOT, REVISION, sha256

OUT = ROOT.parents[1] / "audit" / REVISION
LOCAL_ISSUER = re.compile(r"\b(?:ubnd|hđnd|tỉnh|huyện|quận|phường|thành phố|thành ủy|thành uỷ|tỉnh ủy|tỉnh uỷ)\b|(?:uỷ|ủy) ban nhân dân|hội đồng nhân dân|(?:^|, )sở |\btp\.|ban quản lý khu")
CENTRAL_ISSUER = re.compile(r"^(?:bộ |chính phủ|thủ tướng|chủ tịch (?:nước|chính phủ|hội đồng|quốc hội)|quốc hội|uỷ ban |ủy ban |tổng cục |tổng liên đoàn |tổng công đoàn |ngân hàng |văn phòng |viện |tòa án |toà án |hội đồng |ban (?:bí thư|chấp hành trung ương|thường trực quốc hội|tổ chức|tài chính - quản trị trung ương|vật giá|tôn giáo|việt kiều)|thanh tra |kiểm toán |hội |trung ương |the |đoàn |bảo hiểm xã hội việt nam|cục |liên bộ |phủ thủ tướng|trọng tài kinh tế nhà nước|cộng hoà xã hội chủ nghĩa việt nam)")
LOCAL_SCOPE = re.compile(r"^(?:địa phương|tỉnh(?:\s|$)|huyện |quận |xã |phường |thị xã |thành phố |ubnd tỉnh )")


def norm(value):
    return " ".join(unicodedata.normalize("NFC", value or "").casefold().split())


def scope_reason(value):
    value = norm(value)
    if value == "trung ương":
        return "central_exact"
    if LOCAL_SCOPE.search(value) or value in {"tuyên quang", "lâm đồng"}:
        return "exclude_local_scope"
    return "quarantine_missing_scope" if not value else "quarantine_unrecognized_scope"


def issuer_signal(value):
    value = norm(html.unescape(value or ""))
    if LOCAL_ISSUER.search(value):
        return "local_issuer_signal"
    if not value or "chưa xác định" in value:
        return "missing_or_unknown_issuer"
    if CENTRAL_ISSUER.search(value):
        return "central_issuer_signal"
    return "unrecognized_issuer"


def text_fingerprint(value):
    # ponytail: markup stripping is a duplicate/empty-text heuristic, replace with
    # source-specific DOM extraction before creating any quotable article spans.
    value = re.sub(r"<!--.*?-->|<(head|script|style|title)\b[^>]*>.*?</\1\s*>", " ", value, flags=re.S | re.I)
    value = re.sub(r"<[^>]*>", " ", value)
    return " ".join(unicodedata.normalize("NFC", html.unescape(value)).split())


def expiry_state(row):
    return "unknown_expiry" if not norm(row.get("ngay_het_hieu_luc")) else "reported_expiry_unverified"


def write_csv(name, fields, rows):
    with (OUT / name).open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def duplicate_groups(groups):
    return {key: values for key, values in groups.items() if len(values) > 1}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["revision"] == REVISION
    for file in manifest["files"]:
        path = ROOT / file["file"]
        assert path.stat().st_size == file["bytes"] and sha256(path) == file["sha256"], path
    rows = pq.read_table(ROOT / "metadata.parquet").to_pylist()
    assert all(isinstance(row["id"], str) and row["id"].strip() for row in rows)
    raw_scopes = collections.Counter(row["pham_vi"] for row in rows)
    scope_inventory = [{"raw_value_json": json.dumps(value, ensure_ascii=False), "normalized_value": norm(value), "count": count, "scope_reason": scope_reason(value)} for value, count in sorted(raw_scopes.items(), key=lambda item: (-item[1], str(item[0])))]
    write_csv("pham_vi_inventory.csv", list(scope_inventory[0]), scope_inventory)
    print("Scope inventory written before filtering:", len(rows), "rows;", len(raw_scopes), "raw values", flush=True)

    id_counts = collections.Counter(row["id"] for row in rows)
    by_id = {row["id"]: row for row in rows}
    identities = collections.defaultdict(list)
    exact_metadata = collections.defaultdict(list)
    issuers = collections.Counter()
    for row in rows:
        key = tuple(norm(row[field]) for field in ("so_ky_hieu", "co_quan_ban_hanh", "ngay_ban_hanh"))
        if all(key):
            identities[key].append(row["id"])
        exact_metadata[json.dumps({k: v for k, v in row.items() if k != "id"}, sort_keys=True, ensure_ascii=False)].append(row["id"])
        issuers[(row["co_quan_ban_hanh"], row["pham_vi"], issuer_signal(row["co_quan_ban_hanh"]))] += 1
    write_csv("issuer_inventory.csv", ["issuer", "pham_vi", "signal", "count"], ({"issuer": k[0], "pham_vi": k[1], "signal": k[2], "count": v} for k, v in sorted(issuers.items(), key=lambda item: (-item[1], str(item[0])))))

    content_counts = collections.Counter()
    content_info = {}
    raw_groups, text_groups = collections.defaultdict(list), collections.defaultdict(list)
    for batch in pq.ParquetFile(ROOT / "content.parquet").iter_batches(batch_size=256):
        for item in batch.to_pylist():
            doc_id, body = item["id"], item["content_html"]
            assert isinstance(doc_id, str) and doc_id.strip()
            content_counts[doc_id] += 1
            text = text_fingerprint(body or "")
            raw_hash = hashlib.sha256((body or "").encode()).hexdigest()
            text_hash = hashlib.sha256(text.encode()).hexdigest() if text else ""
            state = "blank_html" if not (body or "").strip() else "no_visible_text_heuristic" if not text else "present"
            content_info[doc_id] = {"content_state": state, "raw_sha256": raw_hash, "text_sha256": text_hash, "visible_characters": len(text)}
            if state == "present":
                raw_groups[raw_hash].append(doc_id)
                text_groups[text_hash].append(doc_id)
        if sum(content_counts.values()) // 20000 != (sum(content_counts.values()) - batch.num_rows) // 20000:
            print("Content audited:", sum(content_counts.values()), flush=True)

    groups = {
        "metadata_id": {k: [k] * v for k, v in id_counts.items() if v > 1},
        "content_id": {k: [k] * v for k, v in content_counts.items() if v > 1},
        "exact_metadata_except_id": duplicate_groups(exact_metadata),
        "bibliographic_identity": duplicate_groups(identities),
        "exact_html": duplicate_groups(raw_groups),
        "normalized_text_candidate": duplicate_groups(text_groups),
    }
    duplicate_flags = collections.defaultdict(set)
    duplicate_ledger = []
    for kind, mapping in groups.items():
        for key, members in mapping.items():
            group_id = hashlib.sha256(json.dumps(key, ensure_ascii=False).encode()).hexdigest()
            duplicate_ledger.append({"kind": kind, "group_id": group_id, "record_count": len(members), "ids_json": json.dumps(sorted(members), ensure_ascii=False)})
            for doc_id in members:
                duplicate_flags[doc_id].add(kind)
    write_csv("duplicate_groups.csv", ["kind", "group_id", "record_count", "ids_json"], duplicate_ledger)

    decisions, audits = [], {}
    issues = collections.Counter()
    for index, row in enumerate(rows):
        doc_id = row["id"]
        scope = scope_reason(row["pham_vi"])
        issuer = issuer_signal(row["co_quan_ban_hanh"])
        flags = []
        if scope == "central_exact" and issuer == "local_issuer_signal":
            flags.append("central_scope_local_issuer_conflict")
        if scope == "exclude_local_scope" and issuer == "central_issuer_signal":
            flags.append("local_scope_central_issuer_suspected_conflict")
        if issuer in {"missing_or_unknown_issuer", "unrecognized_issuer"}:
            flags.append(issuer)
        info = content_info.get(doc_id, {"content_state": "missing_content_row", "raw_sha256": "", "text_sha256": "", "visible_characters": 0})
        if info["content_state"] != "present":
            flags.append(info["content_state"])
        flags.extend("duplicate_" + kind for kind in sorted(duplicate_flags[doc_id]))
        # Scope is never promoted based on issuer guesses; retain every reason.
        if scope != "central_exact":
            primary = scope
        elif flags:
            primary = "quarantine_" + flags[0]
        else:
            primary = "include_for_employment_review"
        issues.update(flags)
        audit = {"row_index": index, "id": doc_id, "title": row["title"], "so_ky_hieu": row["so_ky_hieu"], "pham_vi_raw": row["pham_vi"], "scope_reason": scope, "issuer": row["co_quan_ban_hanh"], "issuer_signal": issuer, **info, "primary_reason": primary, "all_flags_json": json.dumps(flags), "expiry_state": expiry_state(row), "reported_expiry": row["ngay_het_hieu_luc"], "reported_status": row["tinh_trang_hieu_luc"], "current_validity": "unverified", "employment_scope": "not_yet_reviewed", "searchable": False}
        decisions.append(audit)
        audits[doc_id] = audit
    write_csv("document_decisions.csv", list(decisions[0]), decisions)
    write_csv("issuer_conflicts.csv", list(decisions[0]), (x for x in decisions if "issuer_conflict" in x["all_flags_json"] or "issuer_suspected_conflict" in x["all_flags_json"]))
    write_csv("missing_content.csv", list(decisions[0]), (x for x in decisions if x["content_state"] != "present"))
    write_csv("orphan_content.csv", ["id", "count"], ({"id": k, "count": v} for k, v in content_counts.items() if k not in by_id))

    edge_counts, edge_types, target_states = collections.Counter(), collections.Counter(), collections.Counter()
    absent_sources, absent_targets = set(), set()
    central_absent_targets, included_absent_targets = set(), set()
    edge_metrics = collections.Counter()

    def endpoint(doc_id):
        if doc_id not in audits:
            return "missing_metadata"
        return audits[doc_id]["primary_reason"]

    with (OUT / "relationship_issues.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["doc_id", "other_doc_id", "relationship", "source_state", "target_state", "flags_json"])
        writer.writeheader()
        for batch in pq.ParquetFile(ROOT / "relationships.parquet").iter_batches(batch_size=8192):
            for edge in batch.to_pylist():
                source, target, label = edge["doc_id"], edge["other_doc_id"], edge["relationship"]
                assert isinstance(source, str) and isinstance(target, str)
                edge_counts[(source, target, label)] += 1
                edge_types[label] += 1
                edge_metrics["rows"] += 1
                source_state, target_state = endpoint(source), endpoint(target)
                flags = []
                if source not in by_id:
                    absent_sources.add(source)
                    flags.append("source_missing_metadata")
                if target not in by_id:
                    absent_targets.add(target)
                    flags.append("target_missing_metadata")
                if source == target:
                    flags.append("self_edge")
                if not norm(label):
                    flags.append("missing_relationship_label")
                central_source = source in audits and audits[source]["scope_reason"] == "central_exact"
                included_source = source_state == "include_for_employment_review"
                if central_source:
                    edge_metrics["central_source_edges"] += 1
                    target_states[target_state] += 1
                    if target not in by_id:
                        central_absent_targets.add(target)
                if included_source:
                    edge_metrics["included_source_edges"] += 1
                    if target not in by_id:
                        included_absent_targets.add(target)
                    if target_state != "include_for_employment_review":
                        flags.append("included_source_target_unavailable_after_audit")
                if central_source and target_state != "include_for_employment_review":
                    flags.append("central_source_target_unavailable_after_audit")
                edge_metrics.update(flags)
                if flags:
                    writer.writerow({**edge, "source_state": source_state, "target_state": target_state, "flags_json": json.dumps(flags)})
    duplicate_edges = [{"doc_id": k[0], "other_doc_id": k[1], "relationship": k[2], "count": v} for k, v in edge_counts.items() if v > 1]
    write_csv("duplicate_relationships.csv", ["doc_id", "other_doc_id", "relationship", "count"], duplicate_edges)
    summary = {
        "dataset": manifest["dataset"], "revision": REVISION,
        "generated_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "metadata_rows": len(rows), "metadata_unique_ids": len(id_counts),
        "content_rows": sum(content_counts.values()), "content_unique_ids": len(content_counts),
        "scope_raw_value_count": len(raw_scopes), "scope_normalized_value_count": len({norm(x) for x in raw_scopes}),
        "scope_counts": dict(collections.Counter(scope_reason(x["pham_vi"]) for x in rows)),
        "primary_reasons": dict(collections.Counter(x["primary_reason"] for x in decisions)),
        "central_primary_reasons": dict(collections.Counter(x["primary_reason"] for x in decisions if x["scope_reason"] == "central_exact")),
        "overlapping_issue_counts": dict(issues),
        "content_states_all": dict(collections.Counter(x["content_state"] for x in decisions)),
        "content_states_central": dict(collections.Counter(x["content_state"] for x in decisions if x["scope_reason"] == "central_exact")),
        "orphan_content_ids": len(set(content_counts) - set(by_id)),
        "duplicates": {kind: {"groups": len(mapping), "participating_rows": sum(map(len, mapping.values())), "distinct_ids": len({i for members in mapping.values() for i in members}), "excess_rows_within_groups": sum(len(members) - 1 for members in mapping.values())} for kind, mapping in groups.items()},
        "relationship_metrics": dict(edge_metrics), "relationship_types": dict(edge_types),
        "relationship_duplicate_groups": len(duplicate_edges), "relationship_duplicate_excess_rows": sum(x["count"] - 1 for x in duplicate_edges),
        "missing_source_distinct_ids": len(absent_sources), "missing_target_distinct_ids": len(absent_targets),
        "central_source_missing_target_distinct_ids": len(central_absent_targets),
        "included_source_missing_target_distinct_ids": len(included_absent_targets),
        "central_source_target_states": dict(target_states),
        "blank_expiry_all": sum(expiry_state(x) == "unknown_expiry" for x in rows),
        "blank_expiry_central": sum(expiry_state(x) == "unknown_expiry" for x in rows if scope_reason(x["pham_vi"]) == "central_exact"),
        "blank_expiry_by_reported_status": dict(collections.Counter(x["tinh_trang_hieu_luc"] for x in rows if expiry_state(x) == "unknown_expiry")),
        "searchable_documents": 0, "article_parsing_performed": False, "embedding_performed": False,
        "employment_scope": "Ordinary adult private-sector probation, contracts, working time and leave; excludes disputes, insurance, public employment and special categories. Relevant central interpretive dependencies need review. No domain selection performed by this audit.",
        "current_validity_policy": "Unverified for every record. Blank expiry is unknown_expiry, never proof of current validity. Reported dates and statuses are preserved without legal verification.",
    }
    assert sum(summary["scope_counts"].values()) == len(rows)
    assert sum(summary["primary_reasons"].values()) == len(rows)
    assert sum(summary["central_primary_reasons"].values()) == summary["scope_counts"]["central_exact"]
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    outputs = [{"file": file.name, "sha256": sha256(file), "bytes": file.stat().st_size} for file in sorted(OUT.glob("*")) if file.is_file() and file.name != "audit_manifest.json"]
    (OUT / "audit_manifest.json").write_text(json.dumps({"source_manifest": manifest, "audit_script_sha256": sha256(Path(__file__)), "python": __import__("sys").version, "pyarrow": pyarrow.__version__, "outputs": outputs}, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=True, indent=2), flush=True)


if __name__ == "__main__":
    main()
