import unittest

from metrics import mrr_at_k, ndcg_at_k, recall_at_k, sufficient_evidence_recall, unique_article_ids


class MetricsTest(unittest.TestCase):
    def test_metrics_dedupe_child_hits_by_article(self):
        hits = [{"article_id": "a"}, {"article_id": "a"}, {"article_id": "b"}]
        self.assertEqual(unique_article_ids(hits), ["a", "b"])
        self.assertEqual(recall_at_k(hits, {"b"}, 2), 1.0)
        self.assertEqual(mrr_at_k(hits, {"b"}, 2), 0.5)

    def test_ndcg_uses_relevance_grades(self):
        hits = [{"article_id": "a"}, {"article_id": "b"}]
        self.assertAlmostEqual(ndcg_at_k(hits, {"a": 3, "b": 0}, 2), 1.0)

    def test_sufficient_evidence_requires_the_whole_set(self):
        self.assertEqual(sufficient_evidence_recall([["a", "b"], ["a"]], [{"a", "b"}, {"a", "c"}]), 0.5)


if __name__ == "__main__":
    unittest.main()
