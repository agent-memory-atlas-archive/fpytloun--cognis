# Classification and retry runtime fixes

## Classification

Profile-group keyword hints are used for deterministic fallback, not as a reason
to reject a structurally valid LLM classification. The same validator is used
for generated results, cache hits, persisted overlays, and queue admission.
Reserved or unknown profile groups and missing capabilities remain invalid.

The durable classifier allows three failed attempts per unchanged fingerprint.
Exhausted rows remain `failed`; ordinary discovery does not reset them.
A changed fingerprint starts a new budget. Pending or failed classification
continues to use the existing deterministic fallback; it does not block tools.
These statuses use the existing string column and require no schema change.

## Retry runtime and cancellation

The scheduler owns durable turn state. A retry-pending notice reads its active
turn metadata from that state, not from the local task that has already ended.
The transport passes the same waiting metadata to local clients and the relay.
If the durable turn is gone or a successor owns the scope, the old notice does
not publish a new active runtime frame.

Cancellation persists first, outside external I/O. Each changed request then
uses the existing best-effort durable-change publisher to invalidate other
controllers, including cancellation of a recoverable request with no live owner.
The existing active-owner cancellation signal is retained. Queued successors
keep the existing `clear_queue` semantics.

Direct-turn conflicts return structured HTTP 409 responses rather than HTTP 500.
This does not weaken admission hashes or automatically mint replacement keys.

## Limits

These changes do not establish the cause of the reported disappearing message,
the specific mismatching idempotency payload, or executor cancellation logs.
No speculative changes are made to canonical timeline membership, sequence-gap
backfill, or executor delivery reconciliation.
