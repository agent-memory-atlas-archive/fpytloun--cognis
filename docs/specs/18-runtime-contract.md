# Cognis: Runtime Contract

## Purpose

This document defines the runtime contract that all Cognis agent runtimes must
satisfy. The current runtimes are:

- `native` — the existing Cognis controller-driven agent loop
- `claude_code` — a Claude Code + Intaris backed runtime hosted on an executor

The goal is to keep upper layers runtime-agnostic:

- conversations
- channels
- slash commands
- tasks
- workflows
- delegation
- notifications
- worktree policy
- delivery

Those layers must depend only on this contract, not on runtime-specific logic.

## Terminology

| Term | Meaning |
|---|---|
| **conversation** | User-visible long-lived chat/thread identity |
| **cognis_session** | Cognis orchestration epoch within a conversation |
| **runtime_session** | Opaque durable runtime-owned session handle |
| **execution** | One active runtime run/attempt within a session or step |
| **step_run** | Workflow-level execution wrapper tracked by Cognis |
| **projection** | Normalized Cognis-visible event stream derived from runtime trace + Cognis overlay events |

## Design Rules

1. Runtimes are low-level execution engines.
2. Cognis owns orchestration and user-facing product behavior.
3. Tool policy semantics are Cognis-owned and runtime-neutral.
4. Runtime-specific event traces are never exposed directly as the product transcript without normalization.
5. Runtimes may differ internally, but must satisfy the same upward contract.

## Runtime Boundary

### Durable admission metadata identity

The turn scheduler owns whether message metadata was supplied by the caller or
generated for this admission attempt. It passes that distinction directly to
the store; payload fields cannot assert it. The admission descriptor excludes
only the timestamp in scheduler-generated message metadata and includes its
generated or explicit origin as a top-level descriptor field. Neither new branch
uses the unversioned legacy descriptor namespace. Explicit timestamps and all other request fields retain
strict idempotency conflict checking. The immutable persisted payload keeps the
first admission's timestamp; replay returns that original row.

This is request-admission state, not runtime execution state. The existing
store transaction continues to own deduplication and atomic predecessor/successor
handoff. The scheduler retains its pre-admission capacity checks. No new external
side effect, lock, schema column or cancellation owner is introduced.

On replay the store accepts either the current descriptor hash or the exact
legacy descriptor hash computed from the incoming request, with its timestamp
still included. It never derives provenance from an old payload and never rewrites
the persisted admission or payload hashes. Pending and completed legacy rows have
the same policy: exact old replay works; a timestamp-only difference still
conflicts even if the current caller generated it. Legacy descriptors did not
distinguish origin, so either caller origin can replay the exact old request.
New descriptors distinguish both origins and cannot pass the legacy fallback.
Hash matching does not expire keys or change the original request's lifecycle.

**Coordinated upgrade required:** there is no mixed-version rollout protocol.
Quiesce admission ingress and automatic continuation producers, allow active
admission/handoff transactions to finish, stop all old controller writers, and
upgrade the complete controller fleet before reopening ingress. Do not leave
old workers/recovery writers connected while new admissions are accepted.
Retain pending/completed rows and keys. Exact legacy replay is supported, but
clients without the original timestamp still need reconciliation rather than a
new key. Draining pending work alone does not solve that limitation.

An old controller cannot recognize newly written descriptor hashes. Rollback
after accepting new admissions is therefore not a rolling downgrade: keep
ingress quiescent and decide a separately verified recovery procedure. Do not
bypass hash checks, delete rows, mutate old hashes, or issue a fresh key for an
uncertain operation. This patch does not authorize deployment or database
migration; publication and the coordinated deployment window require approval.

### Cognis-owned responsibilities

- conversation identity and routing
- channel delivery
- task and workflow state
- notification persistence and `PauseWaiter`
- slash command handling
- worktree and branch policy
- executor placement
- runtime selection from agent definition
- normalized transcript/projection consumption

### Runtime-owned responsibilities

