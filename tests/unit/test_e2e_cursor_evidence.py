from cognis.api.chat_v2.cursors import InternalChatCursorPayload, decode_cursor, encode_cursor
from tests.e2e.cursor_evidence import cursor_position


def test_real_cursor_producer_renewal_and_changed_position():
    payload = InternalChatCursorPayload(
        scope_key="conversation:fixture",
        conversation_id="fixture",
        projection_version="fixture-projection",
        view_revision=3,
        session_watermarks=[{"store": "intaris", "session_id": "fixture-session", "last_seq": 7}],
        issued_at="2025-01-01T00:00:00Z",
        expires_at="2025-01-02T00:00:00Z",
    )
    secret = b"synthetic-test-signing-secret"

    def token(value):
        result = encode_cursor(value, secret)
        assert decode_cursor(result, secret) == value
        return result

    renewed = payload.model_copy(
        update={
            "issued_at": "2025-01-01T01:00:00Z",
            "expires_at": "2025-01-02T01:00:00Z",
        }
    )
    assert token(payload) != token(renewed)
    assert cursor_position(token(payload)) == cursor_position(token(renewed))
    assert set(cursor_position(token(payload))) == set(payload.model_dump(exclude_none=True)) - {
        "issued_at",
        "expires_at",
    }
    for changes in (
        {"view_revision": 4},
        {"conversation_id": "other"},
        {"scope_key": "conversation:other"},
        {"session_watermarks": [payload.session_watermarks[0].model_copy(update={"last_seq": 8})]},
        {"before_positions": payload.session_watermarks},
        {"ordinal_frontiers": [1]},
        {"projection_version": "other-projection"},
        {"graph_fingerprint": "changed"},
    ):
        assert cursor_position(token(payload)) != cursor_position(
            token(payload.model_copy(update=changes))
        )
