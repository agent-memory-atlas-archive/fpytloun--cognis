from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from cognis.knowledgebase.service import KnowledgebaseService
from cognis.store.models import Agent
from cognis.store.queries import assign_knowledgebase_to_agent, create_agent_grant
from cognis.tools.builtin.knowledgebase import build_knowledgebase_tool_handlers
from cognis.tools.registry import ToolExecutionContext
from tests.unit.test_knowledgebase_access import _setup


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scenario",
    [
        "assigned",
        "unassigned",
        "revoked",
        "draft",
        "missing_agent",
        "foreign_kb",
        "wrong_agent_owner",
        "grantee",
        "foreign_actor",
        "direct_owner",
    ],
)
async def test_real_kb_handlers_preserve_owner_and_assignment_boundary(tmp_path, scenario):
    engine, factory = await _setup(tmp_path)
    vector = SimpleNamespace(health=AsyncMock(return_value={"status": "ok"}))
    service = KnowledgebaseService(
        session_factory=factory,
        artifact_store=None,
        llm=None,
        vector_backend=vector,
        enabled=True,
    )
    handlers = build_knowledgebase_tool_handlers(service)
    actor, agent, agent_owner, kb = (
        "owner@example.com",
        "agent_owner",
        "owner@example.com",
        "kb_owner",
    )
    try:
        async with factory() as session:
            if scenario != "unassigned":
                await assign_knowledgebase_to_agent(
                    session, owner_email=actor, knowledgebase_id=kb, agent_id=agent
                )
            row = await session.get(Agent, agent)
            if scenario == "revoked":
                row.permissions = {"allowed_knowledgebases": []}
            if scenario == "draft":
                row.status = "draft"
            if scenario == "grantee":
                await create_agent_grant(
                    session,
                    agent_id=agent,
                    grantee_user_email="grantee@example.com",
                    executor_scope="shared_pool",
                    granted_by=actor,
                )
                actor = "grantee@example.com"
            await session.commit()
        if scenario == "missing_agent":
            agent = "absent-agent"
        if scenario == "foreign_kb":
            kb = "kb_other"
        if scenario == "wrong_agent_owner":
            agent_owner = "other@example.com"
        if scenario == "foreign_actor":
            actor = "other@example.com"
        if scenario == "direct_owner":
            agent = None
        context = ToolExecutionContext(
            executor_handle=None,
            runtime_metadata={
                "runtime_access": {
                    "user_email": actor,
                    "agent_id": agent,
                    "agent_owner_email": agent_owner,
                }
            },
        )
        for name in (
            "knowledgebase_status",
            "knowledgebase_diagnostics",
            "knowledgebase_list_jobs",
            "knowledgebase_list_artifacts",
        ):
            result = await handlers[name]({"knowledgebase_id": kb}, context)
            if scenario in {"assigned", "direct_owner"}:
                if name in {"knowledgebase_status", "knowledgebase_diagnostics"}:
                    assert result["chunk_count"] == 0
                    assert result["artifact_counts"] == {}
                else:
                    assert result == []
            else:
                assert result["error"] == "knowledgebase_not_found_or_unavailable"
        if scenario not in {"assigned", "direct_owner"}:
            vector.health.assert_not_called()
    finally:
        await engine.dispose()
