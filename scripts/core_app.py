"""Build the opt-in local app over the pinned inactive core corpus."""
from pathlib import Path
import json
import os

from app import create_app
from audit_corpus import REVISION
from core_retriever import CoreCorpusRetriever
from e5_artifacts import load_transformers_encoder
from groq import GroqProvider, http_transport
from groq_config import load_config
from import_core_corpus_qdrant import versioned_collection_name
from qdrant_contract import QdrantLocalConfig, QdrantRestAdapter


def create_core_app(*, provider=None, corpus_root=None, artifact_dir=None, model_dir="data/models/e5-small", env=None, dotenv_path=".env"):
    revision = REVISION
    corpus_root = Path(corpus_root or Path("data/curated") / revision / "core-employment-portfolio-v1")
    artifact_dir = Path(artifact_dir or "data/embeddings/core-employment-portfolio-v1-e5-small-provisional-v4")
    model_dir = Path(model_dir)
    encoder = load_transformers_encoder(model_path=model_dir, tokenizer_path=model_dir, local_files_only=True)
    artifact = json.loads((artifact_dir / "embedding_manifest.json").read_text(encoding="utf-8"))
    key = _qdrant_api_key(env, dotenv_path)
    qdrant_config = QdrantLocalConfig(api_key=key)
    qdrant = QdrantRestAdapter(qdrant_config)
    collection = versioned_collection_name(artifact, artifact_dir, qdrant_config)
    validate_qdrant_collection(qdrant.get_collection_info(collection), artifact)
    retriever = CoreCorpusRetriever(corpus_root / "articles.jsonl", corpus_root / "corpus_manifest.json", artifact_dir, encoder, qdrant=qdrant, collection=collection)
    config, key = load_config(env=env, dotenv_path=dotenv_path)
    if provider is None and config.enabled:
        provider = GroqProvider(config, http_transport(), key)
    provenance = {
        "model_version": artifact["model"]["model_id"] + "@" + artifact["model"]["revision"],
        "prompt_version": "provisional-snapshot-v1",
        "index_version": retriever.index_version,
        "corpus": "pinned-central-employment-prototype",
    }
    return create_app(provider=provider, retriever=retriever, provenance=provenance, provisional_snapshot_enabled=True)


def _qdrant_api_key(env, dotenv_path):
    values = {**_read_dotenv(dotenv_path), **(dict(env) if env is not None else os.environ)}
    key = values.get("QDRANT_API_KEY")
    if not isinstance(key, str) or not key.strip():
        raise ValueError("QDRANT_API_KEY is required for the pinned local collection")
    return key


def _read_dotenv(path):
    values = {}
    file = Path(path)
    if not file.exists():
        return values
    for line in file.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = (part.strip() for part in line.split("=", 1))
        if name == "QDRANT_API_KEY":
            if name in values or not value:
                raise ValueError("invalid QDRANT_API_KEY configuration")
            values[name] = value
    return values


def validate_qdrant_collection(response, artifact):
    info = response.get("result", {}) if isinstance(response, dict) else {}
    vectors = info.get("config", {}).get("params", {}).get("vectors", {})
    dimension = vectors.get("size") if isinstance(vectors, dict) else None
    if dimension != artifact["model"]["dimension"] or info.get("points_count") != artifact.get("records"):
        raise ValueError("versioned Qdrant collection does not match the pinned embedding artifact")
    if info.get("status") != "green":
        raise ValueError("versioned Qdrant collection is not ready")
