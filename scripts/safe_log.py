"""Privacy-safe event shape: raw questions and answer text never enter logs."""
import hashlib


def event(stage, *, trace_id, query=None, duration_ms=None, outcome=None, provenance=None, evidence_ids=None, usage=None, reason=None):
    allowed_provenance = {key: value for key, value in (provenance or {}).items() if key in {"model_version", "prompt_version", "index_version"} and isinstance(value, str)}
    allowed_usage = {key: value for key, value in usage.items() if key in {"prompt_tokens", "completion_tokens", "total_tokens"} and type(value) is int and value >= 0} if isinstance(usage, dict) else {}
    row = {"trace_id": trace_id, "stage": stage, "outcome": outcome, "duration_ms": duration_ms, "provenance": allowed_provenance, "evidence_ids": [value for value in (evidence_ids or []) if isinstance(value, str)], "usage": allowed_usage or None, "reason": reason if reason in {"provider_timeout", "provider_error", "invalid_provider_output", "clarify", "unavailable", "abstain_conflict", "abstain_insufficient_evidence"} else None}
    if query is not None:
        row["query_sha256"] = hashlib.sha256(query.encode("utf-8")).hexdigest()
    return row
