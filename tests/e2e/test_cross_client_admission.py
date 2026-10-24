"""Real transport tests. Requires the isolated e2e_stack; no synthetic projections."""

import json
import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
import websockets.sync.client as wsc

from tests.e2e.conftest import (
    E2E_AGENT_ID,
    E2EStack,
    _subscribe_chat_v2,
    capture_ws_events,
    clear_active_scenario,
    inject_scenario,
)
from tests.e2e.cursor_evidence import cursor_position

pytestmark = pytest.mark.e2e


def test_cross_client_browser_recipients(e2e_stack: E2EStack, tmp_path: Path) -> None:
    """Run the real two-context browser matrix against this fixture's own stack."""
    ui = Path(__file__).parents[2] / "ui"
    environment = dict(os.environ)
    environment.pop("COGNIS_LOCAL_ADMIN_EMAIL", None)
    environment.pop("COGNIS_LOCAL_ADMIN_PASSWORD", None)
    environment.update(
        {
            "COGNIS_E2E_URL": e2e_stack.cognis_url,
            "COGNIS_E2E_ADMIN_EMAIL": e2e_stack.admin_email,
            "COGNIS_E2E_ADMIN_PASSWORD": e2e_stack.admin_password,
            "MOCK_LLM_URL": e2e_stack.mock_llm_url,
        }
    )
    diagnostic_args = []
    diagnostic_cases = {
        "main_queued_after_ui_stop": r"independent main recipient converges before sender application ACK \(queued_after_ui_stop\)",
        "scoped_normal": r"independent scoped recipient converges before sender application ACK \(normal\)",
    }
    diagnostic = os.environ.get("COGNIS_E2E_DIAGNOSTIC_CASE")
    if diagnostic:
        assert diagnostic in diagnostic_cases, "Unsupported diagnostic selection"
        diagnostic_args = ["--grep", diagnostic_cases[diagnostic]]
    if os.environ.get("COGNIS_E2E_DIAGNOSTIC_MAIN_NORMAL") == "1":
        assert not diagnostic, "Diagnostic selectors are mutually exclusive"
        diagnostic_args = [
            "--grep",
            r"independent main recipient converges before sender application ACK \(normal\)",
        ]
    with (tmp_path / "cross-client-browser.log").open("w") as output:
        result = subprocess.run(
            [
                "npx",
                "--no-install",
                "playwright",
                "test",
                "e2e/cross-client-admission.spec.ts",
                "--workers=1",
                "--retries=0",
                *diagnostic_args,
            ],
            cwd=ui,
            env=environment,
            stdout=output,
            stderr=subprocess.STDOUT,
            timeout=600,
            check=False,
        )
    assert result.returncode == 0, f"Browser lifecycle acceptance failed; log: {output.name}"


