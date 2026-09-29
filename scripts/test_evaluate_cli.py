import unittest
from unittest.mock import patch

from evaluate_cli import main, validate_measurement_cases, validate_split_separation


class EvaluateCliTest(unittest.TestCase):
    def test_unreviewed_or_empty_positive_cases_cannot_measure(self):
        draft = {"case_id": "d", "scenario_family_id": "d", "family": "answerable", "query": "q", "legal_date": "2024-01-01", "reference_status": "unreviewed", "expected_answer_state": "answer", "relevant_article_ids": [], "reference_required_fields": ["document_version_id"], "references": []}
        with self.assertRaises(ValueError):
            validate_measurement_cases([draft])
        with self.assertRaises(ValueError):
            validate_measurement_cases([{**draft, "reference_status": "reviewed"}])
        validate_measurement_cases([{**draft, "reference_status": "reviewed", "expected_answer_state": "unavailable"}])
        with self.assertRaises(ValueError):
            validate_measurement_cases([{**draft, "reference_status": "reviewed", "expected_answer_state": "garbage"}])
        validate_measurement_cases([{**draft, "reference_status": "reviewed", "relevant_article_ids": ["a1"], "references": [{"document_version_id": "v1", "article_id": "a1", "quote": "q", "span_start": 0, "span_end": 1, "applicable_on_requested_date": True}]}])
        with self.assertRaises(ValueError):
            validate_split_separation([{"scenario_family_id": "same", "split": "dev"}, {"scenario_family_id": "same", "split": "heldout"}])

    def test_draft_never_imports_requested_retriever(self):
        with patch("sys.argv", ["evaluate_cli.py", "data/benchmarks/vietnamese_employment_draft.json", "--retriever", "missing_module:factory", "--output", "out.json"]):
            with self.assertRaises(ValueError):
                main()


if __name__ == "__main__":
    unittest.main()
