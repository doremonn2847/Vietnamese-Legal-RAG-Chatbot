import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from core_retriever import CoreCorpusRetriever
from core_app import REVISION, _pinned_dataset_revision, validate_qdrant_collection
from e5_artifacts import E5ArtifactSpec
from qdrant_contract import stable_point_id


class QueryEncoder:
    def encode_queries(self, queries):
        return [[1.0] + [0.0] * 383 for _ in queries]


class CoreRetrieverTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.articles_path = self.root / "articles.jsonl"
        self.corpus_path = self.root / "corpus_manifest.json"
        self.artifact = self.root / "artifact"
        self.artifact.mkdir()
        self.articles = [self.article("a1", "v1", "Điều 24 nói về thử việc."), self.article("a2", "v2", "Điều 25 nói về chấm dứt.")]
        self.articles_path.write_text("".join(json.dumps(item, ensure_ascii=False) + "\n" for item in self.articles), encoding="utf-8")
        articles_sha = self.sha(self.articles_path)
        self.corpus_path.write_text(json.dumps({"corpus_id": "core-employment-portfolio-v1", "dataset_revision": "revision-fixture", "article_count": len(self.articles), "active": False, "answer_evidence_enabled": False, "outputs": {"articles.jsonl": {"sha256": articles_sha}}}), encoding="utf-8")
        points = [self.point("a1", "v1", "c1", "Điều 24 nói về thử việc.", [1.0] + [0.0] * 383), self.point("a2", "v2", "c2", "Điều 25 nói về chấm dứt.", [0.0, 1.0] + [0.0] * 382)]
        shard = self.artifact / "vectors-00000.jsonl"
        shard.write_text("".join(json.dumps(point, ensure_ascii=False) + "\n" for point in points), encoding="utf-8")
        spec = E5ArtifactSpec.pinned_small().manifest()
        manifest = {"context": {"corpus_id": "core-employment-portfolio-v1", "dataset_revision": "revision-fixture", "corpus_manifest_sha256": self.sha(self.corpus_path), "articles_sha256": articles_sha, "model_manifest_sha256": "a" * 64}, "model": spec, "answer_evidence_enabled": False, "records": len(points), "ordered_point_ids": [point["id"] for point in points], "shards": [{"file": shard.name, "records": len(points), "sha256": self.sha(shard)}]}
        (self.artifact / "embedding_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def sha(path):
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()

    @staticmethod
    def article(article_id, version, text):
        return {"article_id": article_id, "article_version_id": article_id, "document_id": "139264", "document_version_id": version, "label": "Điều " + article_id[-1], "canonical_text": text, "source_start": 0, "source_end": len(text), "validity": "unverified", "topic_candidates": [], "document_metadata": {"title": "Bộ luật Lao động", "so_ky_hieu": "45/2019/QH14", "issuer": "Quốc hội", "pham_vi": "Trung ương", "current_validity": "unverified", "expiry_state": "unknown_expiry", "reported_status_conflict": False, "amendment_state": "not_verified", "quarantined_related_document_ids": [], "retrieval_index_candidate": True, "answer_evidence_enabled": False, "source_dataset_revision": "revision-fixture", "source_dataset_url": "https://huggingface.co/datasets/example"}}

    @staticmethod
    def point(article_id, version, child_id, text, vector):
        payload = {"article_id": article_id, "article_version_id": article_id, "document_id": "139264", "document_version_id": version, "child_id": child_id, "canonical_text": text, "pham_vi": "Trung ương", "retrieval_index_candidate": True, "answer_evidence_enabled": False, "current_validity": "unverified", "expiry_state": "unknown_expiry", "reported_status_conflict": False, "amendment_state": "not_verified", "quarantined_related_document_ids": [], "canonical_char_start": 0, "canonical_char_end": len(text), "source_dataset_revision": "revision-fixture"}
        return {"id": stable_point_id(article_id, version, child_id), "vector": vector, "payload": payload}

    def test_hybrid_search_returns_parent_article_citations_with_provenance(self):
        retriever = CoreCorpusRetriever(self.articles_path, self.corpus_path, self.artifact, QueryEncoder())
        result = retriever.search("thử việc", "2026-09-30")
        self.assertEqual(result["evidence"][0]["article_id"], "a1")
        self.assertEqual(result["evidence"][0]["document_version_id"], "v1")
        self.assertEqual(result["evidence"][0]["canonical_text"], "Điều 24 nói về thử việc.")
        self.assertFalse(result["evidence"][0]["answer_evidence_enabled"])
        self.assertEqual(result["evidence"][0]["source_dataset_revision"], "revision-fixture")

    def test_configured_qdrant_supplies_dense_hits_without_in_memory_fallback(self):
        class Qdrant:
            calls = []
            def search(self, collection, vector, filters, limit):
                self.calls.append((collection, filters, limit))
                return {"result": [{"score": 1.0, "payload": {"article_id": "a2", "child_id": "c2", "canonical_text": "Điều 25 nói về chấm dứt."}}]}
        qdrant = Qdrant()
        retriever = CoreCorpusRetriever(self.articles_path, self.corpus_path, self.artifact, QueryEncoder(), qdrant=qdrant, collection="pinned")
        result = retriever.search("query")
        self.assertEqual(result["dense"][0]["article_id"], "a2")
        self.assertEqual(qdrant.calls[0][0], "pinned")
        self.assertIn("fusion_and_evidence", result["timings_ms"])
        self.assertNotIn("rerank_and_evidence", result["timings_ms"])

    def test_configured_qdrant_without_collection_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "collection"):
            CoreCorpusRetriever(self.articles_path, self.corpus_path, self.artifact, QueryEncoder(), qdrant=object())

    def test_core_app_requires_matching_green_collection(self):
        artifact = {"model": {"dimension": 384}, "records": 85}
        valid = {"result": {"status": "green", "points_count": 85, "config": {"params": {"vectors": {"size": 384}}}}}
        validate_qdrant_collection(valid, artifact)
        for changed in ({**valid, "result": {**valid["result"], "points_count": 84}},
                        {"result": {**valid["result"], "status": "yellow"}}, {}):
            with self.subTest(changed=changed):
                with self.assertRaises(ValueError):
                    validate_qdrant_collection(changed, artifact)

    def test_core_app_pins_the_snapshot_revision_from_manifest(self):
        self.corpus_path.write_text(json.dumps({"dataset_revision": REVISION}), encoding="utf-8")
        self.assertEqual(_pinned_dataset_revision(self.root), REVISION)
        self.corpus_path.write_text(json.dumps({"dataset_revision": "other-revision"}), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "pinned dataset revision"):
            _pinned_dataset_revision(self.root)


if __name__ == "__main__":
    unittest.main()
