# Background shell termination evidence

Before dispatching the native `bash_kill` tool, the controller resolves the exact
shell on the already selected executor. The target must match the current user,
conversation and executor. Session rotation within that conversation is allowed;
the original session and originating call remain part of the evidence.

Remote status is bound to the authenticated controller-side executor connection,
including when routed through another controller replica. An executor's local
label (for example `remote`) is preserved as `reported_executor_id`, not used as
the routing identity. This requires no executor upgrade and also covers jobs
started before the controller upgrade. User and conversation checks are unchanged.

The bounded, credential-redacted snapshot includes command, purpose, working
directory and current status. It excludes process output and unrelated jobs.
Missing, foreign, ambiguous or unavailable targets are represented as unknown.
Incomplete and truncated snapshots are marked explicitly. The lookup is
read-only, timeout-bounded and repeated for each dispatch, not cached.

Intaris must support the `shell_target` runtime section to deliver this evidence
to both policy assessment and Judge review. Evidence describes a target; it is
not permission to stop it. Existing authorization, approval and execution
ownership checks remain responsible for the decision and action.

The snapshot is point-in-time: a process can complete after assessment. The
executor's normal shell-ID lookup and termination behavior still apply.
