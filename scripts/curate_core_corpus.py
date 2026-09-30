"""Build an inactive, reproducible core-employment corpus from the pinned snapshot."""
import argparse
import csv
import hashlib
import html
import json
import re
from collections import Counter
from pathlib import Path

import pyarrow.dataset as ds

from audit_corpus import REVISION, ROOT as RAW_ROOT, scope_reason, sha256
from corpus_stage import _segments


CORE_IDS = ("139264", "152668", "146696")
LABOR_CODE_PAIR = ("139264", "vbpqta_11135")
TOPIC_TERMS = {
    "probation": ("thử việc",),
    "contracts": ("hợp đồng lao động", "hợp đồng thử việc"),
    "working_time": ("thời giờ làm việc", "thời giờ nghỉ ngơi", "làm thêm giờ"),
    "leave": ("nghỉ hằng năm", "nghỉ hàng năm", "nghỉ lễ", "nghỉ phép", "ngày nghỉ hằng năm"),
}
DEPENDENCY_ALLOWLIST = {
    "139264": frozenset({"Điều 2", "Điều 3"}),
    "152668": frozenset({"Điều 2"}),
    "146696": frozenset({"Điều 1"}),
}
AMENDMENT_RELATION_TYPES = frozenset({
    "Sửa đổi, bổ sung", "Văn bản được sửa đổi", "Văn bản bổ sung", "Hợp nhất",
    "Thay thế", "Bãi bỏ", "Văn bản hết hiệu lực", "Văn bản quy định hết hiệu lực",
    "Văn bản bị hết hiệu lực 1 phần", "Văn bản quy định hết hiệu lực 1 phần",
})


def classify_topic_candidates(canonical_text):
    """Return topic labels matched in an extracted article heading."""
    heading = " ".join((canonical_text or "").split()).casefold()
    return [topic for topic, terms in TOPIC_TERMS.items() if any(term in heading for term in terms)]


def is_core_retrieval_candidate(document_id, article):
    return bool(article.get("topic_candidates")) or article.get("label") in DEPENDENCY_ALLOWLIST.get(str(document_id), ())


def audit_amendment_boundary(relationships, core_ids):
    core_ids = set(core_ids)
    rows = []
    for edge in relationships:
        source, target, kind = edge.get("doc_id"), edge.get("other_doc_id"), edge.get("relationship")
        if kind not in AMENDMENT_RELATION_TYPES or not ({source, target} & core_ids):
            continue
        related = target if source in core_ids else source
        rows.append({"source": source, "target": target, "relationship": kind,
                     "core_document_id": source if source in core_ids else target,
                     "related_document_id": related,
                     "disposition": "quarantined_outside_core_corpus"})
    return sorted(rows, key=lambda row: (row["core_document_id"], row["source"], row["target"], row["relationship"]))


def _content_marker(value, marker):
    text = re.sub(r"<[^>]*>", " ", value or "")
    return marker.casefold() in " ".join(html.unescape(text).split()).casefold()


def _duplicate_group_matches(groups, pair):
    expected = set(pair)
    for group in groups:
        if group.get("kind") == "bibliographic_identity" and set(json.loads(group["ids_json"])) == expected:
            return True
    return False


def _require_central(doc_id, metadata, content, audit, *, duplicate=False):
    if doc_id not in metadata or doc_id not in content or doc_id not in audit:
        raise ValueError(f"missing source/audit record for {doc_id}")
    row, decision = metadata[doc_id], audit[doc_id]
    if scope_reason(row.get("pham_vi")) != "central_exact" or decision.get("scope_reason") != "central_exact":
        raise ValueError(f"central-only filter rejected {doc_id}")
    if decision.get("content_state") != "present" or not int(decision.get("visible_characters") or 0):
        raise ValueError(f"content quality gate rejected {doc_id}")
    if decision.get("issuer_signal") != "central_issuer_signal":
        raise ValueError(f"issuer conflict gate rejected {doc_id}")
    flags = set(json.loads(decision.get("all_flags_json") or "[]"))
    allowed = {"duplicate_bibliographic_identity"} if duplicate else set()
    if flags - allowed:
        raise ValueError(f"unresolved audit flags for {doc_id}: {sorted(flags - allowed)}")
    if duplicate:
        if decision.get("primary_reason") != "quarantine_duplicate_bibliographic_identity":
            raise ValueError(f"unexpected duplicate disposition for {doc_id}")
    elif decision.get("primary_reason") != "include_for_employment_review":
        raise ValueError(f"audit disposition rejected {doc_id}: {decision.get('primary_reason')}")


