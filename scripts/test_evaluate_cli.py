import unittest
from unittest.mock import patch

from evaluate_cli import main, validate_measurement_cases


class EvaluateCliTest(unittest.TestCase):
    def test_unreviewed_or_empty_positive_cases_cannot_measure(self):
        draft = {"case_id": "d", "scenario_family_id": "d", "family": "answerable", "query": "q", "legal_date": "2024-01-01", "reference_status": "unreviewed", "expected_answer_state": "answer", "relevant_article_ids": [], "reference_required_fields": []}
        with self.assertRaises(ValueError):
            validate_measurement_cases([draft])
        with self.assertRaises(ValueError):
            validate_measurement_cases([{**draft, "reference_status": "reviewed"}])
        validate_measurement_cases([{**draft, "reference_status": "reviewed", "expected_answer_state": "unavailable"}])

    def test_draft_never_imports_requested_retriever(self):
        with patch("sys.argv", ["evaluate_cli.py", "data/benchmarks/vietnamese_employment_draft.json", "--retriever", "missing_module:factory", "--output", "out.json"]):
            with self.assertRaises(ValueError):
                main()


if __name__ == "__main__":
    unittest.main()
