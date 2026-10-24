# Tools and Skills

The `Tools` workspace helps you understand what Cognis can execute and how those capabilities are exposed to agents.

## Tool registry

The tool registry lists available tools from multiple sources, including:

- built-in executor tools
- MCP tools
- skill-defined tools
- orchestration-related capabilities
- system utilities

Use the filters to narrow by category or source when you want to understand what is available before enabling it on an executor or agent.

Tool categories also drive workflow step tool profiles. A step profile can reduce which categories and capabilities are exposed by default for a specific step without changing the agent's underlying capability boundary.

Built-in, controller, and executor-native tools have declared classifications.
Their profile group and capabilities come from structured tool metadata, not
keywords in descriptions. Native definitions are audited at registration.
Only external MCP and executable skill tools use dynamic classification.

## Why the registry matters

The registry is a reference view, not the final permission model.

Whether an agent can actually use a tool depends on:

- which executor it resolves to
- which tools and MCP servers that executor exposes
- which skills are active on the agent
- which Intaris MCP servers are allowed directly on the agent
- which restrictions the agent applies on top
- whether Intaris allows, escalates, or denies the runtime call

For direct chat, tools in an explicitly assigned `tool_groups` collection that
belongs to the core `filesystem`, `shell`, `development`, or `web` groups are
normally visible under `system:direct-default` (soft). This does not override
other soft profiles or their intended defaults. Explicit exclusions, hard
profiles, and the effective authorization inventory still constrain exposure.
Long-tail MCP, administration, and skill tools remain deferred; discover them
with `search_tools`. A tool name mentioned in guidance is not itself callable
unless its schema is currently visible.

Controller discovery appends results to the conversation without promoting found
tools into the initial tool list. Use `describe_tool` for a discovered tool's schema
and `call_tool` to invoke it, unless it is already directly visible. The existing
discovery events retain handles across turns; every invocation still checks the
current permissions and step profile. Skill activation also appends instructions
and eligibility without changing direct schemas. Sessions that can load skills use
the fixed controller discovery surface from the first request, including Anthropic
and inference fallback candidates. Other Anthropic sessions may use native deferred
tool references. Permissions, model changes or external inventory changes can
intentionally change exposure.

The agent-loop turn owner owns rejected-tool repair state, retry budgeting, and
lifecycle events. Typed recovery state is keyed to the controller `turn_id` and
survives same-turn profile switches and compaction reentry; a new turn resets it.
The recovery planner is pure: it proposes safe bridge guidance from the
current authorized inventory instead of adding a direct tool schema. The retry passes through normal exposure
planning and `ToolRouter`/Intaris authorization; rejected arguments and
incomplete provider tool calls are discarded. Successful recovery records
discovery through the canonical `tool_discovery` lifecycle event so session
cache replay restores the handle consistently.

## Model-specific file editors

Cognis selects file editors from the authorized inventory before tool discovery:

- GPT-5, GPT-6, and Codex models use `apply_patch`.
- Anthropic models use `edit`, `multiedit`, and `write`.

The selected editors are directly visible without `search_tools`, including under
tool-slot pressure. An insufficient slot limit produces an error instead of
silently hiding the editing surface.

Discovery and indirect calls cannot restore incompatible editors. This policy
does not grant missing tools or bypass read-only restrictions. External MCP tools
with similar names retain their own authorization.

## Skills

Skills are reusable instruction bundles stored in the database and exposed through the `Tools` workspace and skill APIs.

Today, the most visible skill workflow is:

- create or edit database-backed skills
- import skills from supported external formats such as `SKILL.md`
- export skills for sharing or version control
- organize skills with tags and global attachment behavior
- attach skills to agents so their instructions are available at runtime

Depending on the imported format and runtime configuration, a skill can also carry richer metadata such as templates, assets, or tool-related information. This guide focuses on the shipped workflow you can use directly from the current app.

In practice, a skill can expose capability in three distinct ways:

- **Instructions** for reasoning and operating procedure
- **Linked runtime tools** that point at existing builtin or MCP tools already present in the registry
- **Bundled executable skill tools** that ship inside the skill version itself

