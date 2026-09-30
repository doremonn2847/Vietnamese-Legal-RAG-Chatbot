"""Build the opt-in local app over the pinned inactive core corpus."""
from pathlib import Path
import json

from app import create_app
from audit_corpus import REVISION
from core_retriever import CoreCorpusRetriever
from e5_artifacts import load_transformers_encoder
from groq import GroqProvider, http_transport
from groq_config import load_config


def create_core_app(*, provider=None, corpus_root=None, artifact_dir=None, model_dir="data/models/e5-small", env=None, dotenv_path=".env"):
    revision = REVISION
    corpus_root = Path(corpus_root or Path("data/curated") / revision / "core-employment-portfolio-v1")
    artifact_dir = Path(artifact_dir or "data/embeddings/core-employment-portfolio-v1-e5-small-provisional-v1")
    model_dir = Path(model_dir)
    encoder = load_transformers_encoder(model_path=model_dir, tokenizer_path=model_dir, local_files_only=True)
    retriever = CoreCorpusRetriever(corpus_root / "articles.jsonl", corpus_root / "corpus_manifest.json", artifact_dir, encoder)
    config, key = load_config(env=env, dotenv_path=dotenv_path)
    if provider is None and config.enabled:
        provider = GroqProvider(config, http_transport(), key)
    artifact = json.loads((artifact_dir / "embedding_manifest.json").read_text(encoding="utf-8"))
    provenance = {
        "model_version": artifact["model"]["model_id"] + "@" + artifact["model"]["revision"],
        "prompt_version": "provisional-snapshot-v1",
        "index_version": retriever.index_version,
        "corpus": "pinned-central-employment-prototype",
    }
    return create_app(provider=provider, retriever=retriever, provenance=provenance, provisional_snapshot_enabled=True)
