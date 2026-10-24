# Creating Agents

For event-driven customization, see [Agent hooks](agent-hooks.md). Hooks inject
instructions or run independent background work for an owned agent.

Open `Agents` to create or edit agents. An agent defines how Cognis should behave, what tools it can use, which model it prefers, and which workflows it may run.

## Editor tabs and saving

Agent settings use one tab bar: **Identity**, **Providers & models**, **Tools**,
**Access & delegation**, **Profiles**, **Workflows**, **Hooks**, and
**Collaboration**. Tabs depend on the agent type and your permissions.
**Collaboration** contains project assignments and sharing; **Identity**
contains availability and system-agent actions. A shared agent's personal
executor settings are under **Access & delegation**.

Configuration changes remain drafts when switching tabs. **Save changes**
(or **Save overrides** for system agents) saves configuration across all tabs.
The save bar indicates whether configuration has unsaved changes.

The following actions save separately and show a success notification when complete:

- Hook assignments, toggles, removal, and **Save parameters**.
- Secondary-agent binding toggles under **Workflows**.
- Sharing, share executor-scope changes, and revocation.
- Activation, suspension, system enable/disable, and personality sync.
- A shared agent's **Save executor** action.

These actions preserve unsaved configuration. Personality sync uses saved
personality, so save configuration before syncing. **Reset overrides** is an
explicit exception: it asks for confirmation before discarding saved overrides
and unsaved configuration. Project assignments are managed from each project's
**Agents** tab and apply there, not through the agent configuration save.

Panels mount on first visit and retain their state afterward. Tool catalogs,
hooks, and collaboration data load when their tabs are first opened.

Under **Providers & models**, memory and guardrails have separate groups.
**Advanced evaluation controls** contains outcome overrides and the escalation
timeout. This group opens automatically when an override is configured; safety
warnings remain visible even when the group is collapsed.

![Executor tool pool to effective tool set](../assets/images/cognis-agent-tool-inheritance.svg)

## Key sections

### Identity

- agent ID
- name / display name
- description
- avatar URL

These fields make the agent recognizable in the UI and help you distinguish between general-purpose, specialist, and background agents.

### Chat quick-switch profiles

Repeated profile switches before the next message update one persistent system
notice in place. The last successful selection remains after reload; admission
of the next message freezes that notice. Individual switches remain in the
session audit log. The settings control is hidden while a turn is running.
An exclamation mark on the selected thumb indicates a session override to the
model, thinking effort, or fast mode. The popover lists the overrides; selecting
the same profile again or **Restore profile settings** clears them.

Assign `quick_switch_color` to a profile to accent its selected switcher fill and active
desktop chip: `neutral` (default), `blue`, `teal`, `amber`, `violet`, or `rose`.
The editor and `manage_agents` profile CRUD support the same palette.
Click or use the keyboard to animate between levels. Drag across the track to
preview a level, then release to apply it once. Canceling the gesture leaves the
profile unchanged. Animations respect reduced-motion preferences.

In **Profiles**, enable **Show in chat quick switcher** for the runtime profiles
you want available beside the chat composer. Set **Quick-switch position** to a
non-negative integer; lower positions come first, with profile ID breaking ties.
Disabled profiles do not appear. These controls are separate from **Agent can
switch to this profile**, which controls autonomous switching.

One quick profile other than the agent default creates an on/off toggle.
Multiple quick profiles create a discrete level selector. The configured default
keeps its position if included; otherwise a Default position is added at the
start. With no configured default, Default uses the agent's base LLM settings.
A default-only selection is hidden because it offers no alternative.

Switching applies to the next message, persists in the conversation, and clears
`/model`, `/thinking`, and `/fast` overrides. It is unavailable while a turn or
another switch is running. A profile selected outside the quick list is shown
as Custom rather than incorrectly marking the default.

Agents can manage the same fields through `manage_agents`:
`runtime_profiles_create` and `runtime_profiles_update` accept
`profile.quick_switch` (boolean, default false) and
`profile.quick_switch_index` (non-negative integer, default 0).
`runtime_profiles_get` and `runtime_profiles_list` return these fields.
Updates preserve omitted fields; set `quick_switch` to false to remove a profile
from the control without deleting it. `runtime_profiles_delete` removes the
profile under the existing default and in-use safeguards.

