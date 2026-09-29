import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from artifact_import import import_synthetic_artifact
from e5_artifacts import E5ArtifactSpec
from kaggle_batch import build_embedding_batch
from qdrant_contract import QdrantLocalConfig, QdrantRestAdapter
from rehearse_artifact_import import run


class ArtifactImportTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.source = self.root / "fictional-reviewed-articles.jsonl"
        self.source.write_text(json.dumps({
            "article_id": "fictional-article-1", "document_version_id": "fictional-v1",
            "canonical_text": "Nội dung hư cấu dùng cho kiểm thử.",
            "children": [{"child_id": "article", "canonical_text": "Nội dung hư cấu dùng cho kiểm thử."}],
            "pham_vi": "Trung ương", "provision": "probation", "effective_from_day": 737425,
            "effective_to_day": 741077, "reviewed_status": "reviewed", "central_eligible": True,
            "reviewed_open_ended": False, "reviewed_through_day": 739888,
        }) + "\n", encoding="utf-8")
        self.spec = E5ArtifactSpec.pinned_small()

        class FakeEncoder:
            def token_count(self, text):
                return len(text.split()) + 2

            def __call__(self, texts):
                return [[1.0] + [0.0] * 383 for _ in texts]

        self.artifact = self.root / "artifact"
        self.manifest = build_embedding_batch(
            self.source, self.artifact, self.spec, FakeEncoder(), shard_size=1,
            artifact_context={"corpus_revision": "fictional-r1", "parent_lookup_version": "fictional-parent-v1"},
        )
        self.parent_lookup = {"fictional-article-1": {"document_version_id": "fictional-v1"}}

    def tearDown(self):
        self.directory.cleanup()

    def _adapter(self, requests):
        return QdrantRestAdapter(
            QdrantLocalConfig(),
            transport=lambda method, path, body: requests.append((method, path, body)) or {"result": True},
        )

    def test_imports_fictional_shards_with_stable_retry_ids(self):
        requests = []
        for _ in range(2):
            result = import_synthetic_artifact(
                self.artifact, self._adapter(requests), "synthetic_rehearsal_test",
                corpus_revision="fictional-r1", query_encoder_spec=self.spec,
                parent_lookup=self.parent_lookup, parent_lookup_version="fictional-parent-v1",
            )
        self.assertEqual(result["points"], 1)
        upserts = [body["points"] for _, path, body in requests if path.endswith("points?wait=true")]
        self.assertEqual(upserts[0][0]["id"], upserts[1][0]["id"])
        self.assertEqual(upserts[0][0]["payload"]["article_id"], "fictional-article-1")

    def test_rejects_incompatible_artifacts_before_qdrant_writes(self):
        cases = (
            {"corpus_revision": "fictional-r2"},
            {"query_encoder_spec": replace(E5ArtifactSpec.base_comparison(revision="a" * 40), tokenizer_revision="b" * 40)},
            {"parent_lookup_version": "fictional-parent-v2"},
            {"parent_lookup": {}},
        )
        for changes in cases:
            with self.subTest(changes=changes):
                requests = []
                args = {
                    "corpus_revision": "fictional-r1", "query_encoder_spec": self.spec,
                    "parent_lookup": self.parent_lookup, "parent_lookup_version": "fictional-parent-v1",
                }
                args.update(changes)
                with self.assertRaises(ValueError):
                    import_synthetic_artifact(self.artifact, self._adapter(requests), "synthetic_rehearsal_test", **args)
                self.assertEqual(requests, [])

    def test_rehearsal_command_path_uses_only_fictional_injected_transport(self):
        result = run(self.root / "command")
        self.assertEqual(result["points"], 1)
        self.assertTrue((self.root / "command" / "fictional-reviewed-articles.jsonl").is_file())
        self.assertEqual([call[0] for call in result["requests"]], ["PUT", "PUT"])


if __name__ == "__main__":
    unittest.main()
