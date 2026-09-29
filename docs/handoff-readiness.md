# Handoff readiness

This is an engineering status sheet, not legal approval. The pinned source is
`8977887f17be2defae4c5171d55562e1cde7d695`; the active provisional build is
`data/staging/8977887f17be2defae4c5171d55562e1cde7d695/build-20260928T161342Z-a43ae575`.

| Stage | Implemented | Mock-tested | Local live-tested | Not yet demonstrated |
| --- | --- | --- | --- | --- |
| 0. Audit | Strict central-only ledgers and source hashes | Unit tests | Pinned local data outputs | Legal authority, relevance, validity |
| 1. Staging | Parser, child chunks, review packets | Parser tests | Active provisional build | Owner employment/version review |
| 2. Sparse baseline | Article BM25 and legal metadata contracts | Unit tests | Local file path only | Reviewed searchable corpus |
| 3. Dense/retrieval | E5/reranker loaders, Qdrant adapter, hybrid/RRF contracts, synthetic artifact-import rehearsal | Injected encoder/reranker/import tests | Qdrant 1.13 synthetic points; rehearsal default is injected | Real model vectors, reviewed-corpus import, activation, quality |
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

# Fictional reviewed fixture only; injected Qdrant transport by default.
.\.venv\Scripts\python.exe scripts/rehearse_artifact_import.py --output data/embeddings/synthetic-artifact-rehearsal-v2

# Optional local Qdrant rehearsal; uses a unique synthetic collection and deletes it.
.\.venv\Scripts\python.exe scripts/rehearse_artifact_import.py --local-qdrant --output data/embeddings/synthetic-artifact-rehearsal-v2

# Synthetic UI only; no legal corpus or provider request.
.\.venv\Scripts\python.exe -m uvicorn app:app --app-dir scripts

# Explicit provider factory; remains fictional retrieval until corpus activation.
.\.venv\Scripts\python.exe -m uvicorn nine_router_config:create_runtime_app --factory --app-dir scripts

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
The synthetic rehearsal also binds corpus revision and parent-lookup version,
rejecting recipe, dimension, hash, corpus, or parent-lookup mismatches before
Qdrant writes. It accepts only `synthetic_` collections and never changes an
alias. `scripts/qdrant_contract.py` requires matching vector dimensions and
preserves versioned collection/alias operations. Do not activate an artifact
until the returned manifest, collection dimension, and reviewed benchmark
provenance agree.

## Remaining work

The manifest-only synthetic artifact import rehearsal is complete. It reads a
fictional reviewed fixture, produces/checks a shard manifest, validates it before
synthetic staging writes, and never activates an alias or a real collection.

Remaining independent engineering tasks:

- Use the opt-in 9Router stdlib HTTP transport only with an explicit enabled
  route/model/base URL; it has a finite timeout, 1 MB response limit, no retry,
  and no fallback. Confirm a free route before configuring it.
- For local CPU measurements, install compatible `torch` and `transformers` in
  the virtual environment only after owner approval: `python -m pip install torch transformers`.
  Place owner-supplied files under `data/models/e5-small/` and invoke
  `load_transformers_encoder(model_path="data/models/e5-small", tokenizer_path="data/models/e5-small", local_files_only=True)`.
  The loader uses the immutable small-E5 revisions in `data/config/e5_revisions.json`.
  The runner is `python scripts/cpu_benchmark.py data/models/e5-small --output data/benchmarks/cpu-e5.json --repeats 5`; it verifies `artifact_manifest.json` hashes before loading and uses `local_files_only=True`.
  Compatible dependency versions and real measurements remain unverified. The BGE reranker remains optional and is not a
  default dependency. Do not download or run weights until the owner supplies
  local artifacts.
- Connect the existing hybrid retriever to the app behind reviewed-corpus
  activation, preserving the synthetic demo until that gate is passed.

Owner/resource work:

- Obtain and pin local E5 and reranker files, then run bounded CPU
  encoding/reranking measurements using the documented recipe.
- Confirm a no-cost 9Router route, explicit base URL/route/model, and usage terms
  before enabling its configuration. The adapter has no default route or fallback.
- Review `owner_review_packet.csv`, authoritative source/version identity,
  applicability dates, employment relevance, and benchmark references.

The benchmark at `data/benchmarks/vietnamese_employment_draft.json` is unreviewed
scaffolding. It cannot generate retrieval-quality or legal-correctness claims.
