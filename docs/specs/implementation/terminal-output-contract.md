# Terminal completion and required-run output ownership

The workflow-owned resolver proves the existing sequential run chain plus one
unconditional trailing successful silent `complete` with null content and
notification. It does not disregard arbitrary deterministic nodes, branches,
cycles, early termination or unknown context positions.

`WorkflowEngine._execute_complete_step` puts `complete.outputs` in
`StepOutput.outputs`, not in its content or deliverable ID.
`_resolve_final_deliverable` selects required run artifacts, and
`_build_result_data` prefers that artifact's content and ID before any
last-step fallback. Thus the verified canary's nonempty outputs cannot change
the canonical producer. Explicit content and notification variants remain
unproven/strict rather than broadening the terminal semantics.

## State and compatibility

The resolver is pure, derived from the pinned workflow and current step.
AgentLoop's added validation diagnostic is per-call metadata only; it does
not change transactions, locks, cancellation, receipts, replay or retries.
Existing validation-state fingerprints remain authoritative. No new database
state, policy grants or cross-agent history transfer is introduced.

## Evidence provenance

The fixture preserves both root-verified structural snapshots and persisted
digest labels. Omitted prompt/objective text is not evidence of absence.
Fixture normalization does not recompute or claim to match the original
unsanitized digest. Engine tests substitute only owned synthetic actor IDs
and supply local service doubles; they use real graph normalization, claim,
fence, native validation, artifact persistence and completion.
