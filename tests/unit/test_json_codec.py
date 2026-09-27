from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from uuid import UUID

import msgspec
import pytest

from cognis import json_codec


def test_compact_codec_round_trip() -> None:
    value = {"unicode": "Příliš 🐈", "nested": [{"ok": True, "value": 3}]}

    encoded = json_codec.encode(value)

    assert isinstance(encoded, bytes)
    assert json_codec.encode_text(value) == encoded.decode()
    assert json_codec.decode(encoded) == value
    assert json_codec.loads(encoded) == value


def test_dumps_uses_compact_utf8_when_requested() -> None:
    value = {"unicode": "Příliš", "nested": {"value": 3}}

    rendered = json_codec.dumps(value, ensure_ascii=False, separators=(",", ":"))

    assert rendered == '{"unicode":"Příliš","nested":{"value":3}}'


def test_deterministic_encoding_sorts_mapping_keys() -> None:
    rendered = json_codec.dumps(
        {"z": 1, "a": {"d": 4, "b": 2}},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )

    assert rendered == '{"a":{"b":2,"d":4},"z":1}'


def test_default_str_uses_msgspec_hook() -> None:
    class Value:
        def __str__(self) -> str:
            return "converted"

    assert (
        json_codec.dumps(
            {"value": Value()},
            ensure_ascii=False,
            default=str,
            separators=(",", ":"),
        )
        == '{"value":"converted"}'
    )


@pytest.mark.parametrize(
    "value",
    [
        {"value": -0.0},
        {"value": 1e-7},
        {"value": 1e21},
        {"value": float("nan")},
        {"value": float("inf")},
        {"value": float("-inf")},
        {1: "integer key"},
        {"value": b"bytes"},
        {"value": datetime(2026, 1, 2, tzinfo=UTC)},
        {"value": UUID("12345678-1234-5678-1234-567812345678")},
    ],
)
def test_compact_dumps_preserves_stdlib_semantics(value: object) -> None:
    kwargs = {"ensure_ascii": False, "separators": (",", ":")}
    if isinstance(value, dict) and isinstance(value.get("value"), (bytes, datetime, UUID)):
        kwargs["default"] = str

    rendered = json_codec.dumps(value, **kwargs)

    assert rendered == json.dumps(value, **kwargs)
    if isinstance(value, dict) and isinstance(value.get("value"), float):
        number = value["value"]
        assert math.isfinite(number) or math.isnan(number) or math.isinf(number)


@pytest.mark.parametrize(
    "value",
    [
        {"value": -0.0},
        {"value": 1e-7},
        {"value": 1e21},
        {"value": float("nan")},
        {"value": float("inf")},
        {"value": b"bytes"},
        {"value": datetime(2026, 1, 2, tzinfo=UTC)},
    ],
)
def test_encode_preserves_compact_stdlib_bytes(value: object) -> None:
    if isinstance(value, dict) and isinstance(value.get("value"), (bytes, datetime)):
        with pytest.raises(TypeError):
            json_codec.encode(value)
        return

    expected = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
    assert json_codec.encode(value) == expected


@pytest.mark.parametrize(
    "raw",
    [
        b'{"value":NaN}',
        b'{"value":Infinity}',
        b'{"value":-Infinity}',
    ],
)
def test_loads_preserves_stdlib_non_finite_extensions(raw: bytes) -> None:
    assert json_codec.loads(raw) == json.loads(raw)


def test_loads_preserves_stdlib_error_details() -> None:
    raw = '{"value":}'
    with pytest.raises(json.JSONDecodeError) as expected:
        json.loads(raw)
    with pytest.raises(json.JSONDecodeError) as actual:
        json_codec.loads(raw)

    assert actual.value.doc == expected.value.doc
    assert actual.value.pos == expected.value.pos
    assert actual.value.lineno == expected.value.lineno
    assert actual.value.colno == expected.value.colno


def test_loads_preserves_invalid_utf8_error() -> None:
    with pytest.raises(UnicodeDecodeError):
        json_codec.loads(b'{"value":"\xff"}')


@pytest.mark.parametrize(
    "kwargs",
    [
        {"indent": 2},
        {"ensure_ascii": True},
        {"allow_nan": False},
        {"separators": (", ", ": ")},
    ],
)
def test_stdlib_only_formatting_matches_stdlib(kwargs: dict[str, object]) -> None:
    value = {"unicode": "Příliš", "value": 3}
    kwargs = {"ensure_ascii": False, **kwargs}

    assert json_codec.dumps(value, **kwargs) == json.dumps(value, **kwargs)


def test_loads_preserves_object_pairs_hook() -> None:
    pairs = json_codec.loads('{"a":1,"a":2}', object_pairs_hook=lambda value: value)

    assert pairs == [("a", 1), ("a", 2)]


def test_json_decode_error_catches_both_implementations() -> None:
    with pytest.raises(json_codec.JSONDecodeError):
        json_codec.loads("{")
    with pytest.raises(json_codec.JSONDecodeError):
        json_codec.loads("{", object_pairs_hook=dict)


def test_msgspec_rejects_unsupported_value_without_fallback() -> None:
    with pytest.raises((msgspec.EncodeError, TypeError)):
        json_codec.encode(object())
