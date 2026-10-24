# Task-managed process lifecycle admission

Status: implemented candidate; rollout must install the consumer first.

Starting a controller-managed background process requests its bounded task
lifecycle, including later termination of that exact process tree. This is the
default, not an agent-provided permission claim. It does not authorize terminating
external services, unrelated processes, or workloads explicitly required to remain
running.

## Owners and identities

- Intaris owns the final spawn admission, restrictions and cleanup admission.
- Cognis owns authenticated dispatch and the join between the Intaris decision,
  originating tool call, conversation and task execution.
- The executor owns the immutable process incarnation and current registry state.
- Task executions bind task ID and attempt. Direct workflow turns without a
  durable task bind the owning conversation; session rotation is not a new owner.
- Neither an agent description nor `authority=context_only` creates or denies
  lifecycle authority.

## Admission and registration

1. Cognis supplies a versioned, authenticated declaration for native managed
   background execution. It includes the actual evaluated argument digest, user,
   agent, conversation, execution scope and logical call ID.
2. Intaris evaluates starting and later stopping the task-managed process as the
   declared scope. Its final admitted call ID is the durable authority reference.
3. Only after successful executor registration can that reference bind a shell.
   Bind canonical executor, shell ID, originating tool call and process incarnation.
   Approval without registration cannot authorize a fabricated resource.
4. Do not retrofit missing receipts from ownership alone. Old processes retain
   existing evaluation unless their original admission and registration can be
   verified under an applicable lifecycle contract.

## Cleanup

Cognis discards caller-supplied lifecycle claims, resolves fresh registry state
and sends an authenticated declaration bound to the exact cleanup arguments.
Intaris verifies the originating admission and identity chain. Established
lifecycle scope is a distinct policy permission basis, not a human approval.

Review may assess a concrete current restriction or additional effects; it must
not demand a new quotation authorizing a stop already included in the admitted
lifecycle. Explicit keep-running instructions, human checkpoints, protected/shared
targets and identified active dependencies remain restrictive. A speculative
future consumer inferred from a broad workflow goal is not an active dependency.

The executor must recheck the resource identity immediately before termination.
Retries cannot target a replacement process. Missing, mismatched, revoked or
unsupported declarations fail closed or retain ordinary evaluation.

## Lifetime and compatibility

The receipt belongs to the registered process lifetime, not one LLM turn.
Completion or revocation retires it; task completion alone must not prevent
cleanup. No new copy of Intaris decisions belongs in Cognis DB. Executor metadata
may carry the opaque admission reference and execution identity.

Deploy consumer support before producer use. Until the consumer acknowledges the
versioned contract, no producer may claim lifecycle authority. Preserve existing
evaluation when the feature is disabled.

## Acceptance

- Admitted task-helper spawn, authenticated registration, cleanup admission and
  actual termination of an isolated helper through the executor.
- External service remains untouched.
- Wrong user, conversation/task attempt, executor, incarnation or originating
  admission cannot establish authority.
- Explicit keep-running and concrete active-dependency controls remain blocked.
- Forged runtime metadata, unapproved/failed spawn, completed resources and stale
  cleanup declarations cannot authorize a different process.
- Session rotation, transport retries and cancellation retain current ownership
  and idempotency guarantees.

Verification includes real native process registration and termination through
router/provider/executor, missing acknowledgment and stale-incarnation controls,
and separately signed Intaris HTTP admission/audit/cleanup tests. The existing
prompt-only cleanup candidate failed real-model acceptance and is not a
replacement for this contract. Old processes without the acknowledged binding
retain the ordinary review path; no retroactive admission is fabricated.
