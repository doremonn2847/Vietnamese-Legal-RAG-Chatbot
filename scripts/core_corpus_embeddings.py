"""Create checksum-manifested E5 vectors for the inactive core corpus."""
import hashlib
import json
import math
from pathlib import Path

from e5_artifacts import E5ArtifactSpec
from qdrant_contract import stable_point_id

WINDOW_TOKENS = 440
OVERLAP_TOKENS = 48


def _sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_model(model_path, spec=None):
    spec = spec or E5ArtifactSpec.pinned_small()
    spec.validate_execution()
    root = Path(model_path).resolve()
    manifest_path = root / "artifact_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_sha = hashlib.sha256(json.dumps(spec.manifest(), ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    if manifest.get("spec") != spec.manifest() or manifest.get("spec_sha256") != expected_sha:
        raise ValueError("local E5 artifact does not match the pinned recipe")
    files = manifest.get("files")
    if not isinstance(files, dict) or not {"config.json", "model.safetensors"}.issubset(files) or not any(name in files for name in ("tokenizer.json", "sentencepiece.bpe.model", "spiece.model")):
        raise ValueError("local E5 artifact manifest is missing model/tokenizer files")
    for name, checksum in files.items():
        file_path = (root / name).resolve()
        if root not in file_path.parents or not file_path.is_file() or _sha(file_path) != checksum:
            raise ValueError(f"E5 artifact checksum mismatch: {name}")
    return manifest


def _read_records(articles_path, tokenizer, spec):
    records, seen = [], set()
    with Path(articles_path).open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            article = json.loads(line)
            metadata = article.get("document_metadata") or {}
            if metadata.get("retrieval_index_candidate") is not True:
                continue
            if article.get("validity") != "unverified" or metadata.get("current_validity") != "unverified":
                raise ValueError(f"unexpected validity promotion at line {line_number}")
            if metadata.get("pham_vi") != "Trung ương":
                raise ValueError(f"noncentral record at line {line_number}")
            if metadata.get("answer_evidence_enabled") is not False:
                raise ValueError(f"unreviewed record incorrectly enables answer evidence at line {line_number}")
            text = spec.prepare_text(article.get("canonical_text", ""))
            tokenized = tokenizer(text, add_special_tokens=True, truncation=False, return_offsets_mapping=True)
            offsets = tokenized["offset_mapping"]
            if offsets and isinstance(offsets[0][0], list):
                offsets = offsets[0]
            offsets = [(start, end) for start, end in offsets if end > start]
            if not offsets:
                raise ValueError(f"empty article text at line {line_number}")
            article_version_id = article["article_version_id"]
            document_version_id = article["document_version_id"]
            window, overlap, position = WINDOW_TOKENS, OVERLAP_TOKENS, 0
            while position < len(offsets):
                last = min(position + window, len(offsets)) - 1
                start, end = offsets[position][0], offsets[last][1]
                chunk_text = text[start:end]
                encoded = tokenizer(spec.document_text(chunk_text), add_special_tokens=True, truncation=False)["input_ids"]
                if encoded and isinstance(encoded[0], list):
                    encoded = encoded[0]
                if len(encoded) > spec.max_tokens:
                    raise ValueError(f"E5 chunk exceeds token limit at line {line_number}")
                child_id = f"{article_version_id}:{start}:{end}"
                point_id = stable_point_id(article["article_id"], document_version_id, child_id)
                if point_id in seen:
                    raise ValueError(f"duplicate chunk identity at line {line_number}")
                seen.add(point_id)
                docmeta = metadata
                payload = {
                    "article_id": article["article_id"],
                    "article_version_id": article_version_id,
                    "document_id": article["document_id"],
                    "document_version_id": document_version_id,
                    "child_id": child_id,
                    "article_label": article["label"],
                    "canonical_char_start": start,
                    "canonical_char_end": end,
                    "canonical_text": chunk_text,
                    "topic_candidates": article.get("topic_candidates", []),
                    "pham_vi": docmeta.get("pham_vi", "Trung ương"),
                    "title": docmeta.get("title"),
                    "so_ky_hieu": docmeta.get("so_ky_hieu"),
                    "issuer": docmeta.get("issuer"),
                    "issue_date": docmeta.get("issue_date"),
                    "effective_date": docmeta.get("effective_date"),
                    "reported_expiry_date": docmeta.get("reported_expiry_date"),
                    "reported_status": docmeta.get("reported_status"),
                    "reported_status_conflict": docmeta.get("reported_status_conflict") is True,
                    "expiry_state": docmeta.get("expiry_state"),
                    "current_validity": "unverified",
                    "amendment_state": docmeta.get("amendment_state"),
                    "retrieval_index_candidate": True,
                    "answer_evidence_enabled": False,
                    "corpus_disposition": docmeta.get("corpus_disposition"),
                    "source_dataset_revision": docmeta.get("source_dataset_revision"),
                    "source_dataset_url": docmeta.get("source_dataset_url"),
                    "content_sha256": article.get("content_sha256"),
                }
                records.append({"id": point_id, "text": spec.document_text(chunk_text), "payload": payload})
                if last + 1 == len(offsets):
                    break
                position = last + 1 - overlap
    if not records:
        raise ValueError("corpus has no retrieval index candidates")
    return records


