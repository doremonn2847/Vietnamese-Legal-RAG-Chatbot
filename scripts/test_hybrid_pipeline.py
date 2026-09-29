import unittest

from bm25 import BM25Index
from hybrid_pipeline import HybridRetriever


class HybridPipelineTest(unittest.TestCase):
    def test_qdrant_dense_and_reranker_are_wired(self):
        day = 738886
        eligible = {"pham_vi": "Trung ương", "provision": "probation", "reviewed_status": "reviewed", "central_eligible": True, "effective_from_day": day - 1, "effective_to_day": day + 1, "reviewed_through_day": day + 1}
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
        index = BM25Index([{"article_id": "a1", "child_id": "c1", "text": "thử việc", **eligible}])
        encoder, qdrant = Encoder(), Qdrant()
        lookup = {"a1": {"canonical_text": "parent one", "document_version_id": "v1", "source_start": 0, "source_end": 10}, "a2": {"canonical_text": "parent two", "document_version_id": "v2", "source_start": 10, "source_end": 20}}
        result = HybridRetriever(index, encoder, qdrant, "demo", lookup, Reranker()).search("thử việc", "2024-01-01", provision="probation")
        self.assertEqual(encoder.queries, ["thử việc"])
        self.assertEqual(qdrant.call[0], "demo")
        self.assertEqual(result["evidence"][0]["article_id"], "a2")

    def test_sparse_filter_refills_and_parent_lookup_keeps_children(self):
        day = 738886
        eligible = {"pham_vi": "Trung ương", "provision": "probation", "reviewed_status": "reviewed", "central_eligible": True, "effective_from_day": day - 1, "effective_to_day": day + 1, "reviewed_through_day": day + 1}
        index = BM25Index([{"article_id": "local", "text": "thử việc thử việc", "pham_vi": "Địa phương"}, {"article_id": "expired", "text": "thử việc", **eligible, "effective_to_day": day}, {"article_id": "a1", "child_id": "c1", "text": "thử việc", **eligible}])
        class Encoder:
            def encode_queries(self, queries): return [[1.0]]
        class Qdrant:
            def search(self, *args, **kwargs): return {"result": [{"score": 1.0, "payload": {"article_id": "a1", "child_id": "c2", "canonical_text": "child"}}, {"score": 0.9, "payload": {"article_id": "a1", "child_id": "c1", "canonical_text": "child"}}]}
        lookup = {"a1": {"canonical_text": "full parent", "document_version_id": "v1", "source_start": 3, "source_end": 14}}
        result = HybridRetriever(index, Encoder(), Qdrant(), "demo", lookup).search("thử việc", "2024-01-01", provision="probation", sparse_limit=1)
        self.assertEqual([row["article_id"] for row in result["sparse"]], ["a1"])
        self.assertEqual(result["evidence"][0]["text"], "full parent")
        self.assertEqual(result["evidence"][0]["matched_child_ids"], ["c1", "c2"])


if __name__ == "__main__":
    unittest.main()
