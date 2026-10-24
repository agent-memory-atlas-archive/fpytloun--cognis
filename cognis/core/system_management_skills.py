"""Portable system-management procedures bundled with the controller."""

from __future__ import annotations

_SAFETY = """
# Access and safety

- These tools are default-off. They require explicit agent tool opt-in and a root
  owner primary chat. Tasks, delegated sessions, and participant chats are denied.
- Discover the tool, then call `describe_tool` with its exact operation name before
  mutations. Never guess resource IDs, schema fields, model names, or revisions.
- Read first. Preserve unrelated configuration. Omitted fields preserve values;
  config objects and arrays replace, rather than deep-merge.
- Use validation-only `preview=true` where the operation supports it. Review the
  proposed values and affected dependencies before applying the exact change.
- Supply the precondition returned by the latest read where supported. A conflict requires a new
  read and reassessment, not an automatic retry with a fresh revision.
- Never put credentials, tokens, cookies, or private keys in arguments or prose.
  Use authorized stored-secret references. Authentication and executor token
  provisioning use secure user-facing flows.
- Ask for explicit user confirmation before destructive operations, changing
  security controls, disconnecting authentication, or affecting this chat's
  provider/executor. Do not weaken policy to authorize yourself.
- If a mutation times out or its result is uncertain, read the current resource
  and reconcile before retrying. Create operations require explicit IDs.
- After a mutation, read back durable state and relevant runtime status. Report
  persisted, applied, pending, and failed states separately. Never equate a saved
  configuration with successful remote initialization.
"""


def _skill(skill_id: str, name: str, description: str, tool: str, body: str) -> dict[str, object]:
    return {
        "skill_id": skill_id,
        "content": f"""---
name: {name}
description: {description}
tags:
  - cognis
  - system-management
linked_tool_ids:
  - builtin:{tool}
---

# Purpose

{description}
{_SAFETY}
{body}
""",
    }


