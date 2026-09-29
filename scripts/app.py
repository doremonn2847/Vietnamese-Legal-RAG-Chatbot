"""Offline-only FastAPI demo. Its evidence is fictional and never legal advice."""
from datetime import date, datetime
import time
import uuid
from collections import deque
from zoneinfo import ZoneInfo

from answer_contract import validate_citations
from bm25 import BM25Index
from retrieval import rrf_fuse, rerank_candidates, select_evidence
from safe_log import event


DEMO_BANNER = "DỮ LIỆU HƯ CẤU CHỈ DÙNG ĐỂ KIỂM THỬ — KHÔNG PHẢI VĂN BẢN PHÁP LUẬT"
DEMO_EVIDENCE = {
    "fiction-e1": {
        "article_id": "fiction-a1", "child_id": "fiction-c1",
        "canonical_text": "[HƯ CẤU] Ví dụ kiểm thử: một quy tắc giả lập về thử việc.",
        "reviewed_version_id": "fiction-v1", "reviewed_status": "reviewed", "central_eligible": True,
        "effective_from_day": date(2020, 1, 1).toordinal(), "effective_to_day": date(2030, 1, 1).toordinal(),
        "reviewed_through_day": date(2030, 1, 1).toordinal(), "source_label": "Nguồn hư cấu kiểm thử",
    },
    "fiction-e2": {
        "article_id": "fiction-a2", "child_id": "fiction-c2",
        "canonical_text": "[HƯ CẤU] Ví dụ kiểm thử: dữ liệu này không xác nhận hiệu lực pháp luật.",
        "reviewed_version_id": "fiction-v1", "reviewed_status": "reviewed", "central_eligible": True,
        "effective_from_day": date(2020, 1, 1).toordinal(), "effective_to_day": date(2030, 1, 1).toordinal(),
        "reviewed_through_day": date(2030, 1, 1).toordinal(), "source_label": "Nguồn hư cấu kiểm thử",
    },
}


def synthetic_retrieve(question):
    documents = [{"evidence_id": key, "article_id": item["article_id"], "child_id": item["child_id"], "text": item["canonical_text"]} for key, item in DEMO_EVIDENCE.items()]
    sparse = BM25Index(documents).search(question, limit=2)
    dense = [{key: value for key, value in hit.items() if key != "rank"} for hit in sparse]
    fused = rrf_fuse({"bm25": sparse, "synthetic_dense": dense})
    scores = {item["article_id"]: 1.0 if item["article_id"] == "fiction-a1" else 0.5 for item in fused}
    selected = select_evidence(rerank_candidates(fused, scores), cap=1)
    selected_ids = [next(key for key, item in DEMO_EVIDENCE.items() if item["article_id"] == row["article_id"]) for row in selected]
    return {"sparse": sparse, "fused": fused, "selected_evidence_ids": selected_ids}


def _empty(state, reason):
    return {"state": state, "text": "", "claims": [], "citations": [], "reason": reason}


class MockProvider:
    def answer(self, question, legal_date, selected_evidence):
        if not question.strip():
            return _empty("clarify", "Cần nêu câu hỏi cụ thể.")
        if "xung đột" in question.casefold():
            return _empty("abstain_conflict", "Bản demo mô phỏng bằng chứng mâu thuẫn.")
        if "hiệu lực" in question.casefold():
            return _empty("abstain_insufficient_evidence", "Dữ liệu hư cấu không xác nhận hiệu lực pháp luật.")
        if "thử việc" not in question.casefold():
            return _empty("unavailable", "Bản demo chỉ có một ví dụ hư cấu về thử việc.")
        if not selected_evidence:
            return _empty("unavailable", "Bản demo không tìm thấy dữ liệu hư cấu phù hợp.")
        evidence_id = next(iter(selected_evidence))
        quote = selected_evidence[evidence_id]["canonical_text"]
        answer = {"state": "answer", "legal_date": legal_date, "claims": [{"claim_id": "fiction-c1", "text": quote, "evidence_ids": [evidence_id]}], "citations": [{"evidence_id": evidence_id, "quote": quote, "span_start": 0, "span_end": len(quote), "reviewed_version_id": "fiction-v1"}], "text": quote}
        if "một phần" in question.casefold():
            answer.update(state="partial", unanswered="Bản demo không có dữ liệu pháp luật thật.")
        return answer