### Personality

- tone
- temperament
- purpose
- behavioral rules
- system prompt

The runtime identity is composed in two layers:

- `tone`, `temperament`, `purpose`, and `behavioral rules` form the core identity
- `system prompt` adds free-form instructions on top of that core

The editor shows a **System prompt preview** so you can see the exact combined
system message the LLM will receive.

If you use **Sync personality**, Cognis re-bootstraps the structured
personality fields to Mnemory as the evolution seed. This can override evolved
identity in Mnemory, so the UI asks for confirmation first.

For a first agent, keep personality instructions short and practical. Add more constraints only when you know the agent needs them.

### Tools and permissions

#### Existing credential assignments

In a root chat with an owner-controlled primary agent, `manage_agents` can assign
an existing credential without requesting its password again:

- `credentials_get`: supply `agent_id` and `credential_id` to read the assignment,
  safe policy metadata, and the agent's `updated_at` revision.
- `credentials_grant` and `credentials_revoke`: supply the same IDs plus
  `expected_updated_at` from that read. Each operation changes only one
  `allowed_credentials` entry and preserves the other agent permissions.

Both resources must belong to the caller; administrator status does not bypass
ownership. Grant requires an active, unexpired credential whose scope permits
the target agent. These operations never change credential scope or secret
values. Revoke removes the agent's assignment; it does not revoke the credential
itself. A revoked or expired credential's existing assignment can still be removed.
After a revision conflict, read again before retrying. Repeating the desired
state with a fresh revision is safe and returns `changed: false`.

Results contain credential ID, kind, scope, scoped agent ID, status, and expiry,
not password values, payload, free-form metadata, or descriptions. Agent status,
sharing, and activation are unchanged. Updated assignments apply when the runtime
loads the updated agent definition; revocation does not cancel in-flight tool work.

- executor binding (specific executor or label selector)
- additional executors (optional, agent-only routable — see below)
- inherited tool categories from the selected executor
- explicit tool groups plus granular `allow_tools` / `deny_tools`
- legacy category and per-tool disable switches
- per-tool permission policy (`allow`, `evaluate`, `deny`)
- assigned knowledgebases
- allowed secrets
- delegation master switch
- allowed primary and system-agent targets
- primary-agent inbound controller restrictions
- managed-conversation depth

### Intaris evaluation outcomes

**Intaris evaluation** is one human-owned setting: `legacy`, `strict`,
`balanced`, or `bounded_autonomy`. Hybrid modes send `hybrid_v1` and the
selected profile to Intaris; legacy sends `legacy` without a profile.
The default is Balanced. Explicitly configured legacy selections remain legacy.

Delegated child sessions inherit their parent's effective Intaris policy instead
of selecting the child agent's default. Runtime policy refreshes preserve that
inheritance; delegation does not create a new independent policy boundary.

Set `capabilities.intaris_evaluation` on an agent. A task can override it with
`session_policy.intaris_evaluation`; schedules forward the selection in their
task template. The task override wins over the agent setting, then the default.
The task and schedule selectors show both inheritance and the effective value.
Workflow defaults cannot choose an evaluation mode.

Agent null values are invalid. Omitted agent updates preserve the selection.
For a task or schedule policy, null restores inheritance; omitted policy updates
leave the existing policy unchanged. Whole-policy replacement retains the
existing API semantics. Model-authored tools cannot select or clear evaluation
modes, including through nested metadata; prose-only tool updates preserve the
human selection. Existing clauses, outcome bounds, and human approval precedence
still apply.

Hybrid activation requires Intaris to acknowledge the exact active version and
profile. An older server that drops these fields cannot silently run a hybrid
request as legacy. Legacy tolerates older servers that omit the version.
These controls do not repair missing intention or delegation provenance.

Agent settings can select a **minimum evaluation outcome** (`deny`, `escalate`, or
`approve`) and a **maximum evaluation outcome** (`deny`, `escalate`, or `approve`).
In this ordering, deny is the strictest outcome. The minimum selects a stricter
result; the maximum can turn a denial into an escalation or approval. When both
apply, the stricter minimum wins. These settings affect calls actually evaluated
by Intaris, not tools explicitly denied or allowed by Cognis permissions. They
require the Intaris guardrails backend.

