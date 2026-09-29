"""Wire legally filtered BM25, dense Qdrant retrieval, and reranking."""
from datetime import date
import time

from qdrant_contract import legal_filter
from retrieval import rrf_fuse, rerank_candidates, select_evidence


class HybridRetriever:
    def __init__(self, bm25_index, encoder, qdrant, collection, article_lookup, reranker=None):
        self.bm25_index, self.encoder, self.qdrant, self.collection, self.article_lookup, self.reranker = bm25_index, encoder, qdrant, collection, dict(article_lookup), reranker

    def search(self, query, legal_date, provision=None, include_open_ended=False, sparse_limit=20, dense_limit=20, rerank_limit=20, evidence_cap=5):
        legal_day = date.fromisoformat(legal_date).toordinal()
        started = time.perf_counter_ns()
        sparse = [hit for hit in self.bm25_index.search(query, limit=len(self.bm25_index.documents)) if _eligible(hit, legal_day, provision, include_open_ended)][:sparse_limit]
        sparse_ms = (time.perf_counter_ns() - started) / 1_000_000
        dense_started = time.perf_counter_ns()
        vector = self.encoder.encode_queries([query])[0]
        response = self.qdrant.search(self.collection, vector, legal_filter(legal_date=legal_date, provision=provision, include_open_ended=include_open_ended), limit=dense_limit)
        dense = [{"article_id": point["payload"]["article_id"], "child_id": point["payload"].get("child_id"), "score": point["score"], "text": point["payload"].get("canonical_text", "")} for point in response.get("result", [])]
        dense_ms = (time.perf_counter_ns() - dense_started) / 1_000_000
        rerank_started = time.perf_counter_ns()
        fused = rrf_fuse({"bm25": sparse, "dense": dense})
        matched_children = {}
        for row in sparse + dense:
            if row.get("child_id"):
                matched_children.setdefault(row["article_id"], set()).add(row["child_id"])
        candidates = []
        for row in fused[:rerank_limit]:
            source = self.article_lookup.get(row["article_id"])
            if not source:
                continue
            candidates.append({**row, "text": source["canonical_text"], "document_version_id": source["document_version_id"], "source_start": source["source_start"], "source_end": source["source_end"], "matched_child_ids": sorted(matched_children.get(row["article_id"], set()))})
        if self.reranker:
            candidates = rerank_candidates(candidates, self.reranker.score(query, candidates))
        evidence = select_evidence(candidates, evidence_cap)
        return {"sparse": sparse, "dense": dense, "fused": fused, "evidence": evidence, "timings_ms": {"sparse": sparse_ms, "dense": dense_ms, "rerank_and_evidence": (time.perf_counter_ns() - rerank_started) / 1_000_000}}


def _eligible(hit, legal_day, provision, include_open_ended=False):
    effective_from, effective_to, reviewed_through = hit.get("effective_from_day"), hit.get("effective_to_day"), hit.get("reviewed_through_day")
    open_ended = effective_to is None and hit.get("reviewed_open_ended") is True
    dates_are_valid = type(effective_from) is int and type(reviewed_through) is int and (open_ended or type(effective_to) is int)
    return dates_are_valid and hit.get("pham_vi") == "Trung ương" and hit.get("reviewed_status") == "reviewed" and hit.get("central_eligible") is True and effective_from <= legal_day and reviewed_through >= legal_day and ((include_open_ended and open_ended) or (type(effective_to) is int and effective_to > legal_day)) and (provision is None or hit.get("provision") == provision)
