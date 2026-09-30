"""One-call real-provider smoke, gated on explicit Free-tier confirmation and config."""
import argparse
import hashlib
import json
import time

from groq import GroqProvider, http_transport
from groq_config import load_config

MAX_PROVIDER_CALLS = 1
QUESTION = "Thời giờ nào được tính vào thời giờ làm việc hưởng lương?"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-free-tier", action="store_true",
                        help="confirm the configured Groq account is Free tier and permit one request")
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
    def bounded_transport(*args):
        nonlocal calls
        if calls >= MAX_PROVIDER_CALLS:
            raise RuntimeError("smoke provider call limit reached")
        calls += 1
        return transport(*args)

    provider = GroqProvider(config, bounded_transport, key)
    from core_app import create_core_app
    from fastapi.testclient import TestClient
    client = TestClient(create_core_app(provider=provider, experimental_snapshot_excerpt_enabled=True))
    started = time.perf_counter_ns()
    response = client.post("/api/answer", json={"question": QUESTION})
    elapsed_ms = round((time.perf_counter_ns() - started) / 1_000_000, 2)
    body, answer = response.json(), response.json().get("answer", {})
    citations = answer.get("citations", [])
    report = {"status": "complete" if response.status_code == 200 and body.get("validation", {}).get("valid") else "failed",
              "status_code": response.status_code, "max_provider_calls": MAX_PROVIDER_CALLS,
              "provider_calls": calls, "model": config.model, "answer_state": answer.get("state"),
              "legal_date": answer.get("legal_date"), "citation_valid": body.get("validation", {}).get("valid"),
              "citation_count": len(citations), "citations": [
                  {"evidence_id": citation.get("evidence_id"),
                   "quote_length_chars": len(citation.get("quote", "")),
                   "quote_sha256": hashlib.sha256(citation.get("quote", "").encode("utf-8")).hexdigest()}
                  for citation in citations],
              "end_to_end_ms": elapsed_ms,
              "retrieval_timings_ms": body.get("retrieval", {}).get("timings_ms", {}),
              "current_validity": [source.get("current_validity") for source in body.get("sources", [])],
              "caveat_present": bool(body.get("caveat")), "paid_fallback": False}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if calls > MAX_PROVIDER_CALLS or report["status"] != "complete" or answer.get("state") != "provisional" or answer.get("legal_date") is not None or not 1 <= len(citations) <= 3 or any(len(c.get("quote", "")) > 500 for c in citations):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
