"""Small deterministic retrieval evaluation with provenance and stage timing."""
import json
import time
from pathlib import Path

from metrics import mrr_at_k, recall_at_k


def evaluate_retrieval(cases, retriever, provenance, k=5):
    rows = []
    for case in cases:
        started = time.perf_counter_ns()
        result = retriever.search(case["query"], case["legal_date"])
        elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
        hits = result["evidence"]
        relevant = case["relevant_article_ids"]
        rows.append({"case_id": case["case_id"], "recall_at_k": recall_at_k(hits, relevant, k), "mrr_at_k": mrr_at_k(hits, relevant, k), "latency_ms": elapsed_ms, "evidence_article_ids": [hit["article_id"] for hit in hits]})
    return {"provenance": dict(provenance), "k": k, "cases": rows, "summary": {"cases": len(rows), "mean_recall_at_k": sum(row["recall_at_k"] for row in rows) / len(rows) if rows else 0.0, "mean_mrr_at_k": sum(row["mrr_at_k"] for row in rows) / len(rows) if rows else 0.0, "mean_latency_ms": sum(row["latency_ms"] for row in rows) / len(rows) if rows else 0.0}}


def write_evaluation(report, output_path):
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
