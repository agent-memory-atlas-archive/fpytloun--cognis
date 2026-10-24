"""Built-in project management tools.

Authorization mirrors the REST API through :mod:`cognis.core.project_access`:
viewers read, members use, managers edit project configuration and agent
assignments, and only owners share or archive. There is no admin bypass.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from cognis.api.serializers import (
    project_agent_to_response,
    project_grant_to_response,
    project_source_to_response,
    project_to_response,
)
from cognis.core.project_access import (
    ProjectAssignmentError,
    append_project_instructions,
    change_conversation_project,
    resolve_project_role,
    role_satisfies,
)
from cognis.core.project_knowledge import project_knowledgebase_metadata, set_project_knowledgebase
from cognis.core.project_management import ProjectManagementService, require_project
from cognis.models.tool import NativeToolDefinition as ToolDefinition
from cognis.models.tool import ToolCapability, ToolSource
from cognis.store.project_knowledge import list_project_knowledgebases
from cognis.store.project_queries import (
    get_project_agent,
    list_project_agents,
    remove_project_agent,
    upsert_project_agent,
)
from cognis.store.queries import (
    attach_project_workflow,
    create_project,
    create_project_source,
    delete_project_source,
    detach_project_workflow,
    get_agent,
    get_conversation,
    get_project,
    get_project_source,
    list_project_sources,
    list_project_workflow_ids,
    list_projects_for_user,
    update_project,
    update_project_source,
)
from cognis.tools.registry import ToolExecutionContext

_SOURCE = ToolSource(type="builtin")
_PROJECT_CAUTION = (
    "Do not invent projects. Do not assign a project to a task unless an exact match "
    "(project name alias, source path prefix, or remote URL) exists. Project assignment is optional."
)
_INSTRUCTIONS_CAUTION = (
    "Project instructions are injected into every future session in the project, including "
    "other members' sessions in shared projects. Change them only when the user explicitly asks; "
    "prefer instructions_mode=append to add a rule without rewriting existing instructions."
)
_CLEAR_PROJECT_VALUES = frozenset({"", "none", "null"})
_CREATE_PROJECT_FIELDS = ("name", "description", "instructions", "default_workflow_id")
_UPDATABLE_PROJECT_FIELDS = ("name", "description", "instructions", "default_workflow_id")
_UPDATABLE_SOURCE_FIELDS = (
    "name",
    "local_path",
    "remote_url",
    "default_branch",
    "credential_ref",
    "instructions",
)


def _annotate_role(row: Any, role: str | None) -> None:
    """Attach the caller's role for response serialization."""

    row.caller_role = role


def _tool(
    name: str,
    description: str,
    properties: dict[str, Any],
    required: list[str] | None = None,
    *,
    read_only: bool = False,
    destructive: bool = False,
) -> ToolDefinition:
    capabilities = [ToolCapability.READ] if read_only else [ToolCapability.WRITE]
    if destructive:
        capabilities.append(ToolCapability.DESTRUCTIVE)
    return ToolDefinition(
        name=name,
        description=f"{description} {_PROJECT_CAUTION}",
        parameters={"type": "object", "properties": properties, "required": required or []},
        source=_SOURCE,
        category="projects",
        read_only=read_only,
        capabilities=capabilities,
    )


_PROJECT_ID = {"type": "string", "description": "Project ID returned by list_projects."}