**Maximum allow is dangerous (yolo):** evaluated critical and denied calls may
execute. Intaris retains the original result, risk, and policy override in its
audit and analysis. It does not bypass disabled tools, plan-mode write
restrictions, inactive sessions, or a failed Intaris evaluation.

Use `/yolo` to enable maximum allow in the current conversation only;
`/yolo off` restores the agent default. The setting survives Intaris session
rotation, does not change other conversations or the agent default, and cannot
change while a turn is active. Cognis confirms the Intaris policy update before
acknowledging the command.
Agents receive a bounded current-policy notice in task, chat, and managed
conversation prompts, based on the acknowledged Intaris session rather than
agent defaults. The notice refreshes with current policy and session changes.
Unavailable fields are reported as unknown. Historical evaluation denials do
not automatically establish a current prohibition; explicit human refusals,
operational preconditions, and normal tool evaluation still apply. The notice
is controller-policy evidence, not a new user authorization.
The current conversation header and session details display an amber warning
while either its conversation override or its agent default enables yolo mode.
Unattended tasks never wait for escalation and deny calls that would otherwise
need approval, even if the agent's maximum outcome permits them.

The agent **Approvals** setting (`capabilities.approval_mode`) applies the same
behavior to every session of an agent. `ask` (default) shows approval requests.
`unattended` lets the Judge approve or deny, and nothing waits for you: an
escalation, including a maximum outcome of `escalate`, becomes a denial. It
applies in direct chat, child sessions, and tasks without an explicit
interaction mode; a task's own interaction mode takes precedence. Only the
human UI/API can change it; model-authored tools are rejected.

### Escalation timeout

Set **Escalation timeout (seconds)** in agent settings or via `manage_agents`
`settings_update`. Empty inherits the global `session.escalation_timeout_seconds`
setting (300 seconds by default). Tasks can override the agent via their
creation/edit UI, API, or `create_task` and `update_task` tools. Valid overrides
are whole seconds from 1 to 86400; setting a task override to `null` restores
inheritance. Precedence is task, then agent, then global.

The effective timeout is recorded when an escalation is created, so changing
settings cannot extend an already pending approval. Expired escalations are
denied; unattended tasks never wait for one.

Approval cards and channel messages include the action's ID and safe argument
preview. Use `/approve --id <approval-id> [note]` or
`/deny --id <approval-id> [note]` to select one particular action. A bare command
only resolves when exactly one actionable approval is pending; otherwise it
lists the choices without resolving anything. Expired approvals cannot be
revived. See [actionable approvals](actionable-approvals.md).

Agents combine curated tool assignment with runtime availability. The effective
tool set is:

1. default/static tools available to the agent runtime
2. plus tools from explicit `tool_groups`
3. plus individual `allow_tools`
4. minus individual `deny_tools` and legacy disabled categories/tools
5. then filtered by executor/MCP/runtime availability
6. with `tool_permissions` applied separately for guardrails behavior

Owner-managed agents must explicitly bind an executor ID or a non-empty label
selector. They do not fall back to the system default executor.

Use `manage_agents` `settings_update` with `settings.executor_id` or
`settings.executor_selector` to change the primary binding. IDs and selectors
must reference executors available to the agent owner (owned or shared).
Selectors are non-empty objects of non-empty string labels and must match at
least one available executor. Runtime readiness and executor policy are still
checked when the agent runs.

Omitted fields are preserved. A non-null ID clears the selector, and a non-null
selector clears the ID. Setting both to non-null values is rejected. Null clears
only the named field; clearing the last primary binding leaves the agent unable
to run until configured again. Other execution settings, including additional
executors and workflows, are preserved.

This operation does not change sharing. A `grantee_executor` share continues to
use the grantee's override or their default executor, never the owner's binding.
Grantees cannot change the owner's settings through `manage_agents`; they can
configure their own executor on the shared agent page.

Knowledgebase assignment is separate from tool assignment: `allowed_knowledgebases`
controls which KBs the agent can access, while knowledgebase tools control what
the agent can do with those KBs.

Delegation is split into two domains:

