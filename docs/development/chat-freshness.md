# Chat freshness and read cost

`GET /api/v1/conversations/background-work` returns current-user work summaries.
`include_agent_direct=true` additionally uses the existing authorized agent-home
projection. It never discovers conversation history or context types. The
response contains `background_work`, `background_work_changed` and
`agent_direct_chats`. An incomplete executor lookup sets
`background_work_changed=false`; clients retain their previous complete work
snapshot. Executor I/O completes before entering the database snapshot.

Compact and pinned views use this endpoint through the existing serial refresh
controller. Normal spacing, bounded failure probes and server cooldowns remain.
Actual shared-history refreshes still replace the authorized shared snapshot;
there is no permission TTL cache. Filter changes obtain context types from that
same snapshot rather than issuing a preceding duplicate discovery query.

The sidebar admits canonical pushes before allowing older device-cache results.
Foreground/reconnect urgency flows through its existing serial owner and bypasses
only normal success spacing, never an in-flight request, authorization block or
server cooldown.

## Timing instrumentation

`cognis_turn_admission_phase_seconds{phase,outcome}` uses fixed labels:

- `request_prepare`: mutable-conversation authorization, transaction claim and
  attachment preparation until scheduler submission (successful preparation only).
- `submit_to_admission`: scheduler submission to its durable admission observer.
- `admission_to_receipt`: admission observer to completed receipt preparation.
- `submit_total`: scheduler call duration, including exceptional cancellation.
- `first_claim_wait`: first persisted claim minus persisted admission creation;
  includes intentional queue/capacity wait, excludes repeat recovery claims.
- `claim_notification`: awaited claim-state notification before dispatch.

No metric labels contain user, conversation, request or turn IDs. Timing failures
are fail-open. SQLite's naive persisted UTC values and PostgreSQL's aware values
are normalized for the queue-wait measurement. These measurements do not claim
to time the first model token or browser paint. `submit_total` success describes
a normal return; use the API outcome to distinguish business rejections.

The on-device bounded loading log adds outbox-lock, attachment, admission and
local receipt-persistence timing. It stores no content or correlation identifiers.

## Lifecycle invariants

Foreground opening observes failures even before a timeline controller is bound.
An ownership failure for the currently selected load generation enters the same
fail-closed session-verification state as an adopted controller invalidation.
Obsolete routes and ordinary navigation cancellation cannot invalidate a newer
view; background preloads do not own this foreground transition. Other opening
failures use the existing page error state rather than an unhandled rejection.

A failed post-admission cursor sync remains unreconciled and exposes recovery.
It does not imply an automatic replacement snapshot. Explicit recovery requests
a snapshot; only its completed projection restores authoritative freshness.

Runtime timing observes existing turn rows and phases only. It introduces no
durable state, transaction, lock, wakeup, retry or external side effect.
The direct-turn runtime still owns cancellation/lease fencing and the scheduler
still owns durable admission. Admission receipt/idempotency behavior is unchanged.

## Verification gates

- No history/DISTINCT owner invoked by background-only reads.
- No old device rollback after accepted live sidebar mutations.
- Equivalent opens coalesce; invalidations during an older response cause a
  trailing sync, including in compact views.
- Account changes discard both pending and trailing work.
- Failure/rate-limit policy remains bounded.
- Cached timeline readiness is not presented as authoritative freshness.
- Send retry identities and capacity/fencing behavior remain unchanged.

This batch reduces unnecessary reads and fixes freshness races. It does not
establish a RAM-growth fix or optimize every legitimate full-history SQL plan.
