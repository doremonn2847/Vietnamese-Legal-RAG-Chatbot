"""Evaluate frozen heading-level held-out retrieval with bounded CPU reranking."""
import argparse
import hashlib
import json
import math
import statistics
import time
from pathlib import Path

from core_retriever import CoreCorpusRetriever
from e5_artifacts import E5ArtifactSpec, load_transformers_encoder
from metrics import mrr_at_k, recall_at_k
from reranker_artifacts import RerankerSpec, load_transformers_reranker
from retrieval import group_article_hits, rerank_candidates


DEPTHS = (5, 10, 20)


def evaluate_cases(cases, retriever, reranker, articles, *, depths=DEPTHS, k=5):
    if tuple(depths) != DEPTHS or type(k) is not int or not 1 <= k <= 10:
        raise ValueError("held-out run requires rerank depths 5/10/20 and k in 1..10")
    results, retrieval_times, stage_times = [], [], {}
    rerank_times = {depth: [] for depth in depths}
    for case in cases:
        started = time.perf_counter_ns()
        search = retriever.search(case["query"])
        retrieval_ms = (time.perf_counter_ns() - started) / 1_000_000
        retrieval_times.append(retrieval_ms)
        timings = search.get("timings_ms", {})
        for stage, duration in timings.items():
            if isinstance(duration, (int, float)) and math.isfinite(duration):
                stage_times.setdefault(stage, []).append(float(duration))
        rankings = {
            "bm25": group_article_hits(search["sparse"]),
            "dense": group_article_hits(search["dense"]),
            "rrf": search["fused"],
        }
        relevant = case["relevant_article_ids"]
        branch_metrics = {name: _metric(rows, relevant, k) for name, rows in rankings.items()}
        reranked = {}
        for depth in depths:
            candidates = [{**hit, **articles[hit["article_id"]], "text": articles[hit["article_id"]]["canonical_text"]}
                          for hit in search["fused"][:depth] if hit["article_id"] in articles]
            start = time.perf_counter_ns()
            scores = reranker.score(case["query"], candidates)
            elapsed = (time.perf_counter_ns() - start) / 1_000_000
            rerank_times[depth].append(elapsed)
            ranked = rerank_candidates(candidates, scores)
            reranked[str(depth)] = {"metrics": _metric(ranked, relevant, k), "top_article_ids": [row["article_id"] for row in ranked[:k]], "candidate_count": len(candidates), "latency_ms": elapsed}
        results.append({
            "case_id": case["case_id"], "scenario_family_id": case["scenario_family_id"], "kind": case["kind"],
            "retrieval_latency_ms": retrieval_ms,
            "baseline": {name: {"metrics": branch_metrics[name], "top_article_ids": [row["article_id"] for row in rows[:k]]} for name, rows in rankings.items()},
            "reranked": reranked,
        })
    measured = [row for row in results if row["kind"] != "negative"]
    summary = {
        "case_counts": {kind: sum(row["kind"] == kind for row in results) for kind in ("answerable", "ambiguous", "negative")},
        "baseline": {name: _mean_metric([row["baseline"][name]["metrics"] for row in measured]) for name in ("bm25", "dense", "rrf")},
        "reranked": {str(depth): _mean_metric([row["reranked"][str(depth)]["metrics"] for row in measured]) for depth in depths},
        "negative_cases_with_any_rrf_candidate": sum(row["kind"] == "negative" and bool(row["baseline"]["rrf"]["top_article_ids"]) for row in results),
        "latency_ms": {"retrieval": _distribution(retrieval_times), "retrieval_stages": {stage: _distribution(values) for stage, values in stage_times.items()}, "rerank_by_depth": {str(depth): _distribution(values) for depth, values in rerank_times.items()}},
    }
    return {"results": results, "summary": summary}


