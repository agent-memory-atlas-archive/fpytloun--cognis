# Inference API

Cognis exposes `/v1/models`, `/v1/chat/completions`, `/v1/embeddings`, and
`/v1/systemone`.
Chat supports streaming, tool definitions, and structured output when supported
by the configured provider. This is inference, not agent execution: it does not
execute tools, inject memories, or recursively invoke Intaris. `/v1/responses`,
audio/image endpoints, and token-array embedding inputs are not implemented.
Unsupported request fields are rejected rather than silently ignored.

Upstream request/schema failures return HTTP 422 with content-free metadata:
`{"error":{"code":"upstream_json_validate_failed","category":"request"}}`.
Other recognized request codes use the same `upstream_` prefix. Unknown request
codes become `upstream_request_error`. Outages and timeouts retain HTTP 502/503.
For streams whose headers were already sent, the same sanitized error body is
sent as an SSE event before `[DONE]`.

## External clients

### Named routes and recovery

Administrators configure named routes in **Settings → Inference routes**.
In agent defaults and runtime profiles, select **Cognis (custom routes)** and
the route model. Thinking-effort choices are shared values supported by every
target, and fast mode is available only if every target supports it. Missing
target metadata leaves only inheritance and provider-default controls available.

Use `cognis/<name>` as the model reference, or assign it to an existing system
role such as `routes/intaris_evaluation`. Each target specifies a provider,
model, and priority. Lower priorities are preferred; equal-priority targets
balance new sessions. Active sessions retain their selected target. After
inactivity, a fallback session can probe a higher-priority target once. Eligibility
uses the shorter of its effective cache lifetime and
`session.route_failback_idle_seconds` (default 3600). Unknown cache lifetimes use
the idle timeout alone. Cache lifetime is an estimate from request markers, not
a provider-confirmed expiry. Existing quota/circuit blocks and native-history
compatibility checks still apply. A failed probe leaves the working fallback
available, and completion starts a fresh idle window. Redis serializes probe
admission across replicas; without Redis, coordination is local.

Claude cache TTLs are configured in each provider's model editor, not system
settings. `primary_cache_ttl` defaults to `1h` for primary-agent conversations,
including managed conversations. `auxiliary_cache_ttl` defaults to `5m` for task
steps (even with primary agents), secondary delegates, compaction, background jobs
and hooks. The serving target's settings apply after fallback. Backend capability
limits take precedence: unsupported extended TTLs use `5m`.

The retired `session.anthropic_cache_ttl` value is no longer exposed or consumed.
Existing models without explicit per-model settings adopt these defaults; the old
global `5m` value is not copied into primary settings. No history or credentials
are migrated.

Search the target picker by model or provider. Selecting the first target fills
an empty route name with its model ID (without the provider prefix); an entered
name is never overwritten. Unsupported name characters become hyphens.

Routes created with only shared providers are global. If any target uses your
personal provider, the route is private to you. Private credentials are never
published through a global route. Existing routes retain their ownership when
edited; system roles and companion clients require global routes.

Chat clients can send `X-Cognis-Session-ID` to retain affinity across requests.
The identity is scoped to the authenticated client. Without this header,
chat requests share the client's default affinity. This controls target affinity, not a
guarantee of an upstream prompt-cache hit.

Direct targets and named routes use the same bounded recovery executor.
Recoverable failures can retry before output is committed; a stream never
silently switches targets after semantic output. Route recovery settings bound
retries, target switches, recovery windows, and request deadlines. Compatibility
repairs consume the same attempt allowance as ordinary requests.
When every compatible target is rate-limited or temporarily unavailable,
recovery waits for the earliest eligible target, not necessarily the preferred
target. Each target must satisfy all of its account, model, and circuit blocks.
Known-reset retries retain their physical-attempt and route-switch budgets.
If the earliest reset is outside the request deadline, the call fails with the
upstream category and the route's remaining retry time instead of a generic
unavailability error. Shared circuit state retains only the failure category,
not provider messages or request contents.

Fallback targets must support the request's tools, structured output, and
attachments. Native continuation state can prevent cross-provider fallback.
Native Anthropic history permits configured account fallback on the official
Messages endpoint only when the model, auth policy, execution location, model
capabilities, thinking configuration, and frozen tool bundle match. Recovery
preserves signed blocks and tool IDs and validates the active continuation
before rebinding its account metadata in a request-local copy. Other native
protocols and incompatible targets remain blocked. A rejected fallback does
not replace an earlier upstream rate-limit or outage error.
Multi-target embedding routes are rejected: equal dimensions do not prove
equivalent embedding spaces, and companion embedding pins remain enforced.

Redis coordinates availability and half-open trials when configured. A Redis
outage does not silently fall back to per-process state. Deployments without
Redis use local availability state and must remain single-replica.

### System One typed decisions

