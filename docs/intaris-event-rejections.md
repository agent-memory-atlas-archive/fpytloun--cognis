# Intaris event append failures

The event sender recognizes `X-Intaris-Event-Error: session_not_found` on a
404 response. Only this explicit category enables the existing opt-in,
bounded missing-session retry and unsuccessful `EventAppendResult`.

Disabled recording, unknown codes, and legacy receivers without the header
raise the original HTTP error. This conservative legacy fallback does not
parse error messages, infer session absence, recreate sessions, or discard
events. Successful responses from older receivers remain supported.

An explicit `append_uncertain` response is not automatically retried. Existing
generic transient retries remain bounded; no generic 4xx retries were added.
409 in-progress/uncertain responses propagate to the caller without replay.
Cancellation propagates and does not create a detached retry task.

The HTTP adapter does not own durable pending events. These changes do not
provide crash recovery for callers that lack durable intent, or make the
receiver's buffered acknowledgement durable. Such guarantees need a separate
producer/persistence contract, not a hidden queue inside the provider.
