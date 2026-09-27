# Creating Agents

Open `Agents` to create or edit agents. An agent defines how Cognis should behave, what tools it can use, which model it prefers, and which workflows it may run.

![Executor tool pool to effective tool set](../assets/images/cognis-agent-tool-inheritance.svg)

## Key sections

### Identity

- agent ID
- name / display name
- description
- avatar URL

These fields make the agent recognizable in the UI and help you distinguish between general-purpose, specialist, and background agents.

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
The current conversation header and session details display an amber warning
while either its conversation override or its agent default enables yolo mode.
Unattended tasks never wait for escalation and deny calls that would otherwise
need approval, even if the agent's maximum outcome permits them.

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

Agents combine curated tool assignment with runtime availability. The effective
tool set is:

1. default/static tools available to the agent runtime
2. plus tools from explicit `tool_groups`
3. plus individual `allow_tools`
4. minus individual `deny_tools` and legacy disabled categories/tools
5. then filtered by executor/MCP/runtime availability
6. with `tool_permissions` applied separately for guardrails behavior

If you leave the executor empty, Cognis resolves it from the agent's label
selector or the system default executor.

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