`POST /v1/systemone` accepts TypeSafe-compatible `model`, `state`, and typed
`questions`. Models can be explicit `providers/<provider-id>/<model-id>`
references, or `routes/intaris_evaluation`. The route is shared with chat
evaluation, but requests must match its model capability: chat cannot invoke
Jev, and System One cannot invoke a chat model. Jev is not eligible for shared
chat defaults, judge, analysis, embedding, or Mnemory routes.

```json
{
  "model": "routes/intaris_evaluation",
  "state": {"tool": "read", "path": "src/main.py"},
  "questions": {
    "aligned": {"type": "noul", "instructions": "Is this action aligned with a read-only code review?"}
  }
}
```

Responses retain the actual provider model, typed `answers`, probabilities,
confidence, usage, and optional provider metadata without chat emulation.
Streaming, sampling, thinking effort, and chat tools are not accepted.
Invalid or incomplete provider answers fail closed with a sanitized error;
requests are not retried or redirected to text-generation fallback models.
The `inference_provider_error` log retains content-free correlation metadata.
Rejected typed answers use `exception_class=SystemOneResponseError`,
`error_category=response_validation`, and a bounded `upstream_code`:
`systemone_response_schema`, `systemone_answer_set`, `systemone_answer_type`,
`systemone_probability_sum`, `systemone_choice_criteria`, or
`systemone_score_criteria`. These distinguish proxy response validation from a
timeout or an upstream HTTP failure; they do not include prompts or responses.
The proxy still rejects the answer. It does not normalize probabilities, invent
missing choices, or downgrade validation to obtain a decision.
Probability sums use the supported native Jev client tolerance: absolute
deviation at most `0.02` from one. Larger deviations, out-of-range values,
incorrect/missing criteria and malformed answers still fail closed. Accepted
probabilities, choices and confidence are returned unchanged.
The existing body, identity, concurrency, ownership, and service-route limits
apply. Restricted inference API keys need the `systemone` operation; companion
JWTs remain confined to their service's global routes.

### Switching the Intaris evaluator

With an Intaris build that supports `EVALUATOR_BACKEND=auto` (the default when
`COGNIS_INFERENCE_URL` is set and `EVALUATOR_BACKEND` is unset), the evaluator
follows the model selected in Cognis's **Intaris evaluation** override:

- Select a Jev (System One) model: `routes/intaris_evaluation` lists
  `systemone`, and Intaris uses its Jev evaluator.
- Select a chat model: the route lists only `chat`, and Intaris uses its LLM
  evaluator.

No Intaris environment change or restart is needed. Intaris reads the route
metadata from `GET /v1/models` and caches it for about 60 seconds, so a switch
takes effect within that window. During the switch, evaluations that already
selected the old backend (normally one, more under concurrent load) fail closed
with `invalid_model` (protocol mismatch, rejected before upstream dispatch);
Intaris then refreshes the metadata and uses the new backend on later calls. Judge and analysis routes always remain chat. Intaris keeps reading
its companion JWT on each request; TypeSafe/OpenRouter keys stay in Cognis.
Jev remains an experimental evaluator; this does not change Intaris's
confidence thresholds or decision policy.

An explicit `EVALUATOR_BACKEND=llm` or `jev` pins the Intaris backend. A
mismatched route then fails each evaluation closed with a clear error instead
of switching. The local stack pins `llm` by default for compatibility with
older Intaris images; set `INTARIS_EVALUATOR_BACKEND=auto` with an Intaris
image that supports it.

Troubleshooting: `GET /api/v1/config` in Intaris reports the evaluator mode,
the active backend, and any backend error. If Intaris logs that route metadata is absent, Cognis predates the
`cognis.operations` field and Intaris stays on the LLM evaluator. If it reports
malformed or unknown metadata, evaluations fail closed until the route lists
`chat` or `systemone`.

### OpenAI-compatible clients

Set an OpenAI client's base URL to `https://your-cognis-host/v1`. Authenticate
using a Cognis access JWT or Cognis API key in `Authorization: Bearer`.
Use the normal login flow for username/password credentials. Do not send
upstream provider secrets to this endpoint.

`GET /v1/models` lists only enabled, usable models and configured routing aliases
visible to the authenticated user:

- `providers/<provider-id>/<model-id>` selects a concrete model.
- `routes/<routing-name>` selects Cognis routing.

Each entry also has `"cognis": {"operations": [...]}`. It lists the operations
(`chat`, `embeddings`, `systemone`) that the model or route resolves for the
authenticated caller, using the same resolution and authorization as an
inference request. It never contains URLs, provider names, or credentials.
Clients can use it to choose a protocol without inferring it from model names.

External clients can use global providers and their own private providers,
not another user's private provider. Aliases resolve on each request.
Existing API keys work; for a dedicated client, create a separately named key
with `scopes.inference_only: true`, `scopes.models` containing exact allowed
model/route identifiers, and `scopes.operations` containing `chat` and/or
`embeddings`. An omitted list is unrestricted; an empty list denies all.
Revoke the key to stop new requests immediately.

