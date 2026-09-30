"""Compare bounded local hybrid retrieval with a distinct CPU cross-encoder."""
import argparse
import hashlib
import json
import statistics
import time
from pathlib import Path

from core_retriever import CoreCorpusRetriever
from e5_artifacts import E5ArtifactSpec, load_transformers_encoder
from metrics import mrr_at_k, recall_at_k
from reranker_artifacts import RerankerSpec, load_transformers_reranker
from retrieval import rerank_candidates


def evaluate(cases_path, output_path, *, model_path, reranker_path, corpus_root, artifact_dir, candidate_limit=20, k=5):
    if type(candidate_limit) is not int or not 1 <= candidate_limit <= 50 or type(k) is not int or not 1 <= k <= 10:
        raise ValueError("candidate_limit must be 1..50 and k must be 1..10")
    cases_path, model_path, reranker_path = map(Path, (cases_path, model_path, reranker_path))
    source = cases_path.read_bytes()
    benchmark = json.loads(source.decode("utf-8"))
    cases = benchmark.get("cases") if isinstance(benchmark, dict) else None
    if not isinstance(cases, list) or not 1 <= len(cases) <= 50:
        raise ValueError("benchmark must contain 1..50 manually labeled cases")
    for case in cases:
        if not isinstance(case, dict) or not all(isinstance(case.get(key), str) and case[key].strip() for key in ("case_id", "query")) or not isinstance(case.get("relevant_article_ids"), list) or not case["relevant_article_ids"]:
            raise ValueError("every case requires an ID, Vietnamese query, and relevant article IDs")

    spec = E5ArtifactSpec.pinned_small()
    encoder = load_transformers_encoder(spec, model_path=model_path, tokenizer_path=model_path, local_files_only=True)
    retriever = CoreCorpusRetriever(Path(corpus_root) / "articles.jsonl", Path(corpus_root) / "corpus_manifest.json", artifact_dir, encoder, sparse_limit=30, dense_limit=30, evidence_cap=k)
    reranker_spec = RerankerSpec()
    reranker = load_transformers_reranker(reranker_spec, model_path=reranker_path, local_files_only=True)
    articles = retriever.articles
    rows = []
    for case in cases:
        start = time.perf_counter_ns()
        result = retriever.search(case["query"])
        baseline_ms = (time.perf_counter_ns() - start) / 1_000_000
        candidates = [{**hit, **articles[hit["article_id"]], "text": articles[hit["article_id"]]["canonical_text"]} for hit in result["fused"][:candidate_limit] if hit["article_id"] in articles]
        start = time.perf_counter_ns()
        scores = reranker.score(case["query"], candidates)
        reranker_ms = (time.perf_counter_ns() - start) / 1_000_000
        reranked = rerank_candidates(candidates, scores)
        relevant = case["relevant_article_ids"]
        rows.append({
            "case_id": case["case_id"], "candidate_count": len(candidates),
            "pre_rerank": _scores(result["fused"], relevant, k),
            "post_rerank": _scores(reranked, relevant, k),
            "baseline_latency_ms": baseline_ms, "reranker_latency_ms": reranker_ms,
            "pre_rerank_top_ids": [hit["article_id"] for hit in result["fused"][:k]],
            "post_rerank_top_ids": [hit["article_id"] for hit in reranked[:k]],
        })
    report = {
        "benchmark": {"id": benchmark.get("benchmark_id"), "sha256": hashlib.sha256(source).hexdigest(), "labeling": benchmark.get("labeling"), "cases": len(cases)},
        "corpus": {"id": benchmark.get("corpus_id"), "dataset_revision": benchmark.get("dataset_revision"), "manifest_sha256": _sha(Path(corpus_root) / "corpus_manifest.json")},
        "embedding_artifact": {"manifest_sha256": _sha(Path(artifact_dir) / "embedding_manifest.json"), "model_id": spec.model_id, "revision": spec.revision},
        "reranker": {"model_id": reranker_spec.model_id, "revision": reranker_spec.revision, "execution": "CPU", "manifest_sha256": _sha(reranker_path / "artifact_manifest.json")},
        "limits": {"sparse_candidates": 30, "dense_candidates": 30, "rerank_candidates": candidate_limit, "k": k},
        "retrieval_mode": "real pinned corpus and vectors, local exact dot-product dense search (no Qdrant request)",
        "results": rows,
        "summary": {name: {"mean_recall_at_k": statistics.mean(row[name]["recall_at_k"] for row in rows), "mean_mrr_at_k": statistics.mean(row[name]["mrr_at_k"] for row in rows)} for name in ("pre_rerank", "post_rerank")},
        "latency_ms": {"baseline_mean": statistics.mean(row["baseline_latency_ms"] for row in rows), "reranker_mean": statistics.mean(row["reranker_latency_ms"] for row in rows)},
        "claims": "retrieval-ranking engineering measurement only; labels are manually assigned section-heading relevance, not legal validity or advice",
    }
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp = output_path.with_suffix(output_path.suffix + ".part")
    temp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(output_path)
    return report


def _scores(ranked, relevant, k):
    return {"recall_at_k": recall_at_k(ranked, relevant, k), "mrr_at_k": mrr_at_k(ranked, relevant, k)}


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", default="data/benchmarks/vietnamese_employment_retrieval_v1.json")
    parser.add_argument("--output", required=True)
    parser.add_argument("--model", default="data/models/e5-small")
    parser.add_argument("--reranker", required=True, help="local BGE reranker directory; downloads are never attempted")
    parser.add_argument("--corpus", default="data/curated/8977887f17be2defae4c5171d55562e1cde7d695/core-employment-portfolio-v1")
    parser.add_argument("--artifact", default="data/embeddings/core-employment-portfolio-v1-e5-small-provisional-v4")
    parser.add_argument("--candidate-limit", type=int, default=20)
    parser.add_argument("--k", type=int, default=5)
    args = parser.parse_args()
    evaluate(args.cases, args.output, model_path=args.model, reranker_path=args.reranker, corpus_root=args.corpus, artifact_dir=args.artifact, candidate_limit=args.candidate_limit, k=args.k)
