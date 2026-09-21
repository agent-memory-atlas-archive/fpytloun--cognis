# Retry-wait status projection

Public scheduler status queries include recoverable requests as active waiting
work. Both the single-conversation and batch/sidebar queries opt into this
projection; opening a chat and refreshing its sidebar must not disagree.

The store's active queries retain their execution-only defaults. The opt-in
`include_recoverable` argument changes only read filtering, not `ACTIVE_STATUSES`,
lease recovery, retry timing, admission, cancellation, or transaction ownership.
Queries reuse a supplied database session and perform no external side effects.
Existing rows require no migration. Terminal requests remain excluded.

Regression coverage compares single, batch and snapshot projections of the same
durable retry-wait row with no local executing task, repeatedly refreshes those
views, and checks that cancellation clears all of them. It also verifies that
default execution queries still exclude recoverable requests.
