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
