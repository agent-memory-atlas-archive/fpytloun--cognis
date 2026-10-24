from cognis.store.queries import create_llm_provider
from tests.unit.test_model_routing_routes import _auth_headers, _create_test_client, _seed_user


def test_private_provider_route_save_and_ownership(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'private.db'}")
    with _create_test_client(monkeypatch, tmp_path) as client:
        app = client.app

        async def seed():
            await _seed_user(app, "admin@cognis.local", "admin")
            await _seed_user(app, "other@cognis.local", "admin")
            async with app.state.session_factory() as session:
                await create_llm_provider(
                    session,
                    provider_id="anthropic-sample",
                    display_name="Sample Anthropic",
                    owner_email="admin@cognis.local",
                    location="controller",
                    backend="litellm",
                    config={"preset": "anthropic", "models": [{"model_id": "claude-opus-5-5"}]},
                )
                await session.commit()

        client.portal.call(seed)
        admin = _auth_headers(app, email="admin@cognis.local", role="admin")
        other = _auth_headers(app, email="other@cognis.local", role="admin")
        config = {
            "name": "claude-opus-5-5",
            "targets": [
                {"provider_id": "anthropic-sample", "model": "claude-opus-5-5", "priority": 0}
            ],
        }
        assert (
            client.post("/api/v1/inference-routes", headers=other, json=config).status_code == 422
        )
        response = client.post("/api/v1/inference-routes", headers=admin, json=config)
        assert response.status_code == 200, response.text
        route = response.json()
        assert route["owner_scope"] == "user"
        assert client.get("/api/v1/inference-routes", headers=other).json()["routes"] == []
        assert len(client.get("/api/v1/inference-routes", headers=admin).json()["routes"]) == 1

        async def resolve():
            plan = await app.state.providers.llm.inference_plan(
                model="cognis/claude-opus-5-5", acting_user_email="admin@cognis.local"
            )
            assert plan.candidates[0].target.provider_id == "anthropic-sample"

        client.portal.call(resolve)
        path = f"/api/v1/inference-routes/{route['route_id']}"
        update = {"config": config, "expected_revision": 1}
        assert client.put(path, headers=other, json=update).status_code == 409
        assert client.put(path, headers=admin, json=update).status_code == 200
        assert client.delete(f"{path}?expected_revision=2", headers=other).status_code == 409
        assert client.delete(f"{path}?expected_revision=2", headers=admin).status_code == 200


def test_private_route_does_not_inherit_global_reference_guards(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'scope.db'}")
    with _create_test_client(monkeypatch, tmp_path) as client:
        app = client.app

        async def seed():
            from cognis.ownership import SYSTEM_USER_EMAIL
            from cognis.store.models import Agent
            from cognis.store.queries import upsert_model_routing

            await _seed_user(app, "admin@cognis.local", "admin")
            await _seed_user(app, "other@cognis.local", "admin")
            async with app.state.session_factory() as session:
                for provider, owner in (
                    ("shared", SYSTEM_USER_EMAIL),
                    ("personal", "admin@cognis.local"),
                ):
                    await create_llm_provider(
                        session,
                        provider_id=provider,
                        display_name=provider,
                        owner_email=owner,
                        location="controller",
                        backend="litellm",
                        config={"preset": "openai", "models": [{"model_id": "gpt-4o-mini"}]},
                    )
                await upsert_model_routing(
                    session,
                    task_type="classifier",
                    model="cognis/chat",
                    provider_id=None,
                    owner_email=SYSTEM_USER_EMAIL,
                )
                session.add(
                    Agent(
                        agent_id="other-chat",
                        owner_email="other@cognis.local",
                        name="Other",
                        llm_config={"model": "cognis/chat"},
                    )
                )
                await session.commit()

        client.portal.call(seed)
        admin = _auth_headers(app, email="admin@cognis.local", role="admin")
        shared = {
            "name": "chat",
            "targets": [{"provider_id": "shared", "model": "gpt-4o-mini", "priority": 0}],
        }
        global_response = client.post("/api/v1/inference-routes", headers=admin, json=shared)
        assert global_response.status_code == 200, global_response.text
        global_route = global_response.json()
        mixed = {
            **shared,
            "targets": [
                *shared["targets"],
                {"provider_id": "personal", "model": "gpt-4o-mini", "priority": 1},
            ],
        }
        private_response = client.post("/api/v1/inference-routes", headers=admin, json=mixed)
        assert private_response.status_code == 200, private_response.text
        private = private_response.json()
        assert private["owner_scope"] == "user"
        assert (
            client.put(
                f"/api/v1/inference-routes/{global_route['route_id']}",
                headers=admin,
                json={"config": mixed, "expected_revision": 1},
            ).status_code
            == 409
        )
        assert (
            client.put(
                f"/api/v1/inference-routes/{private['route_id']}",
                headers=admin,
                json={"config": {**mixed, "name": "private-chat"}, "expected_revision": 1},
            ).status_code
            == 200
        )
        assert (
            client.delete(
                f"/api/v1/inference-routes/{private['route_id']}?expected_revision=2", headers=admin
            ).status_code
            == 200
        )
        assert (
            client.delete(
                f"/api/v1/inference-routes/{global_route['route_id']}?expected_revision=1",
                headers=admin,
            ).status_code
            == 409
        )

        async def switch_consumers_to_private():
            from sqlalchemy import delete

            from cognis.store.models import Agent, ModelRouting

            async with app.state.session_factory() as session:
                await session.execute(
                    delete(ModelRouting).where(ModelRouting.model == "cognis/chat")
                )
                agent = await session.get(Agent, "other-chat")
                agent.owner_email = "admin@cognis.local"
                await session.commit()

        client.portal.call(switch_consumers_to_private)
        private = client.post("/api/v1/inference-routes", headers=admin, json=mixed).json()
        assert (
            client.delete(
                f"/api/v1/inference-routes/{private['route_id']}?expected_revision=1", headers=admin
            ).status_code
            == 409
        )
        assert (
            client.put(
                f"/api/v1/inference-routes/{private['route_id']}",
                headers=admin,
                json={"config": {**mixed, "name": "blocked"}, "expected_revision": 1},
            ).status_code
            == 409
        )
        assert (
            client.delete(
                f"/api/v1/inference-routes/{global_route['route_id']}?expected_revision=1",
                headers=admin,
            ).status_code
            == 200
        )


