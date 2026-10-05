"""At most one answer and one policy-abstention smoke, gated on Free-tier confirmation."""
import argparse
from datetime import datetime, timezone
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


def _provider_responded(attempts, case_id):
    return any(row.get("case") == case_id and row.get("state") == "response_received"
               for row in attempts)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-free-tier", action="store_true",
                        help="confirm Free tier and permit at most one ordinary and one abstention request")
    parser.add_argument("--report", type=Path, default=REPORT_PATH,
                        help="sanitized checkpoint path")
    args = parser.parse_args(argv)
    report_path = args.report
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
    callback_attempts = 0
    transport_calls = 0
    usage = []
    provider_errors = []
    report = {"status": "in_progress", "max_provider_calls": MAX_PROVIDER_CALLS,
              "provider_callback_attempts": callback_attempts, "http_transport_calls": transport_calls,
              "provider_call_count_semantics": "callback attempts vs actual HTTP transport invocations",
              "provider_errors": provider_errors,
              "usage": usage, "model": config.model, "cases": [],
              "no_retries": True, "paid_fallback": False,
              "attempt_started_at_utc": datetime.now(timezone.utc).isoformat()}
    _checkpoint(report, report_path)
    current_case = None
    def fail_before_transport(error, stage, attempt):
        attempt["state"] = "pre_transport_error"
        report["pre_transport_error_type"] = type(error).__name__
        report["error_stage"] = stage
        _checkpoint(report, report_path)

    def bounded_transport(*args):
        nonlocal callback_attempts, transport_calls
        if callback_attempts >= MAX_PROVIDER_CALLS:
            raise RuntimeError("smoke provider call limit reached")
        callback_attempts += 1
        report["provider_callback_attempts"] = callback_attempts
        attempt = {"case": current_case, "state": "callback_started"}
        report["call_attempts"] = report.get("call_attempts", []) + [attempt]
        try:
            _checkpoint(report, report_path)
        except Exception as error:
            fail_before_transport(error, "callback_checkpoint_before_http", attempt)
            raise
        transport_calls += 1
        report["http_transport_calls"] = transport_calls
        attempt["state"] = "http_transport_started"
        try:
            _checkpoint(report, report_path)
        except Exception as error:
            transport_calls -= 1
            report["http_transport_calls"] = transport_calls
            fail_before_transport(error, "transport_checkpoint_before_http", attempt)
            raise
        try:
            response = transport(*args)
        except Exception as error:
            provider_errors.append({"case": current_case, "type": type(error).__name__,
                                    "status": getattr(error, "status", None)})
            attempt["state"] = "transport_error"
            _checkpoint(report, report_path)
            raise
        usage.append(response.get("usage") if isinstance(response, dict) else None)
        attempt["state"] = "response_received"
        _checkpoint(report, report_path)
        return response

    try:
        provider = GroqProvider(config, bounded_transport, key)
        from core_app import create_core_app
        from fastapi.testclient import TestClient
        client = TestClient(create_core_app(provider=provider, experimental_snapshot_excerpt_enabled=True))
    except Exception as error:
        report.update(status="startup_error", startup_error_type=type(error).__name__)
        _checkpoint(report, report_path)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1
    for case_id, question, expected_state in CASES:
        current_case = case_id
        case_report = {"case": case_id, "status": "in_progress", "expected_state": expected_state}
        report["cases"].append(case_report)
        _checkpoint(report, report_path)
        started = time.perf_counter_ns()
        try:
            response = client.post("/api/answer", json={"question": question})
            status_code = response.status_code
            body = response.json()
        except Exception as error:
            case_report.update(status="request_error", error_type=type(error).__name__,
                               end_to_end_ms=round((time.perf_counter_ns() - started) / 1_000_000, 2))
            _checkpoint(report, report_path)
            continue
        elapsed_ms = round((time.perf_counter_ns() - started) / 1_000_000, 2)
        answer = body.get("answer", {})
        citations = answer.get("citations", [])
        citations = citations if isinstance(citations, list) else []
        validation = body.get("validation") or validate_citations(answer, {})
        provider_response_received = _provider_responded(report.get("call_attempts", []), case_id)
        provider_answer_contract_valid = (validation.get("valid") is True
                                           if provider_response_received and status_code == 200 else None)
        if provider_response_received:
            response_origin = "provider_response"
            vietnamese_relevance = "manual_review_required"
        elif any(error.get("case") == case_id for error in provider_errors):
            response_origin = "local_fallback_after_provider_error"
            vietnamese_relevance = "not_assessed_no_provider_answer"
        elif any(row.get("case") == case_id for row in report.get("call_attempts", [])):
            response_origin = "local_runner_error_before_transport"
            vietnamese_relevance = "not_assessed_no_provider_answer"
        else:
            response_origin = "local_policy_gate"
            vietnamese_relevance = "out_of_scope_gate_only"
        case_report.update({"status_code": status_code, "answer_state": answer.get("state"),
                            "response_origin": response_origin,
                            "vietnamese_relevance": vietnamese_relevance,
                            "state_matches": answer.get("state") == expected_state,
                            "provider_schema_and_citation_valid": provider_answer_contract_valid,
                            "visible_answer_contract_valid": validation.get("valid") is True,
                            "citation_count": len(citations),
                            "citations": [_citation_summary(citation) for citation in citations],
                            "end_to_end_ms": elapsed_ms,
                            "retrieval_timings_ms": body.get("retrieval", {}).get("timings_ms", {}),
                            "current_validity": [source.get("current_validity") for source in body.get("sources", [])],
                            "caveat_present": bool(body.get("caveat")),
                            "provider_callback_attempts_after_case": callback_attempts,
                            "http_transport_calls_after_case": transport_calls,
                            "status": "complete" if status_code == 200 and answer.get("state") == expected_state and validation.get("valid") is True else "failed"})
        _checkpoint(report, report_path)
    reports = report["cases"]
    report["status"] = "complete" if len(reports) == len(CASES) and all(row.get("status") == "complete" for row in reports) else "failed"
    _checkpoint(report, report_path)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    ordinary = reports[0]
    abstention = reports[1]
    if (callback_attempts > MAX_PROVIDER_CALLS or report["status"] != "complete"
            or ordinary.get("status") != "complete" or abstention.get("status") != "complete"
            or not 1 <= ordinary.get("citation_count", 0) <= 3
            or any(c["quote_length_chars"] > 1000 for c in ordinary.get("citations", []))
            or abstention.get("citation_count") != 0 or callback_attempts != 1 or transport_calls != 1):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
