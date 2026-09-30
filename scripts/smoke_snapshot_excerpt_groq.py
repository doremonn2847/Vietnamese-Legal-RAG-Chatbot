"""At most one answer and one policy-abstention smoke, gated on Free-tier confirmation."""
import argparse
import hashlib
import json
import time

from answer_contract import validate_citations
from groq import GroqProvider, http_transport
from groq_config import load_config

MAX_PROVIDER_CALLS = 2
CASES = (
    ("ordinary", "Thời giờ nào được tính vào thời giờ làm việc hưởng lương?", "provisional"),
    ("abstention", "Bảo hiểm thất nghiệp được hưởng bao nhiêu?", "abstain_insufficient_evidence"),
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-free-tier", action="store_true",
                        help="confirm Free tier and permit at most one ordinary and one abstention request")
    args = parser.parse_args(argv)
    if not args.confirm_free_tier:
        print(json.dumps({"status": "blocked", "reason": "explicit Free-tier confirmation required",
                          "max_provider_calls": MAX_PROVIDER_CALLS}))
        return 2
    try:
        config, key = load_config()
    except (ValueError, OSError):
        print(json.dumps({"status": "blocked", "reason": "valid Groq configuration and key required",
                          "max_provider_calls": MAX_PROVIDER_CALLS}))
        return 2
    if not config.enabled or not key:
        print(json.dumps({"status": "blocked", "reason": "GROQ_ENABLED=true and GROQ_API_KEY required",
                          "max_provider_calls": MAX_PROVIDER_CALLS}))
        return 2

    transport = http_transport(timeout_seconds=10)
    calls = 0
    usage = []
    provider_errors = []
    def bounded_transport(*args):
        nonlocal calls
        if calls >= MAX_PROVIDER_CALLS:
            raise RuntimeError("smoke provider call limit reached")
        calls += 1
        try:
            response = transport(*args)
        except Exception as error:
            provider_errors.append({"type": type(error).__name__,
                                    "status": getattr(error, "status", None)})
            raise
        usage.append(response.get("usage") if isinstance(response, dict) else None)
        return response

    provider = GroqProvider(config, bounded_transport, key)
    from core_app import create_core_app
    from fastapi.testclient import TestClient
    client = TestClient(create_core_app(provider=provider, experimental_snapshot_excerpt_enabled=True))
    reports = []
    for case_id, question, expected_state in CASES:
        started = time.perf_counter_ns()
        response = client.post("/api/answer", json={"question": question})
        elapsed_ms = round((time.perf_counter_ns() - started) / 1_000_000, 2)
        body = response.json()
        answer = body.get("answer", {})
        citations = answer.get("citations", [])
        validation = body.get("validation") or validate_citations(answer, {})
        reports.append({"case": case_id, "question": question,
                        "status_code": response.status_code, "answer_state": answer.get("state"),
                        "expected_state": expected_state,
                        "state_matches": answer.get("state") == expected_state,
                        "strict_schema_and_citation_valid": validation.get("valid") is True,
                        "citation_count": len(citations),
                        "citations": [{"evidence_id": citation.get("evidence_id"),
                                       "quote": citation.get("quote"),
                                       "quote_length_chars": len(citation.get("quote", "")),
                                       "quote_sha256": hashlib.sha256(citation.get("quote", "").encode("utf-8")).hexdigest(),
                                       "document_version_id": citation.get("document_version_id")}
                                      for citation in citations],
                        "end_to_end_ms": elapsed_ms,
                        "retrieval_timings_ms": body.get("retrieval", {}).get("timings_ms", {}),
                        "current_validity": [source.get("current_validity") for source in body.get("sources", [])],
                        "caveat_present": bool(body.get("caveat")),
                        "provider_calls_after_case": calls})
    report = {"status": "complete" if all(row["status_code"] == 200 and row["state_matches"] and row["strict_schema_and_citation_valid"] for row in reports) else "failed",
              "max_provider_calls": MAX_PROVIDER_CALLS, "provider_calls": calls,
              "provider_calls_by_case": [row["provider_calls_after_case"] for row in reports],
              "provider_errors": provider_errors, "usage": usage, "model": config.model,
              "cases": reports, "no_retries": True, "paid_fallback": False}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    ordinary = reports[0]
    abstention = reports[1]
    if (calls > MAX_PROVIDER_CALLS or report["status"] != "complete"
            or not 1 <= ordinary["citation_count"] <= 3
            or any(c["quote_length_chars"] > 500 for c in ordinary["citations"])
            or abstention["citation_count"] != 0 or calls != 1):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