- executing a direct turn or workflow step
- maintaining runtime-native session state
- streaming low-level runtime events
- translating Cognis tool/policy semantics to native enforcement
- exposing structured terminal outcomes

## Runtime Kinds

### `native`

The existing Cognis controller-driven loop. The runtime session is the Cognis
session itself and tool execution flows through Cognis ToolRouter + executor.

### `claude_code`

Executor-hosted Claude Code using native Claude auth and native Intaris
integration. Claude runtime sessions are durable and opaque. Intaris stores the
raw low-level runtime trace. Cognis consumes a normalized projection.

## Capability Model

Capabilities are product/test oriented, not vendor oriented.

```python
class RuntimeCapabilities(BaseModel):
    durable_session: bool
    streaming_output: bool
    tool_loop: bool
    pause_resume: bool
    cancel: bool
    usage_reporting: bool
    structured_terminal_outcome: bool
    error_taxonomy: bool

    native_compaction: bool = False
    background_execution: bool = False
    reasoning_summary: bool = False
    structured_output: bool = False
```

Mandatory for first-class direct-chat parity:

- `durable_session`
- `streaming_output`
- `tool_loop`
- `pause_resume`
- `cancel`
- `usage_reporting`
- `structured_terminal_outcome`
- `error_taxonomy`

If a runtime does not satisfy these, it cannot claim first-class parity.

## Session Boundary Model

### Base hierarchy

```text
conversation
  -> cognis_session
     -> runtime_session
        -> execution(s)
```

Rules:

- `conversation` is the user-visible chat/thread identity
- `cognis_session` is the Cognis orchestration epoch used for reset/compaction boundaries and session lifecycle
- `runtime_session` is the durable low-level runtime handle
- `execution` is one active turn/attempt/resume within a runtime session

### MVP boundary rule

For MVP external runtimes:

- one active `cognis_session` maps to one active `runtime_session`
- a new `runtime_session` is created only on:
  - conversation reset/new session
  - compaction rollover
  - explicit isolation boundary (future fork-style runtimes remain deferred)
  - delegated child-session creation
  - workflow step isolation boundary

This preserves the current Cognis product model while keeping runtime session
continuation simple.

### Workflow mapping

For workflow steps:

- each executable step owns a `step_run`
- the `step_run` references exactly one active runtime session in MVP
- retries may create new `execution` attempts inside the same runtime session
- if the runtime session becomes unrecoverable, the adapter may rotate to a new runtime session and must record that rollover explicitly

## Lifecycle Contract

All runtimes must support the following lifecycle operations.

```python
class RuntimeAdapter(Protocol):
    async def create_or_resume_runtime_session(
        self,
        request: RuntimeSessionRequest,
    ) -> RuntimeSessionHandle: ...

    async def submit_input(
        self,
        request: RuntimeInputRequest,
    ) -> RuntimeExecutionHandle: ...

    async def stream_events(
        self,
        request: RuntimeEventStreamRequest,
    ) -> AsyncIterator[RuntimeEvent]: ...

    async def pause(
        self,
        request: RuntimePauseRequest,
    ) -> RuntimePauseResult: ...

    async def resume(
        self,
        request: RuntimeResumeRequest,
    ) -> RuntimeExecutionHandle: ...

    async def cancel(
        self,
        request: RuntimeCancelRequest,
    ) -> RuntimeCancelResult: ...

    async def close(
        self,
        request: RuntimeCloseRequest,
    ) -> RuntimeCloseResult: ...
```

### Required properties

- operations must be idempotent where retry is plausible
- each execution has a stable `execution_id`
- each runtime session has a stable `runtime_session_id`
- each event has a stable `event_id` or monotonic `seq`
- terminal outcomes must be explicit, not inferred from silence

### Prospective idle hooks

