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

## Frozen held-out engineering set

`data/benchmarks/vietnamese_employment_heldout_v1.json` was frozen in commit
`f1e4dca` before the multi-depth evaluator was added. It has six answerable
heading-level cases, one multi-target ambiguous case, and one out-of-scope
negative case; its scenario families do not overlap the dev set. The result at
`data/benchmarks/vietnamese_employment_heldout_v1_results.json` reports BM25,
dense, RRF, and rerank candidate depths 5/10/20, plus per-query rankings,
Recall/MRR, p50/p95 latency, and process peak resident memory. The negative case
still receives retrieval candidates, which is a useful limit of ranking-only
evaluation and not a legal-answer decision.

The pinned CPU BGE reranker raised held-out MRR@5 from 0.786 for RRF to 1.0 at
all three candidate depths; recall@5 was 1.0 across answerable and ambiguous
cases. Median rerank latency ranged from 7.2 seconds at depth 5 to 28.6 seconds
at depth 20. Given that cost and the tiny manually labeled set, the interactive
retriever remains pre-rerank. These measurements are exploratory heading-level
retrieval evidence only, not legal validation.