LIST_PROJECTS_TOOL = _tool(
    "list_projects",
    "List owned and shared projects with the caller's role.",
    {"query": {"type": "string"}, "status": {"type": "string"}},
    read_only=True,
)
GET_PROJECT_TOOL = _tool(
    "get_project",
    "Get project details including sources, workflows, assigned agents, membership, and knowledgebases.",
    {"project_id": _PROJECT_ID},
    ["project_id"],
    read_only=True,
)
LIST_PROJECT_KNOWLEDGEBASES_TOOL = _tool(
    "list_project_knowledgebases",
    "List knowledgebases shared with a project, optionally by name. Requires project view access. "
    "Listing metadata does not change content permissions; retrieval uses existing project KB "
    "access rules and agents must be assigned to the active project.",
    {"project_id": _PROJECT_ID, "query": {"type": "string"}},
    ["project_id"],
    read_only=True,
)
ASSIGN_KNOWLEDGEBASE_TO_PROJECT_TOOL = _tool(
    "assign_knowledgebase_to_project",
    "Share an owned active knowledgebase with an active project. Requires KB ownership and "
    "project owner/manager access. Grants members and assigned agents project-scoped read/query "
    "access, not global KB permissions. Identical assignments are idempotent.",
    {"project_id": _PROJECT_ID, "knowledgebase_id": {"type": "string"}},
    ["project_id", "knowledgebase_id"],
)
UNASSIGN_KNOWLEDGEBASE_FROM_PROJECT_TOOL = _tool(
    "unassign_knowledgebase_from_project",
    "Remove project-derived access to a knowledgebase. Requires KB ownership or project "
    "owner/manager access. Does not delete the KB or revoke independent permissions. Idempotent.",
    {"project_id": _PROJECT_ID, "knowledgebase_id": {"type": "string"}},
    ["project_id", "knowledgebase_id"],
    destructive=True,
)
LIST_PROJECT_GRANTS_TOOL = _tool(
    "list_project_grants",
    "Read project membership. Owners see grant history; other readers see active grants.",
    {"project_id": _PROJECT_ID},
    ["project_id"],
    read_only=True,
)
FIND_PROJECT_SHARE_RECIPIENTS_TOOL = _tool(
    "find_project_share_recipients",
    "Find active Cognis recipients by name or exact email before sharing. Requires project "
    "ownership. Returns at most 20 identities; never select an ambiguous match automatically.",
    {"project_id": _PROJECT_ID, "query": {"type": "string", "minLength": 3, "maxLength": 254}},
    ["project_id", "query"],
    read_only=True,
)
_PERMISSION = {"type": "string", "enum": ["viewer", "member", "manager"]}
CREATE_PROJECT_GRANT_TOOL = _tool(
    "create_project_grant",
    "Share a project with a verified registered recipient. Owner-only. Choose permission "
    "explicitly; do not infer manager. Identical existing grants are returned without changes.",
    {
        "project_id": _PROJECT_ID,
        "grantee_user_email": {"type": "string"},
        "permission": _PERMISSION,
        "note": {"type": "string"},
    },
    ["project_id", "grantee_user_email", "permission"],
)
UPDATE_PROJECT_GRANT_TOOL = _tool(
    "update_project_grant",
    "Change an active project grant's permission. Owner-only; use a returned grant ID.",
    {"project_id": _PROJECT_ID, "grant_id": {"type": "string"}, "permission": _PERMISSION},
    ["project_id", "grant_id", "permission"],
)
REVOKE_PROJECT_GRANT_TOOL = _tool(
    "revoke_project_grant",
    "Revoke a project grant. Owner-only. Repeated revocation has no additional effects.",
    {"project_id": _PROJECT_ID, "grant_id": {"type": "string"}},
    ["project_id", "grant_id"],
    destructive=True,
)
SET_PROJECT_AVATAR_TOOL = _tool(
    "set_project_avatar",
    "Set a project's avatar from an authorized image/content ref, or remove it with clear=true. "
    "Requires manager. The project gets a validated snapshot; the source image is not deleted. "
    "Provide exactly one of content_ref or clear=true.",
    {
        "project_id": _PROJECT_ID,
        "content_ref": {"type": "string"},
        "clear": {"type": "boolean"},
    },
    ["project_id"],
)
CREATE_PROJECT_TOOL = _tool(
    "create_project",
    "Create a project owned by the current user.",
    {
        "name": {"type": "string"},
        "description": {"type": "string"},
        "instructions": {"type": "string"},
        "default_workflow_id": {"type": "string"},
    },
    ["name"],
)
UPDATE_PROJECT_TOOL = _tool(
    "update_project",
    "Update a project's name, description, instructions, or default workflow. Requires the "
    f"manager role. {_INSTRUCTIONS_CAUTION}",
    {
        "project_id": _PROJECT_ID,
        "name": {"type": "string"},
        "description": {"type": "string"},
        "instructions": {"type": "string"},
        "instructions_mode": {
            "type": "string",
            "enum": ["replace", "append"],
            "description": "append adds instructions as a new paragraph. Default replace.",
        },
        "default_workflow_id": {"type": "string"},
    },
    ["project_id"],
)
DELETE_PROJECT_TOOL = _tool(
    "delete_project",
    "Archive a project. Only the project owner can archive.",
    {"project_id": _PROJECT_ID},
    ["project_id"],
    destructive=True,
)
ADD_PROJECT_SOURCE_TOOL = _tool(
    "add_project_source",
    "Add a source hint to a project. Requires the manager role.",
    {
        "project_id": _PROJECT_ID,
        "name": {"type": "string"},
        "local_path": {"type": "string"},
        "remote_url": {"type": "string"},
        "default_branch": {"type": "string"},
        "credential_ref": {"type": "string"},
        "instructions": {"type": "string"},
    },
    ["project_id", "name"],
)
UPDATE_PROJECT_SOURCE_TOOL = _tool(
    "update_project_source",
    "Update a project source hint. Requires the manager role.",
    {
        "source_id": {"type": "string"},
        "name": {"type": "string"},
        "local_path": {"type": "string"},
        "remote_url": {"type": "string"},
        "default_branch": {"type": "string"},
        "credential_ref": {"type": "string"},
        "instructions": {"type": "string"},
    },
    ["source_id"],
)
REMOVE_PROJECT_SOURCE_TOOL = _tool(
    "remove_project_source",
    "Remove a project source hint. Requires the manager role.",
    {"source_id": {"type": "string"}},
    ["source_id"],
    destructive=True,
)
ATTACH_WORKFLOW_TO_PROJECT_TOOL = _tool(
    "attach_workflow_to_project",
    "Bind a workflow to a project. Requires the manager role.",
    {"project_id": _PROJECT_ID, "workflow_id": {"type": "string"}},
    ["project_id", "workflow_id"],
)
DETACH_WORKFLOW_FROM_PROJECT_TOOL = _tool(
    "detach_workflow_from_project",
    "Remove a workflow binding from a project. Requires the manager role.",
    {"project_id": _PROJECT_ID, "workflow_id": {"type": "string"}},
    ["project_id", "workflow_id"],
)
ASSIGN_AGENT_TO_PROJECT_TOOL = _tool(
    "assign_agent_to_project",
    "Assign one of the user's own primary agents to a project, or update its assignment. "
    "Assignment shares the agent with every project member, usable only inside that project. "
    "is_default=true classifies the agent's channel, main, and direct chats as project work. "
    "executor_scope chooses whose executor members use: owner_executor (the agent owner's "
    "executor and credentials) or grantee_executor (each member brings their own). "
    "Requires the manager role and agent ownership; only do this when the user asks.",
    {
        "project_id": _PROJECT_ID,
        "agent_id": {"type": "string"},
        "is_default": {"type": "boolean"},
        "executor_scope": {"type": "string", "enum": ["owner_executor", "grantee_executor"]},
    },
    ["project_id", "agent_id"],
)
UNASSIGN_AGENT_FROM_PROJECT_TOOL = _tool(
    "unassign_agent_from_project",
    "Remove an agent assignment from a project (agent owner or project owner).",
    {"project_id": _PROJECT_ID, "agent_id": {"type": "string"}},
    ["project_id", "agent_id"],
)
SET_CONVERSATION_PROJECT_TOOL = _tool(
    "set_conversation_project",
    "Assign an owned topic conversation to a project, or clear it with project_id=null "
    "(legacy 'none' also accepted). Omitted conversation_id uses the current conversation. "
    "Adding a previously unassigned chat shares it with the project by default; set visibility="
    "'private' explicitly to keep it private. Attached documents follow the final scope. "
    "Shared read access does not permit mutation. "
    "Not available in channel, main, agent-direct, task, or managed conversations. Use only "
    "when the user asks to file this conversation under a project. Takes effect next turn.",
    {
        "project_id": {
            "type": ["string", "null"],
            "minLength": 1,
            "description": "Known project ID, or null to clear.",
        },
        "conversation_id": {"type": "string", "minLength": 1},
        "visibility": {"type": "string", "enum": ["private", "project"]},
    },
    ["project_id"],
)

