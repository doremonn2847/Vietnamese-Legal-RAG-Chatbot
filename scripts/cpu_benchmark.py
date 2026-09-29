"""Opt-in local CPU benchmark; factories keep tests and default use offline."""
import hashlib
import json
import platform
import re
import statistics
import time
from importlib.metadata import version
from pathlib import Path


def run_benchmark(model_path, output_path, *, encoder_factory, repeats=5, documents=("Điều hư cấu.",), queries=("thử việc",), reranker_factory=None):
    if repeats <= 0 or not documents or not queries:
        raise ValueError("benchmark requires positive repeats and nonempty inputs")
    manifest = _manifest(Path(model_path))
    encoder = encoder_factory(Path(model_path))
    encoder.encode_documents(documents)
    encoder.encode_queries(queries)
    timings = {"documents": _measure(lambda: encoder.encode_documents(documents), repeats), "queries": _measure(lambda: encoder.encode_queries(queries), repeats)}
    if reranker_factory:
        reranker = reranker_factory(Path(model_path))
        timings["reranker"] = _measure(lambda: reranker.score(queries[0], [{"article_id": "synthetic", "text": documents[0]}]), repeats)
    report = {"artifact": manifest, "counts": {"documents": len(documents), "queries": len(queries)}, "timings_ms": timings, "platform": platform.platform(), "dependencies": {name: _version(name) for name in ("torch", "transformers")}, "memory": {"metric": "unsupported", "value": None}}
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_suffix(output.suffix + ".part")
    partial.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    partial.replace(output)
    return report


def _manifest(path):
    if not path.is_dir():
        raise ValueError("local model path is required")
    manifest_path = path / "artifact_manifest.json"
    if not manifest_path.is_file():
        raise ValueError("local artifact manifest is required")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not all(isinstance(manifest.get(key), str) and re.fullmatch(r"[0-9a-f]{40}", manifest[key]) for key in ("model_revision", "tokenizer_revision")) or manifest.get("recipe") != {"document_prefix": "passage: ", "query_prefix": "query: "} or not isinstance(manifest.get("files"), dict):
        raise ValueError("invalid local artifact manifest")
    for name, expected in manifest["files"].items():
        file = (path / name).resolve()
        if path.resolve() not in file.parents or not isinstance(expected, str) or _sha(file) != expected:
            raise ValueError("local artifact hash mismatch")
    return manifest


def _measure(action, repeats):
    samples = []
    for _ in range(repeats):
        started = time.perf_counter_ns(); action(); samples.append((time.perf_counter_ns() - started) / 1_000_000)
    return {"p50": statistics.median(samples), "p95": sorted(samples)[max(0, round(.95 * len(samples)) - 1)], "wall": sum(samples)}


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _version(name):
    try: return version(name)
    except Exception: return None


if __name__ == "__main__":
    import argparse
    from e5_artifacts import load_transformers_encoder
    parser = argparse.ArgumentParser()
    parser.add_argument("model_path")
    parser.add_argument("--output", required=True)
    parser.add_argument("--repeats", type=int, default=5)
    args = parser.parse_args()
    run_benchmark(args.model_path, args.output, encoder_factory=lambda path: load_transformers_encoder(model_path=path, tokenizer_path=path, local_files_only=True), repeats=args.repeats)
