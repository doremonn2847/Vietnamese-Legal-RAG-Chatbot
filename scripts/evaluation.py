"""Small deterministic retrieval evaluation with provenance and stage timing."""
import json
import time
from pathlib import Path

from metrics import mrr_at_k, recall_at_k


def evaluate_retrieval(cases, retriever, provenance, k=5, evidence_cap=None):
    evidence_cap = k if evidence_cap is None else evidence_cap
    if type(k) is not int or type(evidence_cap) is not int or k <= 0 or evidence_cap <= 0:
        raise ValueError("k and evidence_cap must be positive integers")
    rows = []
    for case in cases:
        started = time.perf_counter_ns()
        result = retriever.search(case["query"], case["legal_date"], evidence_cap=evidence_cap)
        elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
        relevant = case["relevant_article_ids"]
        branches = {name: {"recall_at_k": recall_at_k(hits, relevant, min(k, evidence_cap) if name == "evidence" else k), "mrr_at_k": mrr_at_k(hits, relevant, min(k, evidence_cap) if name == "evidence" else k)} for name, hits in result.items() if name in {"sparse", "dense", "fused", "evidence"}}
        rows.append({"case_id": case["case_id"], "branches": branches, "latency_ms": elapsed_ms, "stage_timings_ms": dict(result.get("timings_ms", {})), "evidence_article_ids": [hit["article_id"] for hit in result["evidence"]]})
    return {"provenance": dict(provenance), "k": k, "evidence_cap": evidence_cap, "metric_depths": {"branches": k, "evidence": min(k, evidence_cap)}, "cases": rows, "summary": {"cases": len(rows), "mean_evidence_recall": sum(row["branches"]["evidence"]["recall_at_k"] for row in rows) / len(rows) if rows else 0.0, "mean_evidence_mrr": sum(row["branches"]["evidence"]["mrr_at_k"] for row in rows) / len(rows) if rows else 0.0, "mean_latency_ms": sum(row["latency_ms"] for row in rows) / len(rows) if rows else 0.0}}


def evaluate_grid(cases, retriever, provenance, configs):
    return [{"config": dict(config), "report": evaluate_retrieval(cases, _ConfiguredRetriever(retriever, config), {**provenance, "retrieval_config": dict(config)}, k=config["k"], evidence_cap=config.get("evidence_cap"))} for config in configs]


class _ConfiguredRetriever:
    def __init__(self, retriever, config): self.retriever, self.config = retriever, config
    def search(self, query, legal_date, **kwargs): return self.retriever.search(query, legal_date, **({key: value for key, value in self.config.items() if key != "k"} | kwargs))


def write_evaluation(report, output_path):
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
