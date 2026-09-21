# History replay integrity

Model history is reconstructed from canonical Intaris events by
`events_to_messages`, shared by chat and workflow context assembly.
Guardrail evaluations, intention updates, and other audit-only events are not
model turn boundaries. They must not split a parallel tool-call batch or settle
an outstanding call before its canonical result.

`history_replay.py` owns event visibility and auxiliary notice ordering.
Model-visible feedback, delegation updates, and context notices arriving inside
a tool batch are replayed after its results. User/assistant boundaries and the
end of available history retain existing missing-result handling. Signed native
blocks are never rewritten, and absent native results are never invented.
An incomplete native batch is removed from the native protocol but retained as
historical evidence: assistant text stays assistant text, recorded outputs are
escaped untrusted data in a labelled user-role context message, and missing
outcomes remain explicitly unknown. Error flags and recovery references survive.
The evidence is not a new user request or an instruction to repeat tool calls.
Removing an incomplete native batch emits an ID-only warning.

For non-native history, the existing explicit missing-result marker is placed
beside its owning assistant tool-call batch, even if subsequent tool batches
were already replayed before the interruption was detected. Appending that
marker at the history tail would violate Anthropic's immediate-result contract.
The marker describes an unknown outcome, not a successful or failed execution.

Empty strings are valid recorded tool results, including errors. Current
`result` text takes precedence over legacy `output`, even when empty.
Both context assembly modes reject fallback to a known-stale cache when
canonical refresh fails, propagating the original failure. A later successful
refresh restores normal assembly; healthy warm-cache degradation is unchanged.

The September 2026 incident was reproduced from canonical events: an approval
evaluation between a native tool call and its result caused orphan cleanup to
delete the assistant/tool batch and ignore the later result. Non-native history
instead retained a false missing-result placeholder. This affected subsequent
turn reconstruction, not only controller restarts.

The fix changes derived model history only. It does not mutate canonical events,
change guardrail authorization, or require a database migration or Redis flush.
Existing history is reconstructed correctly on the next context assembly.
Already-created lossy compaction summaries cannot be repaired by this change.

Regression coverage includes audit interleaving, parallel results, auxiliary
notices, actual missing results, raw/cached events, and Redis serialization.
The incident's 588-event history was also replayed in memory without model
calls or external mutations.
