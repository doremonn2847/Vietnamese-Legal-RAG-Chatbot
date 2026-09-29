import tempfile
import unittest
from pathlib import Path

from evaluation import evaluate_retrieval, write_evaluation
from safe_log import event


class EvaluationTest(unittest.TestCase):
    def test_report_has_provenance_and_timing(self):
        class Retriever:
            def search(self, query, legal_date):
                return {"evidence": [{"article_id": "a1"}]}
        report = evaluate_retrieval([{"case_id": "q1", "query": "thử việc", "legal_date": "2024-01-01", "relevant_article_ids": ["a1"]}], Retriever(), {"corpus_revision": "test", "embedding_revision": "fake"})
        self.assertEqual(report["summary"]["mean_recall_at_k"], 1.0)
        self.assertIn("latency_ms", report["cases"][0])
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "report.json"
            write_evaluation(report, output)
            self.assertTrue(output.exists())
        row = event("retrieve", query="private question", duration_ms=1.0)
        self.assertNotIn("private question", str(row))
        self.assertIn("query_sha256", row)


if __name__ == "__main__":
    unittest.main()
