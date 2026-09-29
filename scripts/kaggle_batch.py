"""Plan and export embedding batches; model execution is injected explicitly."""
import hashlib
import json
import math
from pathlib import Path

from e5_artifacts import E5ArtifactSpec
from qdrant_contract import stable_point_id


def build_batch_plan(articles_path, spec=None):
    spec = spec or E5ArtifactSpec()
    records, ordered_ids = _records(articles_path)
    return {"input": str(articles_path), "input_sha256": _sha256(Path(articles_path)), "records": len(records), "ordered_chunk_ids": ordered_ids, "model_id": spec.model_id, "model_revision": spec.revision, "dimension": spec.dimension, "executed": False, "execution_status": "plan_only"}


def build_embedding_batch(articles_path, output_dir, spec, encoder, shard_size=1000, artifact_context=None):
    if shard_size <= 0:
        raise ValueError("shard_size must be positive")
    spec.validate_execution()
    artifact_context = _artifact_context(artifact_context)
    records, ordered_ids = _records(articles_path)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    input_sha = _sha256(Path(articles_path))
    spec_manifest = spec.manifest()
    spec_sha = hashlib.sha256(json.dumps(spec_manifest, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    existing_path = output / "embedding_manifest.json"
    if existing_path.exists():
        existing = json.loads(existing_path.read_text(encoding="utf-8"))
        if existing.get("input_sha256") == input_sha and existing.get("spec_sha256") == spec_sha and existing.get("artifact_context") == artifact_context:
            if existing.get("shard_size") != shard_size:
                raise ValueError("completed manifest has incompatible shard_size")
            _verify_manifest(output, existing, records, spec, shard_size, require_complete=True)
            return existing
        raise ValueError("output directory contains an incompatible completed manifest")
    manifest = {"input": str(articles_path), "input_sha256": input_sha, "spec_sha256": spec_sha, "model": spec_manifest, "records": len(records), "ordered_chunk_ids": ordered_ids, "shard_size": shard_size, "artifact_context": artifact_context, "shards": []}
    progress_path = output / "embedding_progress.json"
    if progress_path.exists():
        progress = json.loads(progress_path.read_text(encoding="utf-8"))
        if progress.get("input_sha256") != input_sha or progress.get("spec_sha256") != spec_sha or progress.get("artifact_context") != artifact_context:
            raise ValueError("output directory contains incompatible embedding progress")
        if progress.get("shard_size") != shard_size:
            raise ValueError("embedding progress has incompatible shard_size")
        manifest["shards"] = progress.get("shards", [])
        _verify_manifest(output, manifest, records, spec, shard_size, require_complete=False)
    for start in range(0, len(records), shard_size):
        batch = records[start:start + shard_size]
        name = f"embeddings-{start // shard_size:05d}.jsonl"
        existing_shard = next((item for item in manifest["shards"] if item["file"] == name), None)
        if existing_shard:
            continue
        if not hasattr(encoder, "token_count"):
            raise ValueError("encoder must provide token_count for the prefixed input")
        texts = [spec.document_text(record["text"]) for record in batch]
        for text in texts:
            spec.prepare_text(text, encoder.token_count(text))
        vectors = encoder(texts)
        if len(vectors) != len(batch) or any(len(vector) != spec.dimension or any(not isinstance(value, (int, float)) or not math.isfinite(value) for value in vector) for vector in vectors):
            raise ValueError("encoder returned the wrong number or dimension of vectors")
        path = output / name
        partial = path.with_suffix(path.suffix + ".part")
        with partial.open("w", encoding="utf-8") as stream:
            for record, vector in zip(batch, vectors):
                stream.write(json.dumps({"id": record["id"], "vector": vector, "payload": record["payload"]}, ensure_ascii=False) + "\n")
        partial.replace(path)
        manifest["shards"].append({"file": name, "records": len(batch), "sha256": _sha256(path)})
        progress_partial = progress_path.with_suffix(progress_path.suffix + ".part")
        progress_partial.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        progress_partial.replace(progress_path)
    manifest_partial = output / "embedding_manifest.json.part"
    _verify_manifest(output, manifest, records, spec, shard_size, require_complete=True)
    manifest_partial.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest_partial.replace(output / "embedding_manifest.json")
    if progress_path.exists():
        progress_path.unlink()
    return manifest


def _artifact_context(context):
    if context is None:
        return None
    required = {"corpus_revision", "parent_lookup_version"}
    if not isinstance(context, dict) or set(context) != required or any(not isinstance(context[key], str) or not context[key].strip() for key in required):
        raise ValueError("artifact context requires corpus_revision and parent_lookup_version")
    return {key: context[key] for key in sorted(required)}


def _records(path):
    records, seen, ordered_ids = [], set(), []
    with Path(path).open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            article = json.loads(line)
            if not isinstance(article, dict):
                raise ValueError(f"record must be an object at line {line_number}")
            for field in ("article_id", "document_version_id", "pham_vi", "provision", "effective_from_day", "effective_to_day", "reviewed_status", "central_eligible", "reviewed_open_ended", "reviewed_through_day"):
                if field == "central_eligible" and field not in article:
                    raise ValueError(f"missing {field} at line {line_number}")
                if field in {"central_eligible", "reviewed_open_ended"}:
                    if field == "reviewed_open_ended" and field not in article:
                        raise ValueError(f"missing {field} at line {line_number}")
                    continue
                if not article.get(field):
                    if field == "effective_to_day" and field in article:
                        continue
                    raise ValueError(f"missing {field} at line {line_number}")
            if article["effective_to_day"] is None and article["reviewed_open_ended"] is not True:
                raise ValueError(f"unknown expiry must be explicitly reviewed_open_ended at line {line_number}")
            children = article.get("children") or [{"child_id": f"{article['article_id']}:article", "canonical_text": article.get("canonical_text", "")}]
            for child in children:
                text = child.get("canonical_text")
                if not isinstance(text, str) or not text.strip():
                    raise ValueError(f"missing canonical_text at line {line_number}")
                child_id = str(child.get("child_id") or f"{article['article_id']}:article")
                point_id = stable_point_id(article["article_id"], article["document_version_id"], child_id)
                if point_id in seen:
                    raise ValueError(f"duplicate child identity: {point_id}")
                seen.add(point_id)
                ordered_ids.append(point_id)
                payload = {key: article[key] for key in ("article_id", "document_version_id", "pham_vi", "provision", "effective_from_day", "effective_to_day", "reviewed_status", "central_eligible", "reviewed_open_ended", "reviewed_through_day")}
                payload["child_id"] = child_id
                records.append({"id": point_id, "text": text, "payload": payload})
    return records, ordered_ids


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_manifest(output, manifest, records, spec, shard_size, require_complete):
    expected = [record["id"] for record in records]
    offset = 0
    for index, shard in enumerate(manifest.get("shards", [])):
        path = Path(output) / shard["file"]
        if not path.exists() or _sha256(path) != shard.get("sha256"):
            raise ValueError(f"corrupt or missing embedding shard: {shard.get('file')}")
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        ids = [row.get("id") for row in rows]
        expected_size = min(shard_size, len(expected) - offset)
        expected_records = records[offset:offset + len(rows)]
        if shard.get("records") != len(rows) or len(rows) != expected_size or ids != expected[offset:offset + len(ids)] or any(row.get("payload") != record["payload"] or len(row.get("vector", [])) != spec.dimension or any(not isinstance(value, (int, float)) or not math.isfinite(value) for value in row["vector"]) for row, record in zip(rows, expected_records)):
            raise ValueError(f"invalid embedding shard content: {shard.get('file')}")
        offset += len(ids)
    if offset > len(expected) or (require_complete and offset != len(expected)):
        raise ValueError("embedding shard record count exceeds input")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("articles")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    Path(args.output).write_text(json.dumps(build_batch_plan(args.articles), ensure_ascii=False, indent=2), encoding="utf-8")