SYSTEM_MANAGEMENT_SKILLS = {
    "cognis-provider-manager": _skill(
        "cognis-provider-manager",
        "Cognis Provider Manager",
        "Safely manage Cognis LLM providers, models, defaults, health, and authentication.",
        "manage_providers",
        """
# Procedure

1. Use `list`, `get`, and `schema`; check ownership, location, preset, executor
   selectors, current defaults, and managed-local dependencies.
2. For `create`, choose an explicit stable provider ID. For `update`, construct a
   complete replacement config only when changing config; preserve secret refs.
   Store provider credentials securely and reference them with `config.api_key_secret`.
3. Use `discover_models` and `enrich_models` to inspect metadata. These do not save
   model changes. Apply selected metadata explicitly through a previewed update.
4. Use `health_get` for cached status. `health_refresh` contacts a provider;
   `test` can perform billable inference and is cooldown-limited.
5. `auth_start` begins the configured OAuth flow. Give the human the authorization
   URL/code returned by the trusted flow; never ask them to paste tokens.
   `auth_status` checks progress; `auth_disconnect` is destructive.
6. `set_default` changes the default only within the provider ownership scope.
   Before `delete`, inspect routing and local-model dependencies. Never cascade
   delete dependents or silently reroute traffic to bypass a dependency conflict.
""",
    ),
    "cognis-route-manager": _skill(
        "cognis-route-manager",
        "Cognis Route Manager",
        "Safely manage custom named inference routes and Cognis task-to-model bindings.",
        "manage_routes",
        """
# Two distinct routing layers

- `named_list/get/create/update/delete` manages custom `cognis/<name>` routes.
  Targets are concrete provider/model pairs; preserve target order, priorities,
  recovery policy, role overrides, and the current revision.
- `bindings_get/update/reset` manages system task bindings such as compaction,
  attachment analysis, embeddings, and companion roles. Bindings can reference
  custom routes. An omitted binding is preserved; reset only explicitly selected
  task types. Read the returned aggregate revision.

# Procedure

1. Inspect providers and the existing named routes and bindings. Do not confuse
   a route ID with its `cognis/<name>` model reference.
2. Use `resolve` to inspect the actual inference planner without generating a
   response. Check ordered candidates and effective policy.
3. Preview target/binding changes. Global bindings require globally usable
   providers/routes; private provider visibility does not grant global usability.
4. Apply with the exact revision. Use `resolve` again and verify the binding.
5. Do not rename or delete a referenced route. Inspect dependency errors and ask
   for a separate migration decision; do not silently modify agent configuration.
6. Embedding routes have one target; do not introduce embedding fallback or
   unsupported reasoning-effort values.
""",
    ),
    "cognis-settings-manager": _skill(
        "cognis-settings-manager",
        "Cognis Settings Manager",
        "Safely inspect, validate, update, and reset typed Cognis application settings.",
        "manage_settings",
        """
# Procedure

1. Read `schema` and `get` for the exact setting. The registry is authoritative
   for types, options, bounds, defaults, and application timing.
2. Use `diagnostics` for safe readiness information. This is not a secrets or
   unrestricted database inspection tool.
3. Preview `update` or `reset`, then apply with `expected_updated_at`.
4. Read back the value and distinguish hot settings from settings applied on the
   next operation/runtime. On application failure, recovery is attempted; read
   current durable state before any further change.
5. Web backend settings use exposed `web.*` registry keys. Store API keys through
   secure credential flows, never as settings values.
   `web_get` filters web settings; `web_update` uses the same readiness validation,
   cancellation-safe persistence, and executor propagation as regular updates.
6. `step_profiles_list/get` returns workflow profiles and their aggregate revision.
   Use `step_profiles_create/update/reset` with that exact revision. Profile
   configuration replaces its document. Resetting a custom profile deletes it
   only when workflows no longer reference it; built-in reset removes overrides.
7. Do not use settings to edit arbitrary environment variables, restart services,
   change user roles, retrieve secrets, or bypass management-tool access rules.
""",
    ),
    "cognis-executor-manager": _skill(
        "cognis-executor-manager",
        "Cognis Executor Manager",
        "Safely manage Cognis executor configuration and verify runtime reconfiguration.",
        "manage_executors",
        """
# Procedure

1. Inspect `list`, `get`, and `schema`; check ownership, executor type,
   availability, default status, desired/applied generations, runtime state,
   observed capabilities, browser configuration, and local-inference settings.
2. For `create`, choose an explicit stable executor ID. Shared/local executors
   require admin. Persistent token provisioning/rotation uses the secure UI;
   never request or return executor token material in conversation history.
3. Preview `update` before applying it. Config objects, enabled tools, groups,
   and labels replace their collections. Preserve unrelated entries.
4. Local Ollama runtime endpoints must remain supported loopback configurations.
   Preserve local-model deployment and MCP visibility guards.
5. Saving configuration can queue asynchronous reconfiguration or fence an
   existing connection. Read back desired/applied generations and runtime state.
   Use `reconfigure` to retry initialization, not to conceal an invalid config.
6. `set_default` operates within ownership scope. Never delete the default
   executor or one with unresolved dependencies; no implicit cascading cleanup.
""",
    ),
    "cognis-mcp-manager": _skill(
        "cognis-mcp-manager",
        "Cognis MCP Manager",
        "Safely configure Cognis MCP servers, executor assignments, and runtime capability refresh.",
        "manage_mcp",
        """
# Procedure

1. Inspect the exact `manage_mcp` action schemas. Read servers, executor status,
   assignments, tool metadata, and visibility before making changes.
2. Use stored credentials and documented secret references. Never paste tokens,
   passwords, headers, or executor registration tokens into tool arguments.
3. Preserve server ownership and deployment scope. Server commands run on assigned
   executors, not necessarily on the controller. Never broaden executor visibility
   or enable an integration without authorization.
4. Reconcile assignments and runtime capability status after updates. A saved server
   configuration does not prove its remote process started or its tools work.
5. Never silently delete assignments or broaden access to work around an error.
   Read the exact dependency or validation error and choose a bounded correction.
""",
    ),
}
