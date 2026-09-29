import unittest


try:
    from fastapi.testclient import TestClient
    from app import create_app
except ImportError:
    TestClient = None
    create_app = None


@unittest.skipUnless(TestClient and create_app, "install requirements-app.txt for API tests")
class AppTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(create_app())

    def test_health_and_grounded_demo(self):
        self.assertEqual(self.client.get("/health").json()["demo"], True)
        response = self.client.post("/api/answer", json={"question": "Thử việc giả lập?", "legal_date": "2024-01-01"})
        body = response.json()
        self.assertEqual(body["state"], "answer")
        self.assertTrue(body["validation"]["valid"])
        self.assertIn("HƯ CẤU", body["banner"])
        self.assertEqual(self.client.get("/api/corpus").json()["legal_corpus_activated"], False)
        self.assertIn("selected_evidence_ids", self.client.get("/api/search", params={"question": "thử việc"}).json()["retrieval"])

    def test_request_logs_are_redacted_and_traceable(self):
        events = []
        client = TestClient(create_app(event_sink=events))
        client.post("/api/answer", json={"question": "thử việc private", "legal_date": "2024-01-01"})
        self.assertTrue(events and events[0]["trace_id"])
        self.assertNotIn("private", str(events))
        self.assertEqual(events[0]["provenance"]["prompt_version"], "synthetic-v1")

    def test_demo_states_are_explicit(self):
        body = self.client.post("/chat", json={"question": "", "legal_date": "2024-01-01"}).json()
        self.assertEqual(body["state"], "clarify")
        body = self.client.post("/chat", json={"question": "Luật thuế?", "legal_date": "2024-01-01"}).json()
        self.assertEqual(body["state"], "unavailable")
        self.assertEqual(self.client.post("/api/answer", json={"question": "Có xung đột?", "legal_date": "2024-01-01"}).json()["state"], "abstain_conflict")
        self.assertEqual(self.client.post("/api/answer", json={"question": "Hiệu lực?", "legal_date": "2024-01-01"}).json()["state"], "abstain_insufficient_evidence")

    def test_bad_input_and_provider_output_are_gated(self):
        called = []
        class BadProvider:
            def answer(self, *args):
                called.append(True)
                return "unsafe"
        events = []
        client = TestClient(create_app(BadProvider(), events))
        self.assertEqual(client.post("/api/answer", json={"question": "thử việc", "legal_date": "bad"}).status_code, 422)
        self.assertEqual(called, [])
        response = client.post("/api/answer", json={"question": "thử việc", "legal_date": "2040-01-01"})
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["state"], "unavailable")
        self.assertNotIn("unsafe", response.text)
        self.assertEqual(events[-1]["reason"], "invalid_provider_output")

    def test_unselected_and_malformed_provider_output_are_gated(self):
        class UnselectedProvider:
            def answer(self, question, legal_date, selected):
                quote = "[HƯ CẤU] Ví dụ kiểm thử: dữ liệu này không xác nhận hiệu lực pháp luật."
                return {"state": "answer", "legal_date": legal_date, "text": quote, "claims": [{"claim_id": "hostile-claim", "text": quote, "evidence_ids": ["fiction-e2"]}], "citations": [{"evidence_id": "fiction-e2", "quote": quote, "span_start": 0, "span_end": len(quote), "reviewed_version_id": "fiction-v1"}]}
        response = TestClient(create_app(UnselectedProvider())).post("/api/answer", json={"question": "thử việc", "legal_date": "2024-01-01"})
        self.assertEqual(response.status_code, 502)
        self.assertNotIn("hostile-claim", response.text)
        class MalformedProvider:
            def answer(self, *args):
                return {"state": [], "text": "hostile", "claims": [], "citations": []}
        response = TestClient(create_app(MalformedProvider())).post("/api/answer", json={"question": "thử việc", "legal_date": "2024-01-01"})
        self.assertEqual(response.status_code, 502)
        self.assertNotIn("hostile", response.text)

    def test_timeout_and_html_ui_are_safe(self):
        class TimeoutProvider:
            def answer(self, *args):
                raise TimeoutError()
        response = TestClient(create_app(TimeoutProvider())).post("/api/answer", json={"question": "thử việc", "legal_date": "2024-01-01"})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["state"], "unavailable")
        page = self.client.get("/")
        self.assertIn("text/html", page.headers["content-type"])
        self.assertIn("DỮ LIỆU HƯ CẤU", page.text)
        self.assertIn("textContent", page.text)
        self.assertIn("b.disabled=true", page.text)
        self.assertIn("abstain_conflict", page.text)

    def test_source_projection_allows_only_http_urls(self):
        from app import _safe_sources
        answer = {"citations":[{"evidence_id":"e","quote":"q","reviewed_version_id":"v"}]}
        source = {"effective_from_day": 737425, "effective_to_day": 741077, "reviewed_through_day": 741077}
        self.assertEqual(_safe_sources(answer, {"e":{**source, "source_url":"https:///missing"}})[0]["source_url"], None)
        self.assertEqual(_safe_sources(answer, {"e":{**source, "source_url":"https://example.invalid"}})[0]["source_url"], "https://example.invalid")

    def test_injected_retrieval_uses_eligible_parent_evidence_without_demo_fallback(self):
        day = 738886
        class Retriever:
            def search(self, *args):
                return {"evidence": [{"article_id": "a1", "text": "Nguồn đã xét duyệt.", "document_version_id": "v1", "reviewed_version_id": "v1", "pham_vi": "Trung ương", "reviewed_status": "reviewed", "central_eligible": True, "effective_from_day": day - 1, "effective_to_day": day + 1, "reviewed_through_day": day + 1}], "timings_ms": {}}
        class Provider:
            def answer(self, question, legal_date, evidence):
                source = evidence["a1:v1"]
                quote = source["canonical_text"]
                return {"state": "answer", "legal_date": legal_date, "text": quote, "claims": [{"claim_id": "c1", "text": quote, "evidence_ids": ["a1:v1"]}], "citations": [{"evidence_id": "a1:v1", "quote": quote, "span_start": 0, "span_end": len(quote), "reviewed_version_id": "v1"}]}
        events = []
        response = TestClient(create_app(Provider(), events, retriever=Retriever(), provenance={"model_version": "fake-provider", "prompt_version": "test-v1", "index_version": "test-index"})).post("/api/answer", json={"question": "thử việc", "legal_date": "2024-01-01"})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["demo"])
        self.assertEqual(response.json()["answer"]["citations"][0]["evidence_id"], "a1:v1")
        self.assertEqual(events[0]["provenance"]["index_version"], "test-index")

    def test_injected_retrieval_rejects_invalid_parent_before_provider(self):
        called = []
        class Retriever:
            def search(self, *args): return {"evidence": [{"article_id": "a1", "text": "bad", "document_version_id": "v1", "reviewed_version_id": "v2"}]}
        class Provider:
            def answer(self, *args): called.append(True)
        response = TestClient(create_app(Provider(), retriever=Retriever())).post("/api/answer", json={"question": "thử việc", "legal_date": "2024-01-01"})
        self.assertEqual(response.json()["state"], "unavailable")
        self.assertEqual(called, [])

    def test_hybrid_and_injected_http_provider_complete_the_configured_route(self):
        from bm25 import BM25Index
        from hybrid_pipeline import HybridRetriever
        from nine_router import NineRouterConfig, NineRouterProvider
        day = 738886
        parent = {"article_id": "a1", "canonical_text": "Reviewed source.", "document_version_id": "v1", "reviewed_version_id": "v1", "source_start": 0, "source_end": 16, "pham_vi": "Trung ương", "provision": "probation", "reviewed_status": "reviewed", "central_eligible": True, "effective_from_day": day - 1, "effective_to_day": day + 1, "reviewed_through_day": day + 1}
        class Encoder:
            def encode_queries(self, queries): return [[1.0]]
        class Qdrant:
            def search(self, *args, **kwargs): return {"result": [{"score": 1.0, "payload": {"article_id": "a1", "child_id": "c1"}}]}
        class Reranker:
            def score(self, query, candidates): return {candidate["article_id"]: 1.0 for candidate in candidates}
        provider = NineRouterProvider(NineRouterConfig("https://example.invalid", "chat", "fake", True), lambda *args: {"choices": [{"message": {"content": '{"state":"answer","legal_date":"2024-01-01","text":"Reviewed source.","claims":[{"claim_id":"c1","text":"Reviewed source.","evidence_ids":["a1:v1"]}],"citations":[{"evidence_id":"a1:v1","quote":"Reviewed source.","span_start":0,"span_end":16,"reviewed_version_id":"v1"}]}'}}], "usage": {}})
        retriever = HybridRetriever(BM25Index([{**parent, "evidence_id": "x", "child_id": "c1", "text": parent["canonical_text"]}]), Encoder(), Qdrant(), "synthetic_test", {"a1": parent}, Reranker())
        response = TestClient(create_app(provider, retriever=retriever, provenance={"model_version": "fake", "prompt_version": "p1", "index_version": "i1"})).post("/api/answer", json={"question": "thử việc", "legal_date": "2024-01-01"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["validation"]["valid"])

    def test_configured_mode_fails_closed_without_leaking_or_demo_metadata(self):
        day = 738886
        class Provider:
            def answer(self, *args): raise TimeoutError()
        class BoundaryRetriever:
            def search(self, *args): return {"evidence": [{"article_id": "a", "document_version_id": "v", "reviewed_version_id": "v", "text": "safe", "pham_vi": "Trung ương", "reviewed_status": "reviewed", "central_eligible": True, "effective_from_day": day - 1, "effective_to_day": day + 100, "reviewed_through_day": day + 1}]}
        response = TestClient(create_app(Provider(), retriever=BoundaryRetriever())).post("/api/answer", json={"question": "q", "legal_date": "2024-01-01"})
        self.assertEqual(response.status_code, 503)
        self.assertFalse(response.json()["demo"])
        self.assertNotIn("DỮ LIỆU HƯ CẤU", response.text)
        class MalformedRetriever:
            def search(self, *args): return []
        response = TestClient(create_app(Provider(), retriever=MalformedRetriever())).post("/api/answer", json={"question": "secret", "legal_date": "2024-01-01"})
        self.assertEqual(response.json()["state"], "unavailable")
        self.assertNotIn("secret", response.text)


if __name__ == "__main__":
    unittest.main()
