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
from provisional_policy import PROVISIONAL_CAVEAT, decide_provisional_eligibility, decide_snapshot_excerpt_eligibility


_VALIDATION_REASON_CODES = {
    "structured_answer_required", "invalid_evidence_schema", "invalid_state", "invalid_schema",
    "empty_claims", "invalid_claim_schema", "invalid_citation_schema", "partial_reason_required",
    "invalid_legal_date", "requested_legal_date_required", "provisional_as_of_date_not_allowed",
    "invalid_answer_legal_date", "contradictory_legal_date", "non_answer_state_contains_claims",
    "unvalidated_text",
}


def _citation_diagnostic(validation):
    codes = {code for code in validation.get("invalid_citations", [])
             if isinstance(code, str) and code in _VALIDATION_REASON_CODES}
    if any(code not in _VALIDATION_REASON_CODES for code in validation.get("invalid_citations", [])):
        codes.add("evidence_or_claim_reference")
    if validation.get("unknown_ids"):
        codes.add("unknown_evidence_reference")
    if validation.get("uncited_claims"):
        codes.add("uncited_claim")
    return {"phase": "citation_validation",
            "outcome": "valid" if validation.get("valid") is True else "rejected",
            "validation_reason_codes": sorted(codes),
            "invalid_citation_count": len(validation.get("invalid_citations", [])),
            "unknown_evidence_count": len(validation.get("unknown_ids", [])),
            "uncited_claim_count": len(validation.get("uncited_claims", []))}


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
            sources.append({"evidence_id": citation["evidence_id"], "document_version_id": version, "title": source.get("title"), "so_ky_hieu": source.get("so_ky_hieu"), "issuer": source.get("issuer"), "reported_status": source.get("reported_status"), "reported_status_conflict": source.get("reported_status_conflict"), "current_validity": "unverified", "amendment_state": source.get("amendment_state"), "quarantined_related_document_ids": source.get("quarantined_related_document_ids", []), "source_dataset_revision": source.get("source_dataset_revision"), "quote": citation["quote"], "source_url": url})
            continue
        try: dates = {key: date.fromordinal(source[key]).isoformat() for key in ("effective_from_day", "effective_to_day", "reviewed_through_day")}
        except (KeyError, TypeError, ValueError): continue
        sources.append({"evidence_id": citation["evidence_id"], "document_version_id": version, **dates, "quote": citation["quote"], "source_url": url})
    return sources


def _provisional_evidence(rows, question, requested_as_of_date, source_catalog=None):
    references = list(re.finditer(r"\b(?:điều|article)\s+(\d+[a-z]?)\b|\btrích\s+(?:nguyên văn\s+)?(?:điều\s+)?(\d+[a-z]?)\b", question, re.IGNORECASE))
    if references:
        gate = decide_provisional_eligibility(question, [], requested_as_of_date=requested_as_of_date)
        if not gate["allowed"] and gate["reason"] != "no_evidence":
            return gate, {}
        requested_numbers = {next(group for group in match.groups() if group).casefold() for match in references}
        if len(requested_numbers) != 1:
            return _article_request_denial("requested_article_ambiguous"), {}
        number = next(iter(requested_numbers)).casefold()
        catalog_rows = source_catalog.values() if isinstance(source_catalog, dict) else source_catalog
        catalog_rows = list(catalog_rows) if catalog_rows is not None else rows
        possible_sources = [row for row in catalog_rows if _article_number(row) == number and _metadata(row, "pham_vi") == "Trung ương" and _metadata(row, "retrieval_index_candidate") is True and (source_catalog is None or isinstance(_metadata(row, "topic_candidates"), list) and bool(_metadata(row, "topic_candidates")))]
        qualifier = re.search(r"\b(?:trong|của)\s+(?:bộ luật|nghị định|thông tư)(?:\s+(?:lao\s+động|số\s+\d+[\w/-]*)){1,2}", question, re.IGNORECASE)
        if qualifier:
            requested_document = re.sub(r"^(?:trong|của)\s+", "", qualifier.group(0), flags=re.IGNORECASE).casefold()
            possible_sources = [row for row in possible_sources if requested_document in _document_identity(row)]
        possible_sources = list({(row.get("article_id"), row.get("document_version_id")): row for row in possible_sources}.values())
        if len(possible_sources) != 1:
            return _article_request_denial("requested_article_not_unambiguous"), {}
        source = possible_sources[0]
        metadata = source.get("document_metadata") if isinstance(source.get("document_metadata"), dict) else {}
        source = {**metadata, **source}
        source["canonical_text"] = source.get("canonical_text", source.get("text"))
        source["source_url"] = source.get("source_url", source.get("source_dataset_url"))
        decision = decide_provisional_eligibility(question, [source], requested_as_of_date=requested_as_of_date)
        if not decision["allowed"]:
            return decision, {}
        rows = [source]
    else:
        decision = decide_provisional_eligibility(question, rows, requested_as_of_date=requested_as_of_date)
        if not decision["allowed"]:
            return decision, {}
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