RESTORE_PROJECT_TOOL = _tool(
    "restore_project",
    "Restore an archived project. Owner-only; does not restore revoked grants.",
    {"project_id": _PROJECT_ID},
    ["project_id"],
)
LEAVE_PROJECT_TOOL = _tool(
    "leave_project",
    "Leave a shared project, optionally making your authored project work private "
    "first. Owners cannot leave. Revokes your project membership, not other users' access.",
    {"project_id": _PROJECT_ID, "make_private": {"type": "boolean", "default": False}},
    ["project_id"],
    destructive=True,
)
LIST_PROJECT_TASKS_TOOL = _tool(
    "list_project_tasks",
    "List readable task metadata in the active project, including shared work "
    "by other members. Private tasks from other users are excluded. Requires an assigned active agent. "
    "Does not grant task mutation or private step-output access.",
    {
        "project_id": _PROJECT_ID,
        "limit": {"type": "integer", "minimum": 1, "maximum": 100},
        "cursor": {"type": "string"},
    },
    ["project_id"],
    read_only=True,
)

_READ_TOOLS = (
    LIST_PROJECT_TASKS_TOOL,
    LIST_PROJECTS_TOOL,
    GET_PROJECT_TOOL,
    LIST_PROJECT_GRANTS_TOOL,
    FIND_PROJECT_SHARE_RECIPIENTS_TOOL,
    LIST_PROJECT_KNOWLEDGEBASES_TOOL,
)
_MANAGE_TOOLS = (
    RESTORE_PROJECT_TOOL,
    LEAVE_PROJECT_TOOL,
    ASSIGN_KNOWLEDGEBASE_TO_PROJECT_TOOL,
    UNASSIGN_KNOWLEDGEBASE_FROM_PROJECT_TOOL,
    CREATE_PROJECT_GRANT_TOOL,
    UPDATE_PROJECT_GRANT_TOOL,
    REVOKE_PROJECT_GRANT_TOOL,
    SET_PROJECT_AVATAR_TOOL,
    CREATE_PROJECT_TOOL,
    UPDATE_PROJECT_TOOL,
    DELETE_PROJECT_TOOL,
    ADD_PROJECT_SOURCE_TOOL,
    UPDATE_PROJECT_SOURCE_TOOL,
    REMOVE_PROJECT_SOURCE_TOOL,
    ATTACH_WORKFLOW_TO_PROJECT_TOOL,
    DETACH_WORKFLOW_FROM_PROJECT_TOOL,
    ASSIGN_AGENT_TO_PROJECT_TOOL,
    UNASSIGN_AGENT_FROM_PROJECT_TOOL,
    SET_CONVERSATION_PROJECT_TOOL,
)
PROJECT_READ_TOOL_IDS = tuple(f"builtin:{tool.name}" for tool in _READ_TOOLS)
PROJECT_MANAGE_TOOL_IDS = tuple(f"builtin:{tool.name}" for tool in (*_READ_TOOLS, *_MANAGE_TOOLS))


