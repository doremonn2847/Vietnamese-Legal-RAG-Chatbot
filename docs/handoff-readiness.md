# Handoff readiness

This is an engineering status sheet, not legal approval. The pinned source is
`8977887f17be2defae4c5171d55562e1cde7d695`; the active provisional build is
`data/staging/8977887f17be2defae4c5171d55562e1cde7d695/build-20260928T161342Z-a43ae575`.

| Stage | Implemented | Mock-tested | Local live-tested | Not yet demonstrated |
| --- | --- | --- | --- | --- |
| 0. Audit | Strict central-only ledgers, source hashes, issuer/duplicate/relationship flags, blank expiry stays unknown | Audit policy tests | Pinned snapshot outputs | Legal authority, completeness, current validity |
| 1. Staging | Article parser, child chunks, deterministic provenance and optional review aids | Parser and curation tests | Pinned central employment prototype | Legal correctness; record-by-record approval is not a development gate |
| 2. Sparse baseline | Article BM25 and legal metadata contracts | Unit tests | Local indexed corpus | Broader retrieval quality |
| 3. Dense/retrieval | Pinned E5-small, 68 eligible article versions, 85 checksummed vectors, versioned Qdrant, hybrid/RRF and distinct CPU reranker | Encoder, scope, manifest, injected Qdrant tests | Real CPU vectors; 85-point local Qdrant collection; bounded real searches | Broad retrieval quality and production latency |
| 4. App/provider | Vietnamese FastAPI UI and local core app; exact-source provisional behavior; safe abstention; direct Groq disabled by default | FastAPI, UI-contract, citation, policy and provider tests; snapshot-only request-schema and route-guard regression tests | Real E5/Qdrant route and manual browser flow; one later leave request got Groq HTTP 200/provisional under the narrowed schema but the route withheld it on citation validation; earlier working-time and leave outputs were also safely withheld | Repeatable model quality, broader answer relevance, legal correctness; valid citations under live generation and working-time acceptance |
| 5. Evaluation/CI | Frozen snapshot behavior benchmark, held-out retrieval set, evaluator/grid, GitHub Actions definition | Offline suite and deterministic injected selector | Local bounded evaluations; hosted CI passed on `5d4687c` | Broader reviewed retrieval labels |

## Current prototype evidence

The pinned dataset revision is `8977887f17be2defae4c5171d55562e1cde7d695`.
The supported portfolio slice remains central employment law. The indexed
artifact contains 68 article versions and 85 real multilingual E5 vectors in
the local versioned Qdrant collection. Employment scope and the strict
central-only filter remain unchanged. Blank expiry and current validity remain
unknown/unverified. The owner removed per-record source review as a development
gate on 2026-09-30; that does not establish legal authority or correctness.

The frozen snapshot behavior v2 evaluation, recorded before the narrow
overtime-topic correction, has 19 cases: relevant evidence was
retrieved for 17/17 answerable cases, 13/17 received exact citations from a
deterministic reference selector, and citation-contract checks passed 19/19.
The selector receives the reference labels. This is evidence about local
retrieval reach and application contracts, not generative model quality,
Vietnamese semantic relevance, legal correctness, or validity. See
`data/benchmarks/snapshot_excerpt_natural_questions_v2_results.json`.
That artifact remains unchanged and was not rerun after the correction.
Inspection found two overtime queries abstained at the topic gate despite
`working_time` reference labels; the matcher now recognizes the narrow phrase
`làm thêm giờ`. The inspected held-out wording is no longer untouched
evaluation evidence.

Direct Groq remains disabled by default and uses the fixed official HTTPS
endpoint, `openai/gpt-oss-20b`, `stream:false`, strict JSON Schema, no retries,
and no paid fallback. Earlier fictional-evidence contract and article smoke
reports are historical. At commit `8ef2ca2`, the 2026-10-01 one-call real route
attempt retrieved three E5/Qdrant records and received HTTP 400
`invalid_request_error` / `json_validate_failed`, `param=other`; the local
route returned 503. `failed_generation` was present but empty, so its local
`invalid` JSON verdict did not establish what the model generated. See
`data/logs/groq_single_route_smoke_20261001_v4.json` and the offline packet
`data/logs/groq_provider_issue_packet_20261001.json`.