Skills may also store a **saved workflow decomposition**. That decomposition is treated as a skill-owned template, not as a persistent workflow definition by itself.

### Managing skills

In the UI you can:

- create and edit database-backed custom skills
- import skills from a URL, including `SKILL.md`-style sources
- export skills for sharing and version control
- organize skills with tags
- attach a skill to all agents by default
- bind linked runtime tools that should become available when the skill is attached or explicitly loaded
- review or save workflow decomposition on the skill itself

### How skills work at runtime

Skills use a hybrid lazy-loading model for token efficiency:

1. **Compact metadata in the system prompt** -- visible skills are announced in the immutable prompt prefix with an ID, name, short description, and attachment/loading state. Tool inventories are omitted. Attached skills are marked so the agent knows which ones are preferred defaults.
2. **On-demand loading via `skill_load`** -- the agent uses the `skill_load` tool to read full instructions when a skill is relevant to the current task. Instructions, prompt templates, and asset references are loaded into the mutable context, not the cached prefix. Saved workflow decomposition and tool summaries stay out of the model context.
3. **Deferred tool exposure** -- linked runtime tools and bundled executable skill tools are discoverable but treated as deferred. Attached skills start available by default; other skills expose their tools through the normal tool runtime after the agent loads the skill, without duplicating their schemas in the skill context.

This means:
- adding or removing skills does not invalidate the entire prompt cache
- the agent only pays token costs for skills it actually uses
- skill edits are visible on the next turn without restarting the session
- after `skill_load`, the loaded skill's linked runtime tools and bundled executable tools become eligible for subsequent model calls in the turn
- if a skill carries saved decomposition, tasks and schedules that use that skill materialize from the latest saved skill version

### Portable skill assets

`skill_load` automatically verifies and caches the current version's assets under
`COGNIS_DATA_DIR/skill_assets` (default `~/.cognis/skill_assets`) on the active
authorized executor. The returned manifest and loaded context include each
asset's `local_path`, executor ID, version ID, and SHA-256 hash. Relative bundle
directories are preserved. Matching cached files are reused; replacements are
atomic and versions have separate paths.
Asset preparation currently supports Linux and macOS executors. Unsupported
platforms return an explicit preparation error rather than reporting a load as
successful.

Reload after publishing or replacing assets, switching executors, or losing
cached files. Load sends the authorized version directly, so it does not depend
on a configure-time executor snapshot or a restart. The separate
`skill_asset_materialize` tool is retired. Automatically injected instructions
without prepared paths still require `skill_load` before using asset-only helpers.

Publish required helper scripts, templates, and static resources as versioned
skill assets. Do not depend on scratch files, absolute executor paths, unbundled
neighboring resources, or prior session state. Document external dependencies,
discover runtime configuration at execution time, and never bundle secrets.
Verify publication → load → execution without the original workspace before
reporting a skill complete. A preparation failure is a runtime blocker, not
permission to use an old local copy or claim end-to-end success.

### Agent skill selection

In the agent editor, you can select which skills to attach to an agent. Attached skills are highlighted in prompt metadata and their tools are available immediately through the deferred tool-loading path.

Attached-skill defaults now include linked runtime tools as well as bundled skill tools. This lets a skill bring an existing builtin or MCP tool surface into scope without duplicating that tool definition inside the skill.

Some shipped system agents also come with default attached skills. For example,
`system:implement` and `system:code-review` attach the built-in Cognis coding
skill by default. When a system agent allows overrides, its attached skill list
can be replaced per user through the normal agent editor.

All visible skills remain discoverable via prompt metadata and `skill_load`. Resolution order is deterministic: agent-attached skills first, then skills attached to all agents, then other discoverable skills.

### LLM skill management

Agents can manage skills through built-in tools:

- `skill_list` -- list available skills
- `skill_load` -- load a skill's full instructions and related metadata
- `skill_get` -- get skill details for inspection or debugging
- `skill_versions` -- inspect version history
- `skill_write` -- create or update a skill (creates a new version)
- `skill_asset_write` -- add or replace a text/script asset on a skill
- `skill_asset_delete` -- remove an asset from a skill
- `skill_delete` -- delete a skill
- `skill_import_url` -- import a skill from a URL
- `skill_restore_version` -- restore a previous immutable version
- `skill_export` -- export a skill as SKILL.md, YAML, or a full Cognis package

