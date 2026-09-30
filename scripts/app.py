"""Offline-only FastAPI demo. Its evidence is fictional and never legal advice."""
from datetime import date, datetime, timedelta, timezone
import math
import re
import time
import uuid
from collections import deque
from urllib.parse import urlparse

from answer_contract import validate_citations
from bm25 import BM25Index
from retrieval import rrf_fuse, rerank_candidates, select_evidence
from safe_log import event
from provisional_policy import PROVISIONAL_CAVEAT, decide_provisional_eligibility


DEMO_BANNER = "DỮ LIỆU HƯ CẤU CHỈ DÙNG ĐỂ KIỂM THỬ — KHÔNG PHẢI VĂN BẢN PHÁP LUẬT"
DEMO_EVIDENCE = {
    "fiction-e1": {
        "article_id": "fiction-a1", "child_id": "fiction-c1",
        "canonical_text": "[HƯ CẤU] Ví dụ kiểm thử: một quy tắc giả lập về thử việc.",
        "reviewed_version_id": "fiction-v1", "document_version_id": "fiction-v1", "reviewed_status": "reviewed", "central_eligible": True,
        "effective_from_day": date(2020, 1, 1).toordinal(), "effective_to_day": date(2030, 1, 1).toordinal(),
        "reviewed_through_day": date(2030, 1, 1).toordinal(), "source_label": "Nguồn hư cấu kiểm thử",
    },
    "fiction-e2": {
        "article_id": "fiction-a2", "child_id": "fiction-c2",
        "canonical_text": "[HƯ CẤU] Ví dụ kiểm thử: dữ liệu này không xác nhận hiệu lực pháp luật.",
        "reviewed_version_id": "fiction-v1", "document_version_id": "fiction-v1", "reviewed_status": "reviewed", "central_eligible": True,
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
        version = citation.get("document_version_id", citation.get("reviewed_version_id"))
        if answer.get("state") == "provisional":
            sources.append({"evidence_id": citation["evidence_id"], "document_version_id": version, "title": source.get("title"), "so_ky_hieu": source.get("so_ky_hieu"), "issuer": source.get("issuer"), "reported_status": source.get("reported_status"), "current_validity": "unverified", "amendment_state": source.get("amendment_state"), "quarantined_related_document_ids": source.get("quarantined_related_document_ids", []), "source_dataset_revision": source.get("source_dataset_revision"), "quote": citation["quote"], "source_url": url})
            continue
        try: dates = {key: date.fromordinal(source[key]).isoformat() for key in ("effective_from_day", "effective_to_day", "reviewed_through_day")}
        except (KeyError, TypeError, ValueError): continue
        sources.append({"evidence_id": citation["evidence_id"], "document_version_id": version, **dates, "quote": citation["quote"], "source_url": url})
    return sources


def _provisional_evidence(rows, question, requested_as_of_date):
    decision = decide_provisional_eligibility(question, rows, requested_as_of_date=requested_as_of_date)
    if not decision["allowed"]:
        return decision, {}
    requested_numbers = set(re.findall(r"\b(?:điều|article)\s+(\d+[a-z]?)\b", question, re.IGNORECASE))
    if requested_numbers:
        if len(requested_numbers) != 1:
            return _article_request_denial("requested_article_ambiguous"), {}
        number = next(iter(requested_numbers)).casefold()
        matching = [row for row in rows if _article_number(row) == number]
        matching = list({(row.get("article_id"), row.get("document_version_id")): row for row in matching}.values())
        if len(matching) > 1:
            named = [row for row in matching if any(
                isinstance(row.get(field), str) and row[field].strip().casefold() in question.casefold()
                for field in ("so_ky_hieu", "title")
            )]
            matching = named if len(named) == 1 else []
        if len(matching) != 1:
            return _article_request_denial("requested_article_not_unambiguous"), {}
        rows = matching
    selected = {}
    for row in rows:
        article_id, version = row["article_id"], row["document_version_id"]
        evidence_id = f"{article_id}:{version}"
        text = row.get("canonical_text", row.get("text"))
        selected[evidence_id] = {**row, "canonical_text": text, "document_version_id": version, "provisional_snapshot_eligible": True}
    return decision, selected


def _article_number(row):
    label = row.get("label")
    if not isinstance(label, str):
        label = row.get("canonical_text", row.get("text", ""))
    match = re.match(r"\s*(?:điều|article)\s+(\d+[a-z]?)\b", label, re.IGNORECASE)
    return match.group(1).casefold() if match else None


def _article_request_denial(reason):
    return {"allowed": False, "mode": "abstain", "reason": reason,
            "message": "Không thể xác định duy nhất đúng điều khoản và văn bản được yêu cầu.",
            "caveat": PROVISIONAL_CAVEAT}


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
        answer = {"state": "answer", "legal_date": legal_date, "claims": [{"claim_id": "fiction-c1", "text": quote, "evidence_ids": [evidence_id]}], "citations": [{"evidence_id": evidence_id, "quote": quote, "span_start": 0, "span_end": len(quote), "document_version_id": "fiction-v1"}], "text": quote}
        if "một phần" in question.casefold():
            answer.update(state="partial", unanswered="Bản demo không có dữ liệu pháp luật thật.")
        return answer


class DisabledProvider:
    def answer(self, question, legal_date, selected_evidence):
        return _empty("unavailable", "Mô hình trả lời chưa được bật.")


def create_app(provider=None, event_sink=None, retriever=None, provenance=None, provisional_snapshot_enabled=False):
    try:
        from fastapi import FastAPI, HTTPException
        from fastapi.responses import HTMLResponse, JSONResponse
        from pydantic import BaseModel
    except ImportError as error:
        raise RuntimeError("install requirements-app.txt to run the demo API") from error

    class ChatRequest(BaseModel):
        question: str
        legal_date: str | None = None

    provider = provider or (DisabledProvider() if provisional_snapshot_enabled else MockProvider())
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
            return datetime.now(timezone(timedelta(hours=7))).date().isoformat()
        try:
            return date.fromisoformat(value).isoformat()
        except (TypeError, ValueError) as error:
            raise HTTPException(status_code=422, detail="legal_date must be ISO YYYY-MM-DD") from error

    def response_for(request):
        trace_id = str(uuid.uuid4())
        started = time.perf_counter_ns()
        legal_date = resolve_legal_date(request.legal_date)
        provisional = False
        policy_decision = None
        if retriever is None:
            retrieval = synthetic_retrieve(request.question)
            selected_evidence = {evidence_id: DEMO_EVIDENCE[evidence_id] for evidence_id in retrieval["selected_evidence_ids"]}
        else:
            try:
                retrieval = retriever.search(request.question, legal_date)
                selected_evidence = _configured_evidence(retrieval.get("evidence", []), legal_date) if isinstance(retrieval, dict) else {}
                if not selected_evidence and provisional_snapshot_enabled and isinstance(retrieval, dict):
                    policy_decision, selected_evidence = _provisional_evidence(retrieval.get("evidence", []), request.question, request.legal_date is not None)
                    provisional = bool(selected_evidence)
            except Exception:
                selected_evidence, retrieval = {}, {"evidence": []}
            timings = retrieval.get("timings_ms", {}) if isinstance(retrieval, dict) else {}
            retrieval = {"selected_evidence_ids": list(selected_evidence), "evidence_count": len(selected_evidence), "timings_ms": {key: value for key, value in timings.items() if key in {"sparse", "dense", "fusion_and_evidence"} and isinstance(value, (int, float)) and math.isfinite(value)} if isinstance(timings, dict) else {}}
            if not selected_evidence:
                if policy_decision is not None:
                    reason = policy_decision["reason"]
                    state = "abstain_conflict" if reason == "conflicting_status" else "abstain_insufficient_evidence"
                    event_sink.append(event("retrieve", trace_id=trace_id, query=request.question, duration_ms=(time.perf_counter_ns() - started) / 1_000_000, outcome="abstain", reason=reason, provenance=provenance))
                    answer = _empty(state, policy_decision["message"])
                    return {"demo": False, "state": state, "answer": answer, "caveat": policy_decision["caveat"], "retrieval": retrieval}
                event_sink.append(event("retrieve", trace_id=trace_id, query=request.question, duration_ms=(time.perf_counter_ns() - started) / 1_000_000, outcome="empty", reason="unavailable", provenance=provenance))
                return {"demo": False, "state": "unavailable", "answer": _empty("unavailable", "Không có bằng chứng đã xét duyệt phù hợp."), "retrieval": retrieval}
        event_sink.append(event("retrieve", trace_id=trace_id, query=request.question, duration_ms=(time.perf_counter_ns() - started) / 1_000_000, outcome="ok", evidence_ids=selected_evidence, provenance=provenance))
        if provisional:
            evidence_id, source = next(iter(selected_evidence.items()))
            quote = source["canonical_text"]
            answer = {"state": "provisional", "legal_date": None, "text": quote,
                      "claims": [{"claim_id": "snapshot-quote", "text": quote, "evidence_ids": [evidence_id]}],
                      "citations": [{"evidence_id": evidence_id, "quote": quote, "span_start": 0,
                                     "span_end": len(quote), "document_version_id": source["document_version_id"]}],
                      "reason": "", "unanswered": ""}
            validation = validate_citations(answer, selected_evidence)
            if not validation["valid"]:
                return unavailable(502, "Đoạn trích không vượt qua kiểm tra bằng chứng.")
            return {"demo": False, "state": "provisional", "answer": answer,
                    "caveat": policy_decision["caveat"], "sources": _safe_sources(answer, selected_evidence),
                    "validation": validation, "retrieval": retrieval}
        provider_started = time.perf_counter_ns()
        try:
            answer = provider.answer(request.question, None if provisional else legal_date, selected_evidence)
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
        validation = validate_citations(answer, selected_evidence, requested_legal_date=None if provisional else legal_date)
        if not validation["valid"]:
            event_sink.append(event("validate", trace_id=trace_id, duration_ms=(time.perf_counter_ns() - validation_started) / 1_000_000, outcome="rejected", reason="invalid_provider_output", evidence_ids=selected_evidence, provenance=provenance))
            return unavailable(502, "Đầu ra không vượt qua kiểm tra bằng chứng.", validation={"valid": False, "reason": "invalid_provider_output"})
        event_sink.append(event("validate", trace_id=trace_id, duration_ms=(time.perf_counter_ns() - validation_started) / 1_000_000, outcome="ok", evidence_ids=selected_evidence, provenance=provenance))
        event_sink.append(event("answer", trace_id=trace_id, outcome=answer["state"], evidence_ids=selected_evidence, usage=usage, provenance=provenance, reason=answer["state"]))
        return {"demo": retriever is None, "banner": DEMO_BANNER if retriever is None else None, "caveat": policy_decision["caveat"] if provisional else None, "state": answer["state"], "answer": answer, "sources": _safe_sources(answer, selected_evidence), "validation": validation, "retrieval": retrieval}

    @app.get("/api/health")
    @app.get("/health")
    def health():
        return {"ok": True, "demo": retriever is None, "corpus": "fictional-only" if retriever is None else provenance.get("corpus", "configured")}

    @app.get("/api/corpus")
    def corpus():
        demo = retriever is None
        return {"demo": demo, "banner": DEMO_BANNER if demo else None, "corpus": "fictional-only" if demo else provenance.get("corpus", "configured"), "legal_corpus_activated": False, "answer_mode": "provisional_snapshot" if provisional_snapshot_enabled else "reviewed_only", "current_validity": "unverified"}

    @app.get("/api/search")
    def search(question: str):
        if retriever is None:
            return {"demo": True, "banner": DEMO_BANNER, "retrieval": synthetic_retrieve(question)}
        try:
            result = retriever.search(question)
        except Exception:
            raise HTTPException(status_code=503, detail="Configured retrieval is unavailable.")
        evidence = [{key: row.get(key) for key in ("article_id", "document_version_id", "label", "title", "canonical_text", "pham_vi", "current_validity", "amendment_state", "source_dataset_revision", "source_url")}
                    for row in result.get("evidence", []) if isinstance(row, dict)]
        return {"demo": False, "banner": None, "retrieval": {"evidence": evidence, "timings_ms": result.get("timings_ms", {})}}

    @app.post("/api/answer")
    @app.post("/chat")
    def answer(request: ChatRequest):
        return response_for(request)

    @app.get("/", response_class=HTMLResponse)
    def index():
        return UI_HTML

    return app


UI_HTML = """<!doctype html><html lang='vi'><meta charset='utf-8'><title>Legal RAG Demo</title><body><main><h1>Vietnamese Legal RAG</h1><p id='banner' role='alert'><strong>DỮ LIỆU HƯ CẤU CHỈ DÙNG ĐỂ KIỂM THỬ — KHÔNG PHẢI TƯ VẤN PHÁP LUẬT</strong></p><p id='mode'>Chế độ dữ liệu hư cấu</p><p id='caveat' role='status' hidden></p><p id='scope'>Phạm vi: thử việc, hợp đồng, giờ làm và nghỉ phép. Hiệu lực cần được xem xét.</p><form id='chat'><label>Câu hỏi <input name='question' required></label><label>Ngày pháp lý <input name='legal_date' type='date'></label><button>Gửi</button></form><section aria-live='polite'><h2 id='state'>Sẵn sàng</h2><pre id='result'></pre><details><summary>Nguồn và trích đoạn</summary><div id='sources'>Chưa có kết quả.</div></details></section></main><script>const f=document.querySelector('#chat'),mode=document.querySelector('#mode'),banner=document.querySelector('#banner'),caveat=document.querySelector('#caveat'),b=f.querySelector('button'),state=document.querySelector('#state'),r=document.querySelector('#result'),s=document.querySelector('#sources');const labels={answer:'Trả lời',partial:'Trả lời một phần',provisional:'Trả lời tạm thời theo bản dữ liệu',clarify:'Cần làm rõ',abstain_conflict:'Bằng chứng xung đột',abstain_insufficient_evidence:'Chưa thể xác nhận theo ngày yêu cầu',unavailable:'Không khả dụng'};f.onsubmit=async e=>{e.preventDefault();b.disabled=true;state.textContent='Đang xử lý';r.textContent='';s.textContent='';caveat.textContent='';let d=Object.fromEntries(new FormData(f));if(!d.legal_date)delete d.legal_date;try{let x=await fetch('/api/answer',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(d)}),z=await x.json(),a=z.answer||{};mode.textContent=z.demo?'Chế độ dữ liệu hư cấu':(a.state==='provisional'?'Trích dẫn tạm thời từ bản dữ liệu':'Chế độ dữ liệu cấu hình');banner.hidden=!z.demo;caveat.textContent=z.caveat||'';caveat.hidden=!z.caveat;state.textContent=labels[a.state]||'Không khả dụng';r.textContent=a.text||a.reason||'Không có kết quả.';(z.sources||[]).forEach(c=>{let p=document.createElement('p');p.textContent=c.current_validity==='unverified'?`${c.evidence_id||''} · ${c.document_version_id||''} · ${c.so_ky_hieu||''} · Hiệu lực chưa xác minh · ${c.quote||''}`:`${c.evidence_id||''} · ${c.document_version_id||''} · Hiệu lực: ${c.effective_from_day||''}–${c.effective_to_day||''}; Rà soát: ${c.reviewed_through_day||''} · ${c.quote||''}`;if(c.source_url){let a=document.createElement('a');a.href=c.source_url;a.textContent=' Nguồn';a.rel='noopener';p.append(a)}s.append(p)});if(!s.textContent)s.textContent='Không có trích đoạn.'}catch(_){state.textContent='Không khả dụng';r.textContent='Không thể kết nối dịch vụ.';s.textContent='Không có trích đoạn.'}finally{b.disabled=false}}</script></body></html>"""
try:
    app = create_app() if __name__ != "__main__" else None
except RuntimeError:
    app = None


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(create_app(), host="127.0.0.1", port=8000)
