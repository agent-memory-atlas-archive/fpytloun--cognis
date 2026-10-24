# Inference accounting

`inference_request` is one **request-level** observation, not a billing ledger.
Its server `request_id` also appears as `llm_request_id` for joining existing chat
provider/recovery observations. Do not sum request and provider observations as
independent spend. `attempt_accounting=incomplete` explicitly means hidden retries,
failed attempts and provider-side work may be unaccounted. Client attempts can
be grouped by the optional operation ID, but are not deduplicated paid work.

Optional `X-Cognis-Inference-` headers carry `Operation`, `Operation-ID`,
`Session-ID`, `Task-ID` and `Client-Request-ID`. Operations are restricted to:
`summary_window`, `compaction`, `l3`, `intention`, `source_context`, `policy_compile`,
`policy_assess`, `alignment`, `evaluation`, `judge`. IDs permit 1–128 ASCII
letters, digits, underscores, dots, colons and hyphens. Invalid values are ignored.
These are untrusted client observations, never proof of ownership or authority.
They do not affect authentication, evaluation, affinity or provider parameters.
Absent headers remain supported; older servers ignore these optional headers.
Never put content or secrets in metadata.

Logs use `input_tokens`, `output_tokens`, `total_tokens`, `cached_input_tokens`,
`cache_write_tokens`, `cache_creation_input_tokens` and `reasoning_tokens`.
Cached/reasoning counts are subsets where the provider contract defines them;
do not add them to input/output totals. Global content redaction is unchanged.
Missing primary counts are null. `usage_status` is `unknown` without usage,
`reported` on success with usage and `partial` when usage survived a failed or
cancelled request. Failed requests with unknown usage are **not proven free**.

Metrics retain existing token-kind labels and add bounded `requested_route`:
registered system route names, `named`, or `direct`. Request/operation/session/task
IDs are log-only. Update metric selectors for this additional dimension; old and
new labelsets can coexist during rollout.

`estimated_cost_usd` is nullable, **not invoiced/billed USD**. It uses the existing
resolved model's price metadata, accompanied by `pricing.rates`, `pricing.sources`
and `cost_calculation_version`. Input/output prices must be known; cached input
requires a known cache-read price. The supported calculation subtracts cached
input before pricing it separately, and never adds reasoning to output again.
Unknown prices, native additive cache accounting, cache writes, partial usage or
a changed fallback target without matching price provenance yield unknown cost.
Explicit zero prices are distinct from absent prices. No new price catalog,
service, database, invoice reconciliation or provider calls are introduced.