The 2026-10-02 request/prompt fix adds `reasoning_effort=low`,
`temperature=0`, and explicit exact-ID/quote/text instructions without changing
the schema or local citation validation. One real production-route call with
real E5/Qdrant evidence returned HTTP 200 provisional output, one validator-
approved 191-character citation, and an uncertainty caveat; its citation hash
matches the pinned source span. End-to-end time was 5.7 seconds and usage was
1,795 tokens. A separate insurance query was answered by the local scope gate
with no additional provider request. Six bounded diagnostic/verification
requests occurred across this investigation; none retried or used paid
fallback. See `docs/groq-inference-fix-20261002.md` and
`data/logs/groq_fixed_route_20261002.json`. This verifies one case only, not
repeatability, broad answer relevance, legal correctness, or Groq's internal
reason for the earlier 400. No further provider call is needed for this fix.

A separately bounded four-topic UI continuation used the same pinned snapshot,
real E5/Qdrant retrieval, strict schema, and unchanged citation validator. The
contracts case passed with one exact 191-character source citation (2,594
tokens); the answer and caveat rendered, while the source panel remained
collapsed. The working-time case returned HTTP 200 from Groq with a
674-character quote whose hash matches the entire canonical article; the
frozen expected sentence is 95 characters. The app's 500-character excerpt
guard rejects this before route citation validation, producing HTTP 502 and an
unavailable UI state with no answer or source. The continuation's separate
validator check also returned false, but its exact failed predicate is unknown
because raw claims were not retained. An offline synthetic production-route
differential confirmed that a consistent 674-character quote is rejected by
the route guard while the exact 95-character quote passes; this was not a replay
of the original model response. The final leave request returned HTTP 200 from
Groq with state `answer`, which the experimental excerpt route rejects because
it requires `provisional`; the UI returned unavailable before route citation
validation and displayed no answer or source. Its 186-character citation
covered, but did not exactly match, the frozen 183-character sentence. The
separate citation validator also returned false; its exact predicates were not
retained. One earlier leave UI submission failed in the temporary harness
before provider transport and consumed no provider call. The final submission
used the fourth and last total HTTP invocation across the original smoke and
continuation; there were no retries or paid fallback. No prompt or citation
validator change followed that live run; the later offline snapshot-only request
schema and system-contract adjustment is recorded below. The redacted checkpoint is
`data/benchmarks/groq_four_topic_continuation_20261002.json`; it contains hashes
and citation metadata, not raw answer text. Source metadata remains
`current_validity=unverified`; the page warns that blank expiry does not confirm
current validity.

Across the frozen four-topic set, the original probation call had a valid
citation but selected a 445-character span instead of the expected 147-character
sentence. Contracts passed with the exact 191-character sentence. Working time
was rejected for an over-500-character quote, and leave was rejected for the
wrong answer state; its citation covered but did not exactly match the frozen
sentence. These outcomes measure one bounded engineering smoke, not answer
reliability, legal correctness, or current validity.

Commit `5d4687c` adds an offline-only state guard for snapshot-mode Groq
requests: when evidence is nonempty and entirely snapshot-eligible, that
request's copied schema permits `provisional` and non-answer states but excludes
`answer` and `partial`. Dated, empty, and mixed-evidence requests retain the
shared schema, and the route guard independently rejects a wrong state. Injected
request tests cover those four cases; another injected provider returns
`answer` to exercise the route guard. The local suite passed 135 tests with 1
skipped and hosted CI passed on the exact commit. In a separate owner-authorized
check on 2026-10-04, one live leave request used the narrowed schema, received
upstream HTTP 200 and state `provisional`, then failed local citation validation;
the route returned HTTP 502/unavailable. The citation quote hash matches the
frozen 183-character sentence, but answer text was only 90 characters and the
raw span was 0..200. The provider may repair unique-quote offsets before
validation; exact validator predicates and claim text were not retained. The
report is `data/benchmarks/groq_snapshot_schema_acceptance_20261004.json`.
The working-time case was not sent in that initial check after the first
unexpected route failure.
This shows one schema-compatible response, not general schema enforcement or
reliability; claim/quote consistency and exact span selection remain unresolved.
The browser UI was not rendered in this check.

