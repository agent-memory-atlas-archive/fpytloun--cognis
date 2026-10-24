"""Keep build metadata separate from executor implementation."""

from __future__ import annotations

import runpy
from pathlib import Path

import pytest

VERIFY = runpy.run_path(
    str(Path(__file__).resolve().parents[2] / "scripts/verify_controller_dist_assets.py")
)["verify_dockerfile"]
DOCKERFILE = """
FROM python:3.12-slim AS controller-wheel
COPY packages/executor/pyproject.toml ./packages/executor/pyproject.toml
FROM python:3.12-slim AS runtime
RUN --mount=type=bind,from=common-wheel,source=/dist,target=/tmp/common-wheels true
RUN --mount=type=bind,from=controller-wheel,source=/dist,target=/tmp/controller-wheels true
RUN apt-get install ffmpeg
HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/health')"
CMD ["cognis-controller", "serve"]
"""


def test_build_only_workspace_manifest_is_allowed(tmp_path: Path) -> None:
    path = tmp_path / "Dockerfile"
    path.write_text(DOCKERFILE)
    VERIFY(path)


@pytest.mark.parametrize(
    "content",
    [
        DOCKERFILE.replace(
            "COPY packages/executor/pyproject.toml ./packages/executor/pyproject.toml",
            "COPY packages/executor/ ./packages/executor/",
        ),
        DOCKERFILE + "\nCOPY packages/executor/pyproject.toml ./packages/executor/pyproject.toml\n",
        DOCKERFILE + "\nCOPY packages/executor/ ./packages/executor/\n",
    ],
)
def test_executor_code_and_runtime_metadata_stay_forbidden(tmp_path: Path, content: str) -> None:
    path = tmp_path / "Dockerfile"
    path.write_text(content)
    with pytest.raises(RuntimeError, match="forbidden image settings"):
        VERIFY(path)
