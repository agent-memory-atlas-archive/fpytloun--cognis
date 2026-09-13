from __future__ import annotations

from cognis.api.error_sanitizer import sanitize_client_error_detail


def test_sanitize_client_error_detail_redacts_api_keys() -> None:
    detail = sanitize_client_error_detail(
        "Unauthorized: sk-secret123 api_key=super-secret key-test-value",
        fallback="request failed",
    )
    assert "sk-secret123" not in detail
    assert "super-secret" not in detail
    assert "key-test-value" not in detail
    assert "[redacted]" in detail


def test_sanitize_client_error_detail_redacts_generic_tokens() -> None:
    detail = sanitize_client_error_detail(
        "Database failed with token=secret-value password=hunter2",
        fallback="request failed",
    )
    assert "secret-value" not in detail
    assert "hunter2" not in detail
    assert detail.count("[redacted]") == 2


def test_sanitize_client_error_detail_redacts_long_quoted_content() -> None:
    detail = sanitize_client_error_detail(
        'Provider error: "' + ("x" * 80) + '"',
        fallback="request failed",
    )
    assert "x" * 20 not in detail
    assert "[redacted-content]" in detail


def test_sanitize_client_error_detail_truncates_long_messages() -> None:
    detail = sanitize_client_error_detail("boom " + ("y" * 500), fallback="request failed")
    assert len(detail) <= 200
    assert detail.endswith("...")


def test_sanitize_client_error_detail_uses_fallback_for_empty_values() -> None:
    assert sanitize_client_error_detail("   ", fallback="request failed") == "request failed"


def test_sanitize_client_error_detail_redacts_cognis_signed_url_signature() -> None:
    # Provider errors routinely echo the attachment URL they failed to fetch.
    # A Cognis signature stays usable until it expires, so it must not survive.
    detail = sanitize_client_error_detail(
        "Could not fetch https://cognis.test/api/artifacts/content/conv/art_1/a.png"
        "?exp=1789000000&sig=6f1c0b2d9a8e4f3b",
        fallback="request failed",
    )

    assert "6f1c0b2d9a8e4f3b" not in detail
    assert "sig=[redacted]" in detail
    # The path and expiry stay readable so the failure is still diagnosable.
    assert "art_1/a.png" in detail
    assert "exp=1789000000" in detail


def test_sanitize_client_error_detail_redacts_cloud_presigned_credentials() -> None:
    detail = sanitize_client_error_detail(
        "GET https://bucket.s3.test/o.png?X-Amz-Credential=AKIAEXAMPLE%2F20260912"
        "&X-Amz-Signature=deadbeefcafe&X-Amz-Expires=900 failed",
        fallback="request failed",
    )

    assert "AKIAEXAMPLE" not in detail
    assert "deadbeefcafe" not in detail
    assert "X-Amz-Expires=900" in detail