An offline-only route repair now handles the case where a provisional
experimental-excerpt response has nonempty display text that differs from its
exact claim text and `unvalidated_text` is the sole validator failure. The app
derives a candidate display only from existing claims and adopts it only if
full validation passes. It does not change claims, citations, quotes, source
eligibility, validity state, or validation rules. The existing blank-display
repair remains. Regression coverage confirms exact claims can pass while
paraphrased claims and wrong document versions remain rejected. The complete
local suite passed 136 tests (135 passed, 1 skipped). This does not change the
recorded leave failure or establish that Groq will reliably produce valid
citations. No live call was made while implementing this patch. After Design
passed it, the one remaining owner-authorized working-time call was used once:
Groq returned HTTP 200 with state `provisional` and a 674-character citation;
the app returned HTTP 502/unavailable at its existing 500-character excerpt
guard. Sanitized pre-route validation also found claim/quote mismatches and
`unvalidated_text`. No retry occurred. The full two-call additive budget is
now used; the original four-call budget remains separately exhausted. See
`data/benchmarks/groq_snapshot_working_time_followup_20261005.json`. This
follow-up does not establish generation reliability or legal correctness.

## Local browser verification

On 2026-10-01, the local core app was opened in a browser with the pinned
E5/Qdrant corpus and `GROQ_ENABLED=false`. The initial UI displayed the pinned
revision, supported scope, and the explicit warning that blank expiry does not
mean current validity. The source-text request “Trích nguyên văn Điều 24 trong
Bộ luật Lao động” displayed the exact extract, source/version citation, and
unverified-validity caveat. “Quy định về thử việc có áp dụng cho trường hợp
của tôi không?” produced a safe abstention with no citation. Both were real
local retrieval/UI paths and made no provider call.

The experimental ordinary-question path with Groq disabled displayed “Dịch vụ
hiện không khả dụng” and “Mô hình trả lời chưa được bật.” For stale-output
clearing, an injected provider first returned a contract-valid excerpt using
real retrieved evidence, then raised an injected error on the next request;
the UI cleared the previous quote and source and displayed the Vietnamese
unavailable state. This sequence is mocked at the provider boundary. These
manual browser checks found no wiring defect and do not establish answer
quality or legal correctness; no redundant regression test was added.

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

# Optional distinct CPU reranker benchmark (9 manually labeled dev queries, <=20 candidates).
.\.venv\Scripts\python.exe scripts/fetch_reranker.py --output data/models/bge-reranker-v2-m3
.\.venv\Scripts\python.exe scripts/evaluate_core_reranker.py --reranker data/models/bge-reranker-v2-m3 --output data/benchmarks/vietnamese_employment_retrieval_v1_results.json
.\.venv\Scripts\python.exe scripts/evaluate_heldout_retrieval.py --cases data/benchmarks/vietnamese_employment_heldout_v2.json --output data/benchmarks/vietnamese_employment_heldout_v2_results.json

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

# Local pinned employment UI; requires matching local Qdrant and QDRANT_API_KEY.
# Force Groq off for local corpus/status and unavailable-state checks.
$env:PYTHONPATH='scripts'
$env:GROQ_ENABLED='false'
.\.venv\Scripts\python.exe -m uvicorn core_app:create_core_app --factory --app-dir scripts

# Explicit provider factory; remains fictional retrieval until corpus activation.
.\.venv\Scripts\python.exe -m uvicorn groq_config:create_runtime_app --factory --app-dir scripts

