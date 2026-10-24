# Cognis named inference routes and unified recovery

Status: Approved after independent architecture review and one bounded correction.
Implementation, parent merge and origin deployment push authorized by the user.
Implementation remains gated: unintegrated primitives are not a delivered feature.
Reference: the private source revision recorded in the original implementation
review. Its checkout location and private commit identifier are omitted here.

## 1. Objective and agreed product contract

Add reusable named inference routes, exposed as `cognis/<name>`, above system-role routing.
System roles may reference a named route or retain a direct provider/model. Agents in
chat, managed conversations, delegates, and workflow tasks, and external callers
(Intaris, Mnemory, other proxy clients), may likewise select named routes or direct
provider/model references. All use one recovery policy implementation.

Named route configuration contains concrete provider/model targets with integer
priority, plus optional Recovery overrides. Lower priority is preferred; equal
priority is a load-balancing pool. Choose uniformly for new LLM sessions, then
remain target-sticky. No weights, model-policy switch, strategy selector, affinity
selector, nested named routes, or arbitrary condition language.

Different models are allowed by explicit target configuration, subject to
operation/history/capability compatibility. This delivery rejects multi-target
embedding routes: retain existing concrete provider/model and dimensions pins,
including atomic first-success companion binding. Single-target embedding routes
and direct embeddings use unified recovery. Cross-provider embedding-space
identity and reindex migrations are a separate feature, not invented here.
Speech-to-text, text-to-speech and image generation are included as inference
operations; named routes are assignable only where the operation adapter can
validate capability and retry safety. All exposed entry points use this owner.
Provider-native agent runtimes that own their model calls externally are not
quietly intercepted; unsupported named references are rejected explicitly.

Sidebar shows configured reference separately from the actual main-agent
provider/model and that provider's health/limits. Auxiliary calls never replace
the main-agent display.

## 2. Verified current boundaries

- `cognis/store/models.py:1784`: providers; `:1816`: provider monitor snapshots;
  `:1834`: role routing rows with owner, task type, provider, model and config.
- `cognis/providers/llm/routing.py:9`: canonical roles and companion inheritance.
- `cognis/providers/llm/litellm.py:3352`: single-target role/model resolution;
  `:3870`: explicit and bare model references; `:5659`: stream generation.
- `cognis/providers/llm/service.py:14`: public service facade presently inherits
  the large LiteLLMProvider implementation.
- `cognis/providers/llm/retry.py:291`: retry loop, classifier, backoff,
  Retry-After inline cap; default three retries, base 1s, max delay 30s.
- `packages/executor/src/cognis/executor/providers/llm/retry.py:292` duplicates
  controller retry machinery. `packages/common/src/cognis/providers/retry.py`
  already owns generic delay calculation.
- `packages/executor/src/cognis/executor/backends/anthropic.py:140` has its own
  configured retry wrapper. Audit every backend and SDK for implicit retries.
- `cognis/core/agent_loop.py:9245`: one authoritative admitted-turn model
  selection; `:9917`: frozen executor affinity; `:10490`: no-visible-output
  stream recovery layered above provider calls.
- `cognis/providers/llm/inference_api.py:88`: separate proxy role/reference
  resolution and companion authorization; `:70`: target is currently concrete.
- `cognis/api/routes/inference.py:165`: proxy disables retries, then selects
  3.5s timeout for intaris_evaluation or 120s otherwise. Streaming emits SSE
  while forwarding provider chunks; observation currently uses admitted target.
- `cognis/providers/llm/monitoring.py:110`: metadata connectivity probe, not
  generation readiness; `:50`: age-aware quota severity.
- `ui/src/lib/components/session/SessionDetailsContent.svelte:68`: sidebar
  selects monitoring using runtime_selection.provider_id.

LiteLLM inspiration: https://docs.litellm.ai/docs/proxy/reliability documents
retries before failover plus failure thresholds and cooldowns. Adopt those
concepts, not another router dependency or its content-policy fallback behavior.

## 3. Minimal ownership design

