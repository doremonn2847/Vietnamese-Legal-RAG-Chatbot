import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError

from e5_artifacts import E5ArtifactSpec
from import_core_corpus_qdrant import import_collection, validate_artifact
from qdrant_contract import QdrantLocalConfig, QdrantRestAdapter, stable_point_id


class CoreCorpusQdrantTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.artifact = self.root / "artifact"
        self.artifact.mkdir()
        self.corpus_path = self.root / "corpus_manifest.json"
        self.articles_path = self.root / "articles.jsonl"
        self.articles_path.write_text("article fixture\n", encoding="utf-8")
        self.corpus_path.write_text(json.dumps({
            "corpus_id": "core-employment-portfolio-v1", "dataset_revision": "revision-fixture",
            "active": False, "answer_evidence_enabled": False,
            "outputs": {"articles.jsonl": {"sha256": self.sha(self.articles_path)}},
        }), encoding="utf-8")
        self.payload = {
            "article_id": "article-id", "document_version_id": "document-version", "child_id": "chunk-0",
            "pham_vi": "Trung ương", "retrieval_index_candidate": True,
            "answer_evidence_enabled": False, "current_validity": "unverified", "expiry_state": "unknown_expiry",
            "canonical_text": "fixture evidence", "source_dataset_revision": "revision-fixture", "reported_status_conflict": False,
            "amendment_state": "not_verified", "quarantined_related_document_ids": [],
        }
        self.point = {"id": stable_point_id("article-id", "document-version", "chunk-0"), "vector": [0.0] * 384, "payload": self.payload}
        self.write_artifact()

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def sha(path):
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()

    def write_artifact(self):
        shard = self.artifact / "vectors-00000.jsonl"
        shard.write_text(json.dumps(self.point) + "\n", encoding="utf-8")
        spec = E5ArtifactSpec.pinned_small().manifest()
        manifest = {
            "context": {"corpus_id": "core-employment-portfolio-v1", "dataset_revision": "revision-fixture",
                        "corpus_manifest_sha256": self.sha(self.corpus_path), "articles_sha256": self.sha(self.articles_path),
                        "model_manifest_sha256": "a" * 64},
            "model": spec, "answer_evidence_enabled": False, "records": 1,
            "ordered_point_ids": [self.point["id"]],
            "shards": [{"file": shard.name, "records": 1, "sha256": self.sha(shard)}],
        }
        (self.artifact / "embedding_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    def test_validates_points_then_creates_inactive_versioned_collection(self):
        requests = []
        def transport(method, path, body):
            requests.append((method, path, body))
            if method == "GET":
                raise HTTPError("http://localhost" + path, 404, "missing", {}, None)
            return {"result": True}
        adapter = QdrantRestAdapter(QdrantLocalConfig(), transport=transport)
        result = import_collection(self.artifact, self.corpus_path, adapter)
        self.assertEqual(result["points"], 1)
        self.assertFalse(result["activated"])
        self.assertFalse(result["answer_evidence_enabled"])
        self.assertTrue(result["collection"].startswith("legalrag_core-employment-portfolio-v1_"))
        self.assertEqual([request[0] for request in requests], ["GET", "PUT", "PUT"])

    def test_corrupt_shard_fails_before_any_qdrant_write(self):
        (self.artifact / "vectors-00000.jsonl").write_text("corrupt\n", encoding="utf-8")
        requests = []
        adapter = QdrantRestAdapter(QdrantLocalConfig(), transport=lambda *args: requests.append(args))
        with self.assertRaisesRegex(ValueError, "shard hash"):
            import_collection(self.artifact, self.corpus_path, adapter)
        self.assertEqual(requests, [])

    def test_collection_identity_changes_with_the_exact_embedding_artifact(self):
        second_artifact = self.root / "artifact-second"
        shutil.copytree(self.artifact, second_artifact)
        shard_path = second_artifact / "vectors-00000.jsonl"
        row = json.loads(shard_path.read_text(encoding="utf-8"))
        row["payload"]["child_id"] = "chunk-1"
        row["id"] = stable_point_id("article-id", "document-version", "chunk-1")
        row["payload"]["canonical_text"] = "a different point set"
        shard_path.write_text(json.dumps(row) + "\n", encoding="utf-8")
        manifest_path = second_artifact / "embedding_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["ordered_point_ids"] = [row["id"]]
        manifest["shards"][0]["sha256"] = self.sha(shard_path)
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        def transport(method, path, body):
            if method == "GET":
                raise HTTPError("http://localhost" + path, 404, "missing", {}, None)
            return {"result": True}
        first = import_collection(self.artifact, self.corpus_path, QdrantRestAdapter(QdrantLocalConfig(), transport=transport))
        changed = import_collection(second_artifact, self.corpus_path, QdrantRestAdapter(QdrantLocalConfig(), transport=transport))
        repeat = import_collection(self.artifact, self.corpus_path, QdrantRestAdapter(QdrantLocalConfig(), transport=transport))
        self.assertNotEqual(first["collection"], changed["collection"])
        self.assertEqual(first["collection"], repeat["collection"])


if __name__ == "__main__":
    unittest.main()
