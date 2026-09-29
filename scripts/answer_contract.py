"""Structured checks around grounded answer states; no model calls."""
from datetime import date


def validate_citations(answer, evidence, requested_legal_date=None):
    if not isinstance(answer, dict):
        return {"valid": False, "citation_ids": [], "unknown_ids": [], "uncited_claims": [], "invalid_citations": ["structured_answer_required"]}
    if evidence is None:
        evidence = {}
    if not isinstance(evidence, dict):
        return {"valid": False, "citation_ids": [], "unknown_ids": [], "uncited_claims": [], "invalid_citations": ["invalid_evidence_schema"]}
    state = answer.get("state")
    if not isinstance(state, str) or state not in {"answer", "partial", "clarify", "unavailable", "abstain_conflict", "abstain_insufficient_evidence"}:
        return {"valid": False, "citation_ids": [], "unknown_ids": [], "uncited_claims": [], "invalid_citations": ["invalid_state"]}
    claims = answer.get("claims") or []
    citations = answer.get("citations") or []
    text = answer.get("text", "")
    if not isinstance(text, str) or not isinstance(claims, list) or not isinstance(citations, list) or any(not isinstance(claim, dict) for claim in claims) or any(not isinstance(citation, dict) for citation in citations):
        return {"valid": False, "citation_ids": [], "unknown_ids": [], "uncited_claims": [], "invalid_citations": ["invalid_schema"]}
    if state in {"answer", "partial"} and not claims:
        return {"valid": False, "citation_ids": [], "unknown_ids": [], "uncited_claims": [], "invalid_citations": ["empty_claims"]}
    claim_ids = [claim.get("claim_id") for claim in claims]
    if any(not isinstance(claim.get("claim_id"), str) or not claim["claim_id"].strip() or not isinstance(claim.get("text"), str) or not claim["text"].strip() or not isinstance(claim.get("evidence_ids"), list) or any(not isinstance(evidence_id, str) or not evidence_id.strip() for evidence_id in claim["evidence_ids"]) for claim in claims) or len(set(claim_ids)) != len(claim_ids):
        return {"valid": False, "citation_ids": [], "unknown_ids": [], "uncited_claims": [], "invalid_citations": ["invalid_claim_schema"]}
    if any(not isinstance(citation.get("evidence_id"), str) or not citation["evidence_id"].strip() or not isinstance(citation.get("quote"), str) or not isinstance(citation.get("span_start"), int) or not isinstance(citation.get("span_end"), int) or not isinstance(citation.get("reviewed_version_id"), str) or not citation["reviewed_version_id"].strip() for citation in citations):
        return {"valid": False, "citation_ids": [], "unknown_ids": [], "uncited_claims": [], "invalid_citations": ["invalid_citation_schema"]}
    if state == "partial" and (not isinstance(answer.get("unanswered", ""), str) or not isinstance(answer.get("reason", ""), str) or not (answer.get("unanswered", "").strip() or answer.get("reason", "").strip())):
        return {"valid": False, "citation_ids": [], "unknown_ids": [], "uncited_claims": [], "invalid_citations": ["partial_reason_required"]}
    citation_ids = [citation["evidence_id"] for citation in citations]
    known = set(evidence)
    unknown = sorted({evidence_id for claim in claims for evidence_id in claim.get("evidence_ids", []) if evidence_id not in known})
    uncited = [claim.get("claim_id", "") for claim in claims if not claim.get("evidence_ids")]
    invalid = []
    legal_day = None
    if requested_legal_date:
        try:
            legal_day = date.fromisoformat(requested_legal_date).toordinal()
        except (TypeError, ValueError):
            invalid.append("invalid_legal_date")
    if state in {"answer", "partial"} and legal_day is None:
        invalid.append("requested_legal_date_required")
    if answer.get("legal_date") is not None and not isinstance(answer.get("legal_date"), str):
        invalid.append("invalid_answer_legal_date")
    if answer.get("legal_date") and requested_legal_date and answer["legal_date"] != requested_legal_date:
        invalid.append("contradictory_legal_date")
    for citation in citations:
        evidence_id = citation.get("evidence_id") if isinstance(citation, dict) else None
        source = evidence.get(evidence_id) if evidence_id else None
        if not isinstance(source, dict) or source.get("reviewed_status") != "reviewed" or source.get("central_eligible") is not True:
            invalid.append(evidence_id or "missing_evidence_id")
            continue
        start, end = citation.get("span_start"), citation.get("span_end")
        canonical = source.get("canonical_text", "")
        if not isinstance(canonical, str):
            invalid.append(evidence_id or "missing_evidence_id")
            continue
        if not isinstance(start, int) or not isinstance(end, int) or start < 0 or start >= end or end > len(canonical) or citation.get("quote") != canonical[start:end]:
            invalid.append(evidence_id or "missing_evidence_id")
        elif not citation.get("reviewed_version_id") or citation["reviewed_version_id"] != source.get("reviewed_version_id"):
            invalid.append(evidence_id)
        elif legal_day is not None:
            open_ended = source.get("effective_to_day") is None and source.get("reviewed_open_ended") is True
            if source.get("effective_from_day") is None or source["effective_from_day"] > legal_day or (not open_ended and (source.get("effective_to_day") is None or source["effective_to_day"] <= legal_day)) or source.get("reviewed_through_day") is None or source["reviewed_through_day"] < legal_day:
                invalid.append(evidence_id)
    cited = set(citation_ids)
    for claim in claims:
        if any(evidence_id in known and evidence_id not in cited for evidence_id in claim.get("evidence_ids", [])):
            uncited.append(claim.get("claim_id", ""))
    expected_text = " ".join(claim.get("text", "").strip() for claim in claims).strip()
    if text.strip() != expected_text:
        invalid.append("unvalidated_text")
    if state not in {"answer", "partial"} and (claims or citations or text.strip()):
        invalid.append("non_answer_state_contains_claims")
    return {"valid": not unknown and not uncited and not invalid, "citation_ids": citation_ids, "unknown_ids": unknown, "uncited_claims": sorted(set(uncited)), "invalid_citations": invalid}


def answer_state(*, missing_facts, evidence_conflict, sufficient_evidence):
    if missing_facts:
        return "clarify"
    if evidence_conflict:
        return "abstain_conflict"
    if not sufficient_evidence:
        return "abstain_insufficient_evidence"
    return "answer"
