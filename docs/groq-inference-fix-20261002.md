# Groq inference investigation — 2026-10-02

The unchanged production request reproduced upstream HTTP 400 with
`json_validate_failed`. Groq's message was “Failed to validate JSON. Please
adjust your prompt. See 'failed_generation' for more details.” No local answer
conversion runs on that response. The earlier coarse error classification did
not identify the cause.

A controlled request with only `reasoning_effort=low` returned JSON, then failed
local citation validation. A subsequent captured response invented claim
evidence ID `e1` and paraphrased the claim. The local validator correctly rejected
it. Explicit field instructions fixed those errors in a candidate request, but
the output changed source whitespace. Adding `temperature=0` produced an exact
quote that passed the unchanged validator. These observations support the
request/prompt fix; they do not establish Groq's internal reason for the 400 or
guarantee deterministic generation.

The reference implementation at
https://github.com/AChingNoLu/Chatbot/blob/mainV3/llm/groq.py uses the same
`openai/gpt-oss-20b` model with strict JSON schema, low reasoning effort and
temperature zero. We reused those request settings, not its SDK or error logging.
Our prompt now explicitly requires full evidence IDs, verbatim provisional
claims and text assembled from claims. Schema and citation validation are unchanged.

Verification:

- Request/prompt regression assertions failed before the patch and passed after.
- `python -m unittest discover -s scripts`: 134 tests run, 133 passed, 1 skipped.
- Real production-route smoke: the question “Thỏa thuận thử việc có thể ghi nhận
  ở đâu?” returned HTTP 200, provisional state, one valid 191-character citation,
  and a caveat. End-to-end latency was 5704.87 ms, including 4710.84 ms dense retrieval.
- The insurance question abstained locally with no additional provider call.
- Six diagnostic/verification inference calls in total; no automatic retries or
  paid fallback. The final smoke alone used one call and 1795 tokens.

Local reports are ignored under `data/logs/`: `groq_debug_20261002.json`,
`groq_prompt_probe_20261002.json`, `groq_prompt_temperature_probe_20261002.json`,
and `groq_fixed_route_20261002.json`. The intermediate low-reasoning response was
inspected in tool output; its attempted report serialization failed on a deque,
so no report from that intermediate call is claimed.

This is a verified repair of one reported case, not a legal-correctness evaluation
or a reliability estimate. Frozen benchmark labels and results were not changed.

## Snapshot-only state guard follow-up

The later four-topic live continuation exhausted its four-call budget. Its final
leave response used state `answer` rather than the required `provisional`; the
experimental route withheld it. Commit `5d4687c` addresses this failure mode
offline by deep-copying the request schema only for undated requests whose
nonempty selected evidence is entirely snapshot-eligible, then removing
`answer` and `partial` from that request's allowed states. The shared schema is
unchanged. Dated, empty, and mixed-evidence requests keep the shared schema,
and the route guard still independently rejects a wrong state.

Request-capture tests inject all four evidence/date combinations, and a route
test injects a provider that returns `answer`. Local verification passed 135
tests with 1 skipped; hosted Actions passed at `5d4687c`. No live generation
was rerun at that point because the four-call budget was exhausted. The previous
live wrong-state response remains evidence that the UI withheld the output.
The overlong quote and non-exact span selection observed in that continuation
remain unresolved reliability gaps. No evaluation labels or benchmark outputs
were changed.

## Additive live schema check — 2026-10-04

After the local Qdrant collection and Groq configuration were restored, one
owner-authorized request used the frozen leave question and real E5/Qdrant
production route. The strict request-schema and system-contract hashes matched
offline fingerprints from `5d4687c`; its state enum excluded `answer` and
`partial`. Groq returned HTTP 200 and a `provisional` response, showing
compatibility for this request. The app then returned HTTP 502/unavailable
because local citation validation failed. The quote hash and 183-character
length matched the frozen sentence, but answer text was 90 characters and the
raw span was `0..200`. `GroqProvider` may repair offsets for a unique quote, so
that raw span does not establish which validator predicate failed. The route
exposed only `invalid_provider_output`; claim text and detailed predicates were
not retained. No raw answer text was saved.

This initial check allowed two actual transports; one was used. The
working-time case was not sent in that run because the stop-on-first-unexpected-result rule
applied. The earlier four-call run remains a separate exhausted budget. No
retries, paid fallback, prompt/schema changes, or browser UI run occurred. See
the sanitized, frozen-set-hash-bound report
`data/benchmarks/groq_snapshot_schema_acceptance_20261004.json`. The local
suite was not rerun; the previously verified 135 passed/1 skipped suite and
hosted CI remain the implementation baseline.

### Offline display-normalization follow-up

The reported 90-character display versus 183-character citation motivated a
narrow route-side repair in the experimental snapshot excerpt path. When the
answer is provisional, has nonempty display text, and the validator reports
exactly `unvalidated_text` with no unknown IDs or uncited claims, the app joins
the existing claim text to form a candidate display. It adopts that candidate
only after full citation validation succeeds. It does not edit claims,
citations, source text, or validator rules. The prior blank-display repair is
preserved. Ordinary dated behavior remains covered by the existing tests.

The focused regression passes for an exact claim with shortened display and
still rejects a paraphrased claim and an incorrect document version. The full
offline suite passes: 136 tests run, 135 passed, 1 skipped. The sanitized live
report records this offline follow-up; the live failure observation remains
unchanged and is not claimed as repaired. No live request was sent during this
patch. After Design passed the patch, the one remaining owner-authorized
working-time request was sent once; its result is recorded below and in
`data/benchmarks/groq_snapshot_working_time_followup_20261005.json`.

### Working-time follow-up — 2026-10-05

After Design review, the frozen working-time question reached Groq once. The
upstream returned HTTP 200 with state `provisional`. The provider returned a
674-character citation, exceeding the experimental excerpt path's existing
500-character limit. The route returned HTTP 502/unavailable at that guard,
before route citation validation. Sanitized in-memory validation diagnostics
also showed claim-to-quote mismatches (`c1`, `c2`) and `unvalidated_text`; the
answer display was 441 characters and the two claims were 95 and 118
characters. The provider quote did not match the frozen 95-character sentence.
No answer text was retained.

This was the one unused transport from the separately authorized two-call
check; together with the earlier leave request, the cap of two was reached.
The original four-call budget remains separately exhausted. No retry, paid
fallback, prompt change, or browser UI run occurred. The route safely withheld
this response; the known oversized-quote failure remains unresolved.

### Experimental quote ceiling update — 2026-10-05

The experimental snapshot excerpt limit is now 1,000 characters in both the
route guard and Groq instructions, and the bounded smoke check uses the same
ceiling. This accommodates longer passages from official legal documents. The
validator still requires the claim to equal an exact cited canonical quote,
and displayed text to equal joined claim text. The captured 674-character
working-time response still fails those equality checks; raising the ceiling
does not retroactively make that response valid. No live request was made for
this update. Regression tests accept exact 674- and 1,000-character quotes,
reject a 1,001-character quote, and assert the provider prompt's 1,000-character
contract. The full offline suite passed 138 tests (137 passed, 1 skipped).
