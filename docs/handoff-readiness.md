# Handoff readiness

This is an engineering status sheet, not legal approval. The pinned source is
`8977887f17be2defae4c5171d55562e1cde7d695`; the active provisional build is
`data/staging/8977887f17be2defae4c5171d55562e1cde7d695/build-20260928T161342Z-a43ae575`.

| Stage | Implemented | Mock-tested | Local live-tested | Not yet demonstrated |
| --- | --- | --- | --- | --- |
| 0. Audit | Strict central-only ledgers and source hashes | Unit tests | Pinned local data outputs | Legal authority, relevance, validity |
| 1. Staging | Parser, child chunks, review packets | Parser tests | Active provisional build | Owner employment/version review |
| 2. Sparse baseline | Article BM25 and legal metadata contracts | Unit tests | Local file path only | Reviewed searchable corpus |
| 3. Dense/retrieval | Pinned E5-small vectors for the inactive core corpus; checksummed shards; versioned Qdrant import path; hybrid/RRF and reranker contracts | Encoder chunking, manifest and injected Qdrant import tests | Real 384-d CPU model/query smoke and 477 core-corpus vectors; local Qdrant unavailable | Real Qdrant writes, provisional answer eligibility, retrieval/reranker quality |
| 4. App/provider | Synthetic Vietnamese UI/API, citation gate, disabled direct Groq bridge, redacted trace events, and accepted UI state/citation presentation contract | FastAPI, mocked HTTP, and static UI contract tests | One fictional Groq contract smoke succeeded; provider remains disabled | App connected to reviewed hybrid retrieval |
| 5. Evaluation/CI | Draft benchmark schema, evaluator/grid, GitHub Actions definition | Offline tests | No hosted CI run | Reviewed benchmark, measurements, CI evidence |

## Verified Stage 4 state

Stage 4 is accepted offline. The direct Groq runtime is disabled by default and
uses only `https://api.groq.com/openai/v1`, `chat/completions`, and
`openai/gpt-oss-20b`; it uses non-streaming strict JSON Schema responses, a
finite timeout, a 1 MB response limit, no redirect, retry, fallback, tools, or
browser search. Commit `184a1c7` sent the fixed application User-Agent and
JSON Accept headers. One bounded request with fictional evidence then succeeded:
state `unavailable`, citation validation true, 1,670.17 ms, and 932 total
tokens. This validates only the provider contract; it is not answer-quality or
legal-correctness evidence. The provider remains disabled and no legal corpus is
active.

Official references: [overview](https://console.groq.com/docs/overview),
[structured outputs](https://console.groq.com/docs/structured-outputs),
[rate limits](https://console.groq.com/docs/rate-limits),
[your data](https://console.groq.com/docs/your-data),
[billing FAQs](https://console.groq.com/docs/billing-faqs), and
[openai/gpt-oss-20b](https://console.groq.com/docs/model/openai/gpt-oss-20b).
The published Free Plan table is not proof of this account's available quota;
account limits remain authoritative. One fictional provider-contract validation passed; reviewed-corpus validation remains pending.

## Reproducible commands

```powershell
$env:PYTHONPATH='scripts'
.\.venv\Scripts\python.exe -m unittest discover -s scripts -p 'test_*.py' -q

# Pin and verify the CPU embedding runtime; download only the immutable E5 revision.
.\.venv\Scripts\python.exe -m pip install -r requirements-embeddings.txt
.\.venv\Scripts\python.exe scripts/fetch_e5_model.py --output data/models/e5-small
.\.venv\Scripts\python.exe scripts/cpu_benchmark.py data/models/e5-small --output data/benchmarks/cpu-e5-small-smoke.json --repeats 1

# Generate inactive real-data vectors, then validate the Qdrant import artifact without writes.
.\.venv\Scripts\python.exe scripts/core_corpus_embeddings.py --articles data/curated/8977887f17be2defae4c5171d55562e1cde7d695/core-employment-portfolio-v1/articles.jsonl --corpus-manifest data/curated/8977887f17be2defae4c5171d55562e1cde7d695/core-employment-portfolio-v1/corpus_manifest.json --model data/models/e5-small --output data/embeddings/core-employment-portfolio-v1-e5-small-r4
.\.venv\Scripts\python.exe scripts/import_core_corpus_qdrant.py --artifact data/embeddings/core-employment-portfolio-v1-e5-small-r4 --corpus-manifest data/curated/8977887f17be2defae4c5171d55562e1cde7d695/core-employment-portfolio-v1/corpus_manifest.json

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
.\.venv\Scripts\python.exe -m uvicorn groq_config:create_runtime_app --factory --app-dir scripts

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

## Current core-corpus batch

Commit `559e021` contains the deterministic three-document corpus. The current
uncommitted follow-up uses the immutable `intfloat/multilingual-e5-small`
revision `614241f622f53c4eeff9890bdc4f31cfecc418b3` and CPU-only
`torch==2.14.0+cpu` / `transformers==4.57.6`. Local files and all 477 vector
points are checksum-verified. Long articles are token-windowed while preserving
article IDs and canonical-text offsets. Every point is exact-central, reports
validity as unverified, and has `answer_evidence_enabled=false`. The Qdrant
import validates the entire artifact before writes, uses a versioned collection,
and does not activate an alias. Injected transport tests pass; the Docker daemon
is unavailable, so no real Qdrant write has occurred. Generated model, corpus,
and vector files are ignored by Git.

## Remaining work

- Implement a conservative source/date policy that allows explicitly
  provisional answers when the pinned record supports them, with a freshness and
  validity caveat. Abstain when requested dates, amendments, partial repeal, or
  conflicting statuses cannot be resolved. Employment scope remains unchanged.
- Run the versioned local Qdrant import when Docker is available, then wire
  real-data BM25+dense retrieval, reranking, and bounded retrieval evaluation.
- Connect the app and UI to this path without allowing retrieval similarity to
  stand in for legal validity. Keep Groq disabled by default and free-only; no
  paid fallback.
- Keep the existing review artifacts as provenance, not as a development gate.
  The benchmark remains a draft and cannot support legal-correctness claims.
- Run hosted CI after the offline gates pass.

The benchmark at `data/benchmarks/vietnamese_employment_draft.json` is unreviewed
scaffolding. It cannot generate retrieval-quality or legal-correctness claims.
