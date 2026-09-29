"""Privacy-safe event shape: raw questions and answer text never enter logs."""
import hashlib


def event(stage, *, trace_id, query=None, duration_ms=None, outcome=None, provenance=None, evidence_ids=None, usage=None, reason=None):
    row = {"trace_id": trace_id, "stage": stage, "outcome": outcome, "duration_ms": duration_ms, "provenance": dict(provenance or {}), "evidence_ids": list(evidence_ids or []), "usage": dict(usage or {}) if isinstance(usage, dict) else None, "reason": reason}
    if query is not None:
        row["query_sha256"] = hashlib.sha256(query.encode("utf-8")).hexdigest()
    return row
