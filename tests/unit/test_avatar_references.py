"""Agent-use authorization is shared by image and artifact avatar references."""

import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import pytest_asyncio

from cognis.artifacts.store import ArtifactStore, ArtifactStoreConfig
from cognis.models.config import GeneratedImage, ImageGenerationResult
from cognis.store.database import create_engine, create_session_factory
from cognis.store.models import Agent, AgentGrantRow, Base, User
from cognis.tools.builtin.artifact_tools import handle_artifact_tool
from cognis.tools.builtin.image import handle_image_tool


@pytest_asyncio.fixture
async def avatar_env(tmp_path):
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path}/avatars.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    store = ArtifactStore(
        ArtifactStoreConfig(
            path=str(tmp_path / "store"),
            base_url="https://cognis.test",
            signing_secret="test-signing-key",
        )
    )
    image_id = f"img_{uuid4().hex}"
    async with factory() as session:
        session.add_all(
            [
                User(email=email)
                for email in [
                    "owner@test.com",
                    "use@test.com",
                    "manage@test.com",
                    "denied@test.com",
                ]
            ]
        )
        await session.flush()
        session.add(
            Agent(
                agent_id="avatar-agent",
                name="Avatar",
                owner_email="owner@test.com",
                avatar_image_id=image_id,
            )
        )
        await session.flush()
        for permission in ("use", "manage"):
            session.add(
                AgentGrantRow(
                    grant_id=uuid4().hex,
                    agent_id="avatar-agent",
                    grantee_user_email=f"{permission}@test.com",
                    permission=permission,
                    granted_by="owner@test.com",
                )
            )
        await session.commit()
    await store.async_save(
        "avatars",
        image_id,
        "image",
        b"\x89PNG\r\navatar",
        "image/png",
        owner_email="owner@test.com",
    )
    try:
        yield factory, store, image_id
    finally:
        await engine.dispose()


async def invoke(env, tool, user, image_id=None):
    factory, store, current_id = env
    image_id = image_id or current_id
    llm = SimpleNamespace(
        image_generate=AsyncMock(
            return_value=ImageGenerationResult(
                model="image-model",
                images=[GeneratedImage(b64_json=base64.b64encode(b"image").decode())],
            )
        ),
        get_model_info=AsyncMock(return_value=SimpleNamespace(supports_vision=True)),
    )
    if tool.startswith("image_"):
        args = {"prompt": "Use this avatar"}
        args["references" if tool == "image_generate" else "images"] = [image_id]
        result = await handle_image_tool(
            tool, args, llm, artifact_store=store, session_factory=factory, user_email=user
        )
        return result, llm
    result = await handle_artifact_tool(
        tool,
        {"artifact_id": image_id},
        llm=llm,
        artifact_store=store,
        session_factory=factory,
        user_email=user,
        current_model="vision-model",
    )
    return result, llm


TOOLS = [
    "image_generate",
    "image_edit",
    "artifact_read",
    "artifact_get_metadata",
    "artifact_get_url",
]


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", TOOLS)
@pytest.mark.parametrize("user", ["owner@test.com", "use@test.com", "manage@test.com"])
async def test_current_avatar_allowed_for_agent_users(avatar_env, tool, user):
    result, llm = await invoke(avatar_env, tool, user)
    assert not result.is_error, result.output
    if tool.startswith("image_"):
        assert llm.image_generate.await_args.kwargs["images"][0].content_type == "image/png"
    elif tool == "artifact_read":
        assert result.metadata["native_attachment"]
    else:
        assert result.metadata["artifact_id"] == avatar_env[2]
        if tool == "artifact_get_url":
            assert "&sig=" in result.metadata["url"]


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", TOOLS)
@pytest.mark.parametrize(
    "condition",
    [
        "no_access",
        "unlinked",
        "missing_metadata",
        "missing_content",
        "wrong_owner",
        "revoked",
        "inactive",
    ],
)
async def test_avatar_denials_are_not_found(avatar_env, tool, condition):
    factory, store, image_id = avatar_env
    user = "use@test.com"
    async with factory() as session:
        agent = await session.get(Agent, "avatar-agent")
        if condition == "no_access":
            user = "denied@test.com"
        elif condition == "unlinked":
            agent.avatar_image_id = None
        elif condition == "missing_metadata":
            await store.async_delete_object("avatars", image_id)
        elif condition == "missing_content":
            await store.async_delete("avatars", image_id, "image")
        elif condition == "wrong_owner":
            await store.async_save(
                "avatars", image_id, "image", b"image", "image/png", owner_email="denied@test.com"
            )
        elif condition == "revoked":
            from datetime import UTC, datetime

            from sqlalchemy import select

            grant = (
                await session.execute(
                    select(AgentGrantRow).where(AgentGrantRow.grantee_user_email == user)
                )
            ).scalar_one()
            grant.revoked_at = datetime.now(UTC)
        elif condition == "inactive":
            (await session.get(User, user)).is_active = False
        await session.commit()
    result, llm = await invoke(avatar_env, tool, user)
    assert result.is_error
    assert "not found" in result.output.lower()
    llm.image_generate.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("agent_type,is_system", [("secondary", False), ("secondary", True)])
