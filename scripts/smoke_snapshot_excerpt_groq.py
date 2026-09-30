"""At most one answer and one policy-abstention smoke, gated on Free-tier confirmation."""
import argparse
import hashlib
import json
from pathlib import Path
import time

from answer_contract import validate_citations
from groq import GroqProvider, http_transport
from groq_config import load_config

MAX_PROVIDER_CALLS = 2
CASES = (
    ("ordinary", "Thời giờ nào được tính vào thời giờ làm việc hưởng lương?", "provisional"),
    ("abstention", "Bảo hiểm thất nghiệp được hưởng bao nhiêu?", "abstain_insufficient_evidence"),
)
REPORT_PATH = Path("data/benchmarks/groq_free_smoke_report.json")


def _citation_summary(citation):
    quote = citation.get("quote", "")
    return {"evidence_id": citation.get("evidence_id"),
            "document_version_id": citation.get("document_version_id"),
            "span_start": citation.get("span_start"), "span_end": citation.get("span_end"),
            "quote_length_chars": len(quote),
            "quote_sha256": hashlib.sha256(quote.encode("utf-8")).hexdigest()}


def _checkpoint(report, path=REPORT_PATH):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


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
    report = {"status": "in_progress", "max_provider_calls": MAX_PROVIDER_CALLS,
              "provider_calls": calls, "provider_errors": provider_errors,
              "usage": usage, "model": config.model, "cases": [],
              "no_retries": True, "paid_fallback": False}
    current_case = None
    def bounded_transport(*args):
        nonlocal calls
        if calls >= MAX_PROVIDER_CALLS:
            raise RuntimeError("smoke provider call limit reached")
        calls += 1
        report["provider_calls"] = calls
        report["call_attempts"] = report.get("call_attempts", []) + [{"case": current_case, "state": "attempt_started"}]
        _checkpoint(report)
        try:
            response = transport(*args)
        except Exception as error:
            provider_errors.append({"type": type(error).__name__,
                                    "status": getattr(error, "status", None)})
            report["call_attempts"][-1]["state"] = "transport_error"
            _checkpoint(report)
            raise
        usage.append(response.get("usage") if isinstance(response, dict) else None)
        report["call_attempts"][-1]["state"] = "response_received"
        _checkpoint(report)
        return response

    provider = GroqProvider(config, bounded_transport, key)
    from core_app import create_core_app
    from fastapi.testclient import TestClient
    client = TestClient(create_core_app(provider=provider, experimental_snapshot_excerpt_enabled=True))
    for case_id, question, expected_state in CASES:
        current_case = case_id
        case_report = {"case": case_id, "status": "in_progress", "expected_state": expected_state}
        report["cases"].append(case_report)
        _checkpoint(report)
        started = time.perf_counter_ns()
        try:
            response = client.post("/api/answer", json={"question": question})
            status_code = response.status_code
            body = response.json()
        except Exception as error:
            case_report.update(status="request_error", error_type=type(error).__name__,
                               end_to_end_ms=round((time.perf_counter_ns() - started) / 1_000_000, 2))
            _checkpoint(report)
            continue
        elapsed_ms = round((time.perf_counter_ns() - started) / 1_000_000, 2)
        answer = body.get("answer", {})
        citations = answer.get("citations", [])
        citations = citations if isinstance(citations, list) else []
        validation = body.get("validation") or validate_citations(answer, {})
        case_report.update({"status_code": status_code, "answer_state": answer.get("state"),
                            "state_matches": answer.get("state") == expected_state,
                            "strict_schema_and_citation_valid": validation.get("valid") is True,
                            "citation_count": len(citations),
                            "citations": [_citation_summary(citation) for citation in citations],
                            "end_to_end_ms": elapsed_ms,
                            "retrieval_timings_ms": body.get("retrieval", {}).get("timings_ms", {}),
                            "current_validity": [source.get("current_validity") for source in body.get("sources", [])],
                            "caveat_present": bool(body.get("caveat")),
                            "provider_calls_after_case": calls,
                            "status": "complete" if status_code == 200 and answer.get("state") == expected_state and validation.get("valid") is True else "failed"})
        _checkpoint(report)
    reports = report["cases"]
    report["status"] = "complete" if len(reports) == len(CASES) and all(row.get("status") == "complete" for row in reports) else "failed"
    _checkpoint(report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    ordinary = reports[0]
    abstention = reports[1]
    if (calls > MAX_PROVIDER_CALLS or report["status"] != "complete"
            or ordinary.get("status") != "complete" or abstention.get("status") != "complete"
            or not 1 <= ordinary.get("citation_count", 0) <= 3
            or any(c["quote_length_chars"] > 500 for c in ordinary.get("citations", []))
            or abstention.get("citation_count") != 0 or calls != 1):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