Use the existing LLMService public entry point. Establish focused owners behind
it, rather than extending the agent-loop hotspot or adding a parallel facade:

1. Plan resolver: resolve role inheritance, named references and direct targets
   into one immutable InferencePlan. Reuse existing provider visibility and
   ambiguity rules. Role references remain distinct from named-route identity.
2. Recovery executor: one controller-side owner for attempts, delays, deadlines,
   pre-output stream retries, target switches and attempt provenance.
3. Routing state: DB owns durable bindings and replacement fencing. The existing
   application-scoped RedisService owns ephemeral availability when configured
   (mandatory for multiple replicas); memory is used only when Redis is
   unconfigured in single-replica deployments. No DB availability backend,
   new Redis client, scheduler, event bus or generic resilience framework.

An InferencePlan contains requested reference, owner/security context, role if
any, concrete candidates, effective recovery policy, route revision, operation
requirements and optional LLM-session identity. A direct target compiles to a
one-candidate plan using the same executor and defaults; it never discovers
unconfigured alternatives.

An individual transport call is a single attempt. Extract existing generate and
stream implementation into private attempt methods incrementally; do not
rewrite provider transports wholesale. Explicit target calls, embedding and
typed System One calls must not bypass the public recovery boundary.
Media entry points likewise consume the same plan/budget/classification owner;
their adapters declare replay safety and stream commitment, not another loop.

Pure classification/error-envelope logic belongs in packages/common so remote
executors and controller normalize failures consistently. Actual sleeping,
retry decisions and target selection belong only in the controller. Executors
perform one upstream attempt and return structured failure evidence.

## 4. Unified policy and exact budget semantics

Policy precedence: global defaults, then named-route overrides; direct targets
use global defaults. Translate supported legacy retry/idle options at admission,
once, preserving intentional overrides. Caller deadlines can shorten but never
extend service/role hard caps; proxy payloads cannot inject retry policies.
Intaris's existing short admission/timeout contract remains an upper bound.
Internal agent/proxy max_retries=0 suppression is wiring to remove, not a user
override to inherit. Inventory and distinguish it from saved/request-authorized
policy before changing defaults.

Optional route Recovery fields:

- max_retries_per_target: extra attempts against a target, excluding first.
- target_recovery_window_seconds: cap from first recoverable failure through
  subsequent waits/attempts, not a timeout on healthy generation.
- max_target_switches: replacement candidates allowed, never revisit a target
  during one logical request.
- request_timeout_seconds: overall deadline from inference admission through
  completion, including waits and generation.
- failure_threshold, failure_window_seconds, cooldown_seconds: circuit policy.

Initial proposed defaults for characterization/review: three extra attempts,
30s target recovery window, 1s exponential base with jitter and 30s delay cap;
at most all remaining configured candidates once; three terminal recoverable
request failures within 60s open a 30s circuit. Keep current per-operation
timeout defaults instead of imposing 120s on all agent requests. Where no
existing operation deadline exists, establish an explicit documented default
after measuring current supported long generations. Values are proposed, not
claims about current behavior.

One request-scoped budget includes all upstream attempts and compatibility
repair resubmissions; no fresh retry counter on fallback or SDK re-entry.
With N allowed targets and R retries each, maximum ordinary attempts is
N * (R + 1), also limited by switch/recovery/deadline bounds. The target
recovery clock resets on a new target, overall deadline does not.
Each attempt receives the lesser of transport timeout and remaining deadline.
Cancellation cancels sleep/RPC/stream and releases admission and trial claims.
The overall deadline is actively enforced with a cancellation scope covering
resolution, candidate preparation, claim waits, transport and stream iteration;
start at entry to the inference boundary, not after resolution finishes.
Recovery-window expiration prohibits new retries/waits; it does not cancel an
already progressing generation. That generation still obeys the overall deadline
and attempt-local idle watchdog. Recheck expiry after preparation before dispatch.
Every upstream resubmission, including a compatibility repair, consumes one of
that target's R + 1 attempt slots. With R=2 and two targets: primary fails,
compatibility repair fails, ordinary retry fails = three primary attempts;
fallback succeeds = fourth overall. With R=0, a failed first attempt cannot
issue a repair on that target. The same rule applies to direct-target plans.

