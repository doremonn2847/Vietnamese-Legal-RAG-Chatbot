# Handoff readiness

This is an engineering status sheet, not legal approval. The pinned source is
`8977887f17be2defae4c5171d55562e1cde7d695`; the active provisional build is
`data/staging/8977887f17be2defae4c5171d55562e1cde7d695/build-20260928T161342Z-a43ae575`.

| Stage | Implemented | Mock-tested | Local live-tested | Not yet demonstrated |
| --- | --- | --- | --- | --- |
| 0. Audit | Strict central-only ledgers and source hashes | Unit tests | Pinned local data outputs | Legal authority, relevance, validity |
| 1. Staging | Parser, child chunks, review packets | Parser tests | Active provisional build | Owner employment/version review |
| 2. Sparse baseline | Article BM25 and legal metadata contracts | Unit tests | Local file path only | Reviewed searchable corpus |
| 3. Dense/retrieval | E5/reranker loaders, Qdrant adapter, hybrid/RRF contracts | Injected encoder/reranker tests | Qdrant 1.13 synthetic points | Real model vectors, import, activation, quality |
| 4. App/provider | Synthetic Vietnamese UI/API, citation gate, disabled 9Router bridge, redacted trace events | FastAPI and mocked HTTP | No provider call | App connected to real hybrid retrieval/provider |
| 5. Evaluation/CI | Draft benchmark schema, evaluator/grid, GitHub Actions definition | Offline tests | No hosted CI run | Reviewed benchmark, measurements, CI evidence |

## Reproducible commands

```powershell
$env:PYTHONPATH='scripts'
.\.venv\Scripts\python.exe -m unittest discover -s scripts -p 'test_*.py' -q

# Synthetic local Qdrant only; needs an already-running local Compose service.
$env:RUN_QDRANT_INTEGRATION='1'
$env:QDRANT_API_KEY='<local-key>'
.\.venv\Scripts\python.exe -m unittest scripts.test_qdrant_integration -q

# Synthetic UI only; no legal corpus or provider request.
.\.venv\Scripts\python.exe -m uvicorn app:app --app-dir scripts

# Draft inspection only. It refuses unreviewed cases in measurement mode.
.\.venv\Scripts\python.exe scripts/evaluate_cli.py data/benchmarks/vietnamese_employment_draft.json
```

Tracked configuration lives in `data/config/e5_revisions.json`,
`data/config/reranker_revision.json`, `docker-compose.qdrant.yml`, and
`.github/workflows/test.yml`. Generated raw/audit/staging data, Qdrant storage,
embeddings, models, logs, and local secrets are ignored. No remote is configured.

## Compatibility before Kaggle import or activation

`scripts/kaggle_batch.py` accepts only reviewed, central-eligible article input
with immutable model/tokenizer revisions, finite vectors, shard checksums, and
ordered child IDs. Its manifest must match the corpus input and embedding spec.
`scripts/qdrant_contract.py` requires matching vector dimensions and preserves
versioned collection/alias operations. Run a local synthetic import before any
artifact is activated. Do not activate an artifact until the returned manifest,
collection dimension, and reviewed benchmark provenance agree.

## Remaining work

The next unblocked engineering slice is a manifest-only artifact import rehearsal:
read a reviewed fixture, produce/check a shard manifest, import synthetic vectors,
and compare the collection/benchmark provenance without alias activation. It must
leave real corpus activation off and pass default plus opt-in Qdrant tests.

Owner/resource work:

- Obtain and pin local E5 and reranker files, install compatible CPU `torch` and
  `transformers`, then run bounded CPU encoding/reranking measurements.
- Confirm a no-cost 9Router route, explicit base URL/route/model, and usage terms
  before enabling its configuration. The adapter has no default route or fallback.
- Review `owner_review_packet.csv`, authoritative source/version identity,
  applicability dates, employment relevance, and benchmark references.

The benchmark at `data/benchmarks/vietnamese_employment_draft.json` is unreviewed
scaffolding. It cannot generate retrieval-quality or legal-correctness claims.