def select_core_records(metadata, content, audit, duplicate_groups):
    """Select the three named core acts and resolve only the known translation pair."""
    pair = set(LABOR_CODE_PAIR)
    if not _duplicate_group_matches(duplicate_groups, LABOR_CODE_PAIR):
        raise ValueError("expected Labor Code bibliographic-identity group is missing or changed")
    for doc_id in CORE_IDS:
        _require_central(doc_id, metadata, content, audit, duplicate=(doc_id == "139264"))
    _require_central("vbpqta_11135", metadata, content, audit, duplicate=True)

    vietnamese, translation = metadata["139264"], metadata["vbpqta_11135"]
    identity = ("so_ky_hieu", "co_quan_ban_hanh", "ngay_ban_hanh")
    if any(vietnamese.get(key) != translation.get(key) for key in identity):
        raise ValueError("Labor Code duplicate identity fields disagree")
    if vietnamese.get("loai_van_ban") != "Bộ luật" or translation.get("loai_van_ban") != "Bản dịch văn bản":
        raise ValueError("Labor Code duplicate types do not identify original and translation")
    if not (_content_marker(content["139264"], "QUỐC HỘI") and _content_marker(content["139264"], "Bộ luật Lao động")):
        raise ValueError("Vietnamese Labor Code original content markers do not match")
    if not (_content_marker(content["vbpqta_11135"], "LABOR CODE") and _content_marker(content["vbpqta_11135"], "The National Assembly promulgates")):
        raise ValueError("Labor Code translation content markers do not match")
    if audit["139264"].get("reported_status") == audit["vbpqta_11135"].get("reported_status"):
        raise ValueError("expected conflicting duplicate validity statuses were not present")

    docs = []
    for doc_id in CORE_IDS:
        row, decision, raw = metadata[doc_id], audit[doc_id], content[doc_id]
        docs.append({
            "id": doc_id,
            "title": row["title"],
            "so_ky_hieu": row["so_ky_hieu"],
            "issuer": row["co_quan_ban_hanh"],
            "document_type": row["loai_van_ban"],
            "pham_vi": row["pham_vi"],
            "issue_date": row.get("ngay_ban_hanh"),
            "effective_date": row.get("ngay_co_hieu_luc"),
            "reported_expiry_date": row.get("ngay_het_hieu_luc"),
            "source_collection": row.get("nguon_thu_thap"),
            "reported_status": decision.get("reported_status"),
            "reported_status_conflict": doc_id == "139264",
            "expiry_state": decision.get("expiry_state"),
            "current_validity": "unverified",
            "amendment_state": "not_verified; corpus record is not a consolidated official text",
            "retrieval_index_candidate": True,
            "answer_evidence_enabled": False,
            "corpus_disposition": "retrieval_only_temporal_uncertainty" if doc_id == "139264" else "prototype_candidate_unverified",
            "source_dataset_revision": REVISION,
            "source_dataset_file": "data/content.parquet",
            "source_dataset_url": f"https://huggingface.co/datasets/th1nhng0/vietnamese-legal-documents/resolve/{REVISION}/data/content.parquet",
            "metadata_dataset_file": "data/metadata.parquet",
            "metadata_dataset_url": f"https://huggingface.co/datasets/th1nhng0/vietnamese-legal-documents/resolve/{REVISION}/data/metadata.parquet",
            "content_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
            "content_html": raw,
        })
    duplicate = [{
        "bibliographic_identity": vietnamese["so_ky_hieu"],
        "selected_id": "139264",
        "selected_language_role": "Vietnamese original",
        "selected_content_sha256": hashlib.sha256(content["139264"].encode("utf-8")).hexdigest(),
        "suppressed_id": "vbpqta_11135",
        "suppressed_language_role": "English translation/alternate record",
        "suppressed_content_sha256": hashlib.sha256(content["vbpqta_11135"].encode("utf-8")).hexdigest(),
        "selection_reason": "same number/issuer/issue date; original Bộ luật record preferred over Bản dịch văn bản",
        "selected_document_type": vietnamese["loai_van_ban"],
        "selected_issue_date": vietnamese.get("ngay_ban_hanh"),
        "selected_effective_date": vietnamese.get("ngay_co_hieu_luc"),
        "selected_reported_expiry_date": vietnamese.get("ngay_het_hieu_luc"),
        "selected_reported_status": audit["139264"].get("reported_status"),
        "suppressed_document_type": translation["loai_van_ban"],
        "suppressed_issue_date": translation.get("ngay_ban_hanh"),
        "suppressed_effective_date": translation.get("ngay_co_hieu_luc"),
        "suppressed_reported_expiry_date": translation.get("ngay_het_hieu_luc"),
        "suppressed_reported_status": audit["vbpqta_11135"].get("reported_status"),
        "reported_status_conflict": "true",
        "content_merged": "false",
        "retrieval_disposition": "translation suppressed; selected original may be indexed for retrieval but neither record is answer evidence until validity/version conflict is resolved",
    }]
    return docs, duplicate


