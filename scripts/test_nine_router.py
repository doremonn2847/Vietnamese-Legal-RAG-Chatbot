import unittest
import json

from app import DEMO_EVIDENCE, create_app
from nine_router import NineRouterConfig, NineRouterProvider, http_transport


class NineRouterTest(unittest.TestCase):
    def test_disabled_and_mocked_transport(self):
        provider = NineRouterProvider(NineRouterConfig(), transport=lambda *args: (_ for _ in ()).throw(AssertionError("must not call")))
        with self.assertRaises(RuntimeError):
            provider.generate([])
        calls = []
        provider = NineRouterProvider(NineRouterConfig(base_url="https://example.invalid", route="chat", model="free-test", enabled=True), transport=lambda *args: calls.append(args) or {"choices": [{"message": {"content": "{}"}}], "usage": {"total_tokens": 1}}, api_key="not-logged")
        self.assertEqual(provider.generate([])["usage"]["total_tokens"], 1)
        self.assertEqual(calls[0][1], "https://example.invalid/chat")

    def test_mocked_http_bridge_validates_selected_evidence(self):
        quote = DEMO_EVIDENCE["fiction-e1"]["canonical_text"]
        answer = {"state": "answer", "legal_date": "2024-01-01", "text": quote, "claims": [{"claim_id": "c1", "text": quote, "evidence_ids": ["fiction-e1"]}], "citations": [{"evidence_id": "fiction-e1", "quote": quote, "span_start": 0, "span_end": len(quote), "reviewed_version_id": "fiction-v1"}]}
        calls = []
        provider = NineRouterProvider(NineRouterConfig(base_url="https://example.invalid", route="chat", model="free-test", enabled=True), transport=lambda *args: calls.append(args) or {"choices": [{"message": {"content": json.dumps(answer)}}], "usage": {"total_tokens": 2}})
        selected = {"fiction-e1": DEMO_EVIDENCE["fiction-e1"]}
        self.assertEqual(provider.answer("q", "2024-01-01", selected)["state"], "answer")
        self.assertIn("synthetic-answer-v1", calls[0][2]["messages"][0]["content"])
        self.assertIn("span_start", calls[0][2]["messages"][0]["content"])
        self.assertIn("fiction-e1", calls[0][2]["messages"][1]["content"])
        self.assertNotIn("fiction-e2", calls[0][2]["messages"][1]["content"])
        events = []
        from fastapi.testclient import TestClient
        response = TestClient(create_app(provider, events)).post("/api/answer", json={"question": "thử việc", "legal_date": "2024-01-01"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(next(row for row in events if row["stage"] == "provider")["usage"]["total_tokens"], 2)
        malformed = NineRouterProvider(NineRouterConfig(base_url="https://example.invalid", route="chat", model="free-test", enabled=True), transport=lambda *args: {"choices": [{"message": {"content": "not json"}}]})
        with self.assertRaises(ValueError):
            malformed.answer("q", "2024-01-01", selected)

    def test_malformed_usage_cannot_break_the_app(self):
        quote = DEMO_EVIDENCE["fiction-e1"]["canonical_text"]
        answer = {"state": "answer", "legal_date": "2024-01-01", "text": quote, "claims": [{"claim_id": "c1", "text": quote, "evidence_ids": ["fiction-e1"]}], "citations": [{"evidence_id": "fiction-e1", "quote": quote, "span_start": 0, "span_end": len(quote), "reviewed_version_id": "fiction-v1"}]}
        provider = NineRouterProvider(NineRouterConfig(base_url="https://example.invalid", route="chat", model="free-test", enabled=True), transport=lambda *args: {"choices": [{"message": {"content": json.dumps(answer)}}], "usage": "bad"})
        from fastapi.testclient import TestClient
        self.assertEqual(TestClient(create_app(provider)).post("/api/answer", json={"question": "thử việc", "legal_date": "2024-01-01"}).status_code, 200)

    def test_opt_in_http_transport_is_bounded_and_never_called_while_disabled(self):
        calls = []
        transport = http_transport(timeout_seconds=3, opener=lambda request, timeout: calls.append((request, timeout)) or (_ for _ in ()).throw(AssertionError("disabled")))
        with self.assertRaises(RuntimeError):
            NineRouterProvider(NineRouterConfig(), transport).generate([])
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
