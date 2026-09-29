"""Create a provisional employment review packet and article JSONL staging set."""
import csv
import datetime
import json
import sys
import uuid
from collections import Counter, defaultdict
from pathlib import Path

import pyarrow.parquet as pq

from audit_corpus import ROOT as RAW_ROOT, scope_reason, sha256
from corpus_stage import collect_dependency_ids, employment_reasons, is_employment_candidate, layout_anomalies, parse_articles

REVISION = RAW_ROOT.name
OUT = RAW_ROOT.parents[1] / "staging" / REVISION
AUDIT = RAW_ROOT.parents[1] / "audit" / REVISION


def activate_build(out, build, manifest):
    for name, info in manifest["outputs"].items():
        path = build / name
        if not path.exists() or path.stat().st_size != info["bytes"] or sha256(path) != info["sha256"]:
            raise ValueError(f"incomplete staging build: {name}")
    pointer_tmp = out / "active_staging.json.part"
    pointer_tmp.write_text(json.dumps({"dataset_revision": manifest["dataset_revision"], "build_dir": build.name, "manifest": "staging_manifest.json"}, indent=2), encoding="utf-8")
    pointer_tmp.replace(out / "active_staging.json")


def load_decisions():
    with (AUDIT / "document_decisions.csv").open(encoding="utf-8-sig", newline="") as stream:
        return {row["id"]: row for row in csv.DictReader(stream)}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    build = OUT / f"build-{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    build.mkdir()
    decisions = load_decisions()
    metadata = {row["id"]: row for row in pq.ParquetFile(RAW_ROOT / "metadata.parquet").iter_batches(batch_size=8192) for row in row.to_pylist()}
    seeds = {doc_id for doc_id, row in metadata.items() if scope_reason(row["pham_vi"]) == "central_exact" and is_employment_candidate(row) and decisions[doc_id]["primary_reason"] == "include_for_employment_review"}
    neighbors = defaultdict(set)
    dependency_edges = defaultdict(list)
    outgoing_edges, incoming_edges = [], []
    dangling = set()
    edge_count = 0
    for batch in pq.ParquetFile(RAW_ROOT / "relationships.parquet").iter_batches(batch_size=8192):
        for edge in batch.to_pylist():
            source, target = edge["doc_id"], edge["other_doc_id"]
            if source in seeds or target in seeds:
                edge_count += 1
                neighbors[source].add(target)
                neighbors[target].add(source)
                if source in seeds:
                    outgoing_edges.append((source, target))
                    dependency_edges[source].append({"source": source, "target": target, "relationship": edge["relationship"], "direction": "outgoing"})
                if target in seeds:
                    incoming_edges.append((target, source))
                    dependency_edges[target].append({"source": source, "target": target, "relationship": edge["relationship"], "direction": "incoming"})
                if source in seeds and target not in metadata:
                    dangling.add(target)
                if target in seeds and source not in metadata:
                    dangling.add(source)
    dependency_ids = (collect_dependency_ids(seeds, outgoing_edges) | collect_dependency_ids(seeds, incoming_edges)) - seeds
    review_ids = seeds | dependency_ids | dangling
    fields = ["id", "title", "so_ky_hieu", "loai_van_ban", "ngay_ban_hanh", "ngay_co_hieu_luc", "ngay_het_hieu_luc", "tinh_trang_hieu_luc", "pham_vi", "co_quan_ban_hanh", "nguon_thu_thap", "source_scope_reason", "audit_primary_reason", "stage_role", "searchable_candidate", "current_validity", "employment_scope", "content_state", "employment_reasons_json", "dependency_edge_count", "dependency_ids_json", "dependency_edges_json"]
    counts = Counter()
    packet_tmp = build / "owner_review_packet.csv.part"
    with packet_tmp.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for doc_id in sorted(review_ids):
            row = metadata.get(doc_id)
            audit = decisions.get(doc_id)
            if row is None:
                output = {field: "" for field in fields}
                output.update({"id": doc_id, "stage_role": "dangling_dependency", "searchable_candidate": "false", "current_validity": "unverified", "employment_scope": "unresolved_dependency"})
                counts["dangling_dependency"] += 1
            else:
                role = "employment_seed" if doc_id in seeds else "central_dependency_candidate" if scope_reason(row["pham_vi"]) == "central_exact" else "excluded_dependency"
                eligible = role in {"employment_seed", "central_dependency_candidate"} and audit["primary_reason"] == "include_for_employment_review" and audit["content_state"] == "present"
                output = {field: row.get(field, "") for field in fields if field in row}
                output.update({"source_scope_reason": scope_reason(row["pham_vi"]), "audit_primary_reason": audit["primary_reason"], "stage_role": role, "searchable_candidate": str(eligible).lower(), "current_validity": "unverified", "employment_scope": "provisional", "content_state": audit["content_state"], "employment_reasons_json": json.dumps(employment_reasons(row), ensure_ascii=False), "dependency_edge_count": len(dependency_edges[doc_id]), "dependency_ids_json": json.dumps(sorted(neighbors[doc_id]), ensure_ascii=False), "dependency_edges_json": json.dumps(dependency_edges[doc_id], ensure_ascii=False)})
                counts[role] += 1
                counts["eligible_search_candidate"] += eligible
            writer.writerow(output)
    packet_tmp.replace(build / "owner_review_packet.csv")

    priority_rows = []
    for doc_id in sorted(seeds)[:20]:
        row = metadata[doc_id]
        priority_rows.append({"id": doc_id, "title": row["title"], "so_ky_hieu": row["so_ky_hieu"], "stage_role": "employment_seed", "source_scope_reason": "central_exact", "source_locator": f"vbpl_id:{doc_id}@{REVISION}", "review_task": "Confirm the document contains provisions for ordinary adult private-sector probation, contracts, working time, or leave; identify exact Điều references and any special-category limits.", "pass_criteria": "Central scope, employment provision identified, exact source span recorded, and no unsupported validity conclusion.", "failure_action": "Quarantine from searchable release and retain the reason."})
    central_dependencies = sorted(doc_id for doc_id in dependency_ids if doc_id in metadata and scope_reason(metadata[doc_id]["pham_vi"]) == "central_exact")
    for doc_id in central_dependencies[:15]:
        row = metadata[doc_id]
        priority_rows.append({"id": doc_id, "title": row["title"], "so_ky_hieu": row["so_ky_hieu"], "stage_role": "central_dependency_candidate", "source_scope_reason": "central_exact", "source_locator": f"vbpl_id:{doc_id}@{REVISION}", "review_task": "Confirm which seed provision needs this dependency and whether the relationship direction/type supports interpretation.", "pass_criteria": "Central source, dependency is necessary for an in-scope answer, and relationship is understood.", "failure_action": "Keep as unresolved dependency; do not index automatically."})
    for doc_id in sorted(doc_id for doc_id in dependency_ids if doc_id in metadata and decisions[doc_id]["primary_reason"] != "include_for_employment_review")[:10]:
        row = metadata[doc_id]
        local = scope_reason(row["pham_vi"]) != "central_exact"
        priority_rows.append({"id": doc_id, "title": row["title"], "so_ky_hieu": row["so_ky_hieu"], "stage_role": "excluded_dependency" if local else "quarantined_dependency", "source_scope_reason": scope_reason(row["pham_vi"]), "source_locator": f"vbpl_id:{doc_id}@{REVISION}", "review_task": "Confirm the strict central-scope exclusion." if local else "Review the quarantine reason (duplicate, content, issuer, or validity signal) before any canonicalization.", "pass_criteria": "Local scope is confirmed excluded." if local else "Reason is confirmed and governing duplicate/version relationship is identified.", "failure_action": "Preserve the edge and keep this dependency excluded or quarantined."})
    for doc_id in sorted(dangling)[:5]:
        priority_rows.append({"id": doc_id, "title": "", "so_ky_hieu": "", "stage_role": "dangling_dependency", "source_scope_reason": "missing_metadata", "source_locator": f"vbpl_id:{doc_id}@{REVISION}", "review_task": "Check the official portal for this target ID and determine whether the missing target is needed for an in-scope provision.", "pass_criteria": "Target identity and relevance are confirmed from an authoritative source.", "failure_action": "Keep the edge unresolved and make no legal claim from it."})
    priority_tmp = build / "owner_review_priority.csv.part"
    with priority_tmp.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["id", "title", "so_ky_hieu", "stage_role", "source_scope_reason", "source_locator", "review_task", "pass_criteria", "failure_action"])
        writer.writeheader()
        writer.writerows(priority_rows)
    priority_tmp.replace(build / "owner_review_priority.csv")

    selected = {doc_id for doc_id in review_ids if decisions.get(doc_id, {}).get("primary_reason") == "include_for_employment_review" and decisions[doc_id]["content_state"] == "present"}
    attempted_documents = 0
    successful_article_segmentations = 0
    zero_article_documents = 0
    quarantined_layout_documents = 0
    articles = 0
    parse_ledger_rows = []
    content_rows = pq.ParquetFile(RAW_ROOT / "content.parquet").iter_batches(batch_size=128)
    articles_tmp = build / "articles.jsonl.part"
    with articles_tmp.open("w", encoding="utf-8") as stream:
        for batch in content_rows:
            for item in batch.to_pylist():
                if item["id"] not in selected:
                    continue
                attempted_documents += 1
                reasons = [item["reason"] for item in layout_anomalies(item["content_html"])]
                parsed_articles = parse_articles(item["id"], item["content_html"])
                if not parsed_articles:
                    reasons.append("zero_article")
                if any(article["source_start"] >= article["source_end"] or any(child["source_start"] >= child["source_end"] for child in article["children"]) for article in parsed_articles):
                    reasons.append("invalid_source_span")
                if reasons:
                    status = "quarantined_layout" if any(reason != "zero_article" for reason in reasons) else "zero_article"
                    if status == "zero_article":
                        zero_article_documents += 1
                    else:
                        quarantined_layout_documents += 1
                    parse_ledger_rows.append({"id": item["id"], "status": status, "article_count": len(parsed_articles), "reasons_json": json.dumps(sorted(set(reasons)), ensure_ascii=False)})
                    continue
                successful_article_segmentations += 1
                parse_ledger_rows.append({"id": item["id"], "status": "segmented", "article_count": len(parsed_articles), "reasons_json": "[]"})
                for article in parsed_articles:
                    # ASCII escaping keeps U+2028/U+2029 inside a JSONL record.
                    stream.write(json.dumps(article, ensure_ascii=True) + "\n")
                    articles += 1
    articles_tmp.replace(build / "articles.jsonl")
    ledger_tmp = build / "parse_ledger.csv.part"
    with ledger_tmp.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["id", "status", "article_count", "reasons_json"])
        writer.writeheader()
        writer.writerows(parse_ledger_rows)
    ledger_tmp.replace(build / "parse_ledger.csv")
    summary = {"dataset_revision": REVISION, "seeds": len(seeds), "dependency_edges_touching_seeds": edge_count, "review_ids": len(review_ids), "dangling_dependency_ids": len(dangling), "counts": dict(counts), "priority_review_rows": len(priority_rows), "attempted_documents": attempted_documents, "documents_with_successful_article_segmentation": successful_article_segmentations, "zero_article_documents": zero_article_documents, "quarantined_layout_documents": quarantined_layout_documents, "parse_ledger_rows": len(parse_ledger_rows), "parsed_documents": successful_article_segmentations, "article_versions": articles, "article_parsing": "provisional; source spans are raw HTML offsets; validity and employment relevance remain unverified", "searchable_release": False, "max_chars": 6000}
    summary_tmp = build / "staging_summary.json.part"
    summary_tmp.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    summary_tmp.replace(build / "staging_summary.json")
    output_names = ("owner_review_packet.csv", "owner_review_priority.csv", "parse_ledger.csv", "articles.jsonl", "staging_summary.json")
    manifest = {"dataset_revision": REVISION, "build_dir": build.name, "source_manifest_sha256": sha256(RAW_ROOT / "manifest.json"), "audit_decisions_sha256": sha256(AUDIT / "document_decisions.csv"), "audit_summary_sha256": sha256(AUDIT / "summary.json"), "stage_script_sha256": sha256(Path(__file__)), "parser_script_sha256": sha256(Path(__file__).with_name("corpus_stage.py")), "config": {"max_chars": 6000, "seed_policy": "central_exact + audit include_for_employment_review + explicit employment title terms", "dependency_policy": "one-hop outgoing and incoming edges touching seeds; relationship direction and type preserved"}, "outputs": {name: {"sha256": sha256(build / name), "bytes": (build / name).stat().st_size} for name in output_names}}
    (build / "staging_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    activate_build(OUT, build, manifest)
    print(json.dumps({"seeds": len(seeds), "review_ids": len(review_ids), "dangling": len(dangling), "attempted_documents": attempted_documents, "documents_with_successful_article_segmentation": successful_article_segmentations, "zero_article_documents": zero_article_documents, "quarantined_layout_documents": quarantined_layout_documents, "parse_ledger_rows": len(parse_ledger_rows), "article_versions": articles, "counts": counts}, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
