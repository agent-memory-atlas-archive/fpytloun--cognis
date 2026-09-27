# Context management

Cognis first reduces the model-facing prompt through **projection**. It uses
**compaction** when projection cannot make the prompt safe, or when you request
`/compact`. A large prompt does not by itself mean compaction is necessary.

## What the numbers mean

| Metric | Meaning |
|---|---|
| Effective prompt budget | Model input capacity after output reserves, input limits, and serialization safety margin. |
| Steady target | Soft goal for between-turn projection, not a compaction limit. |
| Within-turn burst | Working-evidence sizing allowance; not a switch that automatically selects critical mode. |
| Hard target | Projection policy ceiling. |
| Loop pressure | Additional safety boundary at 95% of the effective prompt budget. |
| Effective hard boundary | The lower of hard target and loop pressure. Both checks remain enforced. |

The runtime rejects a projected prompt above the hard target, or at/above loop
pressure. These boundaries are deliberately inside the provider's capacity.
The legacy 85% assembly recommendation does not independently trigger
pressure-driven compaction. Manual compaction, provider-reported overflow
recovery, and idle checkpoint compaction are separate entry points. Long-lived
chats can checkpoint after the configured idle interval and minimum event count,
even below these token boundaries; that lifecycle policy is unchanged.

Token usage includes tool-schema overhead. Local estimates are calibrated from
provider observations only when session, provider, model, and estimator identity
match. Raw and calibrated usage are not interchangeable. The displayed policy
must use the same resolved model budget as the usage snapshot, including when
the previous projection is reused.

### How targets are calculated

Let `A` be the effective prompt budget. Integer token counts are rounded down:

- Steady: `min(0.88 × A, steady cap)`.
- Burst: at least steady, otherwise `min(0.95 × A, burst cap)`.
- Hard: capped at `A`, at least burst, and otherwise the lower of
  `0.98 × A` and `1.1 × burst cap`.

| Model context window | Steady cap | Burst cap |
|---|---:|---:|
| Up to 150k | 95k | 115k |
| Up to 300k | 180k | 245k |
| Up to 500k | 250k | 360k |
| Above 500k | 320k | 600k |

These are current implementation defaults, not provider pricing boundaries.

## Between turns

1. Assemble canonical history and required instructions.
2. Above steady, try normal then pressure projection toward steady.
3. Preserve instructions and unrecoverable evidence even if steady cannot be met.
4. Before any model request, run the model-facing projection/budget gate.
5. Only unresolved hard pressure enters automatic compaction/recovery.

Thus, crossing steady is not a requirement to summarize the conversation.

## During a turn

The controller does not inject percentage-based instructions telling the model
to wind down its work. Usage telemetry, projection, hard-budget enforcement,
and compaction recovery remain active. Removing these advisory messages changes
only the in-memory prompt; no persistence, locking, retry, or cancellation
contract changes.

Context can grow above steady as the agent reads files, runs tools, and reasons.
The conditional projection pipeline can reconsider projection above steady,
when tool output is large, or when pressure changes. It may reuse the previous
projection when safe. Reuse still receives a model-facing budget check.

Normal, pressure, and critical modes progressively reduce retained tool detail.
Mode selection uses pressure bands and hysteresis; burst is not the mode switch.
The usage bands are 92% for pressure and 97% for critical, measured against the
effective prompt budget. Dropping to a lower mode requires two consecutive
cycles below its band. A failed hard-budget check can force stronger projection
before those percentages are reached, particularly for large context windows.
If the selected result violates the effective hard boundary, the loop tries
stronger projection before compaction. Being above steady can persist for a long
turn because useful protected evidence remains and the result still fits.

## What projection preserves

Evidence selection is rule-based, not semantic understanding of relevance:
current-turn/recent tool groups, explicit protection and recovery metadata, and
groups already committed to the model influence preservation. Critical pressure
can demote more evidence than routine projection. User/developer instructions
are not discarded merely to satisfy a soft target.

Projection replaces eligible bulky tool output with compact recovery references.
The durable source remains available, but reopening it costs another tool call
and requires the agent to recognize the need. Compaction instead summarizes
conversation history and continues through session rotation. A failed or
zero-turn attempt must terminate visibly rather than leave a running card.

## Worked examples

These are illustrative resolved budgets, not universal model constants.

### Codex: 250,240 available tokens

With the Responses 8% serialization margin:

- Steady: **220,211**
- Burst: **237,728**
- Hard target: **245,235**
- Loop pressure: **237,728** — the binding safety boundary

At **106,044**, no size-driven reduction is needed. At **216,478**, usage is
above the old 85% threshold but below steady: that alone must not compact.
At **230,000**, between-turn projection tries to return toward steady; if it
cannot and the model-facing prompt remains safe, work continues. At/above
**237,728**, stronger projection must make room before another model request;
otherwise compaction/recovery follows.

Values 229,785 / 248,064 / 255,897 correspond to a different, 4% margin budget
and must not be displayed alongside the 250,240 budget.

### Large-context Claude: 839,232 available tokens

- Steady: **320,000**
- Burst: **600,000**
- Hard target: **660,000** — the binding ceiling
- Loop pressure: **797,270**

At **350,800 calibrated tokens**, between-turn projection tries to reduce
usage toward 320,000. During a turn, that usage is allowed; retained evidence
may keep it above steady. Crossing 600,000 does not independently require
compaction or select critical mode. Above 660,000, stronger projection must
reduce usage enough; unresolved pressure falls back to compaction.

## Manual control and limits

### Compaction in the chat timeline

Automatic recovery appears as one compaction card: **Compacting**, then
**Compacted**, **Failed**, or **Skipped**. Mid-turn cards belong at the tool/model
boundary where recovery happened, not at the beginning of the turn. The started
event is durable, so reconnecting during recovery can reconstruct the card.
Session rotation keeps the same compaction occurrence ID.

For example, 668,585 tokens exceeds Claude's 660,000 hard target even though it
is below the 797,270 loop-pressure ceiling. The card's reason identifies the
binding hard limit. Successful recovery continues the turn without leaving a
separate "stopping this turn" warning. If recovery cannot resume, an explicit
failure notice remains. Historical pressure warnings are suppressed only when
the projected history contains a successful compaction with the same occurrence
ID; unrelated failures are not hidden.

Use `/compact` when you deliberately want a summary boundary. It should not be
routine maintenance required to keep the automatic budget checks working.
Provider overflow can occur despite local estimates and follows bounded
recovery. If projection and compaction cannot make the request safe, the
controller stops rather than retrying indefinitely.
