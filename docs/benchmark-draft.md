# Draft Vietnamese employment benchmark

This is an engineering draft, not legal ground truth. Every case starts with
`reference_status: unreviewed` and no relevant article IDs. It must not be used
to measure legal correctness until a reviewer records authoritative source
versions, exact article IDs, quote spans, requested-date applicability, and the
expected answer state.

Annotators keep `dev` cases for iteration and do not inspect `heldout` cases
while changing retrieval or prompts. For each case, label one family: answerable,
ambiguous, temporal, conflicting, unanswerable, or adversarial. `family` is an
answer-behavior category; `scenario_family_id` groups comparable fact patterns.
Every reviewed record must carry document version, article ID, exact quote/span,
and requested-date applicability fields before a measurement run can construct a
retriever. Record only evidence that
supports the requested date and mark conflicting or insufficient evidence rather
than forcing an answer. The present employment scope remains probation,
contracts, working time, and leave; insurance/public employment/special
categories are out of scope.

## Bounded retrieval engineering check

`data/benchmarks/vietnamese_employment_retrieval_v1.json` is a separate nine-
query dev set. Its manually chosen relevant article IDs follow the curated
section headings; they are not an independent legal review or an applicability
label. `scripts/evaluate_core_reranker.py` compares the real local BM25 + exact
vector + RRF baseline with the pinned BGE cross-encoder on at most 20 fused
candidates and retains the top article-ID rankings and Recall/MRR metrics (not
raw per-candidate model scores). Run `scripts/fetch_reranker.py`
once to fetch the immutable CPU model, then use the command in
`docs/handoff-readiness.md`. Results are exploratory because this small set has
no held-out cases; they do not establish legal correctness or justify activating
the corpus.

## Held-out engineering sets

`vietnamese_employment_heldout_v1.json` and its result are historical only.
`vietnamese_employment_heldout_v1_status.json` marks them superseded and records
the hashes and leakage reason: two leave cases shared development article IDs
and near-identical fact patterns. Do not report v1 metrics as held-out evidence.

`vietnamese_employment_heldout_v2.json` was frozen in commit `3e9285e`. It
replaces the overlapping cases and is validated against both development
scenario families and relevant article IDs before any model loads. It has six
answerable heading-level cases, one multi-target ambiguous case, and one
out-of-scope negative case. The versioned result file reports BM25, dense, RRF,
and rerank candidate depths 5/10/20, per-query rankings and Recall/MRR,
p50/p95 latency, and process peak resident memory. The negative case can still
receive retrieval candidates; ranking is not an abstention decision.

On the v2 run, positive-case Recall@5/MRR@5 were BM25 0.714/0.529, dense
1.0/0.719, and RRF 0.857/0.619. Reranking at depth 5 reached 0.857/0.857;
depths 10 and 20 reached 1.0/1.0. Reranker p50/p95 was 7.8/10.4 s at depth 5,
15.2/16.6 s at depth 10, and 29.2/34.8 s at depth 20. Retrieval p50/p95 was
79/397 ms. Peak process working set was 0.90 GB after model load and 2.04 GB
after evaluation. Keep interactive retrieval pre-rerank given that cost.

The labels are exploratory section-heading relevance labels only, not legal
validity review; the eight cases do not support broad quality claims.