def run(cases_path, output_path, *, model_path, reranker_path, corpus_root, artifact_dir, dev_cases_path):
    cases_path, model_path, reranker_path, corpus_root, artifact_dir = map(Path, (cases_path, model_path, reranker_path, corpus_root, artifact_dir))
    raw = cases_path.read_bytes()
    benchmark = json.loads(raw.decode("utf-8"))
    cases = benchmark.get("cases") if isinstance(benchmark, dict) else None
    if benchmark.get("split") != "heldout" or not isinstance(cases, list) or not 1 <= len(cases) <= 30:
        raise ValueError("input must be a frozen heldout set of 1..30 cases")
    _validate_cases(cases, dev_cases_path)

    e5_spec = E5ArtifactSpec.pinned_small()
    encoder = load_transformers_encoder(e5_spec, model_path=model_path, tokenizer_path=model_path, local_files_only=True)
    corpus = corpus_root / "corpus_manifest.json"
    retriever = CoreCorpusRetriever(corpus_root / "articles.jsonl", corpus, artifact_dir, encoder, sparse_limit=30, dense_limit=30, evidence_cap=5)
    _validate_targets(cases, retriever.articles)
    reranker_spec = RerankerSpec()
    reranker = load_transformers_reranker(reranker_spec, model_path=reranker_path, local_files_only=True)
    memory_before = _peak_rss_bytes()
    evaluated = evaluate_cases(cases, retriever, reranker, retriever.articles)
    memory_after = _peak_rss_bytes()
    report = {
        "benchmark": {"id": benchmark["benchmark_id"], "split": "heldout", "label_freeze": benchmark["label_freeze"], "labeling": benchmark["labeling"], "cases": len(cases), "sha256": hashlib.sha256(raw).hexdigest()},
        "corpus": {"id": benchmark["corpus_id"], "dataset_revision": benchmark["dataset_revision"], "manifest_sha256": _sha(corpus)},
        "embedding": {"model_id": e5_spec.model_id, "revision": e5_spec.revision, "manifest_sha256": _sha(artifact_dir / "embedding_manifest.json")},
        "reranker": {"model_id": reranker_spec.model_id, "revision": reranker_spec.revision, "execution": "CPU", "manifest_sha256": _sha(reranker_path / "artifact_manifest.json")},
        "retrieval_mode": "BM25 + exact dot-product over pinned local vectors + RRF; no Qdrant request",
        "limits": {"sparse_candidates": 30, "dense_candidates": 30, "rerank_depths": list(DEPTHS), "k": 5},
        "memory": {"metric": "process peak resident working set", "bytes_after_models_loaded": memory_before, "bytes_after_evaluation": memory_after},
        **evaluated,
        "claims": "heading-level retrieval engineering only; labels do not validate legal content or current applicability",
    }
    _write_json(report, output_path)
    return report


def _validate_cases(cases, dev_cases_path):
    if len({case.get("case_id") for case in cases if isinstance(case, dict)}) != len(cases) or len({case.get("scenario_family_id") for case in cases if isinstance(case, dict)}) != len(cases):
        raise ValueError("heldout case and scenario-family IDs must be unique")
    dev = json.loads(Path(dev_cases_path).read_text(encoding="utf-8"))
    dev_families = {case.get("scenario_family_id") for case in dev if isinstance(case, dict)}
    for case in cases:
        targets = case.get("relevant_article_ids")
        if not all(isinstance(case.get(key), str) and case[key].strip() for key in ("case_id", "scenario_family_id", "query")) or case.get("scenario_family_id") in dev_families or case.get("kind") not in {"answerable", "ambiguous", "negative"} or not isinstance(targets, list) or len(set(targets)) != len(targets) or any(not isinstance(item, str) for item in targets):
            raise ValueError("heldout schema, labels, or dev-family separation is invalid")
        if (case["kind"] == "negative") != (not targets) or (case["kind"] == "answerable" and len(targets) != 1) or (case["kind"] == "ambiguous" and len(targets) < 2):
            raise ValueError("relevance targets do not match the case kind")


def _validate_targets(cases, articles):
    for case in cases:
        if any(article_id not in articles or articles[article_id]["document_metadata"].get("retrieval_index_candidate") is not True for article_id in case["relevant_article_ids"]):
            raise ValueError("heldout relevance target is not in the eligible pinned corpus")


def _metric(ranked, relevant, k):
    return None if not relevant else {"recall_at_k": recall_at_k(ranked, relevant, k), "mrr_at_k": mrr_at_k(ranked, relevant, k)}


def _mean_metric(metrics):
    usable = [item for item in metrics if item is not None]
    return {"mean_" + key: statistics.mean(item[key] for item in usable) if usable else None for key in ("recall_at_k", "mrr_at_k")}


def _distribution(values):
    ordered = sorted(values)
    return {"samples": len(ordered), "p50": statistics.median(ordered) if ordered else None, "p95": ordered[max(0, math.ceil(.95 * len(ordered)) - 1)] if ordered else None}


def _peak_rss_bytes():
    import os
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        kernel32, psapi = ctypes.windll.kernel32, ctypes.windll.psapi
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        psapi.GetProcessMemoryInfo.argtypes = (ctypes.c_void_p, ctypes.POINTER(Counters), wintypes.DWORD)
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        if not psapi.GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            raise OSError("could not read process peak working set")
        return int(counters.PeakWorkingSetSize)
    import resource
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(value if __import__("sys").platform == "darwin" else value * 1024)


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _write_json(report, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".part")
    temp.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", default="data/benchmarks/vietnamese_employment_heldout_v1.json")
    parser.add_argument("--dev-cases", default="data/benchmarks/vietnamese_employment_retrieval_v1.json")
    parser.add_argument("--output", required=True)
    parser.add_argument("--model", default="data/models/e5-small")
    parser.add_argument("--reranker", default="data/models/bge-reranker-v2-m3")
    parser.add_argument("--corpus", default="data/curated/8977887f17be2defae4c5171d55562e1cde7d695/core-employment-portfolio-v1")
    parser.add_argument("--artifact", default="data/embeddings/core-employment-portfolio-v1-e5-small-provisional-v4")
    args = parser.parse_args()
    run(args.cases, args.output, model_path=args.model, reranker_path=args.reranker, corpus_root=args.corpus, artifact_dir=args.artifact, dev_cases_path=args.dev_cases)