def _metadata(row, key):
    value = row.get(key)
    if value is None and isinstance(row.get("document_metadata"), dict):
        value = row["document_metadata"].get(key)
    return value


def _document_identity(row):
    return " ".join(str(_metadata(row, key) or "") for key in ("title", "so_ky_hieu")).casefold()


def _article_request_denial(reason):
    return {"allowed": False, "mode": "abstain", "reason": reason,
            "message": "Không thể xác định duy nhất đúng điều khoản và văn bản được yêu cầu.",
            "caveat": PROVISIONAL_CAVEAT}


def _snapshot_excerpt_evidence(retrieved_rows, source_catalog, question, requested_as_of_date):
    if not isinstance(source_catalog, dict) or not isinstance(retrieved_rows, list):
        return {"allowed": False, "reason": "no_evidence", "message": "Không tìm thấy đoạn văn bản phù hợp trong phạm vi dữ liệu này.", "caveat": PROVISIONAL_CAVEAT}, {}
    by_version = {}
    for row in source_catalog.values():
        if not isinstance(row, dict):
            continue
        metadata = row.get("document_metadata") if isinstance(row.get("document_metadata"), dict) else {}
        merged = {**metadata, **row}
        key = (merged.get("article_id"), merged.get("document_version_id"))
        if all(isinstance(value, str) and value for value in key):
            by_version.setdefault(key, []).append(merged)
    selected, first_denial = {}, None
    for hit in retrieved_rows:
        if not isinstance(hit, dict):
            continue
        key = (hit.get("article_id"), hit.get("document_version_id"))
        catalog_matches = by_version.get(key, [])
        if len(catalog_matches) != 1:
            continue
        row = catalog_matches[0]
        text = row.get("canonical_text", row.get("text"))
        if not isinstance(text, str) or not text.strip():
            continue
        excerpt_text = text[:2400]
        if len(text) > len(excerpt_text):
            boundary = excerpt_text.rfind(" ")
            if boundary > 0:
                excerpt_text = excerpt_text[:boundary]
        evidence_id = f"{key[0]}:{key[1]}"
        candidate = {**row, "canonical_text": text, "document_version_id": key[1],
                     "provisional_snapshot_eligible": True, "snapshot_excerpt_experimental": True,
                     "snapshot_excerpt_text": excerpt_text}
        decision = decide_snapshot_excerpt_eligibility(question, [candidate], requested_as_of_date=requested_as_of_date)
        if decision["allowed"]:
            selected[evidence_id] = candidate
        elif not selected:
            first_denial = first_denial or decision
        if len(selected) == 12:
            break
    if not selected:
        return (first_denial or decide_snapshot_excerpt_eligibility(
            question, [], requested_as_of_date=requested_as_of_date)), {}
    return decide_snapshot_excerpt_eligibility(question, list(selected.values()), requested_as_of_date=requested_as_of_date), selected


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