- **Primary agents** receive managed conversations or cross-agent task
  ownership. Managed depth `1` allows one worker level; depth `2` allows a
  coordinator and worker. Managed descendants cannot assign tasks to another
  agent to bypass this limit.
- **System specialists** receive bounded synchronous `delegate()` calls. They
  cannot delegate further or create managed conversations, tasks, schedules, or
  workflows.

The allowed target list applies to both domains. Primary target IDs authorize
managed work and task ownership; `system:*` IDs authorize specialist calls.
Restricting the list while leaving it empty disables every outbound target
except the agent itself. Primary agents can always assign managed work or tasks
to themselves. Primary agents also have an inbound controller list. An empty
restricted inbound list prevents every other agent from targeting that agent
while preserving self-targeting, which is appropriate for user-facing executive
agents that must never be launched as children.

Use `manage_agents` tool CRUD actions (`settings_get/update`, `tools_get`,
`tools_set/add/remove`, and `knowledgebases_*`) rather than guessing IDs or
editing raw blobs. `settings_update.delegation` supports the same delegation
policy shown in the agent editor. Use
`search_tools`, `describe_tool`, and `validate_tool_call` for authorized discovery,
operation semantics, and mutation preflight.

#### Secondary and shipped system agents

User-owned secondary agents (`create` with `agent_type="secondary"`) support the
same `manage_agents` actions as primary agents. They never receive management
tools. `bindings_set` applies only to primary agents and accepts only owned
secondary agents; shipped `system:*` agents need no binding.

Shipped `system:*` agents are code-defined. `manage_agents` `list` reports them
under `system_agents`, and they are tuned per user through overrides:

- `system_overrides_get` (also `get`): shipped values, the stored override, the
  effective definition, and `override_updated_at`.
- `system_overrides_update`: an `overrides` patch of `llm_config`, `skills`,
  `tools`, `permissions`, `agent_profiles`, and `default_agent_profile_id`.
  Omitted fields keep the stored override, `null` restores the shipped value,
  and a supplied object replaces the whole field. Tools beyond the shipped set,
  skills, knowledgebases, and credentials must be available to the caller.
- `system_disable`, `system_enable`, and `system_overrides_reset`.

All accept an optional `expected_updated_at` from the last read; an empty
string asserts that no override exists yet. Internal hidden system agents are
read-only.

### Additional executors (Stage 36)

The agent editor lets you attach additional executors next to the primary
executor binding. Each entry is either a specific executor or a label
selector, plus an optional description.

Additional executors are not auto-selected. The agent reaches them in two ways:

- `target_executor=<id>` on a single tool call — runs that one call on
  the named executor without changing the conversation's active binding.
- `switch_executor` tool (or the `/executor <id>` slash command) — moves
  the conversation's active routing slot to that executor for all
  subsequent tool calls until the next switch.

When the active executor is in the additional set, every LLM turn shows
a hidden reminder so the agent stays aware that it is on a non-primary
host. The controller never auto-changes the binding; the agent (or user)
is the only mutator.

### MCP servers

Global MCP servers are managed from **Settings → Tools**, then assigned to
executors from **Settings → Executors**. Agents do not own MCP server process
config anymore — they inherit MCP tools from the executor they run on.

The agent editor can also allow **Intaris MCP servers** directly for that agent. Use that path when the remote MCP capability is managed by Intaris rather than attached to the executor tool pool.

Legacy inline MCP entries may still appear on older agents with:

- name
- command
- arguments
- environment variables
- timeout

Use **Settings → Tools** to create, edit, and test configured MCP servers.
Use **Settings → Executors** to attach those MCP servers to a specific
executor. Agent-side tool toggles then control whether the agent can use the
MCP tool categories provided by that executor.

### LLM configuration

- provider selection
- model override
- temperature
- max tokens

Use overrides only when the agent really needs different behavior from the default routing policy.

### Workflow settings

- available workflows
- default workflow
- selection mode
- step agent overrides

Workflow settings matter most when the agent should do structured background work instead of only direct chat responses.

## Practical create flow

In the create form, the most useful order is:

1. identity and display fields
2. personality and behavior guidance
3. executor and tool restrictions
4. provider/model overrides only if necessary
5. workflow defaults for structured execution

Most agents should inherit as much as possible from system defaults and only override what truly makes them different.