`HookRuntime` owns idle matching, not session status. Each hook assignment persists
an `activated_at` boundary in Cognis metadata. First enable and disabled-to-enabled
transitions establish it in the configuration transaction; duplicate enabled writes,
parameter changes, and definition edits preserve it. A missing boundary fails closed.
An enabled PUT repairs a missing boundary at the current time rather than preserving NULL.
The caller owns commit; updates lock an existing assignment until commit, and local
configuration notification follows commit. No external I/O occurs under that lock.

An idle occurrence qualifies only when its canonical foreground admission's
`created_at` is strictly later than that assignment's activation. Existing and new
conversations use the same rule. Old admissions completing after activation,
automation, absorbed admissions, and legacy `last_message_at` alone cannot qualify.
The latest foreground occurrence, idle duration, and running/queued foreground
checks still govern matching. Configuration refresh and recovery filter candidates
to the latest unhandled foreground occurrence; a run in any status marks that
assignment/occurrence handled. One global configuration job coalesces notifications
with one rerun bit, pages at most 100 IDs, and matches serially. All hook job admission
is capped at 16 per controller; overflow relies on durable recovery rather than
creating waiting tasks. Matching rechecks each assignment before
history reads or snapshot creation. Restart cannot manufacture historical eligibility.

Recovery owns a runtime-local keyset cursor across timed-out/cancelled scans. It
advances only after each candidate finishes, retries an incomplete candidate, and
resets on exhaustion or runtime restart. Configuration scans have independent local
cursors and cannot mutate recovery progress. No database state or locks are added.

Hook snapshot and lifecycle event-append idempotency keys must start with the actual
target Intaris session ID plus `:` (`intaris_session_id` when present, otherwise the
local session ID). Their run/status suffixes remain stable across retries. This is
distinct from direct-turn admission idempotency, whose key remains the hook run ID.

Alembic and idempotent bootstrap seed preexisting assignments once at rollout, install
server defaults for old writers omitting the column, and repair only NULL boundaries.
SQLite's default rounds its millisecond clock up to avoid backdating activation;
PostgreSQL uses `clock_timestamp()`, not transaction-start time. The prospective
execution guarantee requires replacement of every old hook runtime: schema rollout
cannot make an old binary enforce new eligibility policy.

Unadmitted preparing/pending/dispatching idle runs are rechecked. Dispatch locks the
assignment with a no-op write on both SQLite and PostgreSQL, validates activation,
and CAS-claims the run in that transaction. Claim is the linearization boundary;
later configuration changes do not revoke it. No external I/O occurs under the lock.
Recovery first reconciles durable child/task admissions, including ambiguous child
outcomes, without resubmitting or reading source history. Already-admitted work
retains normal scheduler ownership, cancellation, and idempotent recovery. No session
state is changed to implement hook eligibility. See the
[agent hooks guide](../guide/agent-hooks.md) for user-facing semantics.

## Event Model

Runtimes emit low-level events. Cognis consumes these and produces normalized
projected events for the rest of the system.

### Raw runtime event envelope

```python
class RuntimeEvent(BaseModel):
    event_id: str
    runtime_type: str
    runtime_session_id: str
    execution_id: str
    seq: int
    source: str                # runtime | intaris | cognis_overlay
    kind: str
    payload: dict[str, Any]
    timestamp: datetime
    caused_by: str | None = None
```

### Minimum raw event kinds

- `input_received`
- `message_delta`
- `message_completed`
- `tool_proposed`
- `tool_decision`
- `tool_started`
- `tool_completed`
- `question`
- `approval_required`
- `progress`
- `usage`
- `paused`
- `resumed`
- `completed`
- `failed`
- `cancelled`

### Projection rules

Upper layers do not consume raw runtime events directly. They consume a
normalized projection with deterministic ordering and provenance.

```python
class ProjectedConversationEvent(BaseModel):
    event_id: str
    source: str                # runtime | cognis_overlay
    kind: str
    conversation_id: str
    cognis_session_id: str
    runtime_session_id: str | None = None
    execution_id: str | None = None
    caused_by: str | None = None
    visible_to_user: bool = True
    ordering_key: str
    payload: dict[str, Any]
    timestamp: datetime
```

