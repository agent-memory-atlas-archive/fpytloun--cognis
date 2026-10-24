"""Explicit local-only M2 Compose auth/discovery/owner-wide sidebar smoke.

No executor, LLM, notification permission, native app or production route is used.
The captured row feeds a separately labelled injected terminal replay test.
"""

import asyncio
import json
from pathlib import Path
from uuid import uuid4

import httpx
import websockets
from websockets.exceptions import ConnectionClosed

ORIGIN = "http://127.0.0.1:18763"


async def main() -> None:
    async with httpx.AsyncClient(base_url=ORIGIN, headers={"Origin": ORIGIN}, timeout=20) as client:
        discovery = (await client.get("/.well-known/cognis-client.json")).json()
        assert discovery["protocol"] == {"id": "cognis-client", "version": 1}
        assert discovery["capabilities"]["chat"] == 2
        assert (await client.get("/api/auth/me")).status_code == 401
        login = await client.post(
            "/api/auth/login",
            json={
                "email": "mac-companion@cognis-e2e.localdev.me",
                "password": "mac-companion-local-acceptance",
            },
        )
        login.raise_for_status()
        assert login.json()["status"] == "authenticated"
        assert (await client.get("/api/auth/me")).status_code == 200
        cookies = "; ".join(f"{key}={value}" for key, value in client.cookies.items())
        async with websockets.connect(
            "ws://127.0.0.1:18763/api/ws",
            origin=ORIGIN,
            additional_headers={"Cookie": cookies},
            open_timeout=10,
        ) as socket:
            initial = json.loads(await asyncio.wait_for(socket.recv(), 10))
            assert initial["type"] == "authenticated"
            created = await client.post(
                "/api/v1/agents", json={"name": "M2 resident fixture " + uuid4().hex[:8]}
            )
            created.raise_for_status()
            agent = created.json()
            created = await client.post(
                "/api/v1/conversations",
                json={
                    "agent_id": agent["agent_id"],
                    "title": "M2 isolated resident fixture",
                },
            )
            created.raise_for_status()
            conversation = created.json()
            async with asyncio.timeout(15):
                while True:
                    event = json.loads(await socket.recv())
                    if (
                        event.get("type") == "sidebar_conversation_upsert"
                        and event.get("conversation_id") == conversation["conversation_id"]
                    ):
                        assert event.get("conversation"), (
                            "Resident notifications require a canonical owner-wide summary"
                        )
                        output = Path(".local/platform-sidebar-replay.json")
                        output.parent.mkdir(exist_ok=True)
                        output.write_text(json.dumps(event, indent=2) + "\n")
                        break
        assert (await client.get("/api/v1/inbox")).status_code == 200
        logout = await client.post("/api/auth/logout")
        logout.raise_for_status()
        assert (await client.get("/api/auth/me")).status_code == 401
        try:
            async with websockets.connect(
                "ws://127.0.0.1:18763/api/ws",
                origin=ORIGIN,
                additional_headers={"Cookie": cookies},
                open_timeout=10,
            ) as socket:
                await asyncio.wait_for(socket.recv(), 10)
                raise AssertionError("Revoked session reconnected")
        except ConnectionClosed as error:
            assert error.code == 4401
    print(
        "PASS: real loopback discovery, login/me, one owner-wide WS row, inbox, logout and revoked-session rejection"
    )
    print("Replay input: .local/platform-sidebar-replay.json (no cookies or credentials persisted)")


if __name__ == "__main__":
    asyncio.run(main())