@pytest.mark.parametrize(
    ("admission", "hold_canonical_delivery"),
    [("normal", False), ("absorbed", False), ("queued_after_ui_stop", False), ("absorbed", True)],
)
def test_append_barrier_early_read_recovers_on_real_invalidation(
    e2e_stack: E2EStack,
    admission: str,
    hold_canonical_delivery: bool,
) -> None:
    stack = e2e_stack
    created = stack.post(
        "/api/v1/conversations",
        json={
            "agent_id": E2E_AGENT_ID,
            "title": f"Append barrier {admission}",
        },
    )
    assert created.status_code == 200, created.text
    conversation_id = created.json()["conversation_id"]
    inject_scenario(stack.mock_llm_url, "single-phase-stream")
    capture_ws_events(stack, conversation_id, "scenario:single-phase-stream")
    snapshot_path = f"/api/v1/chat/v2/conversations/{conversation_id}/snapshot"
    initial_response = stack.get(snapshot_path)
    assert initial_response.status_code == 200, initial_response.text
    initial = initial_response.json()
    assert httpx.get(f"{stack.cognis_url}{snapshot_path}", timeout=15).status_code == 401
    outsider_email = f"cross-client-{uuid4().hex}@cognis-test.example.com"
    outsider_password = uuid4().hex
    user = stack.post(
        "/api/v1/admin/users",
        json={
            "email": outsider_email,
            "name": "Synthetic isolation recipient",
            "password": outsider_password,
            "role": "user",
        },
    )
    assert user.status_code in (200, 201), user.text
    login = stack.http.post(
        f"{stack.cognis_url}/api/auth/login",
        json={
            "email": outsider_email,
            "password": outsider_password,
            "mode": "native",
        },
    )
    assert login.status_code == 200, login.text
    outsider_token = login.json()["token"]
    denied = stack.http.get(
        f"{stack.cognis_url}{snapshot_path}",
        headers={"Authorization": f"Bearer {outsider_token}"},
    )
    assert denied.status_code in (403, 404)
    with wsc.connect(stack.ws_url, close_timeout=5, open_timeout=10) as outsider:
        outsider.send(json.dumps({"type": "auth", "token": outsider_token}))
        assert json.loads(outsider.recv(timeout=15))["type"] == "authenticated"
        outsider.send(
            json.dumps(
                {
                    "type": "chat_v2_subscribe",
                    "scope": initial["scope"],
                    "cursor": initial["cursor"],
                }
            )
        )
        rejected = json.loads(outsider.recv(timeout=15))
        assert rejected["type"] == "error", rejected
    session_id = initial["state"]["active_session"]["session_id"]
    detail = stack.get(f"/api/v1/sessions/{session_id}/intaris")
    assert detail.status_code == 200, detail.text
    intaris_session_id = detail.json()["intaris_session_id"]
    client_id = uuid4().hex
    text = f"Synthetic barrier input {client_id}"
    proxy = stack.append_proxy

    def send(identity, content):
        transaction_id = uuid4().hex
        assert transaction_id != identity
        return httpx.put(
            f"{stack.cognis_url}/api/v1/chat/v2/conversations/{conversation_id}/messages/{transaction_id}",
            headers=stack.admin_headers(),
            json={"client_message_id": identity, "content": content, "attachments": []},
            timeout=90,
        )

    pool = ThreadPoolExecutor(max_workers=2)
    leader_turn_id = None
    try:
        if admission != "normal":
            armed = stack.http.post(
                f"{stack.mock_llm_url}/__mock/barrier",
                json={"scenario_id": "single-phase-stream", "turn_index": 1},
            )
            assert armed.status_code == 201, armed.text
        proxy.arm(intaris_session_id, client_id)
        if admission != "normal":
            leader = pool.submit(send, uuid4().hex, "Synthetic active turn")
            entered = stack.http.get(f"{stack.mock_llm_url}/__mock/barrier", timeout=35)
            assert entered.status_code == 204, entered.text
            assert leader.result(timeout=90).status_code == 202
            leader_state = stack.get(snapshot_path).json()["runtime"]["active_turn"]
            assert leader_state["status"] == "running", leader_state
            leader_turn_id = leader_state["turn_id"]
        sent = pool.submit(send, client_id, text)
        if admission != "normal":
            queued = sent.result(timeout=90)
            assert queued.status_code == 202, queued.text
            assert queued.json()["status"] == "queued", queued.text
            queue_snapshot = stack.get(snapshot_path).json()
            assert any(
                item.get("client_message_id") == client_id
                for item in queue_snapshot["queue"]["messages"]
            ), queue_snapshot["queue"]
            if admission == "absorbed":
                released = stack.http.put(f"{stack.mock_llm_url}/__mock/barrier")
                assert released.status_code == 204, released.text
            else:
                cancelled = stack.post(
                    f"/api/v1/chat/v2/conversations/{conversation_id}/cancel",
                    json={"client_txn_id": uuid4().hex},
                )
                assert cancelled.status_code == 200, cancelled.text
                stack.http.delete(f"{stack.mock_llm_url}/__mock/barrier")
        proxy.wait_entered()
        # Subscribe while the real provider's request is held before Intaris.
        with wsc.connect(stack.ws_url, close_timeout=5, open_timeout=10) as recipient:
            recipient.send(json.dumps({"type": "auth", "token": stack.admin_token}))
            assert json.loads(recipient.recv(timeout=15))["type"] == "authenticated"
            before = _subscribe_chat_v2(recipient, stack, conversation_id)
            # Ping is processed after subscribe hydration on this socket. Consume
            # all earlier frames/hints before releasing the held canonical write.
            recipient.send(json.dumps({"type": "ping"}))
            while True:
                event = json.loads(recipient.recv(timeout=15))
                assert event["type"] != "error", event
                if event["type"] == "pong":
                    break
            cursor = before["cursor"]
            sync_path = snapshot_path.replace("/snapshot", "/sync")
            early = stack.get(sync_path, params={"cursor": cursor})
            assert early.status_code == 200, early.text
            early_delta = early.json()
            assert not early_delta["reset_required"]

            # Re-signing renews timestamps without changing canonical stream positions.
            assert cursor_position(early_delta["cursor_after"]) == cursor_position(cursor)
            assert not any(
                op.get("item", {}).get("client_message_id") == client_id
                for op in early_delta["ops"]
            )
            proxy.release()
            items = {item["id"]: item for item in before["timeline"]["items"]}
            deadline = time.monotonic() + 90
            found = []
            recovery_reads = 0
            delivery_gate_checked = False
            while not found:
                remaining = deadline - time.monotonic()
                assert remaining > 0, "Missing canonical post-append recovery"
                event = json.loads(recipient.recv(timeout=remaining))
                assert event["type"] != "error", event
                if (
                    event["type"] != "scope_invalidated"
                    or event.get("reason") != "event_store_session_invalidated"
                ):
                    continue
                if hold_canonical_delivery and not delivery_gate_checked:
                    # Receiver-side delivery suppression only: this is the
                    # actual authorized post-append notification, not a made-up
                    # event or an origin-publication hook. Keep it pending while
                    # a protocol fence completes. No canonical read is allowed
                    # to consume this or other hints during this bounded phase.
                    held_notification = event
                    recipient.send(json.dumps({"type": "ping"}))
                    while True:
                        buffered = json.loads(recipient.recv(timeout=15))
                        assert buffered["type"] != "error", buffered
                        if buffered["type"] == "pong":
                            break
                    assert recovery_reads == 0
                    assert not found
                    delivery_gate_checked = True
                    # Release exactly the held notification to the normal
                    # recipient read below; real append and IDs are unchanged.
                    event = held_notification
                recovery_reads += 1
                response = stack.get(sync_path, params={"cursor": cursor})
                assert response.status_code == 200, response.text
                delta = response.json()
                assert not delta["reset_required"]
                for op in delta["ops"]:
                    if op["op"] == "upsert_item":
                        items[op["item"]["id"]] = op["item"]
                cursor = delta["cursor_after"]
                found = [
                    item for item in items.values() if item.get("client_message_id") == client_id
                ]
            assert len(found) == 1
            assert found[0]["content"] == text
            assert found[0]["source_refs"]
            assert delivery_gate_checked is hold_canonical_delivery
            if admission == "absorbed":
                assert found[0]["turn_id"] == leader_turn_id
            elif admission == "queued_after_ui_stop":
                assert found[0]["turn_id"] != leader_turn_id
                assert before["runtime"]["active_turn"]["turn_id"] == found[0]["turn_id"]
                assert before["runtime"]["active_turn"]["status"] in ("starting", "running")
            assert sent.result(timeout=90).status_code == 202
    finally:
        try:
            proxy.cancel()
        finally:
            try:
                if admission != "normal":
                    stack.http.delete(f"{stack.mock_llm_url}/__mock/barrier")
            finally:
                try:
                    clear_active_scenario(stack.mock_llm_url)
                finally:
                    pool.shutdown(wait=True, cancel_futures=True)
                    clear_active_scenario(stack.mock_llm_url)
