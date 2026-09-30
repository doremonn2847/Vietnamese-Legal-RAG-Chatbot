"""Validate and optionally import an inactive E5 core-corpus collection."""
import hashlib
import json
import math
import re
from pathlib import Path
from urllib.error import HTTPError

from e5_artifacts import E5ArtifactSpec
from qdrant_contract import QdrantLocalConfig, QdrantRestAdapter, stable_point_id


def _sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_artifact(artifact_dir, corpus_manifest_path):
    root = Path(artifact_dir).resolve()
    manifest_path = root / "embedding_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    corpus_path = Path(corpus_manifest_path)
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    spec = E5ArtifactSpec.pinned_small()
    context = manifest.get("context", {})
    if manifest.get("model") != spec.manifest() or manifest.get("answer_evidence_enabled") is not False:
        raise ValueError("embedding manifest has an unexpected model or answer-evidence state")
    if context.get("corpus_id") != corpus.get("corpus_id") or context.get("dataset_revision") != corpus.get("dataset_revision") or context.get("corpus_manifest_sha256") != _sha(corpus_path) or context.get("articles_sha256") != corpus.get("outputs", {}).get("articles.jsonl", {}).get("sha256"):
        raise ValueError("embedding artifact does not match the current curated corpus")
    if not isinstance(context.get("model_manifest_sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", context["model_manifest_sha256"]):
        raise ValueError("embedding artifact lacks its model-file manifest hash")
    points, ids = [], []
    for shard in manifest.get("shards", []):
        path = (root / shard.get("file", "")).resolve()
        if root not in path.parents or not path.is_file() or _sha(path) != shard.get("sha256"):
            raise ValueError(f"embedding shard hash mismatch: {shard.get('file')}")
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if len(rows) != shard.get("records"):
            raise ValueError(f"embedding shard record count mismatch: {shard.get('file')}")
        for row in rows:
            payload, vector = row.get("payload"), row.get("vector")
            if not isinstance(payload, dict) or not isinstance(vector, list) or len(vector) != spec.dimension or any(not isinstance(value, (int, float)) or not math.isfinite(value) for value in vector):
                raise ValueError("invalid E5 point vector or payload")
            if payload.get("pham_vi") != "Trung ương" or payload.get("retrieval_index_candidate") is not True or payload.get("answer_evidence_enabled") is not False or payload.get("current_validity") != "unverified" or payload.get("expiry_state") != "unknown_expiry":
                raise ValueError("point violates central-only or unverified-evidence policy")
            if not payload.get("canonical_text", "").strip() or payload.get("source_dataset_revision") != context.get("dataset_revision"):
                raise ValueError("point is missing its evidence text or pinned dataset provenance")
            expected_id = stable_point_id(payload.get("article_id"), payload.get("document_version_id"), payload.get("child_id"))
            if row.get("id") != expected_id:
                raise ValueError("point ID does not match its article/version/chunk identity")
            ids.append(row["id"])
            points.append({"id": row["id"], "vector": vector, "payload": payload})
    if len(points) != manifest.get("records") or ids != manifest.get("ordered_point_ids") or len(set(ids)) != len(ids):
        raise ValueError("point identities/count do not match the embedding manifest")
    if corpus.get("active") is not False or corpus.get("answer_evidence_enabled") is not False:
        raise ValueError("source corpus must remain inactive")
    return manifest, points


def import_collection(artifact_dir, corpus_manifest_path, qdrant, config=None):
    config = config or QdrantLocalConfig()
    manifest, points = validate_artifact(artifact_dir, corpus_manifest_path)
    context = manifest["context"]
    artifact_manifest_sha256 = _sha(Path(artifact_dir) / "embedding_manifest.json")
    revision = re.sub(r"[^A-Za-z0-9_.-]", "_", context["corpus_id"])
    revision = f"{revision}_{context['corpus_manifest_sha256'][:12]}_{artifact_manifest_sha256[:12]}"
    collection = config.collection_name(revision, manifest["context"].get("embedding_spec_sha256") or hashlib.sha256(json.dumps(manifest["model"], sort_keys=True).encode()).hexdigest())
    created = False
    try:
        dimension = qdrant.get_collection_dimension(collection)
    except HTTPError as error:
        if error.code != 404:
            raise
        error.close()
        qdrant.create_collection(collection, manifest["model"]["dimension"])
        created = True
    else:
        if dimension != manifest["model"]["dimension"]:
            raise ValueError("existing versioned collection has incompatible vector dimension")
    for start in range(0, len(points), 128):
        qdrant.upsert(collection, points[start:start + 128])
    return {"collection": collection, "created": created, "points": len(points), "artifact_manifest_sha256": artifact_manifest_sha256, "activated": False, "answer_evidence_enabled": False}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--corpus-manifest", required=True)
    parser.add_argument("--write-local-qdrant", action="store_true", help="write the validated versioned collection to localhost:6333")
    args = parser.parse_args()
    if args.write_local_qdrant:
        result = import_collection(args.artifact, args.corpus_manifest, QdrantRestAdapter())
    else:
        manifest, points = validate_artifact(args.artifact, args.corpus_manifest)
        result = {"collection_points_validated": len(points), "model_revision": manifest["model"]["revision"], "write_performed": False}
    print(json.dumps(result, indent=2))
