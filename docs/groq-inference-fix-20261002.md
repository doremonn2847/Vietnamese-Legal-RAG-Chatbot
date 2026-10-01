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