def project_tools() -> list[ToolDefinition]:
    return [*_READ_TOOLS, *_MANAGE_TOOLS]


def build_project_tool_handlers(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    management_service: ProjectManagementService | None = None,
) -> dict[str, Any]:
    async def restore_project_handler(
        arguments: dict[str, Any], context: ToolExecutionContext
    ) -> Any:
        async with session_factory() as session:
            project_id = str(arguments["project_id"])
            await _require_role(session, project_id, _user(context), "share")
            row = await update_project(session, project_id, status="active")
            await session.commit()
        return _project_payload(row)

    async def leave_project_handler(
        arguments: dict[str, Any], context: ToolExecutionContext
    ) -> Any:
        return await service.leave(
            str(arguments["project_id"]),
            _user(context),
            make_private=bool(arguments.get("make_private", False)),
        )

    async def list_project_tasks_handler(
        arguments: dict[str, Any], context: ToolExecutionContext
    ) -> Any:
        from cognis.api.project_pagination import decode_project_cursor, encode_project_cursor
        from cognis.core.project_conversation_access import require_project_agent
        from cognis.store.project_queries import list_project_tasks

        actor = _user(context)
        project_id = str(arguments["project_id"])
        access = context.runtime_metadata.get("runtime_access") or {}
        scope = ["list_project_tasks", actor, project_id, access.get("agent_id")]
        before = decode_project_cursor(arguments.get("cursor"), scope)
        limit = min(max(int(arguments.get("limit") or 25), 1), 100)
        async with session_factory() as session:
            await require_project_agent(
                session, actor=actor, project_id=project_id, runtime_access=access
            )
            rows = await list_project_tasks(
                session, project_id, viewer_email=actor, limit=limit + 1, before=before
            )
        page = rows[:limit]
        return {
            "items": [
                {
                    "task_id": row.task_id,
                    "title": row.title,
                    "agent_id": row.agent_id,
                    "status": row.status,
                    "visibility": row.visibility,
                    "project_id": row.project_id,
                }
                for row in page
            ],
            "next_cursor": encode_project_cursor(scope, page[-1].updated_at, page[-1].task_id)
            if len(rows) > limit
            else None,
        }

    service = management_service or ProjectManagementService(session_factory)

    async def _require_role(
        session: AsyncSession, project_id: str, user_email: str, required: str
    ) -> Any:
        row = await get_project(session, project_id)
        resolution = await resolve_project_role(session, row, user_email)
        if row is None or resolution.role is None:
            raise ValueError("Project not found")
        if not role_satisfies(resolution.role, required):
            raise ValueError(f"Your project role ({resolution.role}) does not allow this action")
        if required in {"manage", "share"}:
            await require_project(session, project_id, user_email, required)
        _annotate_role(row, resolution.role)
        return row

    def _runtime_value(context: ToolExecutionContext, key: str) -> Any:
        value = context.runtime_metadata.get(key)
        if value is None:
            runtime_access = context.runtime_metadata.get("runtime_access")
            if isinstance(runtime_access, dict):
                value = runtime_access.get(key)
        if value is None and isinstance(context.shared_runtime_metadata, dict):
            value = context.shared_runtime_metadata.get(key)
        return value

    def _user(context: ToolExecutionContext) -> str:
        user_email = _runtime_value(context, "user_email")
        if not isinstance(user_email, str):
            raise ValueError("User context is unavailable")
        return user_email

    def _project_payload(row: Any, **kwargs: Any) -> dict[str, Any]:
        return project_to_response(row, **kwargs).model_dump(mode="json")

    async def list_projects_handler(
        arguments: dict[str, Any], context: ToolExecutionContext
    ) -> list[dict[str, Any]]:
        user_email = _user(context)
        async with session_factory() as session:
            rows = await list_projects_for_user(
                session,
                user_email,
                status=arguments.get("status") or "active",
                query=arguments.get("query"),
            )
            for row in rows:
                _annotate_role(row, (await resolve_project_role(session, row, user_email)).role)
        return [_project_payload(row) for row in rows]

    async def get_project_handler(
        arguments: dict[str, Any], context: ToolExecutionContext
    ) -> dict[str, Any]:
        user_email = _user(context)
        async with session_factory() as session:
            row = await _require_role(session, str(arguments["project_id"]), user_email, "view")
            sources = await list_project_sources(session, row.project_id)
            workflow_ids = await list_project_workflow_ids(session, row.project_id)
            agents = await list_project_agents(session, row.project_id)
            knowledgebases = await list_project_knowledgebases(
                session, user_email=user_email, project_id=row.project_id
            )
        grants = await service.list_grants(row.project_id, user_email)
        return {
            **_project_payload(
                row,
                sources=sources,
                workflow_ids=workflow_ids,
                grants=grants,
                agents=[
                    project_agent_to_response(assignment, agent, viewer_email=user_email)
                    for assignment, agent in agents
                ],
            ),
            "knowledgebases": [
                project_knowledgebase_metadata(kb, user_email).model_dump(mode="json")
                for kb in knowledgebases
            ],
        }

    async def list_knowledgebases_handler(
        arguments: dict[str, Any], context: ToolExecutionContext
    ) -> list[dict[str, Any]]:
        actor = _user(context)
        async with session_factory() as session:
            await _require_role(session, str(arguments["project_id"]), actor, "view")
            rows = await list_project_knowledgebases(
                session, user_email=actor, project_id=str(arguments["project_id"])
            )
        query = str(arguments.get("query") or "").strip().casefold()
        return [
            project_knowledgebase_metadata(row, actor).model_dump(mode="json")
            for row in rows
            if not query or query in row.name.casefold()
        ]

    async def _change_knowledgebase(
        arguments: dict[str, Any], context: ToolExecutionContext, *, assigned: bool
    ) -> dict[str, Any]:
        async with session_factory() as session:
            await set_project_knowledgebase(
                session,
                project_id=str(arguments["project_id"]),
                knowledgebase_id=str(arguments["knowledgebase_id"]),
                actor_email=_user(context),
                assigned=assigned,
            )
            await session.commit()
        return {
            "project_id": arguments["project_id"],
            "knowledgebase_id": arguments["knowledgebase_id"],
            "assigned": assigned,
        }

    async def assign_knowledgebase_handler(
        arguments: dict[str, Any], context: ToolExecutionContext
    ) -> dict[str, Any]:
        return await _change_knowledgebase(arguments, context, assigned=True)

    async def unassign_knowledgebase_handler(
        arguments: dict[str, Any], context: ToolExecutionContext
    ) -> dict[str, Any]:
        return await _change_knowledgebase(arguments, context, assigned=False)

    async def create_project_handler(
        arguments: dict[str, Any], context: ToolExecutionContext
    ) -> dict[str, Any]:
        if arguments.get("default_workflow_id"):
            await service.require_workflow(arguments["default_workflow_id"], None, _user(context))
        async with session_factory() as session:
            row = await create_project(
                session,
                owner_email=_user(context),
                **{key: arguments[key] for key in _CREATE_PROJECT_FIELDS if key in arguments},
            )
            await session.commit()
        _annotate_role(row, "owner")
        return _project_payload(row)

    async def update_project_handler(
        arguments: dict[str, Any], context: ToolExecutionContext
    ) -> dict[str, Any]:
        project_id = str(arguments["project_id"])
        mode = arguments.get("instructions_mode", "replace")
        # Only configuration fields are editable here; status/ownership stay owner-only.
        fields = {key: arguments[key] for key in _UPDATABLE_PROJECT_FIELDS if key in arguments}
        if fields.get("default_workflow_id"):
            await service.require_workflow(
                fields["default_workflow_id"], project_id, _user(context)
            )
        async with session_factory() as session:
            project = await _require_role(session, project_id, _user(context), "manage")
            role = getattr(project, "caller_role", None)
            if mode == "append" and isinstance(fields.get("instructions"), str):
                fields["instructions"] = append_project_instructions(
                    project.instructions, fields["instructions"]
                )
            row = await update_project(session, project_id, **fields)
            await session.commit()
        _annotate_role(row, role)
        return _project_payload(row)

    async def delete_project_handler(
        arguments: dict[str, Any], context: ToolExecutionContext
    ) -> dict[str, Any]:
        project_id = str(arguments["project_id"])
        async with session_factory() as session:
            await _require_role(session, project_id, _user(context), "share")
            await update_project(session, project_id, status="archived")
            await session.commit()
        return {"ok": True}

    async def add_source_handler(
        arguments: dict[str, Any], context: ToolExecutionContext
    ) -> dict[str, Any]:
        async with session_factory() as session:
            await _require_role(session, str(arguments["project_id"]), _user(context), "manage")
            row = await create_project_source(
                session,
                project_id=str(arguments["project_id"]),
                **{key: arguments[key] for key in _UPDATABLE_SOURCE_FIELDS if key in arguments},
            )
            await session.commit()
        return project_source_to_response(row).model_dump(mode="json")

    async def _require_source_manager(
        session: AsyncSession, source_id: str, user_email: str
    ) -> None:
        source = await get_project_source(session, source_id)
        if source is None:
            raise ValueError("Project source not found")
        await _require_role(session, source.project_id, user_email, "manage")

    async def update_source_handler(
        arguments: dict[str, Any], context: ToolExecutionContext
    ) -> dict[str, Any]:
        source_id = str(arguments["source_id"])
        fields = {key: arguments[key] for key in _UPDATABLE_SOURCE_FIELDS if key in arguments}
        async with session_factory() as session:
            await _require_source_manager(session, source_id, _user(context))
            row = await update_project_source(session, source_id, **fields)
            await session.commit()
        return project_source_to_response(row).model_dump(mode="json")

    async def remove_source_handler(
        arguments: dict[str, Any], context: ToolExecutionContext
    ) -> dict[str, Any]:
        source_id = str(arguments["source_id"])
        async with session_factory() as session:
            await _require_source_manager(session, source_id, _user(context))
            ok = await delete_project_source(session, source_id)
            await session.commit()
        return {"ok": ok}

    async def attach_workflow_handler(
        arguments: dict[str, Any], context: ToolExecutionContext
    ) -> dict[str, Any]:
        project_id = str(arguments["project_id"])
        await service.require_workflow(str(arguments["workflow_id"]), project_id, _user(context))
        async with session_factory() as session:
            await _require_role(session, project_id, _user(context), "manage")
            await attach_project_workflow(session, project_id, str(arguments["workflow_id"]))
            await session.commit()
        return {"ok": True}

    async def detach_workflow_handler(
        arguments: dict[str, Any], context: ToolExecutionContext
    ) -> dict[str, Any]:
        project_id = str(arguments["project_id"])
        async with session_factory() as session:
            await _require_role(session, project_id, _user(context), "manage")
            ok = await detach_project_workflow(session, project_id, str(arguments["workflow_id"]))
            await session.commit()
        return {"ok": ok}

    async def assign_agent_handler(
        arguments: dict[str, Any], context: ToolExecutionContext
    ) -> dict[str, Any]:
        user_email = _user(context)
        project_id = str(arguments["project_id"])
        agent_id = str(arguments["agent_id"])
        async with session_factory() as session:
            project = await _require_role(session, project_id, user_email, "manage")
            if project.status != "active":
                raise ValueError("Project is not active")
            agent = await get_agent(session, agent_id)
            if agent is None:
                raise ValueError("Agent not found")
            if agent.owner_email != user_email or agent.agent_type != "primary":
                raise ValueError("Only the owner of a primary agent can assign it to a project")
            assignment = await upsert_project_agent(
                session,
                project_id=project_id,
                agent_id=agent_id,
                added_by=user_email,
                executor_scope=arguments.get("executor_scope"),
                is_default=arguments.get("is_default"),
            )
            await session.commit()
            await session.refresh(assignment)
        return project_agent_to_response(assignment, agent, viewer_email=user_email).model_dump(
            mode="json"
        )

    async def unassign_agent_handler(
        arguments: dict[str, Any], context: ToolExecutionContext
    ) -> dict[str, Any]:
        user_email = _user(context)
        project_id = str(arguments["project_id"])
        agent_id = str(arguments["agent_id"])
        async with session_factory() as session:
            project = await _require_role(session, project_id, user_email, "manage")
            if await get_project_agent(session, project_id, agent_id) is None:
                raise ValueError("Project agent not found")
            agent = await get_agent(session, agent_id)
            if user_email not in {getattr(agent, "owner_email", None), project.owner_email}:
                raise ValueError("Only the agent owner or project owner can remove it")
            ok = await remove_project_agent(session, project_id, agent_id)
            await session.commit()
        return {"ok": ok}

    async def set_conversation_project_handler(
        arguments: dict[str, Any], context: ToolExecutionContext
    ) -> dict[str, Any]:
        user_email = _user(context)
        conversation_id = arguments.get("conversation_id") or _runtime_value(
            context, "conversation_id"
        )
        if not isinstance(conversation_id, str) or not conversation_id:
            raise ValueError("Conversation context is unavailable")
        raw_project_id = str(arguments.get("project_id") or "").strip()
        project_id = None if raw_project_id.lower() in _CLEAR_PROJECT_VALUES else raw_project_id
        async with session_factory() as session:
            row = await get_conversation(session, conversation_id)
            if row is None or row.status == "deleted":
                raise ValueError("Conversation not found")
            from cognis.store.queries import get_user

            user = await get_user(session, user_email)
            if user is None or not user.is_active or user.role == "viewer":
                raise ValueError("User may not change conversation projects")
            try:
                await change_conversation_project(
                    session,
                    row,
                    project_id=project_id,
                    user_email=user_email,
                    visibility=arguments.get("visibility"),
                )
            except ProjectAssignmentError as exc:
                raise ValueError(str(exc)) from exc
            await session.commit()
        return {
            "ok": True,
            "conversation_id": conversation_id,
            "project_id": project_id,
            "visibility": row.visibility,
            "note": "Project context applies from the next turn.",
        }

    async def list_grants_handler(arguments: dict[str, Any], context: ToolExecutionContext) -> Any:
        rows = await service.list_grants(str(arguments["project_id"]), _user(context))
        return [project_grant_to_response(row).model_dump(mode="json") for row in rows]

    async def find_recipients_handler(
        arguments: dict[str, Any], context: ToolExecutionContext
    ) -> Any:
        return await service.find_recipients(
            str(arguments["project_id"]), _user(context), str(arguments["query"])
        )

    async def create_grant_handler(arguments: dict[str, Any], context: ToolExecutionContext) -> Any:
        row = await service.change_grant(
            str(arguments["project_id"]),
            _user(context),
            grantee_email=str(arguments["grantee_user_email"]),
            permission=str(arguments["permission"]),
            note=arguments.get("note"),
        )
        return project_grant_to_response(row).model_dump(mode="json")

    async def update_grant_handler(arguments: dict[str, Any], context: ToolExecutionContext) -> Any:
        row = await service.change_grant(
            str(arguments["project_id"]),
            _user(context),
            grant_id=str(arguments["grant_id"]),
            permission=str(arguments["permission"]),
        )
        return project_grant_to_response(row).model_dump(mode="json")

    async def revoke_grant_handler(arguments: dict[str, Any], context: ToolExecutionContext) -> Any:
        await service.change_grant(
            str(arguments["project_id"]),
            _user(context),
            grant_id=str(arguments["grant_id"]),
            revoke=True,
        )
        return {"ok": True}

    async def set_avatar_handler(arguments: dict[str, Any], context: ToolExecutionContext) -> Any:
        content_ref = arguments.get("content_ref")
        clear = arguments.get("clear") is True
        if bool(content_ref) == clear:
            raise ValueError("Provide exactly one of content_ref or clear=true")
        project_id = str(arguments["project_id"])
        actor = _user(context)
        async with session_factory() as session:
            project = await _require_role(session, project_id, actor, "manage")
            owner = project.owner_email
        image_id = None
        if not clear:
            image_id = await service.avatar_snapshot(
                str(content_ref),
                actor=actor,
                project_owner=owner,
                runtime_metadata={
                    key: _runtime_value(context, key)
                    for key in ("conversation_id", "agent_id", "session_id")
                },
            )
        async with session_factory() as session:
            await _require_role(session, project_id, actor, "manage")
            row = await update_project(
                session, project_id, avatar_image_id=image_id, avatar_url=None
            )
            await session.commit()
        return _project_payload(row)

    return {
        RESTORE_PROJECT_TOOL.name: restore_project_handler,
        LEAVE_PROJECT_TOOL.name: leave_project_handler,
        LIST_PROJECT_TASKS_TOOL.name: list_project_tasks_handler,
        LIST_PROJECTS_TOOL.name: list_projects_handler,
        GET_PROJECT_TOOL.name: get_project_handler,
        LIST_PROJECT_KNOWLEDGEBASES_TOOL.name: list_knowledgebases_handler,
        ASSIGN_KNOWLEDGEBASE_TO_PROJECT_TOOL.name: assign_knowledgebase_handler,
        UNASSIGN_KNOWLEDGEBASE_FROM_PROJECT_TOOL.name: unassign_knowledgebase_handler,
        LIST_PROJECT_GRANTS_TOOL.name: list_grants_handler,
        FIND_PROJECT_SHARE_RECIPIENTS_TOOL.name: find_recipients_handler,
        CREATE_PROJECT_GRANT_TOOL.name: create_grant_handler,
        UPDATE_PROJECT_GRANT_TOOL.name: update_grant_handler,
        REVOKE_PROJECT_GRANT_TOOL.name: revoke_grant_handler,
        SET_PROJECT_AVATAR_TOOL.name: set_avatar_handler,
        CREATE_PROJECT_TOOL.name: create_project_handler,
        UPDATE_PROJECT_TOOL.name: update_project_handler,
        DELETE_PROJECT_TOOL.name: delete_project_handler,
        ADD_PROJECT_SOURCE_TOOL.name: add_source_handler,
        UPDATE_PROJECT_SOURCE_TOOL.name: update_source_handler,
        REMOVE_PROJECT_SOURCE_TOOL.name: remove_source_handler,
        ATTACH_WORKFLOW_TO_PROJECT_TOOL.name: attach_workflow_handler,
        DETACH_WORKFLOW_FROM_PROJECT_TOOL.name: detach_workflow_handler,
        ASSIGN_AGENT_TO_PROJECT_TOOL.name: assign_agent_handler,
        UNASSIGN_AGENT_FROM_PROJECT_TOOL.name: unassign_agent_handler,
        SET_CONVERSATION_PROJECT_TOOL.name: set_conversation_project_handler,
    }
