"""Runtime discovery and schema version use the canonical package owner."""

from cognis import __version__
from cognis.api.app import create_app


def test_openapi_uses_canonical_runtime_version() -> None:
    app = create_app()
    assert app.version == __version__
    assert app.openapi()["info"]["version"] == __version__
