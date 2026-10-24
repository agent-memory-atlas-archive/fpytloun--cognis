# Evaluation size fitting and response diagnostics

## Confirmed local request-size defect

The tool router clips individual values but does not bound the final JSON
object. A synthetic tool description and twelve schema descriptions, each
within their existing raw-character limits, exceed Intaris's 8192-character
compact/ASCII-escaped serialized context limit. Unicode and JSON escaping amplify
the mismatch. This reproduces a request-validation defect, not a historical
integration failure.

The final Intaris provider boundary fits only known explanatory description
fields, after the router adds the minimum outcome and approval receipt. It uses
the receiver's JSON size convention and visible middle-truncation markers.
Reductions are shared among descriptions; head/tail text is retained where space
permits.

Protected identities, source/operation descriptors, schema hashes, modes,
read-only requirements, policy/receipt fields, unknown context fields, and
complete action arguments are unchanged. Too-large protected context fails
closed before HTTP dispatch, reporting only numeric size/limit metadata.
Genuine action arguments are never shrunk to evade a server limit.

Ownership: pure per-call provider projection; no shared state, cache mutation,
I/O, lock, transaction or cancellation work. Existing dispatch/retry owners
remain. No public API/schema or serialized-size limit changes.

## Response diagnostic boundaries

A short provider failure does not establish a proxy timeout. An
`OtherError/unknown` result without an upstream HTTP status or code cannot
identify the underlying exception. Inspect the content-free diagnostic category
before changing timeout or model configuration.

Typed provider-response validation was an observability gap:
ValueError/Pydantic failures mapped to `OtherError/unknown`. Existing validation
rejections now use content-free typed exceptions with finite diagnostic codes.
Validation is unchanged; no answer is accepted, normalized, retried by the proxy
or redirected to fallback to suppress errors. Confirm observed exception
categories through separately authorized live checks. This change does not
alter timeouts or model configuration.

Do not replay, cancel or mutate running tasks solely to collect diagnostics.
Live inference and production rollout require separate authorization.

## Verification

Checks cover native inference API rejection, the typed adapter, final context
fitting, protected outcome acknowledgements, router semantics, Unicode, emoji,
quotes/backslashes/newlines, immutable objects/arguments and protected overflow.

```bash
uv run --python 3.12 --all-packages --extra dev --frozen pytest -q tests/unit/test_intaris_context_budget.py tests/unit/test_systemone_response_diagnostics.py tests/unit/test_inference_api.py tests/unit/test_guardrails_context.py tests/unit/test_intaris_evaluation.py tests/unit/test_tool_router.py --tb=short
```

No live integration replay or broad provider benchmark was run.

Final results:

- 278 passed, 1 skipped for the affected regression selection.
- Ruff check/format and scoped controller/common mypy passed.
- The isolated package matrix was attempted but timed out at 240 seconds after
  ten completed checks. It is not reported as passing.
- Offline cross-repository validation against the receiver's
  `EvaluateRequest` schema reproduced `context_too_large` at 29312 serialized
  characters. The fitted object used 8191 characters and passed that receiver
  schema, with read-only requirements and genuine action arguments unchanged.

The last cross-check uses only synthetic metadata and the local Intaris source;
it does not send an evaluator request or execute a tool.
