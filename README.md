# Vietnamese Legal RAG — pinned corpus audit and prototype

This workspace contains a strict audit of the pinned legal snapshot and a
narrow central-only employment prototype. The prototype uses local BM25, real
multilingual E5 embeddings, versioned Qdrant, and a Vietnamese FastAPI UI.
Direct Groq inference remains disabled by default. Snapshot dates and reported
status do not establish current legal validity, and prototype evaluations do
not establish legal correctness. The owner removed record-by-record source
review as a development gate on 2026-09-30; legal/source review remains needed
before making legal-correctness or current-applicability claims.

Source: [th1nhng0/vietnamese-legal-documents](https://huggingface.co/datasets/th1nhng0/vietnamese-legal-documents/tree/8977887f17be2defae4c5171d55562e1cde7d695),
revision `8977887f17be2defae4c5171d55562e1cde7d695`.
The publisher declares CC BY 4.0 for the compiled dataset; its dataset card is
preserved with the snapshot. This declaration does not verify individual-source
authority, completeness, current validity, or redistribution rights.

## Run on Windows

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-audit.txt
.\.venv\Scripts\python.exe scripts/download_snapshot.py
.\.venv\Scripts\python.exe -m unittest discover -s scripts -p test_*.py
.\.venv\Scripts\python.exe scripts/audit_corpus.py
# Optional synthetic API demo (never uses the legal corpus)
$env:PYTHONPATH='scripts'; .\.venv\Scripts\python.exe -m uvicorn app:app --app-dir scripts

# Local pinned employment UI; requires the matching Qdrant collection and QDRANT_API_KEY.
# Keep direct Groq disabled for this local run.
$env:PYTHONPATH='scripts'; $env:GROQ_ENABLED='false'; .\.venv\Scripts\python.exe -m uvicorn core_app:create_core_app --factory --app-dir scripts
```

Downloads only `metadata`, `content`, `relationships`, and the dataset card at
the pinned revision. Existing source files must match their expected hashes;
they are never silently overwritten. Downloads use validated byte ranges and
verify final upstream SHA-256 hashes. `legacy_*` is excluded.

Originals and their provenance manifest live in `data/raw/<revision>/`.
Reproducible audit ledgers and checksums live in `data/audit/<revision>/`.
Both are excluded from Git. The broad audit does not create a searchable
release; the separately scoped employment prototype is documented below.

## Audit policy

1. Inventory every original `pham_vi` value, preserving null separately, before
   filtering. Normalize with Unicode NFC, case folding, and whitespace collapse.
2. Only exact normalized `trung ương` passes the scope gate. Known local values
   are excluded. `Toàn quốc`, ambiguous labels, and missing labels are quarantined.
   Issuer names never override the scope label to promote a record.
3. Issuer name patterns flag local/central contradictions and missing or
   unrecognized issuers. These are audit signals, not verified authority. Central
   records with unresolved issuer signals are quarantined. Local-labeled records
   remain excluded even when their issuer looks central.
4. Audit missing content, blank HTML, and apparently textless HTML. Preserve
   image/PDF-only records for source review; do not pretend to have usable text.
5. Audit repeated metadata/content IDs, exact metadata excluding IDs,
   bibliographic identity (number + issuer + issuance date), exact HTML, and
   normalized visible-text fingerprints. Preserve all originals and all group
   members. Central records in duplicate groups are quarantined, not merged.
   Bibliographic and text matches are candidates, not proof of legal equivalence.
6. Check all directed relationships for absent endpoints, repeated edges, and
   self-links. Also record links from central documents to targets unavailable
   after filtering. A dangling relationship is not proof of a legally necessary
   dependency, nor does filtering a target erase the reference.
7. Blank expiry means `unknown_expiry`. All current-validity assessments remain
   `unverified`, regardless of reported status. Expired/historical records may be
   retained for review; no date is used to assert present applicability.

`include_for_employment_review` means that a document passed the mechanical
central/data-quality screen. It is **not** an employment-relevance decision,
verified legal authority, nationwide applicability, or permission to index it.
Relationships do not expand the supported domain or override the central gate.

Employment scope remains ordinary adult private-sector probation, contracts,
working time, and leave, with necessary central interpretive dependencies.
Disputes, insurance, public employment, and special categories remain excluded.
Document/provision relevance and validity review are subsequent gates.

## Outputs

- `pham_vi_inventory.csv`: every raw and normalized scope value and count.
- `document_decisions.csv`: every metadata row, its primary disposition, all
  overlapping flags, source content hashes, and explicit validity/relevance state.
- `issuer_inventory.csv`, `issuer_conflicts.csv`: issuer signals and conflicts.
- `missing_content.csv`, `orphan_content.csv`: missing/unusable and unjoined content.
- `duplicate_groups.csv`, `duplicate_relationships.csv`: full duplicate membership.
- `relationship_issues.csv`: dangling, self, and filtered-target references.
- `summary.json`: reconciled counts; primary reasons are mutually exclusive,
  while issue and duplicate categories overlap and must not be summed.
- `audit_manifest.json`: input provenance, script/runtime identity and output hashes.

The HTML text fingerprint is only a whitespace/markup heuristic used to flag
duplicates and missing visible text. It is not article parsing, legal text
normalization, an exact source span, or evidence suitable for quotation.

## Current implementation milestone

The next provisional stage is available locally:

```powershell
.\.venv\Scripts\python.exe scripts/stage_corpus.py
# Resolve the active build from data/staging/<revision>/active_staging.json,
# then pass its articles.jsonl path to search_bm25.py.
```

The broad provisional run found 527 central employment seed documents, 3,789
seed/dependency review IDs, 45 dangling dependency IDs, and attempted 1,420
audit-eligible documents. Article segmentation succeeded for 1,085 documents,
320 produced zero articles, and 15 were quarantined for explicit layout anomalies,
yielding 18,595 article versions and 1,766 child chunks. This is a review packet,
not a searchable release.
`owner_review_packet.csv` preserves seed, dependency, excluded, and dangling
records. `articles.jsonl` uses deterministic content/version UUIDs, raw HTML
source offsets, article context, cross-reference labels, hierarchy nodes, and
bounded child spans for oversized articles. `parse_ledger.csv` records a status
and reason for every attempted document, including zero-article and quarantined
layouts. BM25 ranks unique article versions;
child hits are not used to inflate counts. `staging_manifest.json` records
source, code, configuration, and output hashes. Final files are replaced only
after complete `.part` writes. `owner_review_priority.csv` is an optional
review aid containing 20 employment seeds, 15 central dependencies, 10
quarantined dependencies, and 5 dangling targets, each with a source locator,
review task, pass criteria, and failure action. Per-record approval is not a
development gate.

The separate narrow employment prototype is built in this order so the central
and data-quality checks happen before parsing and only eligible topical
articles reach the embedding builder:

```powershell
.\.venv\Scripts\python.exe scripts/core_article_stage.py
.\.venv\Scripts\python.exe scripts/curate_core_corpus.py
.\.venv\Scripts\python.exe scripts/core_corpus_embeddings.py --articles data/curated/8977887f17be2defae4c5171d55562e1cde7d695/core-employment-portfolio-v1/articles.jsonl --corpus-manifest data/curated/8977887f17be2defae4c5171d55562e1cde7d695/core-employment-portfolio-v1/corpus_manifest.json --model data/models/e5-small --output data/embeddings/core-employment-portfolio-v1-e5-small-provisional-v4
docker compose -f docker-compose.qdrant.yml up -d
.\.venv\Scripts\python.exe scripts/import_core_corpus_qdrant.py --artifact data/embeddings/core-employment-portfolio-v1-e5-small-provisional-v4 --corpus-manifest data/curated/8977887f17be2defae4c5171d55562e1cde7d695/core-employment-portfolio-v1/corpus_manifest.json --write-local-qdrant
```

The core app requires that local Qdrant collection and fails closed if its
artifact digest, vector size, or point count does not match. It never activates
an alias. Provisional replies are exact source extracts only for explicit
source-text requests. Applicability, ambiguous permission, current validity,
amendments, and date-specific questions abstain or remain unverified.

The frozen 19-case snapshot behavior evaluation, recorded before the narrow
overtime-topic correction, retrieved relevant evidence
for all 17 answerable cases; its deterministic reference selector produced 13
exact answer citations, and the citation contract passed all 19 cases. The
selector receives reference labels and is not a language model. These results
measure retrieval reach and contract handling, not model quality, legal
correctness, or current validity (`data/benchmarks/snapshot_excerpt_natural_questions_v2_results.json`).
The report remains unchanged and was not rerun after the correction. Inspection
found two safe abstentions where overtime queries failed the working-time topic
gate despite references tagged `working_time`; the matcher now recognizes the
narrow phrase `làm thêm giờ`. The inspected held-out wording is no longer
untouched evaluation evidence.
The corpus uses 85 real E5 vectors in local Qdrant, with 68 article versions
eligible for the index.

An earlier one-call real Groq route attempt at commit `8ef2ca2` returned HTTP
400 `invalid_request_error` / `json_validate_failed` after real retrieval. Its
empty `failed_generation` field's local `invalid` verdict does not establish
what the model generated. On 2026-10-02, after adding low reasoning effort,
temperature zero, and more explicit quote/ID instructions, one real route call
returned HTTP 200 with a provisional answer and one validator-approved,
191-character exact citation plus an uncertainty caveat. The citation hash
matches the pinned Article 24 source span. This verifies one case only; answer
relevance still requires human review, and it does not measure repeatability or
legal correctness. Groq remains disabled by default. The success report and
earlier failure evidence are
`data/logs/groq_fixed_route_20261002.json`,
`data/logs/groq_single_route_smoke_20261001_v4.json` and
`data/logs/groq_provider_issue_packet_20261001.json`.

A bounded four-topic smoke recorded these outcomes: probation produced a
validator-approved citation but selected a 445-character span instead of the
frozen 147-character sentence; contracts passed with the exact 191-character
sentence; working time returned a 674-character quote rejected by the route's
500-character guard; and leave returned `answer` instead of the required
`provisional` state, so the route withheld it. The leave citation covered but
did not exactly match the frozen 183-character sentence. The first leave UI
submission hit a temporary harness error before provider transport; the final
leave submission used the fourth and last live call. No retries or paid
fallback were used. The redacted checkpoint is
`data/benchmarks/groq_four_topic_continuation_20261002.json`. See
[`docs/handoff-readiness.md`](docs/handoff-readiness.md) for the portfolio run
steps, validity caveats, and measured limits.

The historical 500-character route cap was raised to 1,000 characters on
2026-10-05 for the experimental snapshot excerpt path. This accommodates longer
official-source passages; it does not relax exact quote/claim validation or
change the outcomes recorded by earlier runs.

On 2026-10-01, a local browser smoke verified the core Vietnamese UI with the
pinned corpus and `GROQ_ENABLED=false`: the corpus revision and unknown-validity
warning loaded; an explicit Article 24 source-text request displayed the exact
extract, source/version citation, and caveat; and an applicability question
showed a safe abstention. The experimental ordinary-question path showed a
Vietnamese unavailable state while Groq was disabled. A separate injected
provider sequence first rendered a valid cited excerpt and then failed; the UI
cleared the previous answer and source. Retrieval used local E5/Qdrant; the
first two flows needed no provider, the experimental ordinary-question flow
used the local disabled provider, and the answer-then-failure sequence used a
mock provider. This was a manual browser check, not legal-quality evidence or
an automated regression test; no UI wiring defect was found.

Remaining implementation milestones:

- [x] Pinned snapshot, strict central-only audit, provenance and ledgers.
- [x] Provisional employment seed/dependency review packet and article parser.
- [x] Offline article-level BM25 baseline with tests.
- [x] Qdrant REST/E5 contract tests with synthetic points; live Qdrant integration is opt-in and the real model smoke is recorded below.
- [x] Minimal FastAPI demo with mocked Vietnamese grounded answers, explicit clarification/unavailable states, and strict citation validation.
- [x] Pinned local Transformers E5 loader contract with checksummed local artifacts and a real CPU smoke.
- [x] Deterministic core article staging reuses active staged parses and parses only the audited duplicate-original document missing from that build.
- [x] Core retrieval is limited to probation, contracts, working time, leave, and the explicit dependency allowlist; 68 of 365 article versions are indexed.
- [x] Pinned CPU multilingual-E5-small generated 85 checksum-manifested vectors for the inactive topical corpus.
- [x] Imported those 85 vectors into an artifact-digest-versioned local Qdrant collection and verified a bounded local search; alias remains inactive.
- [x] Hybrid retrieval, CPU reranker, evaluation, and privacy-safe logging contracts with injected offline tests. Synthetic branches are not quality measurements.
- [x] Offline GitHub Actions unit-test workflow; live Qdrant remains opt-in.
- [x] Synthetic API/provider bridge and privacy-safe trace contract, including disabled-by-default mocked direct Groq transport.
- [x] Synthetic manifest/shard import rehearsal with pre-write compatibility checks and no alias activation.
- [x] App uses local BM25 plus the validated Qdrant collection; `/api/search` uses configured retrieval.
- [x] Provisional output is deterministic extractive text for explicit source-text requests; applicability, ambiguous permission, date, and amendment-status questions abstain. No provider call is used for provisional answers.
- [x] Ran a bounded nine-query manually labeled retrieval comparison with the pinned CPU reranker; the report retains pre-rerank and post-rerank results and is explicitly exploratory.
- [x] Superseded leaked held-out v1 without rewriting its labels; froze and evaluated v2 after family/reference overlap checks. Results include BM25/dense/RRF and rerank depths 5/10/20 with Recall/MRR, p50/p95 latency, and peak memory. Keep interactive retrieval pre-rerank due to CPU latency; current validity and legal correctness remain unverified.
- [ ] Expand the corrected exploratory set before broad retrieval claims and run hosted CI.

See [handoff readiness](docs/handoff-readiness.md) for stage-by-stage evidence,
runnable commands, artifact paths, and owner/resource gates.
