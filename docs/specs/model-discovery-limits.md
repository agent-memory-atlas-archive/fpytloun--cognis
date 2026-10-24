# Optional model capacity metadata

The authenticated standard `GET /v1/models` and
`GET /v1/models/{model_id:path}` responses retain `id`, `object`, `created`,
`owned_by` and `cognis.operations`. Slash-containing route/provider IDs work.
Retrieval accepts optional `operation=chat|embeddings|systemone` to resolve the
same operation-specific route used for inference.

Model objects additionally expose `context_window`, `max_input_tokens` and
`max_output_tokens` as positive integers or explicit `null`. Only limits with
provenance in provider-aware `ModelInfo.provider_metadata.field_sources` are
exported; synthetic `ModelInfo` defaults are not advertised capacity.

`resolution_fingerprint` is an opaque process-keyed HMAC of resolved model,
provider, operation and public capacity. It changes with routing/capacity and
process restart, exposes no owner, credentials or internal route configuration,
and is not an authentication token. Consumers should cache briefly and treat
missing metadata as unknown. Metadata lookup errors return unknown limits, not
invented large values. Existing authorization and owner/provider isolation apply
before lookup; generation behavior, output reserves and operation policy are
unchanged.
