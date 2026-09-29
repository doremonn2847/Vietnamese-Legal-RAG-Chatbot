"""Required retrieval-grid bookkeeping; runtime latency remains unmeasured here."""
from retrieval import rrf_fuse, select_evidence

BRANCH_DEPTH_PAIRS = ((10, 10), (20, 20), (40, 40), (20, 40), (40, 20))
RERANK_DEPTHS = (10, 20, 40)
EVIDENCE_CAPS = (3, 5, 8)


def sweep_configs(branches, rerank=None):
    rerank = rerank or (lambda candidates: candidates)
    rows = []
    for bm25_depth, dense_depth in BRANCH_DEPTH_PAIRS:
        limited = {"bm25": branches.get("bm25", [])[:bm25_depth], "dense": branches.get("dense", [])[:dense_depth]}
        fused = rrf_fuse(limited)
        for rerank_depth in RERANK_DEPTHS:
            reranked = rerank(fused[:rerank_depth])[:rerank_depth]
            for evidence_cap in EVIDENCE_CAPS:
                evidence = select_evidence(reranked, evidence_cap)
                rows.append({"k_bm25": bm25_depth, "k_dense": dense_depth, "k_rerank": rerank_depth, "k_evidence": evidence_cap, "requested_unique_articles": max(bm25_depth, dense_depth), "achieved_unique_articles": len(fused), "actual_rerank_candidates": len(reranked), "actual_evidence_articles": len(evidence), "measurement_status": "score_only_unmeasured_latency"})
    return rows
