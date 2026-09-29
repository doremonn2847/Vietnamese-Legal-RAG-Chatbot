import tempfile
import unittest
from pathlib import Path

from evaluation import evaluate_grid, evaluate_retrieval, write_evaluation
from safe_log import event


class EvaluationTest(unittest.TestCase):
    def test_report_has_provenance_and_timing(self):
        class Retriever:
            def search(self, query, legal_date, **kwargs):
                self.kwargs = kwargs
                return {"sparse": [{"article_id": "a1"}], "dense": [{"article_id": "a1"}], "fused": [{"article_id": "a1"}], "evidence": [{"article_id": "a1"}], "timings_ms": {"sparse": 1.0}}
        retriever = Retriever()
        report = evaluate_retrieval([{"case_id": "q1", "query": "thử việc", "legal_date": "2024-01-01", "relevant_article_ids": ["a1"]}], retriever, {"corpus_revision": "test", "embedding_revision": "fake"}, k=5, evidence_cap=3)
        self.assertEqual(report["summary"]["mean_evidence_recall"], 1.0)
        self.assertEqual(report["metric_depths"]["evidence"], 3)
        self.assertEqual(retriever.kwargs["evidence_cap"], 3)
        with self.assertRaises(ValueError):
            evaluate_retrieval([], retriever, {}, k=0)
        negative = evaluate_retrieval([{"case_id": "n", "query": "x", "legal_date": "2024-01-01", "relevant_article_ids": []}], retriever, {})
        self.assertEqual(negative["cases"][0]["retrieval_status"], "not_applicable_no_reference")
        self.assertIsNone(negative["summary"]["mean_evidence_recall"])
        self.assertIn("stage_timings_ms", report["cases"][0])
        self.assertEqual(evaluate_grid([], Retriever(), {}, [{"k": 10, "evidence_cap": 10}])[0]["report"]["evidence_cap"], 10)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "report.json"
            write_evaluation(report, output)
            self.assertTrue(output.exists())
        row = event("retrieve", query="private question", duration_ms=1.0)
        self.assertNotIn("private question", str(row))
        self.assertIn("query_sha256", row)


if __name__ == "__main__":
    unittest.main()
