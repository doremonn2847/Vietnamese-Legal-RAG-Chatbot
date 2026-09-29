import json
import unittest
from urllib.error import HTTPError

from app import DEMO_EVIDENCE, create_app
from groq import GroqConfig, GroqProvider, http_transport


class GroqTest(unittest.TestCase):
    def setUp(self):
        self.config = GroqConfig("https://api.groq.com/openai/v1", "chat/completions", "openai/gpt-oss-20b", True)
        self.quote = DEMO_EVIDENCE["fiction-e1"]["canonical_text"]
        self.answer = {"state": "answer", "legal_date": "2024-01-01", "text": self.quote, "claims": [{"claim_id": "c1", "text": self.quote, "evidence_ids": ["fiction-e1"]}], "citations": [{"evidence_id": "fiction-e1", "quote": self.quote, "span_start": 0, "span_end": len(self.quote), "reviewed_version_id": "fiction-v1"}], "reason": "", "unanswered": ""}

    def test_disabled_and_exact_structured_request(self):
        with self.assertRaises(RuntimeError): GroqProvider(GroqConfig(), lambda *args: None).generate([])
        calls = []
        provider = GroqProvider(self.config, lambda *args: calls.append(args) or {"choices": [{"message": {"content": json.dumps(self.answer)}}], "usage": {"total_tokens": 1}}, "not-logged")
        self.assertEqual(provider.answer("q", "2024-01-01", {"fiction-e1": DEMO_EVIDENCE["fiction-e1"]})["state"], "answer")
        method, url, body, headers = calls[0]
        self.assertEqual((method, url), ("POST", "https://api.groq.com/openai/v1/chat/completions"))
        self.assertTrue(headers["Authorization"].startswith("Bearer "))
        self.assertNotIn("not-logged", str(body))
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

    def test_http_transport_is_bounded_and_does_not_retry(self):
        class Response:
            def __init__(self, body): self.body = body
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, size): return self.body
        calls = []
        self.assertEqual(http_transport(timeout_seconds=1, opener=lambda request, timeout: calls.append((request, timeout)) or Response(b'{"choices":[]}'))("POST", "https://api.groq.com", {}, {})["choices"], [])
        self.assertEqual(len(calls), 1)
        for error in (HTTPError("https://api.groq.com", 429, "rate", None, None), TimeoutError()):
            with self.subTest(error=type(error)), self.assertRaises(RuntimeError):
                http_transport(timeout_seconds=1, opener=lambda *_, **__: (_ for _ in ()).throw(error))("POST", "https://api.groq.com", {}, {})
        with self.assertRaises(ValueError):
            http_transport(timeout_seconds=1, max_response_bytes=8, opener=lambda *_, **__: Response(b"x" * 9))("POST", "https://api.groq.com", {}, {})
        with self.assertRaises(ValueError):
            http_transport(timeout_seconds=1, opener=lambda *_, **__: Response(b"not-json"))("POST", "https://api.groq.com", {}, {})

    def test_provider_error_is_an_unavailable_app_response(self):
        provider = GroqProvider(self.config, lambda *args: (_ for _ in ()).throw(RuntimeError("provider HTTP request failed")), "key")
        from fastapi.testclient import TestClient
        response = TestClient(create_app(provider)).post("/api/answer", json={"question": "thử việc", "legal_date": "2024-01-01"})
        self.assertEqual((response.status_code, response.json()["state"]), (503, "unavailable"))


if __name__ == "__main__":
    unittest.main()