def create_app(provider=None, event_sink=None, retriever=None, provenance=None, provisional_snapshot_enabled=False, experimental_snapshot_excerpt_enabled=False):
    try:
        from fastapi import FastAPI, HTTPException
        from fastapi.responses import HTMLResponse, JSONResponse
        from pydantic import BaseModel
    except ImportError as error:
        raise RuntimeError("install requirements-app.txt to run the demo API") from error

    class ChatRequest(BaseModel):
        question: str
        legal_date: str | None = None

    provider = provider or (DisabledProvider() if provisional_snapshot_enabled or experimental_snapshot_excerpt_enabled else MockProvider())
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
        experimental_excerpt = False
        policy_decision = None
        if retriever is None:
            retrieval = synthetic_retrieve(request.question)
            selected_evidence = {evidence_id: DEMO_EVIDENCE[evidence_id] for evidence_id in retrieval["selected_evidence_ids"]}
        else:
            try:
                snapshot_search = getattr(retriever, "search_snapshot_excerpt", None) if experimental_snapshot_excerpt_enabled else None
                retrieval = snapshot_search(request.question, legal_date) if callable(snapshot_search) else retriever.search(request.question, legal_date)
                selected_evidence = _configured_evidence(retrieval.get("evidence", []), legal_date) if isinstance(retrieval, dict) else {}
                if not selected_evidence and (provisional_snapshot_enabled or experimental_snapshot_excerpt_enabled) and isinstance(retrieval, dict):
                    policy_decision, selected_evidence = _provisional_evidence(retrieval.get("evidence", []), request.question, request.legal_date is not None, getattr(retriever, "articles", None))
                    provisional = bool(selected_evidence)
                    if not provisional and experimental_snapshot_excerpt_enabled:
                        policy_decision, selected_evidence = _snapshot_excerpt_evidence(
                            retrieval.get("evidence", []), getattr(retriever, "articles", None), request.question,
                            request.legal_date is not None)
                        experimental_excerpt = bool(selected_evidence)
                        provisional = experimental_excerpt
            except Exception:
                selected_evidence, retrieval = {}, {"evidence": []}
            if experimental_snapshot_excerpt_enabled:
                selected_evidence = dict(list(selected_evidence.items())[:3])
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
        if provisional and not experimental_excerpt:
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
            provider_evidence = selected_evidence
            if experimental_excerpt:
                provider_evidence = {key: {**source, "canonical_text": source["snapshot_excerpt_text"]}
                                     for key, source in selected_evidence.items()}
            answer = provider.answer(request.question, None if provisional else legal_date, provider_evidence)
        except TimeoutError as error:
            event_sink.append(event("provider", trace_id=trace_id, duration_ms=(time.perf_counter_ns() - provider_started) / 1_000_000, outcome="timeout", reason="provider_timeout", provenance=provenance, diagnostics=getattr(error, "diagnostics", None)))
            return unavailable(503, "Nhà cung cấp quá thời gian chờ.")
        except ValueError as error:
            event_sink.append(event("provider", trace_id=trace_id, duration_ms=(time.perf_counter_ns() - provider_started) / 1_000_000, outcome="invalid", reason="invalid_provider_output", provenance=provenance, diagnostics=getattr(error, "diagnostics", None)))
            return unavailable(502, "Nhà cung cấp trả về dữ liệu không hợp lệ.")
        except Exception as error:
            event_sink.append(event("provider", trace_id=trace_id, duration_ms=(time.perf_counter_ns() - provider_started) / 1_000_000, outcome="error", reason="provider_error", provenance=provenance, diagnostics=getattr(error, "diagnostics", None)))
            return unavailable(503, "Nhà cung cấp không khả dụng.")
        if not isinstance(answer, dict):
            event_sink.append(event("provider", trace_id=trace_id, duration_ms=(time.perf_counter_ns() - provider_started) / 1_000_000, outcome="invalid", reason="invalid_provider_output", provenance=provenance))
            return unavailable(502, "Nhà cung cấp trả về dữ liệu không hợp lệ.")
        usage = answer.pop("_usage", None)
        provider_diagnostics = answer.pop("_provider_diagnostics", None)
        event_sink.append(event("provider", trace_id=trace_id, duration_ms=(time.perf_counter_ns() - provider_started) / 1_000_000, outcome="ok", evidence_ids=selected_evidence, usage=usage, provenance=provenance, diagnostics=provider_diagnostics))
        validation_started = time.perf_counter_ns()
        if experimental_excerpt and (answer.get("state") not in {
                "provisional", "abstain_conflict", "abstain_insufficient_evidence", "clarify", "unavailable"}
                or answer.get("state") == "provisional" and (
                    not isinstance(answer.get("citations"), list) or not 1 <= len(answer["citations"]) <= 3
                    or any(not isinstance(citation, dict) or not isinstance(citation.get("quote"), str)
                           or len(citation["quote"]) > 500 for citation in answer["citations"]))):
            return unavailable(502, "Đoạn trích thử nghiệm vượt quá giới hạn hoặc không đúng trạng thái.")
        validation = validate_citations(answer, selected_evidence, requested_legal_date=None if provisional else legal_date)
        if (not validation["valid"] and experimental_excerpt and answer.get("state") == "provisional"
                and isinstance(answer.get("text"), str) and answer["text"].strip()
                and validation.get("unknown_ids") == [] and validation.get("uncited_claims") == []
                and validation.get("invalid_citations") == ["unvalidated_text"]):
            claims = answer.get("claims")
            if isinstance(claims, list) and all(isinstance(claim, dict) and isinstance(claim.get("text"), str)
                                                for claim in claims):
                candidate = {**answer, "text": " ".join(claim["text"].strip() for claim in claims).strip()}
                candidate_validation = validate_citations(candidate, selected_evidence, requested_legal_date=None)
                if candidate_validation["valid"]:
                    answer, validation = candidate, candidate_validation
        if (not validation["valid"] and experimental_excerpt and isinstance(answer.get("text"), str)
                and not answer["text"].strip()):
            claims = answer.get("claims")
            if isinstance(claims, list) and all(isinstance(claim, dict) and isinstance(claim.get("text"), str)
                                                for claim in claims):
                candidate = {**answer, "text": " ".join(claim["text"].strip() for claim in claims).strip()}
                candidate_validation = validate_citations(
                    candidate, selected_evidence, requested_legal_date=None)
                if candidate_validation["valid"]:
                    answer, validation = candidate, candidate_validation
        if not validation["valid"]:
            event_sink.append(event("validate", trace_id=trace_id, duration_ms=(time.perf_counter_ns() - validation_started) / 1_000_000, outcome="rejected", reason="invalid_provider_output", evidence_ids=selected_evidence, provenance=provenance, diagnostics=[_citation_diagnostic(validation)]))
            return unavailable(502, "Đầu ra không vượt qua kiểm tra bằng chứng.", validation={"valid": False, "reason": "invalid_provider_output"})
        event_sink.append(event("validate", trace_id=trace_id, duration_ms=(time.perf_counter_ns() - validation_started) / 1_000_000, outcome="ok", evidence_ids=selected_evidence, provenance=provenance, diagnostics=[_citation_diagnostic(validation)]))
        event_sink.append(event("answer", trace_id=trace_id, outcome=answer["state"], evidence_ids=selected_evidence, usage=usage, provenance=provenance, reason=answer["state"]))
        return {"demo": retriever is None, "banner": DEMO_BANNER if retriever is None else None, "caveat": policy_decision["caveat"] if provisional else None, "state": answer["state"], "answer": answer, "sources": _safe_sources(answer, selected_evidence), "validation": validation, "retrieval": retrieval}

    @app.get("/api/health")
    @app.get("/health")
    def health():
        return {"ok": True, "demo": retriever is None, "corpus": "fictional-only" if retriever is None else provenance.get("corpus", "configured")}

    @app.get("/api/corpus")
    def corpus():
        demo = retriever is None
        revision = provenance.get("dataset_revision")
        return {"demo": demo, "banner": DEMO_BANNER if demo else None, "corpus": "fictional-only" if demo else provenance.get("corpus", "configured"), "snapshot_revision": revision, "snapshot_verified": demo or isinstance(revision, str) and bool(re.fullmatch(r"[0-9a-f]{40}", revision)), "legal_corpus_activated": False, "answer_mode": "experimental_snapshot_excerpt" if experimental_snapshot_excerpt_enabled else "provisional_snapshot" if provisional_snapshot_enabled else "reviewed_only", "current_validity": "unverified"}

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