async def test_secondary_and_system_agent_avatars(avatar_env, agent_type, is_system):
    factory, _, _ = avatar_env
    async with factory() as session:
        agent = await session.get(Agent, "avatar-agent")
        agent.agent_type = agent_type
        agent.is_system = is_system
        await session.commit()
    result, _ = await invoke(avatar_env, "artifact_get_metadata", "use@test.com")
    assert not result.is_error


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["download", "view"])
async def test_avatar_signed_url_serves_content_and_rejects_stale_link(avatar_env, mode):
    from urllib.parse import parse_qs, urlparse

    from fastapi import FastAPI, HTTPException, Request

    from cognis.api.routes.artifacts import _serve_signed_artifact
    from cognis.store.queries import get_artifact_record

    factory, store, image_id = avatar_env
    result, _ = await invoke(avatar_env, "artifact_get_url", "use@test.com")
    assert not result.is_error
    url = await store.async_get_public_url("avatars", image_id, "image", mode=mode)
    query = parse_qs(urlparse(url).query)
    app = FastAPI()
    app.state.session_factory = factory
    app.state.artifact_store = store
    request = Request(
        {
            "type": "http",
            "app": app,
            "scheme": "https",
            "server": ("cognis.test", 443),
            "path": urlparse(url).path,
            "query_string": urlparse(url).query.encode(),
            "headers": [],
        }
    )
    kwargs = dict(
        namespace="avatars",
        object_id=image_id,
        filename="image",
        exp=int(query["exp"][0]),
        sig=query["sig"][0],
        mode=mode,
    )
    response = await _serve_signed_artifact(request, **kwargs)
    assert response.status_code == 200
    from datetime import UTC, datetime

    from sqlalchemy import select

    async with factory() as session:
        grant = (
            await session.execute(
                select(AgentGrantRow).where(AgentGrantRow.grantee_user_email == "use@test.com")
            )
        ).scalar_one()
        grant.revoked_at = datetime.now(UTC)
        await session.commit()
    denied, _ = await invoke(avatar_env, "artifact_get_url", "use@test.com")
    assert denied.is_error
    assert (await _serve_signed_artifact(request, **kwargs)).status_code == 200
    await store.async_save(
        "avatars", image_id, "image", b"image", "image/png", owner_email="denied@test.com"
    )
    with pytest.raises(HTTPException) as exc:
        await _serve_signed_artifact(request, **kwargs)
    assert exc.value.status_code == 404
    await store.async_save(
        "avatars", image_id, "image", b"image", "image/png", owner_email="owner@test.com"
    )
    async with factory() as session:
        assert await get_artifact_record(session, image_id) is None
        (await session.get(Agent, "avatar-agent")).avatar_image_id = None
        await session.commit()
    with pytest.raises(HTTPException) as exc:
        await _serve_signed_artifact(request, **kwargs)
    assert exc.value.status_code == 404
    kwargs["sig"] = "tampered-signature"
    with pytest.raises(HTTPException) as exc:
        await _serve_signed_artifact(request, **kwargs)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", TOOLS)
async def test_avatar_fallback_cannot_override_deleted_registry_record(avatar_env, tool):
    from cognis.store.models import ArtifactRecordRow

    factory, _, image_id = avatar_env
    async with factory() as session:
        session.add(
            ArtifactRecordRow(
                artifact_id=image_id,
                namespace="images",
                object_id=image_id,
                filename="image.png",
                owner_email="owner@test.com",
                mime_type="image/png",
                kind="image",
                status="deleted",
            )
        )
        await session.commit()
    result, _ = await invoke(avatar_env, tool, "owner@test.com")
    assert result.is_error
    assert "not found" in result.output.lower()


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", TOOLS)
async def test_project_only_avatar_does_not_grant_agent_avatar_access(avatar_env, tool):
    from cognis.store.models import ProjectRow

    factory, _, image_id = avatar_env
    async with factory() as session:
        (await session.get(Agent, "avatar-agent")).avatar_image_id = None
        session.add(
            ProjectRow(
                project_id=uuid4().hex,
                name="Project",
                owner_email="owner@test.com",
                avatar_image_id=image_id,
            )
        )
        await session.commit()
    result, _ = await invoke(avatar_env, tool, "owner@test.com")
    assert result.is_error
    assert "not found" in result.output.lower()
