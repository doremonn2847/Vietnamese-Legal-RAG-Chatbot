import unittest

from retrieval import group_article_hits, rerank_candidates, rrf_fuse, select_evidence


class RetrievalTest(unittest.TestCase):
    def test_child_hits_group_to_one_article_using_max_score(self):
        hits = group_article_hits([
            {"article_id": "a", "child_id": "a1", "score": 0.2},
            {"article_id": "a", "child_id": "a2", "score": 0.9},
            {"article_id": "b", "child_id": "b1", "score": 0.8},
        ])
        self.assertEqual([x["article_id"] for x in hits], ["a", "b"])
        self.assertEqual(hits[0]["score"], 0.9)
        self.assertEqual(hits[0]["matched_child_ids"], ["a2", "a1"])

    def test_rrf_uses_unique_article_ranks(self):
        fused = rrf_fuse({"bm25": [{"article_id": "a"}, {"article_id": "b"}], "dense": [{"article_id": "b"}, {"article_id": "a"}]})
        self.assertEqual({x["article_id"] for x in fused}, {"a", "b"})
        self.assertEqual(fused[0]["rrf_score"], fused[1]["rrf_score"])

    def test_evidence_cap_is_bounded_and_deterministic(self):
        candidates = [{"article_id": str(i), "rrf_score": 1 / (i + 1)} for i in range(5)]
        self.assertEqual([x["article_id"] for x in select_evidence(candidates, 3)], ["0", "1", "2"])

    def test_evidence_selection_preserves_distinct_reranker_order(self):
        candidates = [{"article_id": "a", "rrf_score": 0.9}, {"article_id": "b", "rrf_score": 0.8}]
        reranked = rerank_candidates(candidates, {"a": 0.1, "b": 0.9})
        self.assertEqual([x["article_id"] for x in select_evidence(reranked, 2)], ["b", "a"])


if __name__ == "__main__":
    unittest.main()
