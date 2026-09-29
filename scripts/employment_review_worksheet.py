"""Build an owner worksheet from the existing provisional review packet; no legal decisions."""
import csv
import json
import re
from pathlib import Path


SCOPE_TERMS = re.compile(r"thử việc|hợp đồng lao động|thời giờ làm việc|thời giờ nghỉ ngơi|nghỉ phép", re.IGNORECASE)
FIELDS = ["dataset_id", "title", "so_ky_hieu", "source_locator", "official_source_url", "official_lookup_status", "local_evidence_access_date", "local_provenance", "article_candidates", "candidate_basis", "issuer_and_version_signals", "review_status", "owner_decision"]


def build_worksheet(priority_path, decisions_path, articles_path, output_path, access_date, revision):
    priority = [row for row in _rows(priority_path) if row.get("stage_role") == "employment_seed"]
    decisions = {row.get("id"): row for row in _rows(decisions_path)}
    candidates = {row["id"]: [] for row in priority}
    for line in Path(articles_path).read_text(encoding="utf-8").splitlines():
        article = json.loads(line)
        document_id, text = str(article.get("document_id", "")), article.get("canonical_text")
        if document_id in candidates and isinstance(text, str) and SCOPE_TERMS.search(text):
            label = re.search(r"Điều\s+\d+[A-Za-z]*", text)
            candidates[document_id].append(f"{label.group(0) if label else 'unlabeled article'} [{article.get('article_id', '')}] offsets {article.get('source_start', '')}:{article.get('source_end', '')}")
    with Path(output_path).open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS); writer.writeheader()
        for row in priority:
            decision = decisions.get(row["id"], {})
            signals = "; ".join(f"{key}={decision.get(key, '')}" for key in ("issuer", "issuer_signal", "all_flags_json", "expiry_state", "reported_expiry", "reported_status", "current_validity"))
            writer.writerow({"dataset_id": row["id"], "title": row.get("title", ""), "so_ky_hieu": row.get("so_ky_hieu", ""), "source_locator": row.get("source_locator", "") or f"vbpl_id:{row['id']}@{revision}", "official_source_url": "", "official_lookup_status": "unverified: no reliable official-page locator was verified from local evidence", "local_evidence_access_date": access_date, "local_provenance": f"priority+decisions+articles@{revision}", "article_candidates": " | ".join(candidates[row["id"]]) or "none derived from stored scope terms", "candidate_basis": "stored-text term match only; owner must confirm ordinary adult private-sector applicability", "issuer_and_version_signals": signals, "review_status": "unverified: source authority, version, dates, scope, and validity pending owner review", "owner_decision": "pending"})


def _rows(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("priority_path"); parser.add_argument("decisions_path"); parser.add_argument("articles_path"); parser.add_argument("output_path"); parser.add_argument("--access-date", required=True); parser.add_argument("--revision", required=True)
    args = parser.parse_args()
    build_worksheet(**vars(args))
