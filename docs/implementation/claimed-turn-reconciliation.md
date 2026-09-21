# Claimed turn and cancellation reconciliation

## Ownership and invariants

- The durable direct-turn runtime owns request leases and retry scheduling.
  A durable admission encountering a process-local conversation or session
  lifecycle lock yields through `LocalDirectTurnBusy`. It must not hold and
  renew a durable claim while waiting indefinitely for that local operation.
- The scheduler still serializes launch under its conversation lock. The busy
  checks happen before launch or user-event append; retries retain request
  identity and existing fencing and do not replay external effects.
- Non-durable admission retains its existing session-lock waiting behavior.
  Cancellation remains owned by the durable runtime and scheduler.
- A committed durable transition invalidates projections on the publishing
  controller as well as peers. Cluster notifications intentionally ignore their
  own origin. Earlier completion callbacks are not a substitute for a
  post-commit invalidation.
- Client runtime handover carries local admission ordering even when the old
  turn produced no volatile items. It preserves visible user history instead
  of leaving the old admission in the next turn's active ordering band.

No database schema or public API changes are required. Artifact storage and
avatars are outside this change. The exact production lock holder could not
be recovered after restart; tests cover both identified local blocking paths.