## Managed Intaris and Mnemory

Configure **Settings → Routing → Companion services** as an administrator:

1. Lite: frequent evaluation/extraction/retrieval.
2. Smart: judging, analysis, consolidation, maintenance.
3. Embedding: a model matching the companion vector dimensions.

Lite and Smart each have a **Thinking effort** selector populated from the
selected model's supported levels. Advanced task overrides can change the model,
effort, or both independently. An omitted model inherits its Lite/Smart parent;
an omitted effort inherits the parent's effort even when the model is overridden.
Choose **Provider default (ignore shared effort)** to stop effort inheritance.
**Disabled** (`none`) explicitly turns off reasoning when the model supports it;
it is not the same as omitting the parameter.

On chat requests, explicit client `reasoning_effort` wins over the task and
Lite/Smart defaults. Omitted/null effort uses routing. Explicit `default` requests
provider defaults (Cognis removes this control value before calling upstream).
Settings save rejects unsupported effective effort/model combinations. Changing
a model in the form preserves the selected effort so users can review it rather
than silently losing their configuration.

Managed Intaris/Mnemory clients omit their standalone implicit low/medium
defaults. Explicit companion environment settings remain client overrides; leave
them unset to centralize reasoning in Cognis. This applies to foreground calls,
analysis, retrieval, consolidation and maintenance.

All selections and advanced overrides must use enabled **global** providers.
Each service JWT permits only that service's routing aliases. It cannot select
concrete models, read private providers, impersonate a user, or access ordinary
Cognis APIs. These are installation-wide service identities; user-specific
providers are not used for shared companion jobs.

For managed Compose, credential wiring is automatic. For a separate deployment:

```text
COGNIS_INFERENCE_URL=https://your-cognis-host/v1
COGNIS_INFERENCE_TOKEN_FILE=/run/cognis-inference/token.jwt
```

An administrator obtains the appropriate credential from
`POST /api/v1/inference/companions/intaris/token` or
`POST /api/v1/inference/companions/mnemory/token`. Store the returned JWT in
the configured file with restrictive permissions. Creating a replacement
increments its persisted version, invalidating earlier tokens.
`DELETE` on the same URL revokes that service identity.
Like executor installation credentials, these JWTs do not expire; protect them
as secrets and rotate/revoke them deliberately. Never log or commit them.
The clients reread the file on every call, so replacement does not need a restart.

With `COGNIS_INFERENCE_CREDENTIAL_DIR`, Cognis atomically writes
`intaris/token.jwt` and `mnemory/token.jwt` beneath that directory at startup
and on rotation. Mount each service's directory separately, read-only, with
matching container UID permissions. Revoked identities remain revoked after
restart. Standalone companion mode with direct provider settings is unchanged.

## Startup and storage

Cognis setup and inference do not depend on companion readiness. Companions
construct clients without reading credentials or contacting inference.
Before the token is provisioned or the three routes are configured, inference
is unavailable, not bypassed. Configure providers and routes, then retry.
Persistent JWT keys, Cognis DB, companion databases and Qdrant volumes remain
required. This feature does not combine their databases.

The first successful companion embedding call pins its model/provider and
vector dimensions. A changed model or dimension fails closed instead of mixing
embedding spaces. Changing provider configuration behind an unchanged model ID
also requires operator care: Cognis cannot identify upstream model revisions.
For a migration, pause companion writes/workers, prepare new/reindexed
collections, update dimension settings and routing, then call
`POST /api/v1/inference/companions/<service>/reset-embedding` with
`{"reindex_migration_prepared": true}` before resuming. This acknowledgement
does not itself reindex data. Do not reset the binding on live old vectors.

## Logging, metrics, and limits

Responses include `x-request-id`. Structured completion logs contain the
request ID, authenticated client/key ID, JWT ID when present, owner,
requested alias, resolved provider/model, operation, duration, outcome,
and token counts. Prompts, completions and credentials are not logged.

Prometheus `cognis_inference_requests_total`,
`cognis_inference_duration_seconds`, and `cognis_inference_tokens_total`
distinguish clients and resolved models. Token kinds preserve input, output,
cached input, cache writes and reasoning when the provider reports them.
Missing provider usage is not estimated. A cancelled stream may lack final
usage, so these metrics are not a billing ledger. Monetary cost is not computed.
Existing provider inference telemetry remains available; do not sum it with
gateway counters as if they were separate calls.

The gateway bounds request bodies to 8 MiB and limits concurrent work per
client and per process. These are concurrency safeguards, not monetary quotas
or cluster-wide rate limits. Apply deployment ingress limits as appropriate.
Provider failures return sanitized errors; streaming failures are error events.
