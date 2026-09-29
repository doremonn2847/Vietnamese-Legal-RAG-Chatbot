"""Build an owner worksheet from the existing provisional review packet; no legal decisions."""
import csv
import json
import re
from pathlib import Path


SCOPE_TERMS = re.compile(r"thử việc|hợp đồng lao động|thời giờ làm việc|thời giờ nghỉ ngơi|nghỉ phép", re.IGNORECASE)
FIELDS = ["dataset_id", "title", "so_ky_hieu", "source_locator", "official_source_url", "official_lookup_status", "local_evidence_access_date", "local_provenance", "article_candidate_count", "article_candidates_preview", "article_candidates_detail", "candidate_basis", "issuer_and_version_signals", "review_status", "owner_decision"]
DETAIL_FIELDS = ["dataset_id", "article_id", "article_label", "source_start", "source_end"]


def build_worksheet(priority_path, decisions_path, articles_path, output_path, access_date, revision):
    priority = [row for row in _rows(priority_path) if row.get("stage_role") == "employment_seed"]
    decisions = {row.get("id"): row for row in _rows(decisions_path)}
    candidates = {row["id"]: [] for row in priority}
    for line in Path(articles_path).read_text(encoding="utf-8").splitlines():
        article = json.loads(line)
        document_id, text = str(article.get("document_id", "")), article.get("canonical_text")
        if document_id in candidates and isinstance(text, str) and SCOPE_TERMS.search(text):
            candidates[document_id].append({"article_id": article.get("article_id", ""), "article_label": article.get("label") or "unlabeled stored article", "source_start": article.get("source_start", ""), "source_end": article.get("source_end", "")})
    output_path, detail_path = Path(output_path), Path(output_path).with_name(Path(output_path).stem + "_article_candidates.csv")
    with output_path.open("w", encoding="utf-8-sig", newline="") as file, detail_path.open("w", encoding="utf-8-sig", newline="") as details_file:
        writer = csv.DictWriter(file, fieldnames=FIELDS); writer.writeheader()
        detail_writer = csv.DictWriter(details_file, fieldnames=DETAIL_FIELDS); detail_writer.writeheader()
        for row in priority:
            decision = decisions.get(row["id"], {})
            signals = "; ".join(f"{key}={decision.get(key, '')}" for key in ("issuer", "issuer_signal", "all_flags_json", "expiry_state", "reported_expiry", "reported_status", "current_validity"))
            rows = candidates[row["id"]]
            preview = " | ".join(f"{item['article_label']} [{item['article_id']}] offsets {item['source_start']}:{item['source_end']}" for item in rows[:3]) or "none derived from stored scope terms"
            if len(rows) > 3: preview += f" | +{len(rows) - 3} additional candidates"
            writer.writerow({"dataset_id": row["id"], "title": row.get("title", ""), "so_ky_hieu": row.get("so_ky_hieu", ""), "source_locator": row.get("source_locator", "") or f"vbpl_id:{row['id']}@{revision}", "official_source_url": "", "official_lookup_status": "unverified: no reliable official-page locator was verified from local evidence", "local_evidence_access_date": access_date, "local_provenance": f"priority+decisions+articles@{revision}", "article_candidate_count": len(rows), "article_candidates_preview": preview, "article_candidates_detail": detail_path.name, "candidate_basis": "stored-text term match only; owner must confirm ordinary adult private-sector applicability", "issuer_and_version_signals": signals, "review_status": "unverified: source authority, version, dates, scope, and validity pending owner review", "owner_decision": "pending"})
            for item in rows: detail_writer.writerow({"dataset_id": row["id"], **item})


def _rows(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("priority_path"); parser.add_argument("decisions_path"); parser.add_argument("articles_path"); parser.add_argument("output_path"); parser.add_argument("--access-date", required=True); parser.add_argument("--revision", required=True)
    args = parser.parse_args()
    build_worksheet(**vars(args))
