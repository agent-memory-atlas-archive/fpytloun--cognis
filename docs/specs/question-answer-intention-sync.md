# Human question answers and guardrail intention

Authenticated structured answers are user input, not merely tool output.
Notification resolution is the existing owner of their durable acceptance.

The authenticated REST/WebSocket ingress supplies a controller-only
`human_answer` argument. It is not accepted from the response payload or agent
tools. Agent-mediated `agent_question` responses remain unchanged; this contract
applies to direct and task `step_question` notifications.

Before completing the winning resolution or waking execution:

1. Verify the originating session belongs to the notification owner.
2. Record the stored question as assistant context and the validated selections
   or custom answer as a separate intention-eligible user event.
3. Use a stable notification-based event idempotency key.
4. Invoke the existing event-to-intention update with its wait/evaluation barrier.

Publication failures leave the durable claim unresolved. A same-body retry can
reclaim it after the existing lease expires; a competing answer cannot replace
the accepted body. Retry/recovery must retain authenticated origin. Cancellation
and agent answers do not publish human authority.

The event publication does not fabricate approval or change action evaluation.
It repairs the missing evidence observed when a user corrected an initial PR
target through a question answer and Intaris continued evaluating the old target.

Verification covers publication-before-resolution ordering, question/answer role
separation, payload-origin forgery, duplicate submission, failed-publication
recovery, authenticated task ingress and existing notification API behavior.
No live-session history is rewritten by this implementation.
