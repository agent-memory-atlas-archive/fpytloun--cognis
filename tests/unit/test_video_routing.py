import pytest

from cognis.api.models import ModelRoutingResponse, ModelRoutingUpdateRequest
from cognis.core.routing_management import route_model_is_eligible as _route_model_is_eligible
from cognis.models.config import ModelInfo
from cognis.providers.llm.model_metadata import normalize_model_metadata, resolve_model_metadata
from cognis.providers.llm.routing import ROUTING_TASK_TYPES


def test_all_routing_roles_have_request_and_response_fields():
    request = ModelRoutingUpdateRequest(default={"model": "chat/model"})
    response = ModelRoutingResponse.model_validate(request.model_dump())
    for role in ROUTING_TASK_TYPES:
        assert getattr(request, role) is not None
        assert getattr(response, role) is not None
    assert response.default.model == "chat/model"
    for role in ("video_generation", "video_editing", "video_analysis"):
        parsed = ModelRoutingUpdateRequest.model_validate({role: {"model": "provider/video"}})
        assert (
            ModelRoutingResponse.model_validate(parsed.model_dump()).model_dump()[role]["model"]
            == "provider/video"
        )


def test_video_modes_do_not_depend_on_chat_eligibility():
    video = ModelInfo(model_id="veo-3.1-generate-preview", model_mode="video")
    for role in ("video_generation", "video_editing"):
        assert _route_model_is_eligible(role, model_id=video.model_id, model_info=video)
    assert not _route_model_is_eligible("default", model_id=video.model_id, model_info=video)
    analysis = ModelInfo(model_id="gemini", model_mode="chat", supports_video_input=True)
    assert _route_model_is_eligible(
        "video_analysis", model_id=analysis.model_id, model_info=analysis
    )


@pytest.mark.parametrize(
    "metadata",
    [
        {"mode": "video_generation"},
        {"model_mode": "video_generation"},
        {"output_modalities": ["video"]},
    ],
)
def test_catalog_video_alias_is_normalized_for_route_save(metadata):
    normalized = normalize_model_metadata(metadata)
    info = ModelInfo(model_id="veo-3.1-generate-preview", **normalized)
    assert info.model_mode == "video"
    assert info.supports_video_generation
    assert _route_model_is_eligible("video_generation", model_id=info.model_id, model_info=info)
    assert not _route_model_is_eligible("image_generation", model_id=info.model_id, model_info=info)
    assert not _route_model_is_eligible("default", model_id=info.model_id, model_info=info)


def test_saved_alias_and_cold_veo_metadata_are_video():
    assert ModelInfo(model_id="veo", model_mode="video_generation").model_mode == "video"
    metadata = resolve_model_metadata("veo-3.1-generate-preview", preset="gemini", base_url="")
    assert metadata["model_mode"] == "video"
    assert metadata["supports_video_generation"]


@pytest.mark.asyncio
async def test_veo_catalog_metadata_survives_binding_save_roundtrip(tmp_path):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from fastapi import HTTPException

    from cognis.core.management_access import ManagementActor
    from cognis.core.routing_management import get_bindings, put_bindings
    from cognis.ownership import SYSTEM_USER_EMAIL
    from cognis.store.database import create_engine, create_session_factory
    from cognis.store.models import Base, LLMProvider, User

    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path}/routing.db")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = create_session_factory(engine)
        async with factory() as session:
            session.add_all([User(email=SYSTEM_USER_EMAIL), User(email="admin@test", role="admin")])
            await session.flush()
            session.add(
                LLMProvider(
                    provider_id="gemini",
                    display_name="Google",
                    location="cloud",
                    backend="litellm",
                    owner_email=SYSTEM_USER_EMAIL,
                    config={"preset": "gemini"},
                )
            )
            await session.commit()
        metadata = resolve_model_metadata("veo-3.1-generate-preview", preset="gemini", base_url="")
        info = ModelInfo(model_id="veo-3.1-generate-preview", **metadata)
        llm = SimpleNamespace(
            resolve_model_reference=AsyncMock(return_value=(info.model_id, "gemini")),
            get_model_info=AsyncMock(return_value=info),
        )
        actor = ManagementActor(email="admin@test", role="admin")
        payload = ModelRoutingUpdateRequest(video_generation={"model": f"gemini/{info.model_id}"})
        await put_bindings(factory, llm, actor, payload)
        saved, _ = await get_bindings(factory)
        assert info.model_id in saved.video_generation.model
        with pytest.raises(HTTPException) as error:
            await put_bindings(
                factory,
                llm,
                actor,
                ModelRoutingUpdateRequest(image_generation={"model": f"gemini/{info.model_id}"}),
            )
        assert error.value.status_code == 422
    finally:
        await engine.dispose()