def test_named_route_crud_role_reference_and_authorization(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'routes.db'}")
    with _create_test_client(monkeypatch, tmp_path) as client:
        app = client.app

        async def seed():
            await _seed_user(app, "admin@cognis.local", "admin")
            await _seed_user(app, "user@cognis.local", "user")
            async with app.state.session_factory() as session:
                for provider_id in ("first", "second"):
                    await create_llm_provider(
                        session,
                        provider_id=provider_id,
                        display_name=provider_id,
                        location="controller",
                        backend="litellm",
                        config={"preset": "openai", "models": [{"model_id": "gpt-4o-mini"}]},
                    )
                await session.commit()

        client.portal.call(seed)
        admin = _auth_headers(app, email="admin@cognis.local", role="admin")
        user = _auth_headers(app, email="user@cognis.local")
        config = {
            "name": "chat",
            "targets": [
                {"provider_id": "first", "model": "gpt-4o-mini", "priority": 0},
                {"provider_id": "second", "model": "gpt-4o-mini", "priority": 1},
            ],
        }
        assert client.post("/api/v1/inference-routes", json=config, headers=user).status_code == 403
        response = client.post("/api/v1/inference-routes", json=config, headers=admin)
        assert response.status_code == 200, response.text
        route = response.json()
        assert route["reference"] == "cognis/chat"
        assert client.get("/api/v1/inference-routes", headers=user).json()["routes"]
        assert (
            client.post("/api/v1/inference-routes", json=config, headers=admin).status_code == 409
        )
        routed = client.put(
            "/api/v1/model-routing",
            headers=admin,
            json={"classifier": {"model": "cognis/chat"}},
        )
        assert routed.status_code == 200, routed.text

        async def verify_reference():
            from sqlalchemy import select

            from cognis.store.models import ModelRouting

            async with app.state.session_factory() as session:
                rows = (await session.scalars(select(ModelRouting))).all()
                assert any(row.model == "cognis/chat" for row in rows), [
                    (row.task_type, row.model, row.provider_id) for row in rows
                ]

        client.portal.call(verify_reference)
        route_id = route["route_id"]
        update = {"config": config, "expected_revision": route["revision"]}
        assert (
            client.put(
                f"/api/v1/inference-routes/{route_id}", json=update, headers=admin
            ).status_code
            == 200
        )
        assert (
            client.put(
                f"/api/v1/inference-routes/{route_id}", json=update, headers=admin
            ).status_code
            == 409
        )
        assert (
            client.delete(
                f"/api/v1/inference-routes/{route_id}?expected_revision=1", headers=admin
            ).status_code
            == 409
        )
        assert (
            client.delete(
                f"/api/v1/inference-routes/{route_id}?expected_revision=2", headers=admin
            ).status_code
            == 409
        )
        assert (
            client.put(
                f"/api/v1/inference-routes/{route_id}",
                headers=admin,
                json={"config": {**config, "name": "renamed"}, "expected_revision": 2},
            ).status_code
            == 409
        )
        assert (
            client.put(
                "/api/v1/model-routing",
                headers=admin,
                json={"classifier": {"model": "first/gpt-4o-mini"}},
            ).status_code
            == 200
        )
        assert (
            client.delete(
                f"/api/v1/inference-routes/{route_id}?expected_revision=2", headers=admin
            ).status_code
            == 200
        )
