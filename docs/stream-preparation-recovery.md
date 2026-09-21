# Stream preparation recovery

The agent loop owns per-generation preparation progress and its size/time budget.
The scheduler owns conversation runtime tool snapshots under its existing
`_active_tool_outputs_lock`; it persists those snapshots to the existing Redis
runtime cache. No canonical tool result is fabricated for unexecuted input.

Every unsuccessful generation exit, including cancellation and fallback,
terminates its preparation callbacks before a retry can start. The provider
stream is closed on unsuccessful exit. Cancellation remains owned by the turn.
The existing normalized provider-error recovery budget bounds retries.

`input_abandoned` is an internal progress phase. It terminalizes only the
runtime preparation item. Completed/failed snapshots cannot be reopened by late
progress. Existing snapshot filtering excludes abandoned items with no result
from complete runtime overlays; no new public wire status is required.

Limits apply to progress-emitting tool preparations, not total turn duration,
ordinary response text, or executor runtime. They are safety defaults of ten
minutes and 262,144 aggregate characters per generation. Size accounting is
monotonic per call and resets only for a new generation. Idle detection remains
independent. Providers without preparation progress retain their existing
stream and token limits.

Failure chunks emitted by a provider are recorded as `provider_error`, not
successful model cycles. Diagnostics contain IDs, counts and categories only.
