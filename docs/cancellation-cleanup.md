# Direct-turn cancellation cleanup

The scheduler owns each local execution task and its conversation registration.
The durable execution wrapper retains its request mapping and lease lifecycle
until the launched task settles. Cancelling the wrapper must cancel and join
that task, not detach it through `asyncio.shield`.

The agent loop owns the acquired session lock for the step lifetime. Handoff
recovery runs before release, and repeated cancellation is deferred until that
owned cleanup settles. An unconditional `finally` releases the original session
lock even if recovery fails. This does not forcibly unlock a running step.

Local Stop and remote cancellation signals do not inject another cancellation
into an already-cancelling scheduler task. The scheduler also releases its local
registration synchronously when execution exits, including when asynchronous
terminal persistence fails. Cleanup checks task/control identity so an old task
cannot remove a successor or decrement its concurrency count.

Durable ordering, fencing, event idempotency, and terminal persistence remain
owned by the existing direct-turn store/runtime. No schema or external API
changes are required. Cleanup can perform existing durable managed-join handoff
recovery; this change does not add new external side effects.

Busy deferrals distinguish `conversation_lock`, `session_lock`, and `active_turn`
in their durable outcome. Warnings at power-of-two attempt counts expose a
persistent blocker without logging every retry. A busy record alone is not
proof that an execution is dead and must not authorize forced lock release.
