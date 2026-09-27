"""Fast JSON operations with narrow stdlib compatibility fallbacks."""

from __future__ import annotations

import json as _stdlib_json
from collections.abc import Callable
from typing import Any

import msgspec

JSONDecodeError = _stdlib_json.JSONDecodeError
JSONEncoder = _stdlib_json.JSONEncoder
JSONDecoder = _stdlib_json.JSONDecoder
_UNSET = object()

_encoder = msgspec.json.Encoder()
_deterministic_encoder = msgspec.json.Encoder(order="deterministic")
_str_encoder = msgspec.json.Encoder(enc_hook=str)
_deterministic_str_encoder = msgspec.json.Encoder(order="deterministic", enc_hook=str)


def encode(value: Any) -> bytes:
    """Encode compact UTF-8 JSON bytes without changing stdlib semantics."""

    if _requires_stdlib(value):
        return _stdlib_json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    return _encoder.encode(value)


def encode_text(value: Any) -> str:
    """Encode compact JSON text using msgspec."""

    return encode(value).decode("utf-8")


def decode(value: str | bytes | bytearray | memoryview) -> Any:
    """Decode one complete JSON document using msgspec."""

    if isinstance(value, str) and type(value) is not str:
        value = str(value)
    elif isinstance(value, bytes) and type(value) is not bytes:
        value = bytes(value)
    try:
        return msgspec.json.decode(value)
    except msgspec.DecodeError:
        fallback_value = bytes(value) if isinstance(value, memoryview) else value
        return _stdlib_json.loads(fallback_value)


def _requires_stdlib(value: Any, *, seen: set[int] | None = None) -> bool:
    """Return whether msgspec would differ from stdlib for this value."""

    if value is None or isinstance(value, (str, bool, int)):
        return False
    if isinstance(value, float):
        # Float spellings are part of canonical hashes and differ between
        # encoders for edge exponent forms. Keep the established stdlib bytes.
        return True
    if isinstance(value, (list, tuple)):
        seen = seen or set()
        identity = id(value)
        if identity in seen:
            return True
        seen.add(identity)
        requires_stdlib = any(_requires_stdlib(item, seen=seen) for item in value)
        seen.remove(identity)
        return requires_stdlib
    if isinstance(value, dict):
        seen = seen or set()
        identity = id(value)
        if identity in seen:
            return True
        seen.add(identity)
        requires_stdlib = any(
            not isinstance(key, str) or _requires_stdlib(item, seen=seen)
            for key, item in value.items()
        )
        seen.remove(identity)
        return requires_stdlib
    return True


def dumps(
    value: Any,
    *,
    skipkeys: bool = False,
    ensure_ascii: bool | object = _UNSET,
    check_circular: bool = True,
    allow_nan: bool = True,
    cls: type[_stdlib_json.JSONEncoder] | None = None,
    indent: int | str | None = None,
    separators: tuple[str, str] | None = None,
    default: Callable[[Any], Any] | None = None,
    sort_keys: bool = False,
    **kwargs: Any,
) -> str:
    """Serialize JSON text, accelerating compact compatible calls with msgspec."""

    ascii_output = True if ensure_ascii is _UNSET else bool(ensure_ascii)
    if (
        skipkeys
        or not check_circular
        or cls is not None
        or indent is not None
        or separators is None
        or ascii_output
        or not allow_nan
        or kwargs
        or (separators is not None and separators != (",", ":"))
        or default is not None
        or _requires_stdlib(value)
    ):
        return _stdlib_json.dumps(
            value,
            skipkeys=skipkeys,
            ensure_ascii=ascii_output,
            check_circular=check_circular,
            allow_nan=allow_nan,
            cls=cls,
            indent=indent,
            separators=separators,
            default=default,
            sort_keys=sort_keys,
            **kwargs,
        )

    if default is str:
        encoder = _deterministic_str_encoder if sort_keys else _str_encoder
    else:
        encoder = _deterministic_encoder if sort_keys else _encoder
    return encoder.encode(value).decode("utf-8")


def loads(
    value: str | bytes | bytearray,
    *,
    cls: type[_stdlib_json.JSONDecoder] | None = None,
    object_hook: Callable[[dict[str, Any]], Any] | None = None,
    parse_float: Callable[[str], Any] | None = None,
    parse_int: Callable[[str], Any] | None = None,
    parse_constant: Callable[[str], Any] | None = None,
    object_pairs_hook: Callable[[list[tuple[str, Any]]], Any] | None = None,
    **kwargs: Any,
) -> Any:
    """Deserialize JSON, retaining stdlib-only hooks when requested."""

    if (
        cls is not None
        or object_hook is not None
        or parse_float is not None
        or parse_int is not None
        or parse_constant is not None
        or object_pairs_hook is not None
        or kwargs
    ):
        return _stdlib_json.loads(
            value,
            cls=cls,
            object_hook=object_hook,
            parse_float=parse_float,
            parse_int=parse_int,
            parse_constant=parse_constant,
            object_pairs_hook=object_pairs_hook,
            **kwargs,
        )
    return decode(value)


def dump(value: Any, fp: Any, **kwargs: Any) -> None:
    """Retain stdlib stream writing for the file-like API."""

    _stdlib_json.dump(value, fp, **kwargs)


def load(fp: Any, **kwargs: Any) -> Any:
    """Retain stdlib stream reading for the file-like API."""

    return _stdlib_json.load(fp, **kwargs)
