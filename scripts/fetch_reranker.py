"""Fetch the immutable CPU reranker snapshot and write a file-hash manifest."""
import hashlib
import json
from pathlib import Path

from reranker_artifacts import RerankerSpec


def fetch(output):
    from huggingface_hub import snapshot_download

    spec = RerankerSpec()
    spec.validate()
    root = Path(output)
    root.mkdir(parents=True, exist_ok=True)
    snapshot_download(repo_id=spec.model_id, revision=spec.revision, local_dir=str(root), allow_patterns=("*.json", "*.txt", "*.model", "*.safetensors"))
    files = {path.relative_to(root).as_posix(): _sha(path) for path in sorted(root.rglob("*")) if path.is_file() and ".cache" not in path.relative_to(root).parts and path.name != "artifact_manifest.json"}
    if not any(name.endswith(".safetensors") for name in files) or not any(name.endswith(("tokenizer.json", "vocab.txt", ".model")) for name in files):
        raise ValueError("pinned snapshot is missing weights or tokenizer files")
    manifest = {"source": "huggingface.co/" + spec.model_id, "revision": spec.revision, "spec": {"model_id": spec.model_id, "revision": spec.revision, "max_tokens": spec.max_tokens}, "files": files}
    temp = root / "artifact_manifest.json.part"
    temp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(root / "artifact_manifest.json")
    return manifest


def _sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("data/models/bge-reranker-v2-m3"))
    args = parser.parse_args()
    manifest = fetch(args.output)
    print(json.dumps({"revision": manifest["revision"], "file_count": len(manifest["files"]), "total_bytes": sum((args.output / name).stat().st_size for name in manifest["files"])}))
