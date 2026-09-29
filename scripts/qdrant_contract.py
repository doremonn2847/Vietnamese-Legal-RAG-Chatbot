"""Qdrant REST contract and validation helpers."""
import json
import math
import re
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import date


def stable_point_id(document_id, document_version_id, child_id):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"vietnamese-legal-rag:point:{document_id}:{document_version_id}:{child_id}"))


@dataclass(frozen=True)
class QdrantLocalConfig:
    url: str = "http://localhost:6333"
    image: str = "qdrant/qdrant:v1.13.2"
    storage_path: str = "data/qdrant"
    collection_prefix: str = "legalrag"
    api_key: str | None = None

    def collection_name(self, revision, embedding_spec_sha256=None):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", revision):
            raise ValueError("invalid collection revision")
        suffix = f"_{embedding_spec_sha256[:12]}" if embedding_spec_sha256 else ""
        return f"{self.collection_prefix}_{revision}{suffix}"


class QdrantRestAdapter:
    def __init__(self, config=None, transport=None):
        self.config = config or QdrantLocalConfig()
        self.transport = transport or self._request
        self._dimensions = {}

    def create_collection(self, name, vector_size, distance="Cosine"):
        if vector_size <= 0:
            raise ValueError("vector size must be positive")
        self._dimensions[name] = vector_size
        return self.transport("PUT", f"/collections/{name}", {"vectors": {"size": vector_size, "distance": distance}})

    def upsert(self, collection, points):
        normalized = []
        seen = set()
        dimension = self._dimension_for(collection)
        for point in points:
            point_id = str(point["id"])
            if point_id in seen:
                continue
            payload = dict(point.get("payload", {}))
            _validate_payload_validity(payload)
            normalized.append({"id": point_id, "vector": _validate_vector(point["vector"], dimension), "payload": payload})
            seen.add(point_id)
        return self.transport("PUT", f"/collections/{collection}/points?wait=true", {"points": normalized})

    def search(self, collection, vector, filters=None, limit=10):
        values = _validate_vector(vector)
        _validate_vector(values, self._dimension_for(collection))
        if limit <= 0:
            raise ValueError("limit must be positive")
        if isinstance(filters, list):
            points = {}
            for filter_part in filters:
                for point in self.search(collection, values, filter_part, limit)["result"]:
                    points[str(point["id"])] = point
            return {"result": sorted(points.values(), key=lambda point: (-point["score"], str(point["id"])))[:limit]}
        return self.transport("POST", f"/collections/{collection}/points/search", {"vector": values, "filter": filters or {}, "limit": limit, "with_payload": True})

    def delete_collection(self, collection):
        return self.transport("DELETE", f"/collections/{collection}", {})

    def delete_alias(self, alias):
        return self.transport("POST", "/collections/aliases", {"actions": [{"delete_alias": {"alias_name": alias}}]})

    def activate_alias(self, alias, collection, previous_collection=None):
        actions = []
        if previous_collection:
            actions.append({"delete_alias": {"alias_name": alias}})
        actions.append({"create_alias": {"collection_name": collection, "alias_name": alias}})
        return self.transport("POST", "/collections/aliases", {"actions": actions})

    def rollback_alias(self, alias, previous_collection):
        return self.activate_alias(alias, previous_collection, previous_collection=alias)

    def _request(self, method, path, body):
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["api-key"] = self.config.api_key
        request = urllib.request.Request(self.config.url.rstrip("/") + path, data=json.dumps(body).encode("utf-8"), headers=headers, method=method)
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))

    def _dimension_for(self, collection):
        if collection in self._dimensions:
            return self._dimensions[collection]
        response = self.transport("GET", f"/collections/{collection}", {})
        vectors = response.get("result", {}).get("config", {}).get("params", {}).get("vectors", {})
        dimension = vectors.get("size") if isinstance(vectors, dict) else None
        if not isinstance(dimension, int):
            raise ValueError("collection vector schema is unavailable")
        self._dimensions[collection] = dimension
        return dimension


def legal_filter(*, legal_date, pham_vi="Trung ương", provision=None, include_open_ended=False, **unknown):
    if unknown:
        raise ValueError(f"unknown filter fields: {sorted(unknown)}")
    try:
        legal_day = date.fromisoformat(legal_date).toordinal()
    except (TypeError, ValueError) as error:
        raise ValueError("legal_date must be ISO YYYY-MM-DD") from error
    must = [
        {"key": "pham_vi", "match": {"value": pham_vi}},
        {"key": "reviewed_status", "match": {"value": "reviewed"}},
        {"key": "central_eligible", "match": {"value": True}},
        {"key": "effective_from_day", "range": {"lte": legal_day}},
        {"key": "reviewed_through_day", "range": {"gte": legal_day}},
    ]
    if provision is not None:
        must.append({"key": "provision", "match": {"value": provision}})
    finite = {"must": must + [{"key": "effective_to_day", "range": {"gt": legal_day}}], "must_not": [{"key": "reviewed_open_ended", "match": {"value": True}}]}
    if include_open_ended:
        return [finite, {"must": must + [{"key": "reviewed_open_ended", "match": {"value": True}}, {"is_null": {"key": "effective_to_day"}}]}]
    return finite


def _validate_vector(vector, dimension=None):
    values = list(vector)
    if not values or any(not isinstance(value, (int, float)) or not math.isfinite(value) for value in values):
        raise ValueError("vector must contain finite numbers")
    if dimension is not None and len(values) != dimension:
        raise ValueError("vector dimension mismatch")
    return values


def _validate_payload_validity(payload):
    if payload.get("reviewed_open_ended") is True and payload.get("effective_to_day") is not None:
        raise ValueError("reviewed_open_ended requires effective_to_day to be null")
