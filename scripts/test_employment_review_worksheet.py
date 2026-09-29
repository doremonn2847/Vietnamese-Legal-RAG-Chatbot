import csv
import json
import tempfile
import unittest
from pathlib import Path

from employment_review_worksheet import build_worksheet


class ReviewerWorksheetTest(unittest.TestCase):
    def test_builds_unverified_seed_rows_with_exact_stored_candidates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (root / "priority.csv").open("w", encoding="utf-8", newline="") as file:
                writer = csv.DictWriter(file, fieldnames=["id", "title", "so_ky_hieu", "stage_role", "source_locator"]); writer.writeheader(); writer.writerow({"id":"d1", "title":"Hợp đồng", "so_ky_hieu":"1/X", "stage_role":"employment_seed", "source_locator":"vbpl_id:d1@rev"}); writer.writerow({"id":"d2", "title":"Skip", "so_ky_hieu":"2/X", "stage_role":"dependency", "source_locator":"vbpl_id:d2@rev"})
            with (root / "decisions.csv").open("w", encoding="utf-8", newline="") as file:
                writer = csv.DictWriter(file, fieldnames=["id", "issuer", "issuer_signal", "all_flags_json", "expiry_state", "reported_expiry", "reported_status", "current_validity", "employment_scope"]); writer.writeheader(); writer.writerow({"id":"d1", "issuer":"Bộ", "issuer_signal":"central_issuer_signal", "all_flags_json":"[]", "expiry_state":"unknown_expiry", "reported_expiry":"", "reported_status":"Còn hiệu lực", "current_validity":"unverified", "employment_scope":"not_yet_reviewed"})
            (root / "articles.jsonl").write_text(json.dumps({"document_id":"d1", "article_id":"a1", "label":"Điều 1", "canonical_text":"Điều 2. Hợp đồng lao động điện tử.", "source_start":10, "source_end":50}, ensure_ascii=False) + "\n", encoding="utf-8")
            output = root / "worksheet.csv"
            build_worksheet(root / "priority.csv", root / "decisions.csv", root / "articles.jsonl", output, "2026-09-29", "rev")
            with output.open(encoding="utf-8-sig") as file:
                rows = list(csv.DictReader(file))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["dataset_id"], "d1")
            self.assertEqual(rows[0]["article_candidate_count"], "1")
            self.assertIn("Điều 1 [a1] offsets 10:50", rows[0]["article_candidates_preview"])
            self.assertEqual(rows[0]["official_source_url"], "")
            self.assertIn("unverified", rows[0]["review_status"])
            with (root / "worksheet_article_candidates.csv").open(encoding="utf-8-sig") as file:
                details = list(csv.DictReader(file))
            self.assertEqual(details[0]["article_label"], "Điều 1")


if __name__ == "__main__":
    unittest.main()
