import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import core_app  # noqa: E402
import smoke_snapshot_excerpt_groq as smoke  # noqa: E402
from groq import GROQ_BASE_URL, GROQ_MODEL, GROQ_ROUTE, GroqConfig  # noqa: E402


class GroqSmokeRunnerTest(unittest.TestCase):
    def test_main_invokes_mock_transport_and_classifies_provider_and_local_abstention(self):
        quote = "Thời giờ làm việc hưởng lương gồm thời gian nghỉ theo quy định."
        evidence_id = "article-v1"
        answer = {
            "state": "provisional", "legal_date": None, "text": quote,
            "claims": [{"claim_id": "c1", "text": quote, "evidence_ids": [evidence_id]}],
            "citations": [{"evidence_id": evidence_id, "quote": quote, "span_start": 0,
                           "span_end": len(quote), "document_version_id": "v1"}],
            "reason": "", "unanswered": "",
        }
        transport_responses = []

        def transport(*args):
            transport_responses.append(args)
            return {"choices": [{"message": {"content": json.dumps(answer, ensure_ascii=False)}}],
                    "usage": {"total_tokens": 7}}

        provider_config = GroqConfig(GROQ_BASE_URL, GROQ_ROUTE, GROQ_MODEL, True)
        evidence = {evidence_id: {"canonical_text": quote, "snapshot_excerpt_text": quote,
                                  "document_version_id": "v1"}}
        def build_app(*, provider, experimental_snapshot_excerpt_enabled):
            app = FastAPI()

            @app.post("/api/answer")
            def answer_endpoint(payload: dict):
                question = payload["question"]
                if question == smoke.CASES[1][1]:
                    abstention = {"state": "abstain_insufficient_evidence", "legal_date": None,
                                  "text": "", "claims": [], "citations": [],
                                  "reason": "local policy gate", "unanswered": ""}
                    return {"answer": abstention, "validation": {"valid": True},
                            "sources": [], "retrieval": {}, "caveat": "snapshot caveat"}
                try:
                    generated = provider.answer(question, None, evidence)
                except Exception:
                    return JSONResponse(status_code=503, content={
                        "answer": {"state": "unavailable", "legal_date": None, "text": "",
                                   "claims": [], "citations": [], "reason": "provider unavailable",
                                   "unanswered": ""},
                        "validation": {"valid": True}, "sources": [], "retrieval": {},
                    })
                return {"answer": generated, "validation": {"valid": True},
                        "sources": [], "retrieval": {"timings_ms": {}}}

            return app

        with tempfile.TemporaryDirectory() as directory:
            report_path = Path(directory) / "report.json"
            with (patch.object(smoke, "load_config", return_value=(provider_config, "test-key")),
                  patch.object(smoke, "http_transport", return_value=transport),
                  patch.object(core_app, "create_core_app", side_effect=build_app),
                  contextlib.redirect_stdout(io.StringIO())):
                status = smoke.main(["--confirm-free-tier", "--report", str(report_path)])
            report = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertEqual(status, 0, json.dumps(report, ensure_ascii=False))
        self.assertEqual(len(transport_responses), 1)
        self.assertEqual(report["provider_callback_attempts"], 1)
        self.assertEqual(report["http_transport_calls"], 1)
        self.assertEqual(report["cases"][0]["response_origin"], "provider_response")
        self.assertTrue(report["cases"][0]["provider_schema_and_citation_valid"])
        self.assertEqual(report["cases"][1]["response_origin"], "local_policy_gate")
        self.assertEqual(report["cases"][1]["citation_count"], 0)

        transport_responses.clear()
        checkpoint = smoke._checkpoint
        for failure_call, expected_stage in (
                (3, "callback_checkpoint_before_http"),
                (4, "transport_checkpoint_before_http")):
            transport_responses.clear()
            with tempfile.TemporaryDirectory() as directory:
                report_path = Path(directory) / "pre-transport-error.json"
                checkpoint_calls = 0

                def fail_at_transport_checkpoint(report, path):
                    nonlocal checkpoint_calls
                    checkpoint_calls += 1
                    if checkpoint_calls == failure_call:
                        raise AttributeError("simulated pre-transport checkpoint failure")
                    checkpoint(report, path)

                with (patch.object(smoke, "load_config", return_value=(provider_config, "test-key")),
                      patch.object(smoke, "http_transport", return_value=transport),
                      patch.object(core_app, "create_core_app", side_effect=build_app),
                      patch.object(smoke, "_checkpoint", side_effect=fail_at_transport_checkpoint),
                      contextlib.redirect_stdout(io.StringIO())):
                    status = smoke.main(["--confirm-free-tier", "--report", str(report_path)])
                failed_report = json.loads(report_path.read_text(encoding="utf-8"))

            self.assertEqual(status, 1)
            self.assertEqual(transport_responses, [])
            self.assertEqual(failed_report["provider_callback_attempts"], 1)
            self.assertEqual(failed_report["http_transport_calls"], 0)
            self.assertEqual(failed_report["pre_transport_error_type"], "AttributeError")
            self.assertEqual(failed_report["error_stage"], expected_stage)
            self.assertEqual(failed_report["cases"][0]["status_code"], 503)
            self.assertEqual(failed_report["cases"][0]["response_origin"],
                             "local_runner_error_before_transport")


if __name__ == "__main__":
    unittest.main()