def create_app(provider=None, event_sink=None):
    try:
        from fastapi import FastAPI, HTTPException
        from fastapi.responses import HTMLResponse, JSONResponse
        from pydantic import BaseModel
    except ImportError as error:
        raise RuntimeError("install requirements-app.txt to run the demo API") from error

    class ChatRequest(BaseModel):
        question: str
        legal_date: str | None = None

    provider = provider or MockProvider()
    event_sink = event_sink if event_sink is not None else deque(maxlen=100)
    app = FastAPI(title="Vietnamese Legal RAG synthetic demo")
    app.state.events = event_sink

    def resolve_legal_date(value):
        if value is None:
            return datetime.now(ZoneInfo("Asia/Bangkok")).date().isoformat()
        try:
            return date.fromisoformat(value).isoformat()
        except (TypeError, ValueError) as error:
            raise HTTPException(status_code=422, detail="legal_date must be ISO YYYY-MM-DD") from error

    def response_for(request):
        trace_id = str(uuid.uuid4())
        started = time.perf_counter_ns()
        legal_date = resolve_legal_date(request.legal_date)
        retrieval = synthetic_retrieve(request.question)
        selected_evidence = {evidence_id: DEMO_EVIDENCE[evidence_id] for evidence_id in retrieval["selected_evidence_ids"]}
        event_sink.append(event("retrieve", trace_id=trace_id, query=request.question, duration_ms=(time.perf_counter_ns() - started) / 1_000_000, outcome="ok", evidence_ids=selected_evidence, provenance={"prompt_version": "synthetic-v1", "index_version": "fictional-only", "model_version": type(provider).__name__}))
        provider_started = time.perf_counter_ns()
        try:
            answer = provider.answer(request.question, legal_date, selected_evidence)
        except TimeoutError:
            event_sink.append(event("provider", trace_id=trace_id, duration_ms=(time.perf_counter_ns() - provider_started) / 1_000_000, outcome="timeout", reason="provider_timeout", provenance={"model_version": type(provider).__name__}))
            return JSONResponse(status_code=503, content={"demo": True, "banner": DEMO_BANNER, "state": "unavailable", "answer": _empty("unavailable", "Nhà cung cấp bản demo quá thời gian chờ.")})
        except ValueError:
            event_sink.append(event("provider", trace_id=trace_id, duration_ms=(time.perf_counter_ns() - provider_started) / 1_000_000, outcome="invalid", reason="invalid_provider_output", provenance={"model_version": type(provider).__name__}))
            return JSONResponse(status_code=502, content={"demo": True, "banner": DEMO_BANNER, "state": "unavailable", "answer": _empty("unavailable", "Nhà cung cấp bản demo trả về dữ liệu không hợp lệ.")})
        except Exception:
            event_sink.append(event("provider", trace_id=trace_id, duration_ms=(time.perf_counter_ns() - provider_started) / 1_000_000, outcome="error", reason="provider_error", provenance={"model_version": type(provider).__name__}))
            return JSONResponse(status_code=503, content={"demo": True, "banner": DEMO_BANNER, "state": "unavailable", "answer": _empty("unavailable", "Nhà cung cấp bản demo không khả dụng.")})
        if not isinstance(answer, dict):
            event_sink.append(event("provider", trace_id=trace_id, duration_ms=(time.perf_counter_ns() - provider_started) / 1_000_000, outcome="invalid", reason="invalid_provider_output", provenance={"model_version": type(provider).__name__}))
            return JSONResponse(status_code=502, content={"demo": True, "banner": DEMO_BANNER, "state": "unavailable", "answer": _empty("unavailable", "Nhà cung cấp trả về dữ liệu không hợp lệ.")})
        usage = answer.pop("_usage", None)
        event_sink.append(event("provider", trace_id=trace_id, duration_ms=(time.perf_counter_ns() - provider_started) / 1_000_000, outcome="ok", evidence_ids=selected_evidence, usage=usage, provenance={"model_version": type(provider).__name__}))
        validation_started = time.perf_counter_ns()
        validation = validate_citations(answer, selected_evidence, requested_legal_date=legal_date)
        if not validation["valid"]:
            event_sink.append(event("validate", trace_id=trace_id, duration_ms=(time.perf_counter_ns() - validation_started) / 1_000_000, outcome="rejected", reason="invalid_provider_output", evidence_ids=selected_evidence, provenance={"model_version": type(provider).__name__}))
            return JSONResponse(status_code=502, content={"demo": True, "banner": DEMO_BANNER, "state": "unavailable", "answer": _empty("unavailable", "Đầu ra bản demo không vượt qua kiểm tra bằng chứng."), "validation": {"valid": False, "reason": "invalid_provider_output"}})
        event_sink.append(event("validate", trace_id=trace_id, duration_ms=(time.perf_counter_ns() - validation_started) / 1_000_000, outcome="ok", evidence_ids=selected_evidence, provenance={"model_version": type(provider).__name__}))
        event_sink.append(event("answer", trace_id=trace_id, outcome=answer["state"], evidence_ids=selected_evidence, usage=usage, provenance={"model_version": type(provider).__name__, "prompt_version": "synthetic-v1", "index_version": "fictional-only"}, reason=answer["state"]))
        return {"demo": True, "banner": DEMO_BANNER, "state": answer["state"], "answer": answer, "validation": validation, "retrieval": retrieval}

    @app.get("/api/health")
    @app.get("/health")
    def health():
        return {"ok": True, "demo": True, "corpus": "fictional-only"}

    @app.get("/api/corpus")
    def corpus():
        return {"demo": True, "banner": DEMO_BANNER, "corpus": "fictional-only", "legal_corpus_activated": False, "current_validity": "unverified"}

    @app.get("/api/search")
    def search(question: str):
        return {"demo": True, "banner": DEMO_BANNER, "retrieval": synthetic_retrieve(question)}

    @app.post("/api/answer")
    @app.post("/chat")
    def answer(request: ChatRequest):
        return response_for(request)

    @app.get("/", response_class=HTMLResponse)
    def index():
        return """<!doctype html><html lang='vi'><meta charset='utf-8'><title>Legal RAG Demo</title><body><main><h1>Vietnamese Legal RAG — bản demo</h1><p role='alert'><strong>DỮ LIỆU HƯ CẤU CHỈ DÙNG ĐỂ KIỂM THỬ — KHÔNG PHẢI TƯ VẤN PHÁP LUẬT</strong></p><form id='chat'><label>Câu hỏi <input name='question' required></label><label>Ngày pháp lý <input name='legal_date' type='date'></label><button>Gửi</button></form><section aria-live='polite'><h2>Kết quả</h2><pre id='result'></pre><details><summary>Nguồn và trích đoạn hư cấu</summary><p id='sources'>Chưa có kết quả.</p></details></section></main><script>const f=document.querySelector('#chat'),r=document.querySelector('#result'),s=document.querySelector('#sources');f.onsubmit=async e=>{e.preventDefault();r.textContent='';s.textContent='';let d=Object.fromEntries(new FormData(f));if(!d.legal_date)delete d.legal_date;try{let x=await fetch('/api/answer',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(d)}),b=await x.json();r.textContent=JSON.stringify(b.answer||b,null,2);s.textContent=(b.answer?.citations||[]).map(c=>c.quote).join('\\n')||'Không có trích đoạn.'}catch(_){r.textContent='Không thể kết nối bản demo.';s.textContent='Không có trích đoạn.'}}</script></body></html>"""

    return app


try:
    app = create_app() if __name__ != "__main__" else None
except RuntimeError:
    app = None


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(create_app(), host="127.0.0.1", port=8000)
