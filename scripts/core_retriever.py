"""Local hybrid retrieval over the inactive, checksummed core corpus."""
import hashlib
import json
import math
import time
from pathlib import Path

from bm25 import BM25Index
from import_core_corpus_qdrant import validate_artifact
from retrieval import rrf_fuse, select_evidence


class CoreCorpusRetriever:
    def __init__(self, articles_path, corpus_manifest_path, artifact_dir, encoder, *, qdrant=None, collection=None, sparse_limit=30, dense_limit=30, evidence_cap=5):
        self.articles_path = Path(articles_path)
        self.corpus_manifest_path = Path(corpus_manifest_path)
        self.artifact_dir = Path(artifact_dir)
        if qdrant is not None and (not isinstance(collection, str) or not collection.strip()):
            raise ValueError("Qdrant collection is required when configured retrieval is enabled")
        self.encoder, self.qdrant, self.collection = encoder, qdrant, collection
        self.sparse_limit, self.dense_limit, self.evidence_cap = sparse_limit, dense_limit, evidence_cap
        corpus = json.loads(self.corpus_manifest_path.read_text(encoding="utf-8"))
        if not corpus.get("outputs", {}).get("articles.jsonl", {}).get("sha256") == _sha(self.articles_path):
            raise ValueError("article file does not match the curated corpus manifest")
        manifest, points = validate_artifact(self.artifact_dir, self.corpus_manifest_path)
        self.points = points
        self.articles = {}
        with self.articles_path.open(encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                article = json.loads(line)
                article_id = article.get("article_id")
                if not isinstance(article_id, str) or article_id in self.articles:
                    raise ValueError(f"invalid or duplicate article ID at line {line_number}")
                metadata = article.get("document_metadata") or {}
                if metadata.get("pham_vi") != "Trung ương" or type(metadata.get("retrieval_index_candidate")) is not bool:
                    raise ValueError(f"article fails exact central scope metadata at line {line_number}")
                self.articles[article_id] = article
        docs = []
        for point in self.points:
            payload = point["payload"]
            article = self.articles.get(payload["article_id"])
            if not article or article.get("article_version_id") != payload.get("article_version_id") or article.get("document_version_id") != payload.get("document_version_id"):
                raise ValueError("embedding point does not match its parent article/version")
            metadata = article.get("document_metadata") or {}
            if metadata.get("retrieval_index_candidate") is not True or any(payload.get(key) != metadata.get(key) for key in ("pham_vi", "retrieval_index_candidate", "answer_evidence_enabled", "current_validity", "expiry_state", "reported_status_conflict", "amendment_state", "quarantined_related_document_ids", "source_dataset_revision")):
                raise ValueError("embedding point metadata differs from its parent article")
            docs.append({"article_id": payload["article_id"], "document_version_id": payload["document_version_id"], "child_id": payload["child_id"], "text": payload["canonical_text"]})
        expected_candidates = corpus.get("retrieval_index_article_count", corpus.get("article_count"))
        if len(self.articles) != corpus.get("article_count") or len({point["payload"]["article_version_id"] for point in self.points}) != expected_candidates:
            raise ValueError("article and embedding manifests have different version coverage")
        self.sparse = BM25Index(docs)
        self.index_version = hashlib.sha256((self.corpus_manifest_path.read_bytes() + (self.artifact_dir / "embedding_manifest.json").read_bytes()).strip()).hexdigest()

    def search(self, query, legal_date=None):
        started = time.perf_counter_ns()
        sparse = self.sparse.search(query, limit=self.sparse_limit)
        sparse_ms = (time.perf_counter_ns() - started) / 1_000_000
        dense_started = time.perf_counter_ns()
        vector = self.encoder.encode_queries([query])[0]
        if len(vector) != len(self.points[0]["vector"]) or any(not isinstance(value, (int, float)) or not math.isfinite(value) for value in vector):
            raise ValueError("query encoder returned an incompatible vector")
        if self.qdrant is None:
            dense = sorted(({"article_id": point["payload"]["article_id"], "child_id": point["payload"]["child_id"], "score": sum(left * right for left, right in zip(vector, point["vector"])), "text": point["payload"]["canonical_text"]} for point in self.points), key=lambda row: (-row["score"], row["article_id"], row["child_id"]))[:self.dense_limit]
        else:
            filters = {"must": [{"key": "pham_vi", "match": {"value": "Trung ương"}}, {"key": "retrieval_index_candidate", "match": {"value": True}}]}
            result = self.qdrant.search(self.collection, vector, filters, limit=self.dense_limit).get("result", [])
            dense = [{"article_id": item["payload"]["article_id"], "child_id": item["payload"]["child_id"], "score": item["score"], "text": item["payload"]["canonical_text"]} for item in result]
        dense_ms = (time.perf_counter_ns() - dense_started) / 1_000_000
        ranked_started = time.perf_counter_ns()
        fused = rrf_fuse({"bm25": sparse, "dense": dense})
        matched = {}
        for hit in sparse + dense:
            matched.setdefault(hit["article_id"], set()).add(hit.get("child_id"))
        candidates = []
        for hit in fused:
            article = self.articles.get(hit["article_id"])
            if not article:
                continue
            metadata = article["document_metadata"]
            candidates.append({**article, **metadata, **hit, "text": article["canonical_text"], "source_url": metadata.get("source_dataset_url"), "evidence_id": f"{article['article_id']}:{article['document_version_id']}", "matched_child_ids": sorted(child for child in matched.get(hit["article_id"], set()) if child)})
        evidence = select_evidence(candidates, self.evidence_cap)
        return {"sparse": sparse, "dense": dense, "fused": fused, "evidence": evidence, "timings_ms": {"sparse": sparse_ms, "dense": dense_ms, "fusion_and_evidence": (time.perf_counter_ns() - ranked_started) / 1_000_000}}


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