# Draft inspection only. It refuses unreviewed cases in measurement mode.
.\.venv\Scripts\python.exe scripts/evaluate_cli.py data/benchmarks/vietnamese_employment_draft.json
```

Tracked configuration lives in `data/config/e5_revisions.json`,
`data/config/reranker_revision.json`, `docker-compose.qdrant.yml`, and
`.github/workflows/test.yml`. Generated raw/audit/staging data, Qdrant storage,
embeddings, models, logs, and local secrets are ignored. The configured GitHub
remote is `origin`; hosted Actions passed for `31c28d8`.

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

Commit `3918fd9` implements extractive provisional answers. The follow-up under
review records amendment/version edges, quarantines related noncore texts, and
restricts retrieval to four employment topics plus an explicit dependency
allowlist (61 topic articles, 7 dependencies, 297 exclusions). It reuses active staged parses for the regulation and circular, and
stages the Labor Code original once because the active parse build excluded it
as a duplicate. The curated file still retains 365 articles; 68 enter the index.

The immutable `intfloat/multilingual-e5-small` revision is
`614241f622f53c4eeff9890bdc4f31cfecc418b3`; the new inactive artifact has 85
384-dimensional vectors. Local Qdrant v1.13.2 contains all 85 points in the
artifact-digest-versioned collection. Collection dimension/count and a bounded
three-hit search were verified. The core app resolves that collection, fails
closed on mismatch/unavailability, and `/api/search` uses configured retrieval.
No alias is active. A TestClient check used the real corpus, local Qdrant and
encoder with a provider that fails if called: extractive response validation
passed, and an applicability query abstained. Current validity remains
unverified, blank expiry remains unknown, and Groq stayed disabled. Only a
clearly phrased source-text request can receive the extract; ambiguous
permission questions abstain by default.

## Remaining work

- A bounded nine-query dev check is recorded at `data/benchmarks/vietnamese_employment_retrieval_v1_results.json`. On this machine the distinct pinned BGE CPU reranker raised mean MRR@5 from 0.944 to 1.0 and left recall@5 at 1.0; mean reranker latency was about 27 seconds/query. The set is small and manually labeled from section headings, so these exploratory results do not establish retrieval quality broadly or legal correctness.
- Held-out v1 at `data/benchmarks/vietnamese_employment_heldout_v1.json` is superseded due to dev leakage; see its status sidecar and do not cite its results.
- The corrected, frozen v2 set and local result are at `data/benchmarks/vietnamese_employment_heldout_v2.json` and `data/benchmarks/vietnamese_employment_heldout_v2_results.json`. Positive-case Recall@5/MRR@5: BM25 0.714/0.529, dense 1.0/0.719, RRF 0.857/0.619, and reranking 0.857/0.857 (depth 5), 1.0/1.0 (depths 10 and 20). Rerank p50/p95: 7.8/10.4 s, 15.2/16.6 s, and 29.2/34.8 s. Retrieval p50/p95: 79/397 ms. Peak process working set: 0.90 GB after model load, 2.04 GB after evaluation. Labels remain heading-level relevance, not legal review.
- Keep the online path pre-rerank unless broader evidence justifies change; the single negative case tests ranking only and retrieval candidates do not determine whether a legal answer is safe.
- Expand the exploratory set before broader retrieval-quality claims.
- Continue to keep validity unverified; do not treat the extractive slice as a
  legal-correctness or current-applicability release.
- Keep Groq disabled by default. The original four-call smoke budget remains exhausted. The separate two-call check also reached its cap: leave used one call and working time used one after Design reviewed the offline patch. Do not retry either case or make further live calls under that budget.
- Keep the existing review artifacts as provenance, not as a development gate.
  The benchmark remains a draft and cannot support legal-correctness claims.
- Run hosted CI after the offline gates pass.
- Keep direct Groq disabled by default. The request-schema fix is verified offline and by hosted CI, and was schema-compatible in one live leave request; end-to-end answer reliability remains unverified.

The separate `data/benchmarks/vietnamese_employment_draft.json` remains unreviewed
scaffolding and cannot generate legal-correctness claims.
