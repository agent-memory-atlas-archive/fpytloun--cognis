# Guardrails runtime context

`ToolRouter._evaluation_context` supplies canonical `context.tool` with bounded
annotations and selected native operation facts. Operation selection reuses the
same owner as descriptor validation/introspection. The projection retains source,
authority, selector, schema version/hash, mutation kind, summary and side effects;
it never sends entire schemas or changes permission policy.

`artifact_publish` is CREATE, not READ: the executor reads the source file, but
the controller persists a private owner-scoped Cognis artifact. Its description
and operation contract state that storage does not itself send to an external
recipient or channel. Generic guardrails consume this contract without a tool
exemption.

The runtime section reads existing loaded-skill snapshots. IDs, version/hash,
name and a short description are bounded to approximately 1.8 KB, with explicit
missing/truncated/omitted markers. Activation/reload and reconstruction retain
the description in the existing snapshot owner. Removal and session rotation
use that owner's lifecycle, not a second summary cache. Attached-but-unloaded
catalog skills are not included. Skill context never grants permission.

Canonical tool-result events include bounded execution outcome metadata.
Only native shell result metadata contributes shell identity/status/exit code;
tool output text is never scraped. Recent context joins call/result IDs from the
same cached session plus pending current-turn events. It carries tenant/session
identity, bounded target fields, status/error and executor/process identity.
Approval without execution does not become success, and missing recorded
outcomes remain unknown. Guardrails consumers must redact the resulting model
view and preserve these provenance and incompleteness markers. Cognis redacts
complete credential-bearing values before any truncation, through the shared
common runtime-evidence transport boundary. Descriptions survive canonical
loaded-skill event reconstruction as well as the live snapshot path.
The same boundary recognizes credential key components in environment/JSON
assignments and dictionary labels (including AWS secret access keys and session
tokens). It withholds complete ambiguous credential-bearing scalars before
240/220-character summary/target limits. The snapshot owner also redacts skill
descriptions at live insertion and canonical replay.

## Current policy notice

Canonical `ContextAssembler` injects a `CURRENT POLICY SNAPSHOT` for task,
main-chat and managed context, including memory-disabled turns. The focused
`current_policy_context` collaborator reads the authenticated current Intaris
session, checks its tenant/session identity and projects only acknowledged
evaluation mode/profile, outcome bounds, interaction mode and optional revision.
Missing, invalid or unavailable fields remain unknown; agent capability defaults
and historical audit/journal denials are not substitutes for an acknowledgment.
The notice is observed controller policy, not a new human grant. Human refusals,
operational preconditions and ordinary tool evaluation remain binding.

State is turn-local and protected from pruning, not an immutable-prefix entry or
second persistent cache. Existing shared redaction precedes rendering; finite
labels and integer revision bound the notice without policy-prose duplication.
Assembly/rebuild/rotation reads the current owner, and subsequent model cycles
replace the existing notice before prompt budgeting. This adds read-only external
I/O outside DB transactions, with cancellation owned by the calling turn.
Read failures render unknown; they do not alter fail-closed tool evaluation.
Repeated reads/replacements are idempotent and produce one notice. Optional
session response fields preserve compatibility with older Intaris responses.
