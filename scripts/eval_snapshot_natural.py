"""Offline frozen natural-question check; the injected selector is not a language model."""
import hashlib
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from answer_contract import validate_citations  # noqa: E402
import core_app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from provisional_policy import decide_snapshot_excerpt_eligibility  # noqa: E402

BENCHMARK = ROOT / "data/benchmarks/snapshot_excerpt_natural_questions_v2.json"
REVISION = "8977887f17be2defae4c5171d55562e1cde7d695"


class ReferenceSelector:
    calls = 0
    case = None

    def answer(self, question, legal_date, evidence):
        self.calls += 1
        case = self.case
        if case["kind"] != "answerable":
            return _abstain("frozen case is labeled non-answerable")
        relevant = set(case["relevant_article_ids"])
        match = next(((evidence_id, source) for evidence_id, source in evidence.items()
                      if evidence_id.split(":", 1)[0] in relevant), None)
        if match is None:
            return _abstain("no labeled relevant source reached selector")
        evidence_id, source = match
        text = source.get("canonical_text", "")
        clipped = text[:300]
        quote = clipped.rsplit(" ", 1)[0] if len(text) > 300 else clipped
        return {"state": "provisional", "legal_date": None, "text": quote,
                "claims": [{"claim_id": "frozen-reference", "text": quote,
                            "evidence_ids": [evidence_id]}],
                "citations": [{"evidence_id": evidence_id, "quote": quote,
                               "span_start": 0, "span_end": len(quote),
                               "document_version_id": source["document_version_id"]}],
                "reason": "", "unanswered": ""}


def _abstain(reason):
    return {"state": "abstain_insufficient_evidence", "legal_date": None,
            "text": "", "claims": [], "citations": [], "reason": reason,
            "unanswered": ""}


def _case_summary(case, body, status_code, elapsed_ms, selector_calls, retrieval_trace, articles):
    answer = body.get("answer", {})
    citations = answer.get("citations", [])
    citations = citations if isinstance(citations, list) else []
    validation = body.get("validation") or validate_citations(answer, {})
    selected = body.get("retrieval", {}).get("selected_evidence_ids", [])
    relevant = set(case["relevant_article_ids"])
    provider_relevant = sorted({item.split(":", 1)[0] for item in selected} & relevant)
    top12 = set(retrieval_trace["top12_article_ids"])
    retrieved = sorted(relevant & top12)
    citation = citations[0] if len(citations) == 1 else {}
    cited_article = citation.get("evidence_id", "").split(":", 1)[0]
    reference_diagnostics = {}
    for article_id in sorted(relevant):
        article = articles.get(article_id)
        if article is None:
            reference_diagnostics[article_id] = {"present_in_pinned_corpus": False}
            continue
        merged = {**article.get("document_metadata", {}), **article}
        decision = decide_snapshot_excerpt_eligibility(case["query"], [merged])
        in_top12 = article_id in top12
        provider_hit = article_id in provider_relevant
        if not in_top12:
            miss_reason = "outside_retrieval_top12"
        elif not decision.get("allowed"):
            miss_reason = decision.get("reason")
        elif not provider_hit:
            miss_reason = "not_selected_for_three_source_provider_cap"
        else:
            miss_reason = None
        reference_diagnostics[article_id] = {
            "present_in_pinned_corpus": True,
            "rrf_rank": retrieval_trace["rrf_ranks"].get(article_id),
            "in_retrieval_top12": in_top12,
            "in_provider_evidence": provider_hit,
            "reported_status_conflict": merged.get("reported_status_conflict"),
            "topic_candidates": merged.get("topic_candidates"),
            "snapshot_eligibility_reason": decision.get("reason"),
            "miss_reason": miss_reason,
        }
    expected = "provisional" if case["kind"] == "answerable" and provider_relevant else "abstain_insufficient_evidence"
    if case["kind"] != "answerable":
        expected = "abstain_insufficient_evidence"
    exact_answer = (answer.get("state") == "provisional" and validation.get("valid") is True
                    and cited_article in relevant and len(citations) == 1)
    safe_abstention = (answer.get("state") == "abstain_insufficient_evidence"
                       and validation.get("valid") is True and not citations)
    return {"case_id": case["case_id"], "split": case["split"], "kind": case["kind"],
            "query": case["query"], "relevant_article_ids": case["relevant_article_ids"],
            "status_code": status_code, "expected_state": expected,
            "state": answer.get("state"), "answer_contract_valid": validation.get("valid") is True,
            "retrieved_relevant_article_ids": retrieved,
            "retrieval_hit": bool(retrieved), "citation_count": len(citations),
            "relevant_rrf_ranks": {article_id: retrieval_trace["rrf_ranks"].get(article_id)
                                   for article_id in sorted(relevant)},
            "raw_candidate_count": retrieval_trace["fused_count"],
            "retrieval_top12_count": len(top12),
            "provider_evidence_relevant_article_ids": provider_relevant,
            "provider_evidence_hit": bool(provider_relevant),
            "cited_article_id": cited_article or None,
            "citation_is_relevant": bool(cited_article and cited_article in relevant),
            "reference_diagnostics": reference_diagnostics,
            "exact_answer": exact_answer, "safe_abstention": safe_abstention,
            "provider_selector_calls": selector_calls,
            "provider_evidence_count": body.get("retrieval", {}).get("evidence_count", 0),
            "quote_length_chars": len(citation.get("quote", "")),
            "quote_sha256": hashlib.sha256(citation.get("quote", "").encode("utf-8")).hexdigest(),
            "end_to_end_ms": round(elapsed_ms, 2),
            "retrieval_timings_ms": body.get("retrieval", {}).get("timings_ms", {})}


