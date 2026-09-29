"""Privacy-safe event shape: raw questions and answer text never enter logs."""
import hashlib


def event(stage, *, query=None, duration_ms=None, outcome=None, provenance=None):
    row = {"stage": stage, "outcome": outcome, "duration_ms": duration_ms, "provenance": dict(provenance or {})}
    if query is not None:
        row["query_sha256"] = hashlib.sha256(query.encode("utf-8")).hexdigest()
    return row