UI_HTML = """<!doctype html>
<html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Vietnamese Legal RAG</title><style>
:root{color-scheme:light;--ink:#1d3038;--muted:#546970;--paper:#f3f6f5;--card:#fff;--accent:#176b68;--line:#d6e1df}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:16px/1.55 system-ui,sans-serif}
main{width:min(100% - 2rem,760px);margin:3rem auto}h1,h2{line-height:1.2}h1{font-size:clamp(1.7rem,5vw,2.4rem)}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:clamp(1rem,4vw,2rem);box-shadow:0 8px 28px #18363a0b}
.notice{padding:.8rem 1rem;border-left:4px solid var(--accent);background:#e8f2f0;border-radius:4px}
#banner{background:#fff2dc;border-color:#b56b12}#scope,#freshness{color:var(--muted)}form{display:grid;gap:1rem;margin:1.5rem 0}
label{display:grid;gap:.35rem;font-weight:600}input,button{font:inherit;border-radius:8px;padding:.7rem .8rem}input{border:1px solid #9aacab;color:var(--ink);background:white}
button{width:fit-content;border:0;background:var(--accent);color:white;font-weight:700;cursor:pointer}button:disabled{opacity:.65;cursor:wait}
:focus-visible{outline:3px solid #e7a63a;outline-offset:3px}#state{margin-bottom:.5rem}#result{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit}
details{border-top:1px solid var(--line);padding-top:1rem}summary{cursor:pointer;font-weight:700;color:var(--accent)}.source{margin:1rem 0;padding:.8rem;background:#f6f8f7;border-radius:8px}
.quote{display:block;margin:.5rem 0;color:#283b40;font:1.05rem/1.65 Georgia,serif;white-space:pre-wrap;overflow-wrap:anywhere}a{color:#075e5b}
@media(max-width:520px){main{width:min(100% - 1rem,760px);margin:1rem auto}.card{padding:1rem}button{width:100%}}
</style></head><body><main><h1>Vietnamese Legal RAG</h1><div class="card">
<p id="banner" class="notice" role="alert" hidden><strong>DỮ LIỆU HƯ CẤU CHỈ DÙNG ĐỂ KIỂM THỬ — KHÔNG PHẢI TƯ VẤN PHÁP LUẬT</strong></p>
<p id="mode" class="notice" role="status">Đang xác minh chế độ dữ liệu…</p><p id="caveat" role="status" hidden></p>
<p id="scope"><strong>Phạm vi hỗ trợ:</strong> thử việc, hợp đồng, giờ làm và nghỉ phép.</p>
<p id="freshness">Ảnh chụp dataset <span id="revision">chưa xác minh</span>. Hiệu lực hiện tại chưa được xác minh. Ngày hết hiệu lực để trống không đồng nghĩa văn bản còn hiệu lực.</p>
<form id="chat"><label for="question">Câu hỏi<input id="question" name="question" autocomplete="off" required></label>
<label for="legal-date">Ngày cần tra cứu (không bắt buộc)<input id="legal-date" name="legal_date" type="date"></label><button type="submit" disabled>Gửi câu hỏi</button></form>
<section aria-live="polite" aria-atomic="false"><h2 id="state">Sẵn sàng</h2><pre id="result"></pre>
<details><summary>Nguồn và trích đoạn</summary><div id="sources">Chưa có kết quả.</div></details></section></div></main>
<script>const f=document.querySelector('#chat'),mode=document.querySelector('#mode'),banner=document.querySelector('#banner'),caveat=document.querySelector('#caveat'),b=f.querySelector('button'),state=document.querySelector('#state'),r=document.querySelector('#result'),s=document.querySelector('#sources'),revision=document.querySelector('#revision');let answerMode='reviewed_only';const labels={answer:'Trả lời',partial:'Trả lời một phần',provisional:'Trích đoạn nguyên văn từ bản dữ liệu — hiệu lực chưa xác minh',clarify:'Cần làm rõ',abstain_conflict:'Bằng chứng xung đột',abstain_insufficient_evidence:'Chưa đủ bằng chứng',unavailable:'Dịch vụ hiện không khả dụng'};async function loadCorpus(){try{let x=await fetch('/api/corpus'),z=await x.json();if(!x.ok||typeof z.demo!=='boolean'||!z.answer_mode||z.legal_corpus_activated!==false||z.current_validity!=='unverified'||(!z.demo&&z.snapshot_verified!==true))throw Error('invalid corpus status');answerMode=z.answer_mode;mode.textContent=z.demo?'Chế độ dữ liệu hư cấu':(z.answer_mode==='experimental_snapshot_excerpt'?'Thử nghiệm trích đoạn snapshot — hiệu lực chưa xác minh':z.answer_mode==='provisional_snapshot'?'Trích đoạn từ snapshot; hiệu lực chưa xác minh':'Chế độ dữ liệu cấu hình');banner.hidden=!z.demo;revision.textContent=z.snapshot_revision||'không được cung cấp';b.disabled=false}catch(_){mode.textContent='Không thể xác minh chế độ dữ liệu; tra cứu bị khóa.';banner.textContent='Cấu hình dữ liệu chưa được xác minh. Không gửi câu hỏi.';banner.hidden=false;b.disabled=true}}loadCorpus();f.onsubmit=async e=>{e.preventDefault();b.disabled=true;state.textContent='Đang xử lý';r.textContent='';s.textContent='';caveat.textContent='';let d=Object.fromEntries(new FormData(f));if(!d.legal_date)delete d.legal_date;try{let x=await fetch('/api/answer',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(d)}),z=await x.json(),a=z.answer||{};mode.textContent=z.demo?'Chế độ dữ liệu hư cấu':(answerMode==='experimental_snapshot_excerpt'?'Thử nghiệm trích đoạn snapshot — hiệu lực chưa xác minh':a.state==='provisional'?'Trích đoạn tạm thời từ bản dữ liệu':'Chế độ dữ liệu cấu hình');banner.hidden=!z.demo;caveat.textContent=z.caveat||'';caveat.hidden=!z.caveat;state.textContent=labels[a.state]||'Không khả dụng';r.textContent=a.text||a.reason||'Không có kết quả.';(z.sources||[]).forEach(c=>{let p=document.createElement('div');p.className='source';let m=document.createElement('p');m.textContent=c.current_validity==='unverified'?`${c.evidence_id||''} · ${c.document_version_id||''} · ${c.so_ky_hieu||''} · Hiệu lực chưa xác minh`:`${c.evidence_id||''} · ${c.document_version_id||''} · Hiệu lực: ${c.effective_from_day||''}–${c.effective_to_day||''}; Rà soát: ${c.reviewed_through_day||''}`;p.append(m);let q=document.createElement('blockquote');q.className='quote';q.textContent=c.quote||'';p.append(q);if(c.source_url){let a=document.createElement('a');a.href=c.source_url;a.textContent='Mở nguồn';a.rel='noopener noreferrer';a.target='_blank';p.append(a)}s.append(p)});if(!s.textContent)s.textContent='Không có trích đoạn.'}catch(_){state.textContent='Không khả dụng';r.textContent='Không thể kết nối dịch vụ.';s.textContent='Không có trích đoạn.'}finally{b.disabled=false}}</script></body></html>"""
try:
    app = create_app() if __name__ != "__main__" else None
except RuntimeError:
    app = None


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(create_app(), host="127.0.0.1", port=8000)
