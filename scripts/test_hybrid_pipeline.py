import unittest

from bm25 import BM25Index
from hybrid_pipeline import HybridRetriever


class HybridPipelineTest(unittest.TestCase):
    def test_qdrant_dense_and_reranker_are_wired(self):
        class Encoder:
            def encode_queries(self, queries):
                self.queries = queries
                return [[1.0, 0.0]]
        class Qdrant:
            def search(self, collection, vector, filters, limit):
                self.call = (collection, vector, filters, limit)
                return {"result": [{"score": 0.9, "payload": {"article_id": "a2", "child_id": "c2", "canonical_text": "dense text"}}]}
        class Reranker:
            def score(self, query, candidates):
                return {row["article_id"]: 1.0 if row["article_id"] == "a2" else 0.0 for row in candidates}
        index = BM25Index([{"article_id": "a1", "child_id": "c1", "text": "thử việc"}])
        encoder, qdrant = Encoder(), Qdrant()
        result = HybridRetriever(index, encoder, qdrant, "demo", Reranker()).search("thử việc", "2024-01-01", provision="probation")
        self.assertEqual(encoder.queries, ["thử việc"])
        self.assertEqual(qdrant.call[0], "demo")
        self.assertEqual(result["evidence"][0]["article_id"], "a2")


if __name__ == "__main__":
    unittest.main()
