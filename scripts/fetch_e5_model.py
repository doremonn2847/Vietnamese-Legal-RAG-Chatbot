"""Fetch the pinned E5-small files and write a local integrity manifest."""
import hashlib
import json
from pathlib import Path

from e5_artifacts import E5ArtifactSpec


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def fetch(output):
    from huggingface_hub import snapshot_download

    spec = E5ArtifactSpec.pinned_small()
    spec.validate_execution()
    root = Path(output)
    root.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id=spec.model_id,
        revision=spec.revision,
        local_dir=str(root),
        allow_patterns=("config.json", "model.safetensors", "tokenizer.json", "tokenizer_config.json", "special_tokens_map.json", "sentencepiece.bpe.model", "spiece.model"),
    )
    files = {path.relative_to(root).as_posix(): sha256(path) for path in sorted(root.rglob("*")) if path.is_file() and ".cache" not in path.relative_to(root).parts and path.name != "artifact_manifest.json"}
    if not {"config.json", "model.safetensors"}.issubset(files) or not any(name in files for name in ("tokenizer.json", "sentencepiece.bpe.model", "spiece.model")):
        raise ValueError("pinned snapshot is missing model or tokenizer files")
    manifest = {
        "source": "huggingface.co/" + spec.model_id,
        "revision": spec.revision,
        "spec": spec.manifest(),
        "spec_sha256": hashlib.sha256(json.dumps(spec.manifest(), ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
        "files": files,
    }
    temporary = root / "artifact_manifest.json.part"
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(root / "artifact_manifest.json")
    return manifest


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("data/models/e5-small"))
    args = parser.parse_args()
    result = fetch(args.output)
    print(json.dumps({"revision": result["revision"], "file_count": len(result["files"]), "files": result["files"]}, indent=2))
