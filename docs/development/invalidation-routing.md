# WebSocket invalidation routing

Canonical invalidation evicts the relay's read cache, not the current publisher's
accumulated assistant phases. Terminal publication and generation replacement
continue to retire publisher state. This preserves text while canonical history
is delayed without weakening cancellation authority.

Event-store invalidations reuse a positive token-to-connection routing map for
unchanged authorized subscription membership. Unknown tokens rebuild from active
conversation/session metadata, so rotation does not require negative-cache expiry.
Rebuilds are serialized; publication checks membership after database reads.
The map retains only tokens from the last active subscription resolution.
Subscription changes invalidate reuse on the next lookup; returned routes are
checked against current membership after awaits.

Owner routing can use ordinary user conversation subscriptions. Administrators
do not establish ownership: privileged-only subscriptions use the durable lookup.
Owner-wide notification delivery and database fallback remain unchanged.

This removes database reads on warm matching-token invalidations, not on every
possible invalidation. Unknown tokens, rotation and owner lookups without eligible
subscribers still read metadata. No event backfill, persistence or authorization
policy is changed. Production CPU savings require post-deployment measurement.
