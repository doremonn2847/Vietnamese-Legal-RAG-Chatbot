"""Offline-only FastAPI demo. Its evidence is fictional and never legal advice."""
from datetime import date, datetime
import math
import time
import uuid
from collections import deque
from zoneinfo import ZoneInfo
from urllib.parse import urlparse

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


def _configured_evidence(rows, legal_date):
    day, selected = date.fromisoformat(legal_date).toordinal(), {}
    if not isinstance(rows, list):
        return {}
    for row in rows:
        if not isinstance(row, dict):
            return {}
        article_id, version = row.get("article_id"), row.get("document_version_id")
        text = row.get("canonical_text", row.get("text"))
        if not isinstance(article_id, str) or not article_id.strip() or not isinstance(version, str) or not version.strip() or not isinstance(text, str) or not text.strip() or row.get("reviewed_version_id") != version or row.get("reviewed_open_ended") is True or row.get("pham_vi") != "Trung ương" or row.get("reviewed_status") != "reviewed" or row.get("central_eligible") is not True or not all(type(row.get(key)) is int for key in ("effective_from_day", "effective_to_day", "reviewed_through_day")) or not row["effective_from_day"] <= day < row["effective_to_day"] or row["reviewed_through_day"] < day:
            return {}
        selected[f"{article_id}:{version}"] = {**row, "canonical_text": text, "reviewed_version_id": version}
    return selected


def _safe_sources(answer, evidence):
    sources = []
    for citation in answer.get("citations", []):
        source = evidence.get(citation.get("evidence_id"), {})
        url = source.get("source_url")
        parsed = urlparse(url) if isinstance(url, str) else None
        if not parsed or parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password: url = None
        try: dates = {key: date.fromordinal(source[key]).isoformat() for key in ("effective_from_day", "effective_to_day", "reviewed_through_day")}
        except (KeyError, TypeError, ValueError): continue
        sources.append({"evidence_id": citation["evidence_id"], "document_version_id": citation["reviewed_version_id"], **dates, "quote": citation["quote"], "source_url": url})
    return sources


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


def create_app(provider=None, event_sink=None, retriever=None, provenance=None):
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
    provenance = provenance or {"model_version": type(provider).__name__, "prompt_version": "synthetic-v1" if retriever is None else "configured-v1", "index_version": "fictional-only" if retriever is None else "injected"}
    event_sink = event_sink if event_sink is not None else deque(maxlen=100)
    app = FastAPI(title="Vietnamese Legal RAG synthetic demo")
    app.state.events = event_sink

    def unavailable(status, message, **extra):
        content = {"demo": retriever is None, "state": "unavailable", "answer": _empty("unavailable", message), **extra}
        if retriever is None:
            content["banner"] = DEMO_BANNER
        return JSONResponse(status_code=status, content=content)

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
        if retriever is None:
            retrieval = synthetic_retrieve(request.question)
            selected_evidence = {evidence_id: DEMO_EVIDENCE[evidence_id] for evidence_id in retrieval["selected_evidence_ids"]}
        else:
            try:
                retrieval = retriever.search(request.question, legal_date)
                selected_evidence = _configured_evidence(retrieval.get("evidence", []), legal_date) if isinstance(retrieval, dict) else {}
            except Exception:
                selected_evidence, retrieval = {}, {"evidence": []}
            timings = retrieval.get("timings_ms", {}) if isinstance(retrieval, dict) else {}
            retrieval = {"selected_evidence_ids": list(selected_evidence), "evidence_count": len(selected_evidence), "timings_ms": {key: value for key, value in timings.items() if key in {"sparse", "dense", "rerank_and_evidence"} and isinstance(value, (int, float)) and math.isfinite(value)} if isinstance(timings, dict) else {}}
            if not selected_evidence:
                event_sink.append(event("retrieve", trace_id=trace_id, query=request.question, duration_ms=(time.perf_counter_ns() - started) / 1_000_000, outcome="empty", reason="unavailable", provenance=provenance))
                return {"demo": False, "state": "unavailable", "answer": _empty("unavailable", "Không có bằng chứng đã xét duyệt phù hợp."), "retrieval": retrieval}
        event_sink.append(event("retrieve", trace_id=trace_id, query=request.question, duration_ms=(time.perf_counter_ns() - started) / 1_000_000, outcome="ok", evidence_ids=selected_evidence, provenance=provenance))
        provider_started = time.perf_counter_ns()
        try:
            answer = provider.answer(request.question, legal_date, selected_evidence)
        except TimeoutError:
            event_sink.append(event("provider", trace_id=trace_id, duration_ms=(time.perf_counter_ns() - provider_started) / 1_000_000, outcome="timeout", reason="provider_timeout", provenance=provenance))
            return unavailable(503, "Nhà cung cấp quá thời gian chờ.")
        except ValueError:
            event_sink.append(event("provider", trace_id=trace_id, duration_ms=(time.perf_counter_ns() - provider_started) / 1_000_000, outcome="invalid", reason="invalid_provider_output", provenance=provenance))
            return unavailable(502, "Nhà cung cấp trả về dữ liệu không hợp lệ.")
        except Exception:
            event_sink.append(event("provider", trace_id=trace_id, duration_ms=(time.perf_counter_ns() - provider_started) / 1_000_000, outcome="error", reason="provider_error", provenance=provenance))
            return unavailable(503, "Nhà cung cấp không khả dụng.")
        if not isinstance(answer, dict):
            event_sink.append(event("provider", trace_id=trace_id, duration_ms=(time.perf_counter_ns() - provider_started) / 1_000_000, outcome="invalid", reason="invalid_provider_output", provenance=provenance))
            return unavailable(502, "Nhà cung cấp trả về dữ liệu không hợp lệ.")
        usage = answer.pop("_usage", None)
        event_sink.append(event("provider", trace_id=trace_id, duration_ms=(time.perf_counter_ns() - provider_started) / 1_000_000, outcome="ok", evidence_ids=selected_evidence, usage=usage, provenance=provenance))
        validation_started = time.perf_counter_ns()
        validation = validate_citations(answer, selected_evidence, requested_legal_date=legal_date)
        if not validation["valid"]:
            event_sink.append(event("validate", trace_id=trace_id, duration_ms=(time.perf_counter_ns() - validation_started) / 1_000_000, outcome="rejected", reason="invalid_provider_output", evidence_ids=selected_evidence, provenance=provenance))
            return unavailable(502, "Đầu ra không vượt qua kiểm tra bằng chứng.", validation={"valid": False, "reason": "invalid_provider_output"})
        event_sink.append(event("validate", trace_id=trace_id, duration_ms=(time.perf_counter_ns() - validation_started) / 1_000_000, outcome="ok", evidence_ids=selected_evidence, provenance=provenance))
        event_sink.append(event("answer", trace_id=trace_id, outcome=answer["state"], evidence_ids=selected_evidence, usage=usage, provenance=provenance, reason=answer["state"]))
        return {"demo": retriever is None, "banner": DEMO_BANNER if retriever is None else None, "state": answer["state"], "answer": answer, "sources": _safe_sources(answer, selected_evidence), "validation": validation, "retrieval": retrieval}

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
        return UI_HTML

    return app


