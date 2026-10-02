import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from contextlib import redirect_stdout
from urllib.error import HTTPError
from unittest.mock import patch

from app import DEMO_EVIDENCE, create_app
from answer_contract import validate_citations
from groq import ANSWER_SCHEMA, RESPONSE_FORMAT, GroqConfig, GroqProvider, ProviderHTTPError, http_transport
from smoke_snapshot_excerpt_groq import (_checkpoint, _citation_summary, _provider_responded,
                                         main as snapshot_smoke_main)


class GroqTest(unittest.TestCase):
    def setUp(self):
        self.config = GroqConfig("https://api.groq.com/openai/v1", "chat/completions", "openai/gpt-oss-20b", True)
        self.quote = DEMO_EVIDENCE["fiction-e1"]["canonical_text"]
        self.answer = {"state": "answer", "legal_date": "2024-01-01", "text": self.quote, "claims": [{"claim_id": "c1", "text": self.quote, "evidence_ids": ["fiction-e1"]}], "citations": [{"evidence_id": "fiction-e1", "quote": self.quote, "span_start": 0, "span_end": len(self.quote), "document_version_id": "fiction-v1"}], "reason": "", "unanswered": ""}

    def test_smoke_citation_report_omits_raw_quote(self):
        summary = _citation_summary(self.answer["citations"][0])
        self.assertEqual(summary["quote_length_chars"], len(self.quote))
        self.assertNotIn(self.quote, json.dumps(summary, ensure_ascii=False))
        self.assertEqual(summary["span_start"], 0)

    def test_smoke_distinguishes_transport_error_from_provider_response(self):
        attempts = [{"case": "ordinary", "state": "transport_error"},
                    {"case": "abstention", "state": "local_gate"}]
        self.assertFalse(_provider_responded(attempts, "ordinary"))
        attempts.append({"case": "ordinary", "state": "response_received"})
        self.assertTrue(_provider_responded(attempts, "ordinary"))

    def test_smoke_checkpoint_replaces_report_atomically(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            _checkpoint({"provider_calls": 0, "status": "in_progress"}, path)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["provider_calls"], 0)
            self.assertFalse(path.with_suffix(".json.tmp").exists())

    def test_disabled_and_exact_structured_request(self):
        with self.assertRaises(RuntimeError): GroqProvider(GroqConfig(), lambda *args: None).generate([])
        calls = []
        provider = GroqProvider(self.config, lambda *args: calls.append(args) or {"choices": [{"message": {"content": json.dumps(self.answer)}}], "usage": {"total_tokens": 1}}, "not-logged")
        self.assertEqual(provider.answer("q", "2024-01-01", {"fiction-e1": DEMO_EVIDENCE["fiction-e1"]})["state"], "answer")
        method, url, body, headers = calls[0]
        self.assertEqual((method, url), ("POST", "https://api.groq.com/openai/v1/chat/completions"))
        self.assertTrue(headers["Authorization"].startswith("Bearer "))
        self.assertEqual(headers["User-Agent"], "LegalRAGChatbot/0.1")
        self.assertEqual(headers["Accept"], "application/json")
        self.assertNotIn("not-logged", str(body))
        self.assertEqual(body.get("reasoning_effort"), "low")
        self.assertEqual(body.get("temperature"), 0)
        self.assertEqual((body["model"], body["stream"], body["response_format"]["type"], body["response_format"]["json_schema"]["strict"]), ("openai/gpt-oss-20b", False, "json_schema", True))
        schema = body["response_format"]["json_schema"]["schema"]
        self.assertEqual(set(schema["required"]), {"state", "legal_date", "text", "claims", "citations", "reason", "unanswered"})
        self.assertFalse(schema["additionalProperties"])
        self.assertFalse(schema["properties"]["claims"]["items"]["additionalProperties"])
        self.assertFalse(schema["properties"]["citations"]["items"]["additionalProperties"])

    def test_direct_enabled_provider_rejects_nonallowlisted_or_missing_key(self):
        for config, key in ((GroqConfig("https://other.invalid", "chat/completions", "openai/gpt-oss-20b", True), "key"), (GroqConfig("https://api.groq.com/openai/v1", "chat/completions", "other", True), "key"), (self.config, None), (self.config, " ")):
            with self.subTest(config=config, key=key), self.assertRaises(ValueError):
                GroqProvider(config, lambda *args: None, key)

    def test_unique_span_repair_and_malformed_output_fail_closed(self):
        bad_span = {**self.answer, "citations": [{**self.answer["citations"][0], "span_end": len(self.quote) - 1}]}
        provider = GroqProvider(self.config, lambda *args: {"choices": [{"message": {"content": json.dumps(bad_span)}}]}, "key")
        self.assertEqual(provider.answer("q", "2024-01-01", {"fiction-e1": DEMO_EVIDENCE["fiction-e1"]})["citations"][0]["span_end"], len(self.quote))
        malformed = GroqProvider(self.config, lambda *args: {"choices": [{"message": {"content": "```json\n{}\n```"}}]}, "key")
        with self.assertRaises(ValueError): malformed.answer("q", "2024-01-01", {"fiction-e1": DEMO_EVIDENCE["fiction-e1"]})
        response = create_app(malformed)
        from fastapi.testclient import TestClient
        self.assertEqual(TestClient(response).post("/api/answer", json={"question": "thử việc", "legal_date": "2024-01-01"}).status_code, 502)

    def test_ambiguous_quote_is_not_repaired_and_fails_citation_validation(self):
        quote = "Repeated extract."
        source = {"canonical_text": quote + " Other text. " + quote, "document_version_id": "v1",
                  "provisional_snapshot_eligible": True, "pham_vi": "Trung ương",
                  "retrieval_index_candidate": True, "current_validity": "unverified",
                  "expiry_state": "unknown_expiry", "reported_status_conflict": False,
                  "source_dataset_revision": "r1", "content_sha256": "hash"}
        answer = {"state": "provisional", "legal_date": None, "text": quote,
                  "claims": [{"claim_id": "c1", "text": quote, "evidence_ids": ["a1:v1"]}],
                  "citations": [{"evidence_id": "a1:v1", "quote": quote, "span_start": 0,
                                 "span_end": len(quote) - 1, "document_version_id": "v1"}]}
        provider = GroqProvider(self.config, lambda *args: {"choices": [{"message": {"content": json.dumps(answer)}}]}, "key")
        result = provider.answer("q", None, {"a1:v1": source})
        self.assertEqual(result["citations"][0]["span_end"], len(quote) - 1)
        self.assertFalse(validate_citations(result, {"a1:v1": source})["valid"])

    def test_provisional_request_marks_evidence_as_snapshot_only_and_uses_generic_version_id(self):
        quote = "Điều 24. Thử việc."
        calls = []
        answer = {"state": "provisional", "legal_date": None, "text": quote,
                  "claims": [{"claim_id": "c1", "text": quote, "evidence_ids": ["a1:v1"]}],
                  "citations": [{"evidence_id": "a1:v1", "quote": quote, "span_start": 0, "span_end": len(quote), "document_version_id": "v1"}], "reason": "", "unanswered": ""}
        provider = GroqProvider(self.config, lambda *args: calls.append(args) or {"choices": [{"message": {"content": json.dumps(answer)}}], "usage": {}}, "key")
        source = {"canonical_text": quote, "document_version_id": "v1", "provisional_snapshot_eligible": True}
        self.assertEqual(provider.answer("Điều 24 nói gì?", None, {"a1:v1": source})["state"], "provisional")
        body = calls[0][2]
        self.assertIn("never assert current validity", body["messages"][0]["content"])
        self.assertIn("copy the full selected_evidence[].evidence_id strings exactly", body["messages"][0]["content"])
        self.assertIn("Set text to the claim texts joined with a single space", body["messages"][0]["content"])
        request = json.loads(body["messages"][1]["content"])
        self.assertIsNone(request["legal_date"])
        self.assertTrue(request["selected_evidence"][0]["provisional_snapshot_only"])

    def test_snapshot_mode_narrows_only_its_request_schema(self):
        calls = []
        provider = GroqProvider(
            self.config,
            lambda *args: calls.append(args) or {
                "choices": [{"message": {"content": json.dumps(self.answer)}}], "usage": {}},
            "key")
        snapshot = {"canonical_text": "Snapshot source.", "document_version_id": "snapshot-v1",
                    "provisional_snapshot_eligible": True}
        requests = [
            ("snapshot", None, {"snapshot:v1": snapshot}),
            ("dated reviewed", "2024-01-01", {"fiction-e1": DEMO_EVIDENCE["fiction-e1"]}),
            ("empty evidence", None, {}),
            ("mixed evidence", None, {"snapshot:v1": snapshot,
                                       "fiction-e1": DEMO_EVIDENCE["fiction-e1"]}),
        ]
        for question, legal_date, evidence in requests:
            provider.answer(question, legal_date, evidence)

        global_states = ["answer", "partial", "provisional", "clarify", "unavailable",
                         "abstain_conflict", "abstain_insufficient_evidence"]
        snapshot_states = ["provisional", "clarify", "unavailable", "abstain_conflict",
                           "abstain_insufficient_evidence"]
        self.assertEqual(RESPONSE_FORMAT["json_schema"]["schema"]["properties"]["state"]["enum"], global_states)
        self.assertEqual(ANSWER_SCHEMA["properties"]["state"]["enum"], global_states)
        self.assertEqual(calls[0][2]["response_format"]["json_schema"]["schema"]["properties"]["state"]["enum"], snapshot_states)
        self.assertIn("snapshot-only", calls[0][2]["messages"][0]["content"].lower())
        self.assertIn("must use state provisional", calls[0][2]["messages"][0]["content"].lower())
        for call in calls[1:]:
            self.assertEqual(call[2]["response_format"]["json_schema"]["schema"]["properties"]["state"]["enum"], global_states)
            self.assertNotIn("snapshot-only", call[2]["messages"][0]["content"].lower())

    def test_experimental_snapshot_prompt_uses_bounded_source_text(self):
        quote = "Điều 24. Trích nguyên văn."
        answer = {"state": "provisional", "legal_date": None, "text": quote,
                  "claims": [{"claim_id": "q1", "text": quote, "evidence_ids": ["a1:v1"]}],
                  "citations": [{"evidence_id": "a1:v1", "quote": quote, "span_start": 0,
                                 "span_end": len(quote), "document_version_id": "v1"}],
                  "reason": "", "unanswered": ""}
        calls = []
        provider = GroqProvider(self.config, lambda *args: calls.append(args) or {
            "choices": [{"message": {"content": json.dumps(answer)}}], "usage": {}}, "key")
        full_text = "x" * 7000
        provider.answer("q", None, {"a1:v1": {"canonical_text": full_text, "snapshot_excerpt_text": quote,
                                               "document_version_id": "v1", "provisional_snapshot_eligible": True}})
        request = json.loads(calls[0][2]["messages"][1]["content"])
        self.assertEqual(request["selected_evidence"][0]["canonical_text"], quote)
        self.assertNotIn(full_text, str(calls[0][2]))

    def test_real_snapshot_smoke_requires_explicit_free_tier_and_enabled_config(self):
        output = io.StringIO()
        with patch("smoke_snapshot_excerpt_groq.load_config", return_value=(GroqConfig(), None)), \
             patch("core_app.create_core_app", side_effect=AssertionError("must not start app without enabled provider")), \
             redirect_stdout(output):
            self.assertEqual(snapshot_smoke_main([]), 2)
            self.assertEqual(snapshot_smoke_main(["--confirm-free-tier"]), 2)
        self.assertIn('"max_provider_calls": 2', output.getvalue())
        self.assertNotIn("not-logged", output.getvalue())
        self.assertNotIn("Bearer", output.getvalue())

    def test_http_transport_is_bounded_and_does_not_retry(self):
        class Response:
            def __init__(self, body): self.body = body
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, size): return self.body
        calls = []
        self.assertEqual(http_transport(timeout_seconds=1, opener=lambda request, timeout: calls.append((request, timeout)) or Response(b'{"choices":[]}'))("POST", "https://api.groq.com", {}, {})["choices"], [])
        self.assertEqual(len(calls), 1)
        for error, expected in ((HTTPError("https://api.groq.com", 429, "rate", None, None), RuntimeError),
                                (TimeoutError(), TimeoutError)):
            with self.subTest(error=type(error)), self.assertRaises(expected):
                http_transport(timeout_seconds=1, opener=lambda *_, **__: (_ for _ in ()).throw(error))("POST", "https://api.groq.com", {}, {})
        with self.assertRaises(ValueError):
            http_transport(timeout_seconds=1, max_response_bytes=8, opener=lambda *_, **__: Response(b"x" * 9))("POST", "https://api.groq.com", {}, {})
        with self.assertRaises(ValueError):
            http_transport(timeout_seconds=1, opener=lambda *_, **__: Response(b"not-json"))("POST", "https://api.groq.com", {}, {})

    def test_http_status_is_safe_to_classify_without_response_details(self):
        error = HTTPError("https://api.groq.com/secret", 429, "secret-message", None, io.BytesIO(b"secret-body"))
        with self.assertRaises(ProviderHTTPError) as caught:
            http_transport(timeout_seconds=1, opener=lambda *_, **__: (_ for _ in ()).throw(error))("POST", "https://api.groq.com", {}, {})
        self.assertEqual(caught.exception.status, 429)
        self.assertNotIn("secret", str(caught.exception))

    def test_http_error_classifications_are_bounded_allowlisted_and_private(self):
        from fastapi.testclient import TestClient

        class TrackingBody(io.BytesIO):
            def __init__(self, body):
                super().__init__(body)
                self.read_sizes = []
            def read(self, size=-1):
                self.read_sizes.append(size)
                return super().read(size)

        cases = (
            ({"message": "JSON schema rejected for response_format", "type": "invalid_request_error",
              "code": "json_validate_failed", "param": "response_format", "failed_generation": "PRIVATE_FAILED_GENERATION"},
             "structured_output_rejected", "invalid_request_error", "json_validate_failed", "response_format"),
            ({"message": "Unsupported max_completion_tokens", "type": "invalid_request_error",
              "code": "unsupported_value", "param": "max_completion_tokens"},
             "request_parameter_rejected", "invalid_request_error", "unsupported_value", "max_completion_tokens"),
            ({"message": "PRIVATE_MESSAGE", "type": "PRIVATE_TYPE", "code": "PRIVATE_CODE",
              "param": "PRIVATE_PARAM", "failed_generation": "PRIVATE_FAILED_GENERATION"},
             "other", "other", "other", "other"),
        )
        for error_payload, category, safe_type, safe_code, safe_param in cases:
            with self.subTest(category=category):
                body = TrackingBody(json.dumps({"error": error_payload}).encode("utf-8"))
                upstream = HTTPError("https://api.groq.com", 400, "private reason", None, body)
                events = []
                transport = http_transport(opener=lambda *args, **kwargs: (_ for _ in ()).throw(upstream))
                provider = GroqProvider(self.config, transport, "key")
                response = TestClient(create_app(provider, events)).post(
                    "/api/answer", json={"question": "thử việc", "legal_date": "2024-01-01"})
                provider_event = next(row for row in events if row["stage"] == "provider")
                diagnostic = provider_event["diagnostics"][0]
                self.assertEqual((response.status_code, response.json()["state"]), (503, "unavailable"))
                self.assertEqual(diagnostic["upstream_http_status"], 400)
                self.assertEqual(diagnostic["upstream_error_classification"], category)
                self.assertEqual(diagnostic["upstream_error_type"], safe_type)
                self.assertEqual(diagnostic["upstream_error_code"], safe_code)
                self.assertEqual(diagnostic["upstream_error_param"], safe_param)
                self.assertTrue(body.closed)
                self.assertEqual(body.read_sizes, [16 * 1024 + 1])
                self.assertNotIn("PRIVATE_", json.dumps(events) + str(upstream))

    def test_bad_http_error_bodies_keep_status_and_route_mapping(self):
        from fastapi.testclient import TestClient

        class TrackingBody:
            def __init__(self, *, data=None, fail=False):
                self.data, self.fail, self.closed, self.read_sizes = data, fail, False, []
            def read(self, size):
                self.read_sizes.append(size)
                if self.fail:
                    raise OSError("PRIVATE_READ_FAILURE")
                return self.data
            def close(self):
                self.closed = True

        cases = ((TrackingBody(data=b"{bad"), 4),
                 (TrackingBody(data=b"123456789"), 4),
                 (TrackingBody(fail=True), 64),
                 (TrackingBody(data=b"[" * 6000 + b"]" * 6000), 16 * 1024))
        for body, max_response_bytes in cases:
            with self.subTest(fail=body.fail, size=max_response_bytes):
                upstream = HTTPError("https://api.groq.com", 400, "private reason", None, body)
                events = []
                transport = http_transport(max_response_bytes=max_response_bytes,
                    opener=lambda *args, **kwargs: (_ for _ in ()).throw(upstream))
                provider = GroqProvider(self.config, transport, "key")
                response = TestClient(create_app(provider, events)).post(
                    "/api/answer", json={"question": "thử việc", "legal_date": "2024-01-01"})
                diagnostic = next(row for row in events if row["stage"] == "provider")["diagnostics"][0]
                self.assertEqual(response.status_code, 503)
                self.assertEqual(diagnostic["upstream_http_status"], 400)
                self.assertNotIn("upstream_error_classification", diagnostic)
                self.assertTrue(body.closed)
                self.assertEqual(body.read_sizes, [min(max_response_bytes, 16 * 1024) + 1])
                self.assertNotIn("PRIVATE_READ_FAILURE", json.dumps(events))

    def test_http_error_classifier_failure_preserves_status_and_route_mapping(self):
        from fastapi.testclient import TestClient
        body = io.BytesIO(b'{"error":{"type":"invalid_request_error"}}')
        upstream = HTTPError("https://api.groq.com", 400, "private reason", None, body)
        events = []
        transport = http_transport(opener=lambda *args, **kwargs: (_ for _ in ()).throw(upstream))
        provider = GroqProvider(self.config, transport, "key")
        with patch("groq._classify_upstream_http_error", side_effect=RuntimeError("PRIVATE_CLASSIFIER_FAILURE")):
            response = TestClient(create_app(provider, events)).post(
                "/api/answer", json={"question": "thử việc", "legal_date": "2024-01-01"})
        diagnostic = next(row for row in events if row["stage"] == "provider")["diagnostics"][0]
        self.assertEqual(response.status_code, 503)
        self.assertEqual(diagnostic["upstream_http_status"], 400)
        self.assertEqual(diagnostic["exception_class"], "HTTPError")
        self.assertTrue(body.closed)
        self.assertNotIn("PRIVATE_CLASSIFIER_FAILURE", json.dumps(events))

    def test_failed_generation_metadata_is_syntax_only_and_never_retains_content(self):
        from fastapi.testclient import TestClient

        non_json_decode_error = '{"number":' + '9' * 5000 + '}'
        cases = (
            ({"type": "invalid_request_error", "code": "unknown_parameter", "param": "x"},
             False, None, "absent"),
            ({"type": "invalid_request_error", "code": "unknown_parameter", "param": "x", "failed_generation": None},
             True, None, "not_string"),
            ({"type": "invalid_request_error", "code": "unknown_parameter", "param": "x",
              "failed_generation": '{"answer":"SECRET_VALID_JSON"}'},
             True, len('{"answer":"SECRET_VALID_JSON"}'), "valid"),
            ({"type": "invalid_request_error", "code": "unknown_parameter", "param": "x",
              "failed_generation": '{"answer":"SECRET_INVALID_JSON"'},
             True, len('{"answer":"SECRET_INVALID_JSON"'), "invalid"),
            ({"type": "invalid_request_error", "code": "unknown_parameter", "param": "x",
              "failed_generation": "NaN"}, True, 3, "invalid"),
            ({"type": "invalid_request_error", "code": "unknown_parameter", "param": "x",
              "failed_generation": "Infinity"}, True, 8, "invalid"),
            ({"type": "invalid_request_error", "code": "unknown_parameter", "param": "x",
              "failed_generation": "-Infinity"}, True, 9, "invalid"),
            ({"type": "invalid_request_error", "code": "unknown_parameter", "param": "x",
              "failed_generation": non_json_decode_error},
             True, len(non_json_decode_error), "unassessed"),
        )
        for error_payload, present, length, verdict in cases:
            with self.subTest(verdict=verdict):
                upstream = HTTPError("https://api.groq.com", 400, "private reason", None,
                                     io.BytesIO(json.dumps({"error": error_payload}).encode("utf-8")))
                events = []
                provider = GroqProvider(self.config,
                    http_transport(opener=lambda *args, **kwargs: (_ for _ in ()).throw(upstream)), "key")
                response = TestClient(create_app(provider, events)).post(
                    "/api/answer", json={"question": "thử việc", "legal_date": "2024-01-01"})
                diagnostic = next(row for row in events if row["stage"] == "provider")["diagnostics"][0]
                self.assertEqual(response.status_code, 503)
                self.assertEqual(diagnostic["upstream_http_status"], 400)
                self.assertIs(diagnostic["failed_generation_present"], present)
                self.assertEqual(diagnostic.get("failed_generation_length_chars"), length)
                self.assertEqual(diagnostic["failed_generation_json_verdict"], verdict)
                self.assertNotIn("SECRET_", json.dumps(events) + str(upstream))

    def test_provider_error_is_an_unavailable_app_response(self):
        provider = GroqProvider(self.config, lambda *args: (_ for _ in ()).throw(RuntimeError("provider HTTP request failed")), "key")
        from fastapi.testclient import TestClient
        response = TestClient(create_app(provider)).post("/api/answer", json={"question": "thử việc", "legal_date": "2024-01-01"})
        self.assertEqual((response.status_code, response.json()["state"]), (503, "unavailable"))

    def test_transport_timeout_is_logged_as_timeout(self):
        from fastapi.testclient import TestClient
        events = []
        provider = GroqProvider(self.config, http_transport(opener=lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError())), "key")
        response = TestClient(create_app(provider, events)).post("/api/answer", json={"question": "thử việc", "legal_date": "2024-01-01"})
        provider_event = next(row for row in events if row["stage"] == "provider")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(provider_event["reason"], "provider_timeout")
        self.assertEqual(provider_event["diagnostics"][0]["exception_class"], "TimeoutError")

    def test_provider_diagnostics_distinguish_http_envelope_content_and_validation(self):
        from fastapi.testclient import TestClient

        def run(transport):
            events = []
            provider = GroqProvider(self.config, transport, "key")
            response = TestClient(create_app(provider, events)).post(
                "/api/answer", json={"question": "thử việc", "legal_date": "2024-01-01"})
            return response, events

        http_error = HTTPError("https://api.groq.com/private", 429, "private error",
                               None, io.BytesIO(b"private response body"))
        response, events = run(http_transport(opener=lambda *args, **kwargs: (_ for _ in ()).throw(http_error)))
        self.assertEqual(response.status_code, 503)
        provider_event = next(row for row in events if row["stage"] == "provider")
        http_diag = provider_event["diagnostics"][0]
        self.assertEqual((http_diag["phase"], http_diag["exception_class"], http_diag["upstream_http_status"]),
                         ("http_transport", "HTTPError", 429))
        self.assertNotIn("private", json.dumps(events))

        class BadEnvelopeResponse:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, size): return b"not-json"
        response, events = run(http_transport(opener=lambda *args, **kwargs: BadEnvelopeResponse()))
        self.assertEqual(response.status_code, 502)
        envelope_json_diag = next(row for row in events if row["stage"] == "provider")["diagnostics"][-1]
        self.assertEqual((envelope_json_diag["phase"], envelope_json_diag["exception_class"],
                          envelope_json_diag["upstream_http_status"]),
                         ("provider_envelope_json", "JSONDecodeError", 200))
        self.assertNotIn("not-json", json.dumps(events))

        response, events = run(lambda *args: {"choices": []})
        self.assertEqual(response.status_code, 502)
        envelope_diag = next(row for row in events if row["stage"] == "provider")["diagnostics"][-1]
        self.assertEqual(envelope_diag["phase"], "response_envelope")
        self.assertEqual(envelope_diag["response_shape"]["choices_count"], 0)

        malformed_content = {"choices": [{"message": {"content": "{bad"}, "finish_reason": "length"}],
                            "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10}}
        response, events = run(lambda *args: malformed_content)
        self.assertEqual(response.status_code, 502)
        content_diag = next(row for row in events if row["stage"] == "provider")["diagnostics"][-1]
        self.assertEqual((content_diag["phase"], content_diag["exception_class"], content_diag["finish_reason"]),
                         ("content_json", "JSONDecodeError", "length"))
        self.assertEqual(content_diag["usage"]["total_tokens"], 10)

        invalid_answer = {**self.answer, "citations": [
            {**self.answer["citations"][0], "evidence_id": "private-evidence-id"}]}
        invalid_envelope = {"choices": [{"message": {"content": json.dumps(invalid_answer)},
                                         "finish_reason": "stop"}]}
        response, events = run(lambda *args: invalid_envelope)
        self.assertEqual(response.status_code, 502)
        validation_diag = next(row for row in events if row["stage"] == "validate")["diagnostics"][0]
        self.assertIn("evidence_or_claim_reference", validation_diag["validation_reason_codes"])
        self.assertNotIn("private-evidence-id", json.dumps(events))

        valid_content = {"choices": [{"message": {"content": json.dumps(self.answer)}, "finish_reason": "stop"}],
                         "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10}}
        class Response:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, size): return json.dumps(valid_content).encode("utf-8")
        response, events = run(http_transport(opener=lambda *args, **kwargs: Response()))
        self.assertEqual(response.status_code, 200)
        provider_event = next(row for row in events if row["stage"] == "provider")
        self.assertEqual([row["phase"] for row in provider_event["diagnostics"]],
                         ["http_transport", "provider_envelope_json", "response_envelope",
                          "provider_content", "content_json"])
        self.assertTrue(all(row.get("upstream_http_status") == 200
                            for row in provider_event["diagnostics"]
                            if row["phase"] in {"http_transport", "provider_envelope_json",
                                                "response_envelope", "provider_content", "content_json"}))
        validation_event = next(row for row in events if row["stage"] == "validate")
        self.assertEqual(validation_event["diagnostics"][0]["phase"], "citation_validation")
        self.assertEqual(validation_event["diagnostics"][0]["validation_reason_codes"], [])


if __name__ == "__main__":
    unittest.main()
