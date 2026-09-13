# Task queue and notification reconciliation

The task queue checks durable work on startup, after local or cross-controller
wakeups, and every 15 seconds as a fallback. A successful claim schedules another
pass so coalesced wakeups can fill available capacity. Ready transitions,
dependency resolution, and released capacity wake claimers after commit.
Before claiming, each pass reads the next future ready-task deadline and bounds
the next wait by `scheduled_for`. Scheduled work therefore does not wait for the
15-second fallback. Overdue work blocked by capacity does not create a busy loop.

Notification waits check durable state on entry, local completion, remote
notification invalidation, and every 5 seconds. Cancellation events interrupt
the wait. Resolved notifications retain the 0.5-second capacity retry cadence.
Resolution-claim deadlines and grace periods remain authoritative.

PostgreSQL LISTEN/NOTIFY is best effort. Signals contain no decisions or claim
authority. Lost signals, listener reconnects, and mixed-version deployments rely
on bounded reconciliation. Older replicas ignore the new `task_queue_changed`
kind and keep their existing polling. SQLite uses local wakeups and the same
fallbacks. No schema migration is required.

## Ownership and invariants

`TaskQueue` owns its process-local wake event and drain task. `NotificationService`
owns subscriptions and transient wait tasks for each active notification wait.
`queue_wakeup.publish_queue_wakeup` publishes post-commit hints. The existing
task execution store owns distributed claims, capacity, and fencing.

Register before reading durable notification state. Never hold a database session
across a wait. Duplicate or stale signals only cause another authoritative read.
Direct-turn cancellation (2 seconds) and controller heartbeats (5 seconds,
20-second TTL) are unchanged.

## Verification after deployment

Compare matched idle and active windows, normalized by active tasks and waits:

- `cognis_task_queue_reconciliations_total{reason="signal"|"fallback"}`
- `cognis_task_queue_claim_attempts_total`
- `cognis_notification_wait_reads_total`
- Existing `cognis_db_pool_*` connection counters and gauges
- PostgreSQL transaction rates, active time, CPU, and connection creation
- Notification resolution, task pickup, and cancellation latency

An idle queue falls from about 60 to 4 fallback passes per minute per replica
(93.3% fewer). An unresolved notification falls from about 120 to 12 fallback
passes per minute (90% fewer), excluding events and capacity retries. These are
not estimates of total SQL or CPU savings. Read-only transaction cleanup still
uses normal rollback semantics.
Each queue pass also performs one bounded scheduled-deadline query.

Use a mixed-version canary, then verify degraded operation with dropped signals
in a test environment. Do not change production PostgreSQL settings as part of
this application rollout.