All mutation tools are non-bypassable and evaluated by Intaris guardrails. When an agent creates or imports a skill, Cognis automatically attaches it to that agent for future runs.

An asset upsert can reuse `existing_asset_id` under a different filename. Renames
copy verified bytes into a new immutable storage object; the original version
remains loadable and restorable. Same-name reuse retains the existing storage
object. Remove the old filename in the same patch when replacing rather than
adding an asset.

When a skill already has saved decomposition and its decomposition-driving inputs change, Cognis refreshes that decomposition before publishing the new current version. If the refresh fails, the update fails rather than leaving the latest saved version stale.

### Built-in Cognis skills

Cognis also ships global management skills for Cognis-native operations such as task and workflow management. These skills are intended for the main chat agent and are discoverable through the normal skill tools (`skill_list`, `skill_load`). They guide the agent to inspect state first, use the correct management tools, and avoid mutating protected resources such as system workflows.

Cognis also ships reusable execution guidance. `Cognis Coding` defines the
software delivery workflow. `Cognis Frontend Engineering` adds product judgment,
interaction completeness, visual restraint, and cross-surface validation for
product pages, web and mobile apps, dashboards, and control centers.

### Importing skills

Skills can be imported from:

- **Raw SKILL.md URLs** -- any HTTPS URL pointing to a SKILL.md file
- **GitHub blob URLs** -- automatically resolved to raw content
- **GitHub folder URLs** -- `SKILL.md` is inferred inside the folder
- **Cognis YAML** -- the native portable format
- **Cognis package** -- the full-fidelity portable format for skills with attached assets

Import security:

- HTTPS required for non-localhost URLs
- Private/reserved IP addresses are blocked (SSRF protection)
- Response size limits (10MB default)
- Redirect validation on every hop
- Provenance recorded (source URL, resolved URL, commit SHA, checksum)

### Executable skill tools

Skills can define tools with execution recipes. These bundled executable tools appear as first-class tools in the agent's effective tool set. When called, the executor stages required assets into a temporary workspace, executes the recipe, and cleans up afterward.

### Linked runtime tools

Skills can also point at existing runtime tools through `linked_tool_ids`. These are references to already-registered builtin or MCP tools. They are useful when a skill should expose a known tool surface without re-declaring a bundled executor-side tool recipe.

On explicit skill load, Cognis resolves links against the current registry and
stores canonical tool IDs in session activation state. Links may use a canonical
ID, the callable name, or a qualified MCP server name such as
`mcp:slack-example:conversations_search_messages`. Server-name aliases and bare
operation names must identify exactly one tool. Missing, ambiguous, denied, or
step-excluded links are reported in the activation notice rather than silently
treated as enabled. Loading a skill does not override tool permissions or hard
step restrictions.
Resolved links remain callable through `describe_tool` and `call_tool`, not newly
added direct schemas. Canonical events preserve instructions and eligibility after
cache loss. Loading or reloading a skill, including `/skill`, appends instructions
without deleting earlier exposed instructions; the latest state controls eligibility.

`describe_tool`, `validate_tool_call`, `call_tool`, and exact `search_tools`
lookups use the same reference resolution within their authorized inventory.
Exact discovery also returns a matching tool that is already visible. Natural
language searches remain relevance-ranked; a failed lookup is not evidence that
the underlying service is unavailable.

Use linked runtime tools when:

- the tool already exists in the registry
- the skill should surface that existing tool when attached or loaded
- you do not need to ship new executable code with the skill

Use bundled executable skill tools when:

- the skill needs to carry its own reusable command or script
- the behavior should travel with the skill version and asset package

Skills can also carry reusable workflow step material, including step tool-profile data. That means a skill can ship both runtime tool bindings and the recommended tool surface for the steps it contributes to composed workflows.

When Cognis decomposes a skill into workflow steps, it automatically tries to align step profiles and per-step tool overrides with the skill's linked and bundled tools. The saved decomposition is editable through the workflow editor UI, but saving in that mode writes back to the skill version rather than creating a standalone workflow row.

