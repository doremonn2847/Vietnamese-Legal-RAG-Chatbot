# Vietnamese Legal RAG — corpus audit

This workspace contains the pinned corpus audit, provisional employment
staging/article parsing, offline retrieval contracts, and a synthetic FastAPI
demo. It does not activate the real legal corpus or claim model quality from
synthetic data.

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
```

Downloads only `metadata`, `content`, `relationships`, and the dataset card at
the pinned revision. Existing source files must match their expected hashes;
they are never silently overwritten. Downloads use validated byte ranges and
verify final upstream SHA-256 hashes. `legacy_*` is excluded.

Originals and their provenance manifest live in `data/raw/<revision>/`.
Reproducible audit ledgers and checksums live in `data/audit/<revision>/`.
Both are excluded from Git. No curated searchable release is created.

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

The current run found 527 central employment seed documents, 3,789
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
after complete `.part` writes. `owner_review_priority.csv` is the small manual
packet: 20 employment seeds, 15 central dependencies, 10 quarantined
dependencies, and 5 dangling targets, each with a source locator, review task,
pass criteria, and failure action.

Remaining implementation milestones:

- [x] Pinned snapshot, strict central-only audit, provenance and ledgers.
- [x] Provisional employment seed/dependency review packet and article parser.
- [x] Offline article-level BM25 baseline with tests.
- [x] Qdrant REST/E5 contract tests with synthetic points; live Qdrant integration is opt-in and model execution remains unverified.
- [x] Minimal FastAPI demo with mocked Vietnamese grounded answers, explicit clarification/unavailable states, and strict citation validation.
- [x] Pinned local Transformers E5 loader contract; model loading remains opt-in and requires local artifacts.
- [x] Hybrid retrieval, CPU reranker, evaluation, and privacy-safe logging contracts with injected offline tests. Synthetic branches are not quality measurements.
- [x] Offline GitHub Actions unit-test workflow; live Qdrant remains opt-in.
- [x] Synthetic API/provider bridge and privacy-safe trace contract, including disabled-by-default mocked 9Router transport.
- [x] Synthetic manifest/shard import rehearsal with pre-write compatibility checks and no alias activation.
- [ ] Owner review of employment relevance, duplicates, dependencies, and validity.
- [ ] Real E5 document/query execution, verified artifact import, Qdrant activation, and measured hybrid/reranker quality.
- [ ] Connect the app to real reviewed retrieval and a user-configured provider; run hosted CI and reviewed benchmark evaluation.

See [handoff readiness](docs/handoff-readiness.md) for stage-by-stage evidence,
runnable commands, artifact paths, and owner/resource gates.
