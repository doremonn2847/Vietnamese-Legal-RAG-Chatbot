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
                return {"state": "answer", "text": "unsafe", "claims": [], "citations": []}
        client = TestClient(create_app(BadProvider()))
        self.assertEqual(client.post("/api/answer", json={"question": "thử việc", "legal_date": "bad"}).status_code, 422)
        self.assertEqual(called, [])
        response = client.post("/api/answer", json={"question": "thử việc", "legal_date": "2040-01-01"})
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["state"], "unavailable")
        self.assertNotIn("unsafe", response.text)

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


if __name__ == "__main__":
    unittest.main()