Known short Retry-After: do not call that target before its reset; wait only if
within remaining recovery budget. Long reset or known exhausted quota: skip
pointless retry and select another eligible candidate. Invalid request,
context overflow, refusal, authorization and cancellation do not open circuits.
Authentication failure surfaces a configuration error; do not silently hide it.
Unknown failures fail closed unless classified as safely recoverable.

Compatibility repairs (e.g. Responses-to-chat transport repair) remain narrowly
owned by adapters but must consume the same attempt budget and stop after output
commit. Context compaction and attachment repair remain explicit agent
operations because they change input; they cannot restart exhausted identical
provider recovery. A changed-input inference request is separately identified
and bounded by the existing agent turn/cycle limits.

## 5. Shared availability without a health platform

Maintain observed availability separately from configured targets:

- Explicit quota/rate-limit blocks scoped to the affected provider/model or
  credential account only when the upstream evidence supports that scope.
  Do not infer account equivalence from secret material or unrelated providers.
- Route-specific circuit evaluation over shared target observations; direct
  calls use the default-policy identity. This prevents one aggressive route
  policy from globally poisoning a different route.
- Count terminal recoverable logical-request failures per target, not every
  retry or caller cancellation. Record individual attempts for diagnostics.
  Count the exhausted candidate even when a replacement ultimately succeeds;
  deduplicate terminal evidence by logical request and concrete target.
- closed/open/half-open states; one expiring half-open trial claim per scope.
  Trial success closes; failure reopens; expired/cancelled claims are released.

Reuse provider-monitor quota snapshots only when fresh, applicable and explicitly
exhausted. Warning thresholds alone do not remove a target. Metadata probe
success never clears a generation circuit or a known quota block.
Unknown/stale monitoring is not an outage.

Use bounded atomic Redis Lua operations with tagged results, fingerprints and
trial tokens. None/indeterminate results are unavailable, never a healthy missing
key. Configured Redis never falls back to memory on an outage. Missing ephemeral
state initializes a new generation; stale completions cannot recreate it.
Deduplicate terminal reports; do not retry ambiguously executed mutations.
DB binding reservation is not availability permission: admit through Redis
immediately before dispatch. Reporting failure must not replay generation.
Existing streams may finish during an outage. Runtime observations contain no
credentials or prompt content. No network calls run inside DB transactions.

If all candidates are blocked, bounded wait until earliest applicable reopening
only if permitted by remaining deadline; otherwise return structured unavailable
or rate-limit error and validated Retry-After. Never force traffic through an
open circuit. New calls against an open circuit skip same-target retry budgets.

## 6. Target binding and caching lifecycle

Binding key: owner/security scope + LLM-session/cache-generation identity +
selected reference. Persist selected target and revision, not provider objects.
For named references persist immutable route ID rather than its display name.
Priority-only edits or unrelated policy edits preserve eligible existing bindings;
removed, unauthorized or incompatible targets require reselection. Recheck new
policy at request admission without rebalancing healthy sessions on every revision.
Do not bind an entire conversation or confuse the Intaris log session with the
actual inference/cache lifecycle. Trace actual session rotation/compaction paths
before wiring generation changes: semantic new context permits selection;
metadata-only rotation carries binding forward. Tool-loop calls and later turns
reuse it. Tasks/delegates use their own real session identity.

Reserve initial AND replacement selection atomically before dispatch. For the
same expected binding revision, concurrent callers share the reserved target or
wait for its transition; they cannot choose separate replacements. Claims have
fenced revisions and bounded leases; no network call holds a DB transaction.
Once semantic output commits (or a non-stream response succeeds), promote the
replacement as the cache-affinity binding even if its stream later interrupts:
history now contains that target's output. Track last completed success separately.
Before commitment, a failed/cancelled reservation does not replace the previous
committed binding. Stale cancellation/completion cannot release or overwrite a
newer claim. Active committed streams remain on their target; later requests may
move only through a new binding transition if it becomes unavailable.
Recovery never automatically fails back when original targets recover.