UI_HTML = """<!doctype html><html lang='vi'><meta charset='utf-8'><title>Legal RAG Demo</title><body><main><h1>Vietnamese Legal RAG</h1><p id='banner' role='alert'><strong>DỮ LIỆU HƯ CẤU CHỈ DÙNG ĐỂ KIỂM THỬ — KHÔNG PHẢI TƯ VẤN PHÁP LUẬT</strong></p><p id='mode'>Chế độ dữ liệu hư cấu</p><p id='scope'>Phạm vi: thử việc, hợp đồng, giờ làm và nghỉ phép. Hiệu lực cần được xem xét.</p><form id='chat'><label>Câu hỏi <input name='question' required></label><label>Ngày pháp lý <input name='legal_date' type='date'></label><button>Gửi</button></form><section aria-live='polite'><h2 id='state'>Sẵn sàng</h2><pre id='result'></pre><details><summary>Nguồn và trích đoạn</summary><div id='sources'>Chưa có kết quả.</div></details></section></main><script>const f=document.querySelector('#chat'),mode=document.querySelector('#mode'),banner=document.querySelector('#banner'),b=f.querySelector('button'),state=document.querySelector('#state'),r=document.querySelector('#result'),s=document.querySelector('#sources');const labels={answer:'Trả lời',partial:'Trả lời một phần',clarify:'Cần làm rõ',abstain_conflict:'Bằng chứng xung đột',abstain_insufficient_evidence:'Thiếu bằng chứng',unavailable:'Không khả dụng'};f.onsubmit=async e=>{e.preventDefault();b.disabled=true;state.textContent='Đang xử lý';r.textContent='';s.textContent='';let d=Object.fromEntries(new FormData(f));if(!d.legal_date)delete d.legal_date;try{let x=await fetch('/api/answer',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(d)}),z=await x.json(),a=z.answer||{};mode.textContent=z.demo?'Chế độ dữ liệu hư cấu':'Chế độ dữ liệu đã xét duyệt';banner.hidden=!z.demo;state.textContent=labels[a.state]||'Không khả dụng';r.textContent=a.text||a.reason||'Không có kết quả.';(z.sources||[]).forEach(c=>{let p=document.createElement('p');p.textContent=`${c.evidence_id||''} · ${c.document_version_id||''} · Hiệu lực: ${c.effective_from_day||''}–${c.effective_to_day||''}; Rà soát: ${c.reviewed_through_day||''} · ${c.quote||''}`;if(c.source_url){let a=document.createElement('a');a.href=c.source_url;a.textContent=' Nguồn';a.rel='noopener';p.append(a)}s.append(p)});if(!s.textContent)s.textContent='Không có trích đoạn.'}catch(_){state.textContent='Không khả dụng';r.textContent='Không thể kết nối dịch vụ.';s.textContent='Không có trích đoạn.'}finally{b.disabled=false}}</script></body></html>"""
try:
    app = create_app() if __name__ != "__main__" else None
except RuntimeError:
    app = None


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(create_app(), host="127.0.0.1", port=8000)
