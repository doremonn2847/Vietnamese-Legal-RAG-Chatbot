import tempfile
import unittest
from pathlib import Path

from evaluate_heldout_retrieval import _distribution, evaluate_cases


class HeldoutEvaluationTest(unittest.TestCase):
    def test_reports_branch_and_depth_metrics_separately_and_keeps_negative_case_visible(self):
        class Retriever:
            def search(self, query):
                return {
                    "sparse": [{"article_id": "a", "child_id": "a1", "score": 3.0}, {"article_id": "b", "child_id": "b1", "score": 2.0}],
                    "dense": [{"article_id": "b", "child_id": "b1", "score": 0.9}, {"article_id": "a", "child_id": "a1", "score": 0.8}],
                    "fused": [{"article_id": "a", "rrf_score": 0.04}, {"article_id": "b", "rrf_score": 0.03}, {"article_id": "c", "rrf_score": 0.02}],
                    "timings_ms": {"sparse": 1.0, "dense": 2.0, "fusion_and_evidence": 0.5},
                }
        class Reranker:
            def score(self, query, candidates): return {row["article_id"]: (1 if row["article_id"] == "b" else 0) for row in candidates}
        cases = [
            {"case_id": "one", "scenario_family_id": "f1", "kind": "answerable", "query": "q1", "relevant_article_ids": ["a"]},
            {"case_id": "many", "scenario_family_id": "f2", "kind": "ambiguous", "query": "q2", "relevant_article_ids": ["a", "b"]},
            {"case_id": "none", "scenario_family_id": "f3", "kind": "negative", "query": "q3", "relevant_article_ids": []},
        ]
        articles = {key: {"canonical_text": key} for key in ("a", "b", "c")}
        output = evaluate_cases(cases, Retriever(), Reranker(), articles)
        first = output["results"][0]
        self.assertEqual(first["baseline"]["rrf"]["top_article_ids"][0], "a")
        self.assertEqual(first["reranked"]["5"]["top_article_ids"][0], "b")
        self.assertEqual(first["reranked"]["20"]["candidate_count"], 3)
        self.assertIsNone(output["results"][2]["baseline"]["rrf"]["metrics"])
        self.assertEqual(output["summary"]["negative_cases_with_any_rrf_candidate"], 1)
        self.assertEqual(output["summary"]["case_counts"], {"answerable": 1, "ambiguous": 1, "negative": 1})
        self.assertEqual(output["summary"]["baseline"]["rrf"]["mean_recall_at_k"], 1.0)

    def test_latency_distribution_uses_median_and_nearest_rank_p95(self):
        self.assertEqual(_distribution([1.0, 2.0, 3.0, 4.0]), {"samples": 4, "p50": 2.5, "p95": 4.0})


if __name__ == "__main__":
    unittest.main()
