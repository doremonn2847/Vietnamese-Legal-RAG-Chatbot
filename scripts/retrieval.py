"""Article-level hybrid retrieval primitives, independent of an embedding service."""


def group_article_hits(hits):
    grouped = {}
    for hit in hits:
        article_id = hit["article_id"]
        current = grouped.setdefault(article_id, {"article_id": article_id, "score": hit.get("score", 0.0), "matched_child_ids": [], "_child_scores": {}})
        current["score"] = max(current["score"], hit.get("score", 0.0))
        if hit.get("child_id") and hit["child_id"] not in current["matched_child_ids"]:
            current["matched_child_ids"].append(hit["child_id"])
            current["_child_scores"][hit["child_id"]] = hit.get("score", 0.0)
    for current in grouped.values():
        current["matched_child_ids"].sort(key=lambda child_id: (-current["_child_scores"][child_id], child_id))
        current.pop("_child_scores", None)
    return sorted(grouped.values(), key=lambda item: (-item["score"], item["article_id"]))


def rrf_fuse(branches, rrf_k=60):
    fused = {}
    for branch_name, hits in branches.items():
        unique = group_article_hits(hits) if any("child_id" in hit for hit in hits) else list(hits)
        seen = set()
        for rank, hit in enumerate(unique, 1):
            article_id = hit["article_id"]
            if article_id in seen:
                continue
            seen.add(article_id)
            item = fused.setdefault(article_id, {"article_id": article_id, "rrf_score": 0.0, "branches": {}})
            item["rrf_score"] += 1 / (rrf_k + rank)
            item["branches"][branch_name] = {"rank": rank, "score": hit.get("score")}
    return sorted(fused.values(), key=lambda item: (-item["rrf_score"], item["article_id"]))


def rerank_candidates(candidates, scores):
    ranked = []
    for candidate in candidates:
        item = dict(candidate)
        item["rerank_score"] = scores[item["article_id"]]
        ranked.append(item)
    return sorted(ranked, key=lambda item: (-item["rerank_score"], item["article_id"]))


def select_evidence(candidates, cap):
    key = (lambda item: (-item.get("rerank_score", 0.0), item["article_id"])) if any("rerank_score" in item for item in candidates) else (lambda item: (-item.get("rrf_score", 0.0), item["article_id"]))
    selected = sorted(candidates, key=key)[:max(0, cap)]
    for index, item in enumerate(selected, 1):
        if "rerank_score" in item:
            item["rerank_rank"] = index
    return selected
