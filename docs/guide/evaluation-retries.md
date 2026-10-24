# Evaluation failures and stale approvals

Intaris evaluation retries transient transport errors and HTTP 429/500/502/503/504
twice, with exponential backoff and jitter. Evaluation also respects a numeric
`Retry-After` cooldown, bounded by the existing 30-second maximum delay. Missing,
malformed or non-finite values use the existing backoff.

Only evaluation opts into this cooldown behavior. Tool execution and approval
submission are not retried by this change. Workflow evaluations retain their
logical call identity, declaration and arguments across attempts. Cancellation
interrupts the wait; exhausted retries fail closed.

The inference dependency is intentionally asymmetric. Cognis's companion
inference endpoints authenticate and confine the Intaris identity to its model
routes, but do not invoke agent/tool guardrails recursively. Cognis forwards
these model calls with provider retries disabled. Intaris owns transient model
retries for both chat and Jev, bounded by its shared evaluation deadline; adding
another retry loop to the Cognis inference hop would multiply attempts.

`stale_resolution` means the original approval no longer matches the current
session or policy. Refreshing the old card cannot renew it. Ask the agent to
evaluate the action again; the old attempt is not silently approved, denied on
the user's behalf, or replayed.
