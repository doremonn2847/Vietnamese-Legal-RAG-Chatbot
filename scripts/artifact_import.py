"""Synthetic-only rehearsal for validating a batch artifact before Qdrant writes."""
import hashlib
import json
import math
from pathlib import Path
from urllib.error import HTTPError

from qdrant_contract import stable_point_id


def import_synthetic_artifact(artifact_dir, qdrant, collection, *, corpus_revision, query_encoder_spec, parent_lookup, parent_lookup_version):
    """Validate a fictional artifact completely, then create/upsert its synthetic collection."""
    if not isinstance(collection, str) or not collection.startswith("synthetic_"):
        raise ValueError("rehearsal collection must use the synthetic_ prefix")
    output = Path(artifact_dir)
    manifest = json.loads((output / "embedding_manifest.json").read_text(encoding="utf-8"))
    expected_spec = query_encoder_spec.manifest()
    expected_spec_sha = _sha256_json(expected_spec)
    if manifest.get("spec_sha256") != expected_spec_sha or manifest.get("model") != expected_spec:
        raise ValueError("query encoder recipe does not match artifact")
    context = {"corpus_revision": corpus_revision, "parent_lookup_version": parent_lookup_version, "synthetic_rehearsal": True}
    if manifest.get("artifact_context") != context:
        raise ValueError("artifact corpus or parent lookup version does not match")
    points = _validated_points(output, manifest, query_encoder_spec.dimension, parent_lookup)
    identity = _sha256_json({"input_sha256": manifest.get("input_sha256"), "spec_sha256": manifest.get("spec_sha256"), "artifact_context": context, "ordered_chunk_ids": manifest.get("ordered_chunk_ids"), "shards": manifest.get("shards")})
    marker = {"id": stable_point_id("synthetic-rehearsal", identity, "marker"), "vector": [1.0] + [0.0] * (query_encoder_spec.dimension - 1), "payload": {"synthetic_rehearsal": True, "artifact_identity": identity}}
    try:
        dimension = qdrant.get_collection_dimension(collection)
    except HTTPError as error:
        if error.code != 404:
            raise
        error.close()
        qdrant.create_collection(collection, query_encoder_spec.dimension)
        qdrant.upsert(collection, [marker])
    else:
        if dimension != query_encoder_spec.dimension:
            raise ValueError("existing rehearsal collection has incompatible dimension")
        try:
            stored = qdrant.get_point(collection, marker["id"])
        except HTTPError as error:
            if error.code == 404:
                error.close()
                raise ValueError("existing rehearsal collection has no matching artifact marker") from error
            raise
        if stored.get("result", {}).get("payload") != marker["payload"]:
            raise ValueError("existing rehearsal collection has a different artifact marker")
    qdrant.upsert(collection, points)
    return {"collection": collection, "points": len(points), "spec_sha256": expected_spec_sha}


def _validated_points(output, manifest, dimension, parent_lookup):
    shards = manifest.get("shards")
    if not isinstance(shards, list) or manifest.get("records") is None or not isinstance(parent_lookup, dict):
        raise ValueError("invalid artifact manifest")
    root, points, ids = output.resolve(), [], []
    for shard in shards:
        path = (root / str(shard.get("file", ""))).resolve()
        if root not in path.parents:
            raise ValueError("artifact shard path escapes artifact directory")
        if not path.is_file() or _sha256_file(path) != shard.get("sha256"):
            raise ValueError("artifact shard hash does not match manifest")
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if shard.get("records") != len(rows):
            raise ValueError("artifact shard record count does not match manifest")
        for row in rows:
            payload, vector = row.get("payload"), row.get("vector")
            if not isinstance(payload, dict) or not isinstance(vector, list) or len(vector) != dimension or any(not isinstance(value, (int, float)) or not math.isfinite(value) for value in vector):
                raise ValueError("artifact vector does not match encoder dimension")
            article_id, version, child_id = payload.get("article_id"), payload.get("document_version_id"), payload.get("child_id")
            if row.get("id") != stable_point_id(article_id, version, child_id) or parent_lookup.get(article_id, {}).get("document_version_id") != version:
                raise ValueError("artifact point lacks matching parent lookup")
            ids.append(row["id"])
            points.append({"id": row["id"], "vector": vector, "payload": payload})
    if len(points) != manifest["records"] or ids != manifest.get("ordered_chunk_ids") or len(set(ids)) != len(ids):
        raise ValueError("artifact point identities do not match manifest")
    return points


def _sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_json(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
