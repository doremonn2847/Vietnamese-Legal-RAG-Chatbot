"""Wire BM25, dense Qdrant retrieval, and optional reranking without activation."""
from qdrant_contract import legal_filter
from retrieval import rrf_fuse, rerank_candidates, select_evidence


class HybridRetriever:
    def __init__(self, bm25_index, encoder, qdrant, collection, reranker=None):
        self.bm25_index, self.encoder, self.qdrant, self.collection, self.reranker = bm25_index, encoder, qdrant, collection, reranker

    def search(self, query, legal_date, provision=None, sparse_limit=20, dense_limit=20, rerank_limit=20, evidence_cap=5):
        sparse = self.bm25_index.search(query, limit=sparse_limit)
        vector = self.encoder.encode_queries([query])[0]
        response = self.qdrant.search(self.collection, vector, legal_filter(legal_date=legal_date, provision=provision), limit=dense_limit)
        dense = [{"article_id": point["payload"]["article_id"], "child_id": point["payload"].get("child_id"), "score": point["score"], "text": point["payload"].get("canonical_text", "")} for point in response.get("result", [])]
        fused = rrf_fuse({"bm25": sparse, "dense": dense})
        text_by_article = {row["article_id"]: row.get("text", "") for row in sparse + dense}
        candidates = [{**row, "text": text_by_article.get(row["article_id"], "")} for row in fused[:rerank_limit]]
        if self.reranker:
            candidates = rerank_candidates(candidates, self.reranker.score(query, candidates))
        return {"sparse": sparse, "dense": dense, "fused": fused, "evidence": select_evidence(candidates, evidence_cap)}