Proxy: recognize an explicit bounded `X-Cognis-Session-Id`; otherwise
`X-Cognis-Client-Id`; otherwise use authenticated API-key/service identity for
coarse, mandatory client stickiness. Scope by resolved owner/principal and
reference; keys cannot grant permissions. No source-IP/connection affinity.
Document that shared keys require session/client headers for independent cache
lifecycles. Bound identifier sizes and expire inactive external bindings to
prevent unbounded state; use lazy expiration and existing maintenance hooks.
Propagate the cache-generation identity into supported provider affinity/cache
adapters as well as selection. Keep it separate from audit/Intaris identifiers;
derive proxy affinity from scoped internal identity, never raw untrusted header
values. Metadata-only rotation carries affinity forward; semantic new context
rotates it. Promise stable target/affinity inputs, not guaranteed cache hits.

Do not conflate tool execution affinity with inference executor placement.
Preserve existing frozen execution/security contracts. A candidate that conflicts
with frozen constraints is ineligible, not permission to relocate the agent.

## 7. Stream and compatibility boundaries

Recovery owns stream consumption through the first committed semantic delta:
text, reasoning, tool-call content, or provider-native observable effects.
Also include refusal deltas, thinking blocks, tool progress/native events, and
replay-bearing Responses items; characterize every adapter's event envelope.
Before that point it can discard attempt-local role/empty headers and retry.
Buffer only bounded prelude metadata, never the whole response. A successful
empty terminal response commits once and is not retried as a transport failure.
After commit, interruption is surfaced; never mix generations or replay tools.
Unknown side-effect safety of provider-native tools disables transparent retry
for that operation unless the adapter proves safe/idempotent execution.

The same commit definition is used by agent and proxy adapters. SSE framing must
not commit retryable provider prelude accidentally; retain normal OpenAI framing.
For remote failures preserve normalized category, Retry-After and stage rather
than collapsing all failures into undifferentiated mid_stream_failure flags.
Place the existing idle watchdog around each single attempt INSIDE recovery;
its timeout enters the same classification/budget path. An outer agent watchdog
must not treat recovery backoff as idle upstream generation.
Existing agent post-failure continuation instructions are not transparent
transport retries. Retain only explicitly identified, bounded agent recovery
operations with visible interruption semantics and existing turn/cycle limits;
they must never reset and rerun an exhausted unchanged request accidentally.

Each target is checked against required operation, tools, modalities, structured
output, reasoning and context budget. Agent attempts must prepare projection,
model metadata, context/token budget and tool exposure for that candidate through
existing owners. Do not send primary-provider projections to a fallback.
An agent preflight/attempt-preparation hook is bounded and typed; no opaque context
bag or private-field injection. It refreshes ctx runtime selection through a
public transition before inference; tool execution is not repeated.
Keep configured RuntimeSelection immutable. Introduce a typed attempt-effective
selection distinct from configured reference and last-completed selection.
Candidate preparation refreshes projection, tool exposure, decoding/alias maps,
native continuation handling, budgeting and accounting before dispatch without
creating a user override or changing frozen tool/execution permissions.

Provider-native continuation/cache IDs and encrypted reasoning are not portable.
Use existing canonical history projection where lossless compatible conversion
is supported; otherwise mark candidate ineligible and explain why. No silent
discarding of signed reasoning or dropping requested capabilities. Proxy messages
may not carry enough portable history; in that case return a compatibility error.

Route discovery exposes only guaranteed compatible operations/capabilities;
per-request eligibility is more precise. Context limits must be conservative
until a concrete target is selected. Do not claim one model's exact metadata for
a mixed-model alias.

## 8. Configuration, API, security, persistence and UI

