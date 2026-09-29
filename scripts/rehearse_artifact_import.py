"""Run a fictional artifact import rehearsal without loading models or a legal corpus."""
import argparse
import json
import os
import uuid
from pathlib import Path
from urllib.error import HTTPError

from artifact_import import import_synthetic_artifact
from e5_artifacts import E5ArtifactSpec
from kaggle_batch import build_embedding_batch
from qdrant_contract import QdrantLocalConfig, QdrantRestAdapter


def run(output, local_qdrant=False):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    source = output / "fictional-reviewed-articles.jsonl"
    source.write_text(json.dumps({
        "article_id": "fictional-article-1", "document_version_id": "fictional-v1",
        "canonical_text": "Nội dung hư cấu dùng cho kiểm thử.",
        "children": [{"child_id": "article", "canonical_text": "Nội dung hư cấu dùng cho kiểm thử."}],
        "pham_vi": "Trung ương", "provision": "probation", "effective_from_day": 737425,
        "effective_to_day": 741077, "reviewed_status": "reviewed", "central_eligible": True,
        "reviewed_open_ended": False, "reviewed_through_day": 739888,
    }) + "\n", encoding="utf-8")
    spec = E5ArtifactSpec.pinned_small()

    class FakeEncoder:
        def token_count(self, text):
            return len(text.split()) + 2

        def __call__(self, texts):
            return [[1.0] + [0.0] * 383 for _ in texts]

    artifact = output / "artifact"
    build_embedding_batch(source, artifact, spec, FakeEncoder(), shard_size=1, artifact_context={"corpus_revision": "fictional-r1", "parent_lookup_version": "fictional-parent-v1", "synthetic_rehearsal": True})
    arguments = {"corpus_revision": "fictional-r1", "query_encoder_spec": spec, "parent_lookup": {"fictional-article-1": {"document_version_id": "fictional-v1"}}, "parent_lookup_version": "fictional-parent-v1"}
    requests = []
    collection = "synthetic_artifact_rehearsal_" + uuid.uuid4().hex[:8]
    if not local_qdrant:
        collections = {}
        def transport(method, path, body):
            requests.append((method, path, body))
            name = path.split("/")[2] if path.startswith("/collections/") else None
            if method == "GET" and "/points/" not in path:
                if name not in collections: raise HTTPError(path, 404, "missing", None, None)
                return {"result": {"config": {"params": {"vectors": {"size": collections[name]["dimension"]}}}}}
            if method == "GET":
                point_id = path.rsplit("/", 1)[-1]
                if point_id not in collections[name]["points"]: raise HTTPError(path, 404, "missing", None, None)
                return {"result": collections[name]["points"][point_id]}
            if method == "PUT" and "/points" not in path:
                collections[name] = {"dimension": body["vectors"]["size"], "points": {}}
                return {"result": True}
            collections[name]["points"].update({point["id"]: point for point in body["points"]})
            return {"result": True}
        adapter = QdrantRestAdapter(transport=transport)
        return {**import_synthetic_artifact(artifact, adapter, collection, **arguments), "requests": requests, "mode": "injected"}
    api_key = os.getenv("QDRANT_API_KEY")
    if not api_key:
        raise ValueError("QDRANT_API_KEY is required for --local-qdrant")
    adapter = QdrantRestAdapter(QdrantLocalConfig(api_key=api_key))
    try:
        return {**import_synthetic_artifact(artifact, adapter, collection, **arguments), "requests": [], "mode": "local_qdrant"}
    finally:
        adapter.delete_collection(collection)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="data/embeddings/synthetic-artifact-rehearsal-v2")
    parser.add_argument("--local-qdrant", action="store_true")
    args = parser.parse_args()
    result = run(args.output, args.local_qdrant)
    print(json.dumps({key: value for key, value in result.items() if key != "requests"}, ensure_ascii=False))
