"""Content-free diagnostics for managed inference failures.

Never stringify exceptions, parse messages, or serialize provider payloads.
Only fixed class labels, validated status integers and known codes leave here.
"""

from __future__ import annotations

from typing import Any

_CLASSES = {
    "BadRequestError": "request",
    "AuthenticationError": "authentication",
    "PermissionDeniedError": "permission",
    "NotFoundError": "not_found",
    "UnprocessableEntityError": "request",
    "RateLimitError": "rate_limit",
    "InternalServerError": "upstream",
    "APIStatusError": "http",
    "HTTPStatusError": "http",
    "APITimeoutError": "timeout",
    "TimeoutError": "timeout",
    "ReadTimeout": "timeout",
    "ConnectTimeout": "timeout",
    "APIConnectionError": "connection",
    "ConnectError": "connection",
    "APIResponseValidationError": "response_validation",
    "JSONDecodeError": "response_validation",
    "SystemOneResponseError": "response_validation",
}
_CODES = frozenset(
    {
        "json_validate_failed",
        "json_schema_invalid",
        "invalid_json_schema",
        "invalid_request_error",
        "context_length_exceeded",
        "max_tokens_exceeded",
        "tool_use_failed",
        "rate_limit_exceeded",
        "insufficient_quota",
        "invalid_api_key",
        "authentication_error",
        "permission_denied",
        "model_not_found",
        "unsupported_parameter",
        "invalid_parameter",
        "server_error",
        "timeout",
        "systemone_response_schema",
        "systemone_answer_set",
        "systemone_answer_type",
        "systemone_probability_sum",
        "systemone_choice_criteria",
        "systemone_score_criteria",
    }
)


def _code(value: Any) -> str | None:
    # Follow only documented error envelopes, never arbitrary payload trees.
    for _ in range(4):
        if type(value) is not dict:
            return None
        for key in ("code", "type"):
            candidate = value.get(key)
            if type(candidate) is str and candidate in _CODES:
                return candidate
        value = value.get("error")
    return None


def safe_inference_error(exc: Exception) -> dict[str, str | int | None]:
    """Classify a bounded exception chain without copying content into logs."""
    result: dict[str, str | int | None] = {
        "exception_class": "OtherError",
        "error_category": "unknown",
        "upstream_status": None,
        "upstream_code": None,
    }
    current: BaseException | None = exc
    seen: set[int] = set()
    for _ in range(4):
        if current is None or id(current) in seen:
            break
        seen.add(id(current))
        name = type(current).__name__
        if name in _CLASSES and result["exception_class"] == "OtherError":
            result["exception_class"] = name
            result["error_category"] = _CLASSES[name]
        attributes = vars(current)
        status = attributes.get("status_code")
        if status is None:
            response = attributes.get("response")
            status = getattr(response, "status_code", None)
        if type(status) is int and 400 <= status <= 599 and result["upstream_status"] is None:
            result["upstream_status"] = status
        direct = attributes.get("code")
        code = direct if type(direct) is str and direct in _CODES else None
        code = code or _code(attributes.get("body"))
        if code and result["upstream_code"] is None:
            result["upstream_code"] = code
        current = current.__cause__ or (
            None if current.__suppress_context__ else current.__context__
        )
    return result