Skill assets are stored in Cognis itself (database metadata plus artifact storage)
and are never managed as editable controller filesystem state. Executors receive
versioned cached copies for asset-only helpers and temporary staged copies for
executable recipes.

### Python asset environments

`skill_load` and `/skill` transparently verify assets and prepare one shared Python
virtualenv per owner and skill on the selected executor. This remains a read-only
operation for the agent; no additional skill settings or preparation tool are needed.
All Python assets in the skill contribute requirements to this environment.

Use standard [PEP 723 inline script metadata](https://packaging.python.org/en/latest/specifications/inline-script-metadata/)
to declare dependencies directly in each script:

```python
# /// script
# requires-python = ">=3.12"
# dependencies = ["requests==2.32.3", "rich>=13,<14"]
# ///
```

Exact `==` versions pin direct dependencies, not the complete transitive dependency
graph. Requirements across scripts are resolved together; incompatible pins are
reported rather than assigned separate environments. Without a PEP 723 block,
Cognis infers third-party imports best-effort, excluding standard-library and
bundled Python modules. Import names do not always match package names; explicit
PEP 723 dependencies are authoritative and recommended. Optional and dynamic imports
cannot be inferred reliably.

Run assets with the returned `python_environment.python_path` and their `local_path`
on the named executor. Do not use system Python or make another ad-hoc virtualenv.
The executor uses `uv` when available, otherwise Python's `venv` and `pip`. It uses
its existing Python interpreter and does not download Python or install OS packages.
Dependency installation may access package indexes and execute package build code.

Each load verifies and repairs files, reuses a healthy environment without forced
upgrades, installs missing requirements, and recreates a broken managed environment.
Preparation is serialized, time-bounded, and safe to repeat. Published versions keep
separate asset files but share the skill environment, so incompatible historical
versions should not be run concurrently.

Preparation failures **do not block skill instructions**. The load result and
protected skill context include `preparation_warning` and, when available, an
incomplete `python_environment` with the concrete error. Assets might not be runnable.
The agent can correct missing OS dependencies, package declarations, or executor
problems through normal authorized tools, then reload the skill to retry. Never
claim runtime readiness solely because files were materialized.

Python `script` recipes use the same shared interpreter automatically. During a
rolling upgrade, older executors still return verified assets but no environment;
new controllers expose that as an incomplete-environment warning. New executors
preserve legacy recipe execution for old controller manifests lacking owner
scoping. That compatibility branch can be removed once every controller supplies
the owner-scoped manifest.

Supported recipe modes:

- `script` -- execute a staged asset script with arguments
- `command` -- run a declared command with templated arguments

The controller never executes skill recipes directly -- all execution goes through the executor.

## MCP servers versus tools

MCP servers are configured in settings and then attached to executors. Once attached, they contribute tools to the executor's effective tool set.

This means:

- tools are what the agent can call
- MCP servers are one way those tools become available
- skills are another way tools become available
- executors are the boundary where tools are actually exposed
- Intaris-managed remote MCP servers are a separate per-agent path in the agent editor

## Practical advice

- Start with the smallest useful executor tool set.
- Attach MCP servers only where they are needed.
- Use skills for reusable operating instructions and tool bundles instead of copying them into each agent definition.
- Import existing Claude Code skills from GitHub to bootstrap agent capabilities.
- Use the tool registry to verify naming, categories, and source before troubleshooting agent permissions.

## Image generation and editing

Use `image_generate` to create a new image from a prompt. It optionally accepts
an ordered `references` array of Cognis image or artifact IDs. Use the prompt to
state how each reference should influence the result.

Use `image_edit` to modify or combine existing images. Its required `images`
array is ordered and passed to the selected model as supplied. An optional
`mask_artifact_id` identifies the region for masked editing when the selected
model supports masks.

For both tools, publish executor-local images as Cognis artifacts first, then
pass their IDs. Models have different limits and editing capabilities; an
unsupported reference count or mask is returned as an error and is never
silently converted into a text-only generation request.