def build(articles_path, corpus_manifest_path, model_path, output_dir, encoder, *, batch_size=16):
    spec = E5ArtifactSpec.pinned_small()
    spec.validate_execution()
    model_root, output = Path(model_path), Path(output_dir)
    model_manifest = verify_model(model_root, spec)
    model_manifest_path = model_root / "artifact_manifest.json"
    corpus_manifest_path = Path(corpus_manifest_path)
    corpus_manifest = json.loads(corpus_manifest_path.read_text(encoding="utf-8"))
    if corpus_manifest.get("active") is not False or corpus_manifest.get("answer_evidence_enabled") is not False:
        raise ValueError("embedding input corpus must remain inactive with answer evidence disabled")
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    input_path = Path(articles_path)
    if _sha(input_path) != corpus_manifest.get("outputs", {}).get("articles.jsonl", {}).get("sha256"):
        raise ValueError("article file does not match the curated corpus manifest")
    records = _read_records(input_path, encoder.tokenizer, spec)
    model_manifest_sha = _sha(model_manifest_path)
    context = {
        "corpus_id": corpus_manifest["corpus_id"],
        "dataset_revision": corpus_manifest["dataset_revision"],
        "corpus_manifest_sha256": _sha(corpus_manifest_path),
        "articles_sha256": _sha(input_path),
        "model_manifest_sha256": model_manifest_sha,
        "builder_sha256": _sha(Path(__file__)),
        "chunking": {"window_tokens": WINDOW_TOKENS, "overlap_tokens": OVERLAP_TOKENS, "source": "canonical_text character offsets"},
    }
    output.mkdir(parents=True, exist_ok=True)
    manifest_path = output / "embedding_manifest.json"
    if manifest_path.exists():
        old = json.loads(manifest_path.read_text(encoding="utf-8"))
        if old.get("context") != context or old.get("model") != spec.manifest():
            raise ValueError("embedding output exists for a different input or model")
        checked_ids = []
        for shard in old.get("shards", []):
            path = (output / shard["file"]).resolve()
            if output.resolve() not in path.parents or not path.is_file() or _sha(path) != shard.get("sha256"):
                raise ValueError(f"embedding shard checksum mismatch: {shard.get('file')}")
            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
            if len(rows) != shard.get("records"):
                raise ValueError(f"embedding shard record count mismatch: {shard.get('file')}")
            checked_ids.extend(row.get("id") for row in rows)
        if len(checked_ids) != old.get("records") or checked_ids != old.get("ordered_point_ids"):
            raise ValueError("embedding artifact point order does not match manifest")
        return old

    shard, shard_records, ids = [], [], []
    for offset in range(0, len(records), batch_size):
        batch = records[offset:offset + batch_size]
        vectors = encoder([record["text"] for record in batch])
        if len(vectors) != len(batch) or any(len(vector) != spec.dimension or any(not isinstance(value, (int, float)) or not math.isfinite(value) for value in vector) for vector in vectors):
            raise ValueError("E5 returned incompatible vectors")
        shard_records.extend({"id": item["id"], "vector": vector, "payload": item["payload"]} for item, vector in zip(batch, vectors))
        ids.extend(item["id"] for item in batch)
        if len(shard_records) >= 256 or offset + batch_size >= len(records):
            number = len(shard)
            name = f"vectors-{number:05d}.jsonl"
            path, temporary = output / name, output / (name + ".part")
            temporary.write_text("".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in shard_records), encoding="utf-8")
            temporary.replace(path)
            shard.append({"file": name, "records": len(shard_records), "sha256": _sha(path)})
            shard_records = []
    manifest = {
        "context": context,
        "model": spec.manifest(),
        "answer_evidence_enabled": False,
        "records": len(ids),
        "ordered_point_ids": ids,
        "shards": shard,
    }
    temporary = output / "embedding_manifest.json.part"
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(manifest_path)
    return manifest


if __name__ == "__main__":
    import argparse
    from e5_artifacts import load_transformers_encoder
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--articles", required=True)
    parser.add_argument("--corpus-manifest", required=True)
    parser.add_argument("--model", default="data/models/e5-small")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    verify_model(args.model)
    encoder = load_transformers_encoder(model_path=args.model, tokenizer_path=args.model, local_files_only=True)
    result = build(args.articles, args.corpus_manifest, args.model, args.output, encoder)
    print(json.dumps({"records": result["records"], "shards": result["shards"], "answer_evidence_enabled": result["answer_evidence_enabled"]}, indent=2))
