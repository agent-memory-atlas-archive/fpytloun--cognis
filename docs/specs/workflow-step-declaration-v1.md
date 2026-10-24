# Workflow step declaration v1

Deterministic `tool_call` steps declare their stored definition scope before
evaluation. This is controller evidence, not a user message or a human approval
of the rendered call. Intaris remains the authorization owner.

## Wire contract

`POST /api/v1/intention`, body containing only `session_id` and `workflow_step`.
Both session IDs must match. The `workflow_step` object contains:

- `version: 1`, `origin: "controller_workflow_step"`
- `session_id`, `task_id`, `workflow_id`, `step_name`, `step_run_id`
- `logical_call_id`
- `workflow_definition_digest`, `step_definition_digest`
- `rendered_args_digest`, `tool`, `evaluated_args_digest`, `executor_id`
- `authorized_by: "owner_configured" | "agent_composed"`
- `projection: "exact" | "unsupported"`

The declaration-only operation targets an existing session. It neither creates a
session nor replaces intention text. Identical requests are idempotent. Conflicting
content for a session and logical call returns 409 with code
`workflow_step_conflict`.

Acknowledgement: `{ok: true, declaration_digest, admission_revision}`. A receipt
is not approval. Cognis validates the receipt and its digest before evaluation.

All digests are SHA-256 hex of UTF-8 JSON with sorted keys, separators `(",", ":")`,
`ensure_ascii=False`, and `allow_nan=False`. The declaration digest covers the
complete `workflow_step` object, without an additional digest field. The step
definition digest covers `{"tool": stored_tool, "args": stored_argument_template}`.
Reusable vectors: `tests/fixtures/workflow_step_digest_vectors.json`.

The dedicated ES256 JWT has audience `intaris`, type `controller`, capability
`intaris:controller_context`, a 60-second lifetime, and binds the owner in `sub`,
`agent_id`, `session_id`, `governing_execution_id=step_run_id`,
`governing_snapshot_id=workflow_definition_digest`, and `declaration_digest`.
It is separate from executor peer-controller credentials.

The acknowledged declaration and its explicit tenant/agent identity travel on a
typed, non-serialized prepared call into evaluation. Declared `/api/v1/evaluate`
requests add top-level `logical_call_id` and `controller_context` containing
`governing_execution_id=step_run_id`,
`governing_snapshot_id=workflow_definition_digest`, and `executor_id`.
They use a fresh dedicated controller JWT with the same claim bindings as the
declaration. Intaris evaluation requires session/execution/snapshot matches;
the additional declaration digest claim remains bound but is not required there.
Ordinary evaluations retain their service JWT and existing body shape.
Admission retries retain the typed binding; stale approval recovery removes only
the old approval receipt and forces escalation as before. Arguments and generic
runtime context cannot create a controller binding.

## Provenance and projection

Nullable `tasks.creation_origin` and `schedules.creation_origin` are controller
metadata. API/UI creation records `owner_configured`; agent creation records
`agent_composed`. Scheduler admission copies the persisted schedule origin.
Agent schedule edits demote the origin. Historical NULL origins are not inferred
from ownership and produce non-granting `agent_composed` declarations. These
fields are not accepted from task or schedule request bodies or tool schemas.

Agent edits to a referenced workflow atomically demote dependent schedules and
tasks. The engine rechecks persisted task and schedule origin after pinning to
avoid trusting a detached scheduler snapshot captured before that edit.
Missing source schedules (including deleted one-shot schedules), demoted schedule
origins, and current schedule workflow definitions that differ from the pinned
task definition are non-granting in v1. Cognis records `schedule_missing` or
`schedule_digest_mismatch` in the step's local `runtime_info.scope_origin_reason`;
this diagnostic is not sent to Intaris or included in the frozen declaration.

The engine binds the pinned effective workflow and stored step before dispatch.
Only the router can supply the final evaluated arguments. Removing the top-level
`target_executor` is the sole verified v1 projection; the actual executor is
bound separately. Any other change (sanitization, enrichment, content stripping)
produces `unsupported`, never a claimed exact match. Remote values are not
rendered a second time and cannot replace the stored tool or template.

An exact declaration does not make interpolated shell data safe. Policy caps,
deny floors, human denials, effect analysis and other restrictions still apply.

## Lifecycle and state ownership

`WorkflowStepScope` is immutable, controller-only state for one dispatch, passed
explicitly through `StepContext` and `ToolRouter.execute`. No model-facing
metadata or generic session details carry authority. No database transaction
is held during declaration or evaluation. Cancellation belongs to the existing
step execution task and propagates normally.

Every dispatch, including executor delivery retries, declares before evaluation.
Scoped calls do not automatically replay after remote MCP OAuth failures; a new
normal dispatch must declare and evaluate again.
Reused sessions do not reuse broad tool approvals. Rotation requires a newly
bound scope. Changed content under the same logical call is a conflict, not an
implicit refresh; uncertain delivery still requires normal reconciliation.
Declaration HTTP, authentication, transport or receipt errors stop dispatch with
a `workflow_step.*` reason (409 uses `workflow_step_conflict`). There is no
fallback to session recreation, ordinary service auth, or declaration-free
evaluation.

Deployment is coordinated: this Cognis client requires the matching Intaris
declaration API. Deploying it first causes deterministic calls to fail closed.