Projection requirements:

- deterministic reconstruction after restart
- idempotent replay
- stable causal linkage between overlay events and runtime events
- user-visible transcript separated from raw audit trace

## Source-of-Truth Rules

### Native runtime

- Cognis and Intaris together remain the existing source-of-truth model
- normalized conversation history continues to be read from Intaris events

### Claude runtime

- Intaris is the canonical durable store for the raw low-level runtime trace
- Cognis does not duplicate that raw Claude session log in a second low-level store
- Cognis may persist overlay metadata and derived projection checkpoints
- user-visible history is a normalized projection, not a raw replay

### Overlay events

Overlay events are Cognis-owned events that do not originate inside the raw
runtime trace, for example:

- task status updates
- workflow transitions
- delegation started/completed
- PR opened
- slash command effects
- delivery notices

For external runtimes, overlay events should ideally be durably recorded in
Intaris as a separate source stream so transcript reconstruction can happen
from one durable backend.

## Tool Contract

Tool calls are part of the runtime contract.

### Shared semantics owned by Cognis

- inventory selection
- allow / deny / evaluate permission model
- non-bypassable tool categories
- timeout policy
- cancellation policy
- credential/secret availability
- workflow-level question permission policy

### Runtime responsibilities

Each runtime translates those shared semantics into native enforcement.

#### Native runtime

- Cognis exposes tool definitions directly
- Cognis routes evaluation and execution

#### Claude runtime

- Cognis produces an effective runtime tool policy
- runtime translates that into Claude + Intaris configuration/session policy
- approvals and denials must remain replay-safe and fail-closed where the shared Cognis policy requires it

### Required tool-policy semantics

The following meanings must remain equivalent across runtimes:

- `allow`: tool may proceed without user approval if no stronger policy blocks it
- `deny`: tool must not execute
- `evaluate`: guardrails evaluation decides allow/deny/escalate
- `non_bypassable`: runtime may not skip guardrails even if general policy would otherwise allow
- `timeout`: runtime must surface timeout as explicit failure or cancellation
- `cancel`: runtime must stop in-flight execution if supported, otherwise return a structured non-cancellable error

## Terminal Outcomes

All executions end with exactly one terminal outcome:

- `completed`
- `failed`
- `cancelled`

Each terminal outcome must include:

- `execution_id`
- `runtime_session_id`
- `status`
- `summary`
- `usage` when available
- `structured_result` when available
- `error_code` and `error_category` for failures

## Error Taxonomy

Minimum categories:

- `runtime_unavailable`
- `runtime_protocol_error`
- `runtime_policy_blocked`
- `runtime_question_timeout`
- `runtime_tool_timeout`
- `runtime_cancelled`
- `runtime_unrecoverable_session`
- `runtime_projection_error`

These categories must be stable enough for task/workflow logic and user-facing
messaging.

## Slash Command Contract

Slash commands are Cognis-owned.

Runtime adapters must support the resulting operations, but slash command
parsing and permissioning stay above the runtime layer.

Required parity targets:

- `/approve`
- `/deny`
- `/new`
- `/reset`
- `/compact`
- `/undo`
- `/redo`

The runtime adapter must define what each command means for that runtime. For
example, `/compact` may require runtime-session rollover for an external
runtime while keeping the same user-facing conversation.

## Recovery and Replay

Minimum guarantees:

- deterministic event replay from durable state after controller restart
- resume from latest projected checkpoint
- no duplicate user-visible events after retry/reconnect
- runtime session recovery status is surfaced explicitly to users/operators

Projection engines must store checkpoints containing at least:

- last projected raw event `seq`
- last emitted projected `event_id`
- active `runtime_session_id`
- active `execution_id`

## Conformance

No runtime is considered first-class until it passes parity tests for:

- direct chat
- delegation
- task-backed workflow execution
- notifications/questions/approvals
- slash commands
- cancellation and replay
- normalized transcript reconstruction

See `19-runtime-implementation-plan.md` for the rollout and test plan.