def _aggregate(rows):
    answerable = [row for row in rows if row["kind"] == "answerable"]
    return {"cases": len(rows), "answerable": len(answerable),
            "answerable_retrieval_hits": sum(row["retrieval_hit"] for row in answerable),
            "answerable_provider_evidence_hits": sum(row["provider_evidence_hit"] for row in answerable),
            "exact_answer_citations": sum(row["exact_answer"] for row in answerable),
            "answerable_safe_abstentions": sum(row["safe_abstention"] for row in answerable),
            "ambiguous_cases": sum(row["kind"] == "ambiguous" for row in rows),
            "negative_cases": sum(row["kind"] == "negative" for row in rows),
            "nonanswerable_safe_abstentions": sum(row["kind"] != "answerable" and row["safe_abstention"] for row in rows),
            "citation_contract_passes": sum(row["answer_contract_valid"] for row in rows)}


def main():
    benchmark = json.loads(BENCHMARK.read_text(encoding="utf-8"))
    if benchmark.get("dataset_revision") != REVISION or len(benchmark.get("cases", [])) != 19:
        raise ValueError("frozen natural-question benchmark does not match expected revision/case count")

    selector = ReferenceSelector()
    captured = []
    original_create_app = core_app.create_app
    def capture_retriever(*args, **kwargs):
        captured.append(kwargs["retriever"])
        return original_create_app(*args, **kwargs)
    with patch.object(core_app, "create_app", side_effect=capture_retriever):
        client = TestClient(core_app.create_core_app(provider=selector, experimental_snapshot_excerpt_enabled=True))
    retriever = captured[0]
    retrieval_traces = {}
    original_search = retriever.search_snapshot_excerpt
    def capture_search(query, *args, **kwargs):
        result = original_search(query, *args, **kwargs)
        fused = result.get("fused", [])
        retrieval_traces[query] = {"fused_count": len(fused),
                                   "rrf_ranks": {row["article_id"]: rank for rank, row in enumerate(fused, 1)},
                                   "top12_article_ids": [row["article_id"] for row in result.get("evidence", [])]}
        return result
    retriever.search_snapshot_excerpt = capture_search
    results = []
    for case in benchmark["cases"]:
        selector.case = case
        before = selector.calls
        started = time.perf_counter_ns()
        response = client.post("/api/answer", json={"question": case["query"]})
        elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
        results.append(_case_summary(case, response.json(), response.status_code, elapsed_ms,
                                     selector.calls - before, retrieval_traces.get(case["query"],
                                                                                  {"fused_count": 0, "rrf_ranks": {}, "top12_article_ids": []}),
                                     retriever.articles))
    splits = {name: _aggregate([row for row in results if row["split"] == name])
              for name in ("development", "held_out")}
    sorted_latency = sorted(row["end_to_end_ms"] for row in results)
    report = {"evaluation": benchmark["benchmark_id"], "dataset_revision": REVISION,
              "benchmark_sha256": hashlib.sha256(BENCHMARK.read_bytes()).hexdigest(),
              "provider": "injected deterministic reference selector; no external model calls",
              "provider_selector_calls": selector.calls,
              "interpretation": "Measures pinned local retrieval reach, safe response handling, and exact citation contract on frozen labels. The selector is given reference labels and does not measure model quality, Vietnamese semantic relevance, or legal correctness/validity.",
              "aggregate": _aggregate(results), "by_split": splits,
              "miss_reason_counts": {reason: sum(diagnostic.get("miss_reason") == reason
                                                  for row in results
                                                  for diagnostic in row["reference_diagnostics"].values())
                                     for reason in sorted({diagnostic.get("miss_reason")
                                                           for row in results
                                                           for diagnostic in row["reference_diagnostics"].values()
                                                           if diagnostic.get("miss_reason")})},
              "latency_ms": {"n": len(results), "median": round(sorted_latency[len(sorted_latency) // 2], 2),
                             "max": round(max(sorted_latency), 2)},
              "results": results}
    output = ROOT / "data/benchmarks/snapshot_excerpt_natural_questions_v2_results.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output.relative_to(ROOT)), "aggregate": report["aggregate"],
                      "by_split": splits, "latency_ms": report["latency_ms"],
                      "miss_reason_counts": report["miss_reason_counts"],
                      "provider_selector_calls": selector.calls}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