Add an owner-scoped named-route table with immutable ID, unique owner/name,
revision, validated target list and recovery config. Start with JSON target list
to avoid a target-management subsystem; validate duplicate provider/model pairs,
nonnegative priorities, provider/model availability, operation suitability and
configuration bounds. Provider deletion/inactivation checks references and
invalidates eligibility; JSON references must not silently dangle.
Reserve the `cognis/` namespace; do not create a credential-bearing fake provider.
Named routes refer only to concrete targets, never another named route.

Existing ModelRouting role rows may point at cognis/<name> with no provider_id;
existing direct rows and sentinels remain unchanged. Centralize existing role
inheritance, global companion restrictions and reasoning-effort merge so agents
and proxy resolve identically without weakening service-specific allowlists.
Preserve routes/<role> and providers/<provider>/<model> proxy reference formats.
Companion principals may continue using only their permitted role aliases; those
roles may reference named routes with globally owned targets. General authorized
clients may request either named routes or direct targets.

Recheck visibility/status before each candidate attempt; route authorization is
not permission to access arbitrary hidden providers. Respect route-owner fallback
rules and API-key model/operation allowlists. No admin bypass for private routes.
Namespace ambiguity/conflicts are detected before migration/write.

Add a small durable binding table; ephemeral availability has no DB table or
mirror. Avoid repurposing monitor snapshots as a circuit store.
Indexes support scope and expiration; migrations do not rewrite old selections.
Rollback preserves legacy direct role rows.

Extend Settings Routing with named route editor, target provider/model pickers,
priority and collapsed Recovery overrides. Existing system-role pickers and
agent/profile/task model pickers list authorized named routes alongside direct
targets. Validate inline and server-side; prevent deleting referenced routes
without an explicit replacement. Update /v1/models discovery appropriately.

Attempt-local events/metadata carry requested reference, actual provider/model,
route revision, attempt ordinal, reason, status and usage. Avoid mutable
last-provider state on singleton services. Sidebar updates at attempt selection,
labels attempting vs successful/last-used, reads real-provider monitors and
persists across reload; auxiliary lanes never overwrite main-agent selection.
Proxy response model stays the requested alias for compatibility; actual target
is available in authorized diagnostics/accounting, not leaked across owners.
Observe actual attempts, not only the initial admitted target. Keep content-free
diagnostics and avoid high-cardinality session IDs in metric labels.

## 9. Delivery sequence

1. Characterization: map every inference operation/caller, actual LLM-session
   lifecycle, SDK retry and executor paths. Tests pin existing short Intaris
   deadline, provider retry semantics, agent repairs, proxy framing and auth.
2. Recovery cleanup first: shared normalized failure types/pure classification,
   controller-owned budget and private single-attempt adapters. Direct-target
   agents, system calls and proxy now share bounded recovery. Remove duplicated
   executor/controller sleeping loops and overlapping agent pre-output retries
   only after equivalent invariant tests pass. No route UI yet.
3. Named plan resolution/config/migrations: concrete and named references,
   centralized role inheritance/authorization, discovery and validated settings.
4. Binding and availability: DB claims, target selection, cooldown/half-open,
   compatibility-aware attempt preparation and failover. Wire all agent/task
   sessions, system roles, proxy and companion roles through the same boundary.
5. Actual-target UI/accounting and docs: route editor and all model pickers,
   sidebar, limits, proxy identity/deadline guidance and operational diagnostics.
6. Independent review of final revision, focused regressions plus affected-module
   tests/build/type checks; integrate only with explicit authorization.

Each step is a reviewable behavioral slice, not parallel edits to the same
provider/agent hotspots. Mechanical extraction is separate from behavior changes.

## 10. Acceptance and validation matrix

- Direct vs one-target route parity for chat/generate/stream/embedding/System One
  through agents, workflow tasks, roles and proxy; media entry-point parity
  for image generation, speech-to-text and text-to-speech with replay-safety
  assertions, partial audio commit and cancellation tests.
- Multi-target embeddings rejected without weakening existing companion pins.
- Short Intaris deadline is never expanded; Mnemory global companion inheritance,
  effort-only overrides, operation/model allowlists and ownership remain intact.
