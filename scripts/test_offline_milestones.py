import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from e5_artifacts import E5ArtifactSpec, E5EncoderAdapter, PINNED_E5_REVISIONS
from kaggle_batch import build_embedding_batch, build_batch_plan
from qdrant_contract import QdrantLocalConfig, QdrantRestAdapter, legal_filter, stable_point_id


class OfflineMilestoneTest(unittest.TestCase):
    def test_qdrant_config_is_local_and_versioned(self):
        config = QdrantLocalConfig()
        self.assertEqual(config.collection_name("8977887f"), "legalrag_8977887f")
        self.assertEqual(config.url, "http://localhost:6333")

    def test_rest_upsert_keeps_child_ids_on_retry(self):
        requests = []
        adapter = QdrantRestAdapter(QdrantLocalConfig(), transport=lambda method, path, body: requests.append((method, path, body)) or {"result": True})
        adapter.create_collection("v1", 3)
        points = [{"id": stable_point_id("article-1", "version-1", child), "vector": [1.0, 0.0, 0.0], "payload": {"pham_vi": "Trung ương", "reviewed_status": "reviewed", "central_eligible": True, "effective_from_day": date(2020, 1, 1).toordinal(), "effective_to_day": date(2030, 1, 1).toordinal(), "reviewed_through_day": date(2026, 9, 29).toordinal(), "child_id": child}} for child in ("c1", "c2")]
        adapter.upsert("v1", points)
        adapter.upsert("v1", points)
        self.assertEqual(len({row["id"] for row in requests[-1][2]["points"]}), 2)
        self.assertEqual(requests[-1][1], "/collections/v1/points?wait=true")

    def test_filters_and_version_activation_rollback_are_persistent(self):
        with tempfile.TemporaryDirectory() as directory:
            adapter = QdrantRestAdapter(QdrantLocalConfig(), transport=lambda method, path, body: {"result": True})
            checked = legal_filter(legal_date="2024-01-01", provision="probation")
            self.assertEqual({item["key"] for item in checked["must"]}, {"pham_vi", "provision", "effective_from_day", "effective_to_day", "reviewed_through_day", "reviewed_status", "central_eligible"})
            with self.assertRaises(ValueError):
                legal_filter(legal_date="2024-01-01", extra="bad")
            self.assertTrue(legal_filter(legal_date="2024-01-01", include_open_ended=True)["should"])
            with self.assertRaises(ValueError):
                adapter.search("v1", [float("nan"), 0], 2)
            adapter.create_collection("v2", 2)
            with self.assertRaises(ValueError):
                adapter.search("v2", [1, 0, 0])

    def test_e5_spec_and_batch_plan_are_explicitly_pinned(self):
        self.assertTrue(E5ArtifactSpec.pinned_small().validate_execution())
        self.assertEqual(len(PINNED_E5_REVISIONS["intfloat/multilingual-e5-small"]), 40)
        spec = E5ArtifactSpec(revision="a" * 40, tokenizer_revision="b" * 40)
        self.assertEqual(spec.document_text("Điều 1"), "passage: Điều 1")
        self.assertEqual(spec.query_text("thử việc"), "query: thử việc")
        self.assertEqual(spec.dimension, 384)
        with self.assertRaises(ValueError):
            spec.prepare_text("x " * 600, token_count=600)
        with self.assertRaises(ValueError):
            E5ArtifactSpec().validate_execution()
        with self.assertRaises(ValueError):
            E5ArtifactSpec(revision="main", tokenizer_revision="b" * 40).validate_execution()
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "articles.jsonl"
            source.write_text(json.dumps({"article_id": "a", "document_version_id": "v", "canonical_text": "Điều 1", "children": [{"child_id": "c1", "canonical_text": "Điều 1"}, {"child_id": "c2", "canonical_text": "Khoản 1"}], "pham_vi": "Trung ương", "provision": "probation", "effective_from_day": 737425, "effective_to_day": 741077, "reviewed_status": "reviewed", "central_eligible": True, "reviewed_open_ended": False, "reviewed_through_day": 739888}) + "\n", encoding="utf-8")
            plan = build_batch_plan(source, spec)
            self.assertEqual(plan["records"], 2)
            self.assertEqual(plan["model_id"], spec.model_id)
            self.assertFalse(plan["executed"])
            output = Path(directory) / "vectors"
            # Test double; production execution uses E5EncoderAdapter.
            class FakeEncoder:
                def token_count(self, text):
                    return len(text.split()) + 2
                def __call__(self, texts):
                    return [[float(len(texts[0])), 0.0, 0.0] + [0.0] * 381]
            fake = FakeEncoder()
            result = build_embedding_batch(source, output, spec, encoder=fake, shard_size=1)
            self.assertEqual(result["records"], 2)
            self.assertEqual(result["shard_size"], 1)
            self.assertTrue((output / "embeddings-00000.jsonl").exists())
            resumed = build_embedding_batch(source, output, spec, encoder=lambda _: (_ for _ in ()).throw(AssertionError("should resume")), shard_size=1)
            self.assertEqual(resumed["spec_sha256"], result["spec_sha256"])
            with self.assertRaises(ValueError):
                build_embedding_batch(source, output, spec, encoder=fake, shard_size=2)
            shard = output / "embeddings-00000.jsonl"
            row = json.loads(shard.read_text(encoding="utf-8").splitlines()[0])
            row["payload"]["provision"] = "tampered"
            shard.write_text(json.dumps(row) + "\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                build_embedding_batch(source, output, spec, encoder=fake, shard_size=1)
            (output / "embeddings-00000.jsonl").write_text("corrupt\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                build_embedding_batch(source, output, spec, encoder=lambda _: [])
            source.write_text("42\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                build_batch_plan(source, spec)

    def test_e5_encoder_adapter_counts_prefixed_inputs(self):
        spec = E5ArtifactSpec(revision="a" * 40, tokenizer_revision="b" * 40)
        tokenizer = lambda text, **kwargs: {"input_ids": [[0] * (len(text.split()) + 2)]}
        model = lambda texts, **kwargs: [[0.0] * spec.dimension for _ in texts]
        adapter = E5EncoderAdapter(tokenizer, model, spec)
        self.assertEqual(adapter.token_count("query: thử việc"), 5)
        self.assertEqual(len(adapter.encode_queries(["thử việc"])[0]), 384)


if __name__ == "__main__":
    unittest.main()
