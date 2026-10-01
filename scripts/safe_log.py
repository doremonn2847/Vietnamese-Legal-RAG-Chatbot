"""Privacy-safe event shape: raw questions and answer text never enter logs."""
import hashlib
import math
import re


_DIAGNOSTIC_PHASES = {"http_transport", "http_response_read", "provider_envelope_json",
                      "response_envelope", "provider_content", "content_json",
                      "citation_validation"}
_DIAGNOSTIC_OUTCOMES = {"failed", "response_received", "parsed", "extracted", "valid", "rejected"}
_TYPE_NAMES = {"dict", "list", "str", "int", "float", "bool", "NoneType", "tuple"}
_SHAPE_COUNTS = {"top_level_key_count", "choices_count", "content_length"}
_UPSTREAM_ERROR_TYPES = {"invalid_request_error", "authentication_error", "permission_error", "rate_limit_error", "not_found_error", "server_error", "internal_server_error", "other"}
_UPSTREAM_ERROR_CODES = {"json_validate_failed", "response_format_not_supported", "unsupported_value", "invalid_value", "missing_required_parameter", "unknown_parameter", "model_not_found", "rate_limit_exceeded", "invalid_api_key", "insufficient_quota", "context_length_exceeded", "other"}
_UPSTREAM_ERROR_PARAMS = {"response_format", "max_completion_tokens", "max_tokens", "reasoning_effort", "model", "messages", "other"}
_UPSTREAM_ERROR_CLASSIFICATIONS = {"structured_output_rejected", "request_parameter_rejected", "authentication_or_permission_rejected", "rate_limited", "model_unavailable", "other"}
_FAILED_GENERATION_VERDICTS = {"absent", "not_string", "valid", "invalid", "unassessed"}
_VALIDATION_CODES = {
    "structured_answer_required", "invalid_evidence_schema", "invalid_state", "invalid_schema",
    "empty_claims", "invalid_claim_schema", "invalid_citation_schema", "partial_reason_required",
    "invalid_legal_date", "requested_legal_date_required", "provisional_as_of_date_not_allowed",
    "invalid_answer_legal_date", "contradictory_legal_date", "non_answer_state_contains_claims",
    "unvalidated_text", "unknown_evidence_reference", "uncited_claim",
    "evidence_or_claim_reference",
}


def _safe_diagnostic(source):
    if not isinstance(source, dict) or not isinstance(source.get("phase"), str) or source["phase"] not in _DIAGNOSTIC_PHASES:
        return None
    row = {"phase": source["phase"]}
    if isinstance(source.get("outcome"), str) and source["outcome"] in _DIAGNOSTIC_OUTCOMES:
        row["outcome"] = source["outcome"]
    exception_class = source.get("exception_class")
    if isinstance(exception_class, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,79}", exception_class):
        row["exception_class"] = exception_class
    status = source.get("upstream_http_status")
    if type(status) is int and 100 <= status <= 599:
        row["upstream_http_status"] = status
    for key, allowed in (("upstream_error_type", _UPSTREAM_ERROR_TYPES),
                         ("upstream_error_code", _UPSTREAM_ERROR_CODES),
                         ("upstream_error_param", _UPSTREAM_ERROR_PARAMS),
                         ("upstream_error_classification", _UPSTREAM_ERROR_CLASSIFICATIONS),
                         ("upstream_error_message_classification", _UPSTREAM_ERROR_CLASSIFICATIONS)):
        value = source.get(key)
        if isinstance(value, str) and value in allowed:
            row[key] = value
    present = source.get("failed_generation_present")
    if type(present) is bool:
        row["failed_generation_present"] = present
    length = source.get("failed_generation_length_chars")
    if type(length) is int and length >= 0:
        row["failed_generation_length_chars"] = length
    verdict = source.get("failed_generation_json_verdict")
    if isinstance(verdict, str) and verdict in _FAILED_GENERATION_VERDICTS:
        row["failed_generation_json_verdict"] = verdict
    reason_class = source.get("reason_class")
    if isinstance(reason_class, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,79}", reason_class):
        row["reason_class"] = reason_class
    elapsed = source.get("elapsed_ms")
    if type(elapsed) in (int, float) and math.isfinite(elapsed) and elapsed >= 0:
        row["elapsed_ms"] = round(elapsed, 2)
    shape = source.get("response_shape")
    if isinstance(shape, dict):
        safe_shape = {}
        for key, value in shape.items():
            if not isinstance(key, str):
                continue
            if key in _SHAPE_COUNTS and type(value) is int and value >= 0:
                safe_shape[key] = value
            elif key.endswith("_type") or key == "answer_type":
                safe_shape[key] = value if isinstance(value, str) and value in _TYPE_NAMES else "other"
        row["response_shape"] = safe_shape
    finish = source.get("finish_reason")
    if isinstance(finish, str) and finish in {"stop", "length", "tool_calls", "function_call", "content_filter", "other"}:
        row["finish_reason"] = finish
    usage = source.get("usage")
    if isinstance(usage, dict):
        safe_usage = {key: value for key, value in usage.items()
                      if key in {"prompt_tokens", "completion_tokens", "total_tokens"}
                      and type(value) is int and value >= 0}
        if safe_usage:
            row["usage"] = safe_usage
    codes = source.get("validation_reason_codes")
    if isinstance(codes, list):
        row["validation_reason_codes"] = sorted({code for code in codes
                                                 if isinstance(code, str) and code in _VALIDATION_CODES})
    for key in ("invalid_citation_count", "unknown_evidence_count", "uncited_claim_count"):
        value = source.get(key)
        if type(value) is int and value >= 0:
            row[key] = value
    return row


def event(stage, *, trace_id, query=None, duration_ms=None, outcome=None, provenance=None, evidence_ids=None, usage=None, reason=None, diagnostics=None):
    allowed_provenance = {key: value for key, value in (provenance or {}).items() if key in {"model_version", "prompt_version", "index_version"} and isinstance(value, str)}
    allowed_usage = {key: value for key, value in usage.items() if key in {"prompt_tokens", "completion_tokens", "total_tokens"} and type(value) is int and value >= 0} if isinstance(usage, dict) else {}
    row = {"trace_id": trace_id, "stage": stage, "outcome": outcome, "duration_ms": duration_ms, "provenance": allowed_provenance, "evidence_ids": [value for value in (evidence_ids or []) if isinstance(value, str)], "usage": allowed_usage or None, "reason": reason if reason in {"provider_timeout", "provider_error", "invalid_provider_output", "clarify", "unavailable", "abstain_conflict", "abstain_insufficient_evidence"} else None}
    if query is not None:
        row["query_sha256"] = hashlib.sha256(query.encode("utf-8")).hexdigest()
    if isinstance(diagnostics, list):
        safe_diagnostics = [item for source in diagnostics if (item := _safe_diagnostic(source)) is not None]
        if safe_diagnostics:
            row["diagnostics"] = safe_diagnostics
    return row