- Fake-clock tests: precise attempt counts, exponential waits, Retry-After,
  long quota reset, overall deadline, recovery window and no nested SDK retries.
- Equal priorities distribute new sessions; all calls of one real LLM session
  remain sticky across turns/restarts; semantic reset permits reselection.
- Provider/model switching re-prepares messages/tools/context; incompatible
  modality, context, encrypted state or frozen executor is rejected explicitly.
- Pre-output role/empty chunks followed by failure recover transparently;
  text/reasoning/tool deltas followed by failure never mix generations.
- Cancellation during sleep, RPC, generation and trial selection releases
  resources; success/failure streams are always closed.
- Concurrent clients/replicas: one binding choice, CAS replacement, one
  reserved replacement before dispatch, one half-open trial, no stale success
  clearing newer quota/config state; interrupted committed fallback retains
  affinity, while pre-output cancelled fallback does not promote.
- Circuits count terminal relevant failures, not prompt errors/refusals or retry
  multiplicity; known scopes/reset times respected; all-unavailable is bounded.
- SQLite and PostgreSQL state/migration coverage.
- Proxy shared-key client/session identity, header bounds, expiry and
  cross-owner isolation; no policy injection from request body.
- Sidebar during retry/fallback/reload shows actual provider limits; task/main
  lane separation; attempt usage/accounting attributed accurately.
- Existing retry, inference router/API, agent-loop recovery, settings/model
  routing, provider-monitoring and session-sidebar suites remain green. Execute
  exact selected test/build commands during implementation, not in planning.

## 11. Required slice exit criteria / implementation preflight gates

Record evidence before the affected delivery slice is enabled:
1. Precise cache-generation/session lifecycle owner; do not invent it from
   conversation or Intaris identifiers.
2. Which candidate-aware preparation boundary safely updates the admitted-turn
   selection and frozen tool/executor contract without hidden cross-mutation?
3. Existing operation-specific long-generation timeout defaults and the
   precedence of legacy provider/model retry overrides.
4. Complete event commitment/watchdog and media safety matrix. JSON target
   references versus child rows is a local persistence choice, not an adoption
   gate. Prefer JSON unless existing integrity conventions make rows simpler.

These are bounded code-wiring gates, not justification for a broader redesign.
Slice 2 cannot complete without the retry-owner inventory, precise per-operation
deadlines and commit/watchdog safety characterization. Slice 4 cannot enable
multi-target execution without lifecycle/affinity mapping, candidate preparation
proof, fenced claim-expiry tests on both databases and companion authorization/
embedding-pin regressions. Slice 5 cannot complete without actual-target
sidebar/accounting and picker/discovery acceptance evidence.

## 12. Architecture review disposition

Initial review: system:architect session sess_6599e75c28d84c70af20006cc19d4b36,
reference commit above. Verdict REQUEST REWORK; no architecture rewrite requested.
- Embedding identity blocker: multi-target embeddings explicitly deferred;
  retain exact concrete pins and unified single-target recovery.
- Concurrent fallback blocker: reserve replacement before dispatch; define
  committed interruption, successful completion and stale-claim fencing.
- Retry accounting/deadline: exact repair example, internal zero-retry wiring
  distinguished from user overrides, active whole-boundary cancellation scope,
  recovery window forbids new attempts rather than aborting progressing output.
- Cache locality: identity propagated to provider affinity, not binding only.
- Stream/agent wiring: full commitment events, attempt-local watchdog,
  configured versus effective selection separation and bounded continuations.
- Scope/config improvements: media operation coverage, unsupported external
  runtime references explicitly rejected, route edits preserve healthy affinity,
  exhausted-target observations counted independently of final request success.

Re-review: system:architect session sess_0828ceadabe849008c5f86eb6412f25d.
Verdict APPROVE: no remaining blockers or major plan-adoption findings; no
overengineering found. Preflight results made explicit slice exit criteria as
recommended. Architecture approval is not implementation or integration approval.

