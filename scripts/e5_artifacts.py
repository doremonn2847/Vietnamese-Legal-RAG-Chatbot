"""Pinned E5 specification plus an opt-in local Transformers encoder."""
from dataclasses import asdict, dataclass
import re
import unicodedata
import json
import urllib.request


PINNED_E5_REVISIONS = {
    "intfloat/multilingual-e5-small": "614241f622f53c4eeff9890bdc4f31cfecc418b3",
    "intfloat/multilingual-e5-base": "d128750597153bb5987e10b1c3493a34e5a4502a",
}


@dataclass(frozen=True)
class E5ArtifactSpec:
    model_id: str = "intfloat/multilingual-e5-small"
    revision: str | None = None
    dimension: int = 384
    document_prefix: str = "passage: "
    query_prefix: str = "query: "
    tokenizer_id: str = "intfloat/multilingual-e5-small"
    tokenizer_revision: str | None = None
    pooling: str = "mean"
    max_tokens: int = 512
    normalize_embeddings: bool = True
    preprocessing: str = "NFC + collapse whitespace"

    def document_text(self, text):
        return self.document_prefix + self.prepare_text(text)

    def query_text(self, text):
        return self.query_prefix + self.prepare_text(text)

    def prepare_text(self, text, token_count=None):
        normalized = " ".join(unicodedata.normalize("NFC", text or "").split())
        if token_count is not None and token_count > self.max_tokens:
            raise ValueError("input exceeds the E5 token limit; split before encoding")
        return normalized

    def validate_execution(self):
        if not self.revision or not re.fullmatch(r"[0-9a-f]{40}", self.revision) or not self.tokenizer_revision or not re.fullmatch(r"[0-9a-f]{40}", self.tokenizer_revision):
            raise ValueError("full immutable model and tokenizer revisions are required before execution")
        expected = {"intfloat/multilingual-e5-small": 384, "intfloat/multilingual-e5-base": 768}.get(self.model_id)
        if expected != self.dimension or self.pooling != "mean" or self.max_tokens <= 0 or self.dimension <= 0:
            raise ValueError("invalid E5 artifact specification")
        return True

    def manifest(self):
        return asdict(self)

    @classmethod
    def base_comparison(cls, revision=None):
        return cls(model_id="intfloat/multilingual-e5-base", tokenizer_id="intfloat/multilingual-e5-base", dimension=768, revision=revision)

    @classmethod
    def pinned_small(cls):
        revision = PINNED_E5_REVISIONS["intfloat/multilingual-e5-small"]
        return cls(revision=revision, tokenizer_revision=revision)


class E5EncoderAdapter:
    """CPU-capable adapter around an injected tokenizer/model pair."""
    def __init__(self, tokenizer, model, spec):
        self.tokenizer = tokenizer
        self.model = model
        self.spec = spec
        spec.validate_execution()

    def token_count(self, text):
        encoded = self.tokenizer(text, add_special_tokens=True, truncation=False)
        ids = encoded["input_ids"]
        return len(ids[0]) if ids and isinstance(ids[0], list) else len(ids)

    def encode_documents(self, texts):
        return self._encode([self.spec.document_text(text) for text in texts])

    def encode_queries(self, texts):
        return self._encode([self.spec.query_text(text) for text in texts])

    def __call__(self, texts):
        return self._encode(texts)

    def _encode(self, texts):
        for text in texts:
            self.spec.prepare_text(text, self.token_count(text))
        vectors = self.model(texts, normalize_embeddings=self.spec.normalize_embeddings)
        if len(vectors) != len(texts) or any(len(vector) != self.spec.dimension for vector in vectors):
            raise ValueError("model returned incompatible E5 vectors")
        return vectors


class TransformersE5Encoder:
    """CPU Transformers encoder using attention-mask mean pooling."""
    def __init__(self, tokenizer, model, torch_module, spec):
        spec.validate_execution()
        self.tokenizer, self.model, self.torch, self.spec = tokenizer, model, torch_module, spec
        self.model.to("cpu").eval()

    def token_count(self, text):
        encoded = self.tokenizer(text, add_special_tokens=True, truncation=False)
        ids = encoded["input_ids"]
        return len(ids[0]) if ids and isinstance(ids[0], list) else len(ids)

    def encode_documents(self, texts):
        return self._encode([self.spec.document_text(text) for text in texts])

    def encode_queries(self, texts):
        return self._encode([self.spec.query_text(text) for text in texts])

    def __call__(self, texts):
        return self._encode(texts)

    def _encode(self, texts):
        for text in texts:
            self.spec.prepare_text(text, self.token_count(text))
        batch = self.tokenizer(texts, padding=True, truncation=False, return_tensors="pt")
        with self.torch.no_grad():
            hidden = self.model(**{key: value.to("cpu") for key, value in batch.items()}).last_hidden_state
        mask = batch["attention_mask"].unsqueeze(-1).to(hidden.dtype)
        pooled = (hidden * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1e-9)
        vectors = self.torch.nn.functional.normalize(pooled, p=2, dim=1)
        return vectors.cpu().tolist()


def load_transformers_encoder(spec=None, model_path=None, tokenizer_path=None, local_files_only=True):
    """Load a pinned model from an existing local cache/path; never downloads by default."""
    spec = spec or E5ArtifactSpec.pinned_small()
    spec.validate_execution()
    try:
        import torch
        from transformers import AutoModel, AutoTokenizer
    except ImportError as error:
        raise RuntimeError("install torch and transformers to run the opt-in local encoder") from error
    model_ref = model_path or spec.model_id
    tokenizer_ref = tokenizer_path or spec.tokenizer_id
    tokenizer = AutoTokenizer.from_pretrained(tokenizer_ref, revision=spec.tokenizer_revision, local_files_only=local_files_only)
    model = AutoModel.from_pretrained(model_ref, revision=spec.revision, local_files_only=local_files_only)
    return TransformersE5Encoder(tokenizer, model, torch, spec)


def resolve_hf_revision(model_id, endpoint="https://huggingface.co"):
    """Read-only model metadata lookup; callers must persist the returned SHA."""
    url = endpoint.rstrip("/") + "/api/models/" + model_id
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=10) as response:
        metadata = json.loads(response.read().decode("utf-8"))
    revision = metadata.get("sha")
    if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Hugging Face metadata did not provide an immutable commit SHA")
    return revision