def _read_audit(path, wanted):
    rows = {}
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            if row["id"] in wanted:
                if row["id"] in rows:
                    raise ValueError(f"duplicate audit id: {row['id']}")
                rows[row["id"]] = row
    return rows


def _read_parquet(path, wanted):
    dataset = ds.dataset(path, format="parquet")
    rows = dataset.to_table(filter=ds.field("id").isin(sorted(wanted))).to_pylist()
    result = {row["id"]: row for row in rows}
    if len(result) != len(rows):
        raise ValueError(f"duplicate ids in {path}")
    return result


def _read_amendment_edges(path, wanted):
    rows = []
    for batch in ds.dataset(path, format="parquet").to_batches(batch_size=8192):
        for edge in batch.to_pylist():
            if edge.get("doc_id") in wanted or edge.get("other_doc_id") in wanted:
                rows.append(edge)
    return rows


def _write_jsonl(path, rows):
    partial = path.with_suffix(path.suffix + ".part")
    with partial.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    partial.replace(path)


def load_staged_articles(stage_dir, source_content_hashes):
    stage_dir = Path(stage_dir)
    manifest_path = stage_dir / "core_article_stage_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source_manifest = RAW_ROOT / "manifest.json"
    article_info = manifest.get("outputs", {}).get("core_articles.jsonl", {})
    articles_path = stage_dir / "core_articles.jsonl"
    if manifest.get("dataset_revision") != REVISION or manifest.get("source_manifest_sha256") != sha256(source_manifest) or manifest.get("content_sha256") != source_content_hashes or not articles_path.is_file() or sha256(articles_path) != article_info.get("sha256"):
        raise ValueError("staged article parses do not match the pinned central corpus inputs")
    rows = [json.loads(line) for line in articles_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(rows) != manifest.get("article_count"):
        raise ValueError("staged article count does not match its manifest")
    grouped = {doc_id: [] for doc_id in source_content_hashes}
    for row in rows:
        doc_id = row.get("document_id")
        if doc_id not in grouped or row.get("source_content_sha256") != source_content_hashes[doc_id] or not isinstance(row.get("article"), dict):
            raise ValueError("staged article record is outside the pinned core sources")
        grouped[doc_id].append(row["article"])
    if any(not grouped[doc_id] for doc_id in grouped):
        raise ValueError("staged article parses are missing a selected core document")
    return grouped, sha256(manifest_path)


def build(output):
    audit_root = RAW_ROOT.parents[1] / "audit" / REVISION
    wanted = set(CORE_IDS) | set(LABOR_CODE_PAIR)
    metadata = _read_parquet(RAW_ROOT / "metadata.parquet", wanted)
    contents = {key: row["content_html"] for key, row in _read_parquet(RAW_ROOT / "content.parquet", wanted).items()}
    audit = _read_audit(audit_root / "document_decisions.csv", wanted)
    with (audit_root / "duplicate_groups.csv").open(encoding="utf-8-sig", newline="") as stream:
        duplicate_groups = list(csv.DictReader(stream))
    documents, duplicate_ledger = select_core_records(metadata, contents, audit, duplicate_groups)
    stage_dir = RAW_ROOT.parents[1] / "staging" / REVISION / "core-employment-portfolio-v1"
    staged_articles, stage_manifest_sha = load_staged_articles(
        stage_dir, {doc_id: hashlib.sha256(contents[doc_id].encode("utf-8")).hexdigest() for doc_id in CORE_IDS})
    relationships_path = RAW_ROOT / "relationships.parquet"
    amendment_boundary = audit_amendment_boundary(_read_amendment_edges(relationships_path, set(CORE_IDS)), CORE_IDS)
    related_by_core = {}
    for edge in amendment_boundary:
        related_by_core.setdefault(edge["core_document_id"], set()).add(edge["related_document_id"])
    for document in documents:
        document["quarantined_related_document_ids"] = sorted(related_by_core.get(document["id"], set()) - set(CORE_IDS))
        document["amendment_state"] = "base_snapshot_only; noncore amendment/version records quarantined; not consolidated"

    articles = []
    article_candidate_counts = {}
    for document in documents:
        parsed = staged_articles[document["id"]]
        if not parsed:
            raise ValueError(f"article parser produced no articles for {document['id']}")
        article_candidate_counts[document["id"]] = {topic: [] for topic in TOPIC_TERMS}
        for article in parsed:
            if document["content_html"][article["source_start"]:article["source_end"]] != article["source_html"]:
                raise ValueError(f"article span mismatch for {document['id']}:{article['label']}")
            heading_blocks = _segments(article["source_html"])
            heading = heading_blocks[0][2] if heading_blocks else article["canonical_text"]
            candidates = classify_topic_candidates(heading)
            retrieval_candidate = is_core_retrieval_candidate(document["id"], {"label": article["label"], "topic_candidates": candidates})
            for topic in candidates:
                if article["label"] not in article_candidate_counts[document["id"]][topic]:
                    article_candidate_counts[document["id"]][topic].append(article["label"])
            article["document_metadata"] = {key: document[key] for key in ("title", "so_ky_hieu", "issuer", "pham_vi", "issue_date", "effective_date", "reported_expiry_date", "reported_status", "reported_status_conflict", "expiry_state", "current_validity", "amendment_state", "quarantined_related_document_ids", "corpus_disposition", "retrieval_index_candidate", "answer_evidence_enabled", "source_dataset_revision", "source_dataset_url", "content_sha256")}
            article["document_metadata"]["retrieval_index_candidate"] = retrieval_candidate
            article["index_disposition"] = "in_scope_topic" if candidates else ("explicit_dependency" if retrieval_candidate else "out_of_scope")
            article["topic_candidates"] = candidates
            article["validity"] = "unverified"
            articles.append(article)

    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    _write_jsonl(output / "documents.jsonl", documents)
    _write_jsonl(output / "articles.jsonl", articles)
    duplicate_path = output / "duplicate_ledger.csv"
    partial = duplicate_path.with_suffix(".csv.part")
    with partial.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(duplicate_ledger[0]))
        writer.writeheader(); writer.writerows(duplicate_ledger)
    partial.replace(duplicate_path)

    source_manifest_path = RAW_ROOT / "manifest.json"
    source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    audit_manifest_path = audit_root / "audit_manifest.json"
    audit_manifest = json.loads(audit_manifest_path.read_text(encoding="utf-8"))
    inputs = {row["file"]: row["sha256"] for row in source_manifest["files"] if row["file"] in {"metadata.parquet", "content.parquet", "relationships.parquet"}}
    audited_outputs = {row["file"]: row["sha256"] for row in audit_manifest["outputs"] if row["file"] in {"document_decisions.csv", "duplicate_groups.csv"}}
    outputs = {name: {"bytes": (output / name).stat().st_size, "sha256": sha256(output / name)} for name in ("documents.jsonl", "articles.jsonl", "duplicate_ledger.csv")}
    manifest = {
        "dataset_revision": REVISION,
        "corpus_id": "core-employment-portfolio-v1",
        "input_sha256": inputs,
        "source_manifest_sha256": sha256(source_manifest_path),
        "audit_manifest_sha256": sha256(audit_manifest_path),
        "audit_input_sha256": audited_outputs,
        "curation_script_sha256": sha256(Path(__file__)),
        "core_article_stage_manifest_sha256": stage_manifest_sha,
        "selected_ids": list(CORE_IDS),
        "selection_policy": "explicit core IDs; exact central-only; four topic candidates plus explicit dependency allowlist",
        "duplicate_policy": "prefer Vietnamese original for the verified pinned bibliographic pair; preserve translation separately and do not merge text",
        "document_count": len(documents),
        "article_count": len(articles),
        "retrieval_index_article_count": sum(article["document_metadata"]["retrieval_index_candidate"] for article in articles),
        "retrieval_index_dispositions": dict(sorted(Counter(article["index_disposition"] for article in articles).items())),
        "retrieval_scope": {"topics": list(TOPIC_TERMS), "dependency_allowlist": {key: sorted(value) for key, value in DEPENDENCY_ALLOWLIST.items()}},
        "amendment_boundary": {"policy": "base snapshots may be quoted extractively; related noncore amendment/version records are quarantined; no consolidated/current-effect claim", "records": amendment_boundary},
        "article_topic_candidates": article_candidate_counts,
        "legal_validity": "unverified for every record; blank expiry remains unknown",
        "reported_status_conflict_ids": ["139264"],
        "amendments": "not verified or incorporated; source records are not consolidated texts",
        "answer_evidence_enabled": False,
        "active": False,
        "outputs": outputs,
    }
    temp = output / "corpus_manifest.json.part"
    temp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(output / "corpus_manifest.json")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=RAW_ROOT.parents[1] / "curated" / REVISION / "core-employment-portfolio-v1")
    args = parser.parse_args()
    print(json.dumps(build(args.output), ensure_ascii=True, indent=2))