Redis amendment reviewed by system:architect session
sess_00667d7b5e3c4a2fa489254697988581: approved with fail-closed tagged Lua results,
independent DB/Redis fencing, configuration-based backend selection and no
automatic in-memory fallback when configured Redis is unavailable.

## 13. Candidate-preparation implementation clarification

Advisory review `sess_65361ba14f5642009e875845ba1b5591` identified the concrete
preparation boundary. Do not enable fallback underneath precomputed agent
requests. Context assembly already renders history/attachments and prunes input
before inference. The serving request and response decoder must share a single
immutable preparation record.

Required sequence:

1. Mechanically extract typed preparation/decoder records and native-chain state
   without changing direct-target behavior.
2. Separate collected canonical context from candidate rendering. Collect memory,
   prefix and history once; preserve attachment references and unpruned source.
   Include this cycle's tool results/reminders in candidate rendering.
3. Prepare under the request deadline, before consuming an upstream attempt.
   Outcomes are ready, incompatible, or requires agent recovery. Incompatibility
   is not a provider-health failure. Try a fitting candidate before requesting
   outer-loop compaction.
4. Recheck binding claims, availability and budget immediately before dispatch.
   Publish a typed preparation selection before chunks reach the accumulator.
   The agent adopts its matching aliases/native bundle/projection for decoding.
5. Keep compaction/session rotation and native continuation advancement
   agent-owned. Release claims before returning to compaction. Failed preparation
   cannot publish staged chain/projection state.

Confirmed lifecycle evidence: current COMPACT, RENEW and RESET all change actual
context; there is no metadata-only rotation path to preserve specially.
`ctx.session.session_id` is therefore the current cache-generation identity.
Task/delegate sessions have distinct IDs. Future metadata-only rotations would
need explicit preservation; do not invent another session-ID system now.

## 14. Implementation checkpoint — primitives only

The current isolated branch implements unintegrated recovery primitives, not the
feature. Do not merge/deploy this checkpoint as completion of provider fallback.

Implemented:
- Validated route/target/recovery schemas and owner-scoped route persistence.
- Durable DB binding reservations, revision fencing and database-clock leases.
- Redis Lua / single-replica memory availability, cooldowns and half-open trials.
- Bounded streaming recovery with pre-output fallback and semantic commitment.
- ORM tables and reversible migration; no availability table.

Verification:
- `uv run --no-sync pytest tests/unit/test_inference_availability.py tests/unit/test_inference_recovery.py tests/unit/test_inference_bindings.py tests/integration/test_inference_availability_redis.py -q --tb=short`
  — 31 passed with isolated PostgreSQL and Redis URLs supplied through
  `COGNIS_TEST_POSTGRES_URL` and `COGNIS_TEST_REDIS_URL`.
- Same binding/CAS and migration/ORM-parity tests exercised SQLite and PostgreSQL.
- Real Redis tests used two independent clients, shared cooldowns, one half-open
  trial, stale reports after state reset, and configured-client loss.
- Ruff and `git diff --check` passed for task files.
- Independent primitive review `sess_9d6a0d5750404b4cb2839d53c07fc867`: APPROVE
  after one correction pass. Findings fixed: committed trial failures reopen the
  circuit; backoff oversleep exhausts the target rather than the whole request;
  semantic output is not subject to metadata-prelude size limits; permit cleanup
  covers reservation errors/cancellation.

Still required before full delivery:
- Canonical context and typed candidate-preparation extraction described in §13.
- Unified actual call boundary and removal of overlapping controller/executor/
  agent retry loops; count compatibility resubmissions against one budget.
- Named/direct resolution and authorization for system roles, agents/chat/tasks,
  proxy clients and companions; preserve embedding pins and short deadlines.
- Actual-target runtime/sidebar metadata, settings UI and model discovery.
- Account-scoped quota handling, complete event-envelope characterization,
  binding retention integration, and end-to-end acceptance beyond primitives.
- Full-feature independent review, parent integration, origin push and deployment
  verification. None of these integration/deployment steps has occurred.
