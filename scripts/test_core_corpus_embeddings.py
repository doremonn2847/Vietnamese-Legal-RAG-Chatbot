import json
import re
import tempfile
import unittest
from pathlib import Path

from core_corpus_embeddings import _read_records
from e5_artifacts import E5ArtifactSpec


class WordTokenizer:
    def __call__(self, text, add_special_tokens=True, truncation=False, return_offsets_mapping=False):
        spans = [(match.start(), match.end()) for match in re.finditer(r"\S+", text)]
        if return_offsets_mapping:
            return {"offset_mapping": spans}
        return {"input_ids": list(range(len(spans)))}


class CoreCorpusEmbeddingsTest(unittest.TestCase):
    def test_chunks_long_articles_with_stable_article_and_unverified_payload(self):
        article = {
            "article_id": "article-1", "article_version_id": "article-version-1", "document_id": "139264",
            "document_version_id": "doc-version-1", "label": "Điều 1", "validity": "unverified",
            "canonical_text": " ".join(f"word{i}" for i in range(500)), "topic_candidates": ["contracts"],
            "document_metadata": {"pham_vi": "Trung ương", "retrieval_index_candidate": True, "answer_evidence_enabled": False, "current_validity": "unverified"},
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "articles.jsonl"
            path.write_text(json.dumps(article) + "\n", encoding="utf-8")
            records = _read_records(path, WordTokenizer(), E5ArtifactSpec.pinned_small())
        self.assertEqual(len(records), 2)
        payload = records[0]["payload"]
        self.assertEqual(payload["article_label"], "Điều 1")
        self.assertEqual(payload["current_validity"], "unverified")
        self.assertFalse(payload["answer_evidence_enabled"])
        self.assertLessEqual(len(records[0]["text"].split()), 442)

    def test_fails_closed_without_exact_central_scope(self):
        article = {
            "article_id": "article-1", "article_version_id": "article-version-1", "document_id": "139264",
            "document_version_id": "doc-version-1", "label": "Điều 1", "validity": "unverified", "canonical_text": "one two",
            "document_metadata": {"pham_vi": None, "retrieval_index_candidate": True, "answer_evidence_enabled": False, "current_validity": "unverified"},
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "articles.jsonl"
            path.write_text(json.dumps(article) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "noncentral"):
                _read_records(path, WordTokenizer(), E5ArtifactSpec.pinned_small())


if __name__ == "__main__":
    unittest.main()
