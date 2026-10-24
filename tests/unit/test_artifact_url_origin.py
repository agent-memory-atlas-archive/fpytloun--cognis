"""Artifact URLs must belong to an explicitly configured controller origin."""

from __future__ import annotations

import pytest

from cognis.core.agent_loop import _artifact_url_pattern


@pytest.mark.parametrize("configured_origin", [None, ""])
def test_artifact_urls_require_a_configured_origin(
    monkeypatch: pytest.MonkeyPatch, configured_origin: str | None
) -> None:
    if configured_origin is None:
        monkeypatch.delenv("COGNIS_PUBLIC_BASE_URL", raising=False)
    else:
        monkeypatch.setenv("COGNIS_PUBLIC_BASE_URL", configured_origin)

    pattern = _artifact_url_pattern()

    assert (
        pattern.search(
            "https://controller.example.invalid/api/v1/artifacts/content/"
            "art_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/file"
        )
        is None
    )


def test_artifact_urls_use_the_exact_configured_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COGNIS_PUBLIC_BASE_URL", "https://controller.example.invalid/cognis/")
    pattern = _artifact_url_pattern()
    url = (
        "https://controller.example.invalid/cognis/api/v1/artifacts/content/"
        "art_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/file"
    )

    match = pattern.search(f'Attachment: "{url}"')
    assert match is not None
    assert match.group() == url
    assert (
        pattern.search(url.replace("controller.example.invalid", "other.example.invalid")) is None
    )
    assert (
        pattern.search(url.replace("controller.example.invalid", "controllerXexampleYinvalid"))
        is None
    )
