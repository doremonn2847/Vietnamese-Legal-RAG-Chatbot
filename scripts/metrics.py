"""Unique-article retrieval metrics for offline development evaluations."""
import math


def unique_article_ids(hits):
    seen, result = set(), []
    for hit in hits:
        article_id = hit["article_id"]
        if article_id not in seen:
            seen.add(article_id)
            result.append(article_id)
    return result


def recall_at_k(hits, relevant_ids, k):
    relevant = set(relevant_ids)
    return len(set(unique_article_ids(hits)[:k]) & relevant) / len(relevant) if relevant else 0.0


def mrr_at_k(hits, relevant_ids, k):
    relevant = set(relevant_ids)
    for rank, article_id in enumerate(unique_article_ids(hits)[:k], 1):
        if article_id in relevant:
            return 1 / rank
    return 0.0


def ndcg_at_k(hits, grades, k):
    ranked = unique_article_ids(hits)[:k]
    dcg = sum((2 ** grades.get(article_id, 0) - 1) / math.log2(rank + 1) for rank, article_id in enumerate(ranked, 1))
    ideal = sorted(grades.values(), reverse=True)[:k]
    idcg = sum((2 ** grade - 1) / math.log2(rank + 1) for rank, grade in enumerate(ideal, 1))
    return dcg / idcg if idcg else 0.0


def sufficient_evidence_recall(predicted_sets, reference_sets):
    if not reference_sets:
        return 0.0
    return sum(set(predicted) >= set(reference) for predicted, reference in zip(predicted_sets, reference_sets)) / len(reference_sets)
