"""Opt-in CPU cross-encoder reranker; no download is attempted by default."""
from dataclasses import dataclass
import re


@dataclass(frozen=True)
class RerankerSpec:
    model_id: str = "BAAI/bge-reranker-v2-m3"
    revision: str = "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"
    max_tokens: int = 512

    def validate(self):
        if not re.fullmatch(r"[0-9a-f]{40}", self.revision) or self.max_tokens <= 0:
            raise ValueError("reranker requires an immutable revision and positive token limit")


class TransformersReranker:
    def __init__(self, tokenizer, model, torch_module, spec):
        spec.validate()
        self.tokenizer, self.model, self.torch, self.spec = tokenizer, model, torch_module, spec
        self.model.to("cpu").eval()

    def score(self, query, candidates):
        texts = [candidate["text"] for candidate in candidates]
        if not texts:
            return {}
        batch = self.tokenizer([query] * len(texts), texts, padding=True, truncation=True, max_length=self.spec.max_tokens, return_tensors="pt")
        with self.torch.no_grad():
            logits = self.model(**{key: value.to("cpu") for key, value in batch.items()}).logits
        return {candidate["article_id"]: float(score) for candidate, score in zip(candidates, logits.reshape(-1).cpu().tolist())}


def load_transformers_reranker(spec=None, model_path=None, local_files_only=True):
    spec = spec or RerankerSpec()
    spec.validate()
    try:
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
    except ImportError as error:
        raise RuntimeError("install torch and transformers to run the opt-in local reranker") from error
    reference = model_path or spec.model_id
    tokenizer = AutoTokenizer.from_pretrained(reference, revision=spec.revision, local_files_only=local_files_only)
    model = AutoModelForSequenceClassification.from_pretrained(reference, revision=spec.revision, local_files_only=local_files_only)
    return TransformersReranker(tokenizer, model, torch, spec)
