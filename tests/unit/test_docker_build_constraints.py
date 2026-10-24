"""Docker builds must install dependencies from the workspace lockfile."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_controller_runtime_install_uses_frozen_constraints() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "COPY uv.lock ./" in dockerfile
    assert "uv export --locked --no-dev --no-emit-project --no-emit-workspace" in dockerfile
    assert "--format requirements-txt --no-hashes --output-file /constraints.txt" in dockerfile
    assert "--package cognis-controller" in dockerfile
    assert "COPY --from=controller-wheel /constraints.txt /tmp/constraints.txt" in dockerfile
    assert "--constraint /tmp/constraints.txt" in dockerfile


def test_executor_builds_use_frozen_base_and_full_constraints() -> None:
    dockerfile = (ROOT / "Dockerfile.executor").read_text(encoding="utf-8")

    assert "COPY pyproject.toml uv.lock ./" in dockerfile
    assert (
        dockerfile.count("uv export --locked --no-dev --no-emit-project --no-emit-workspace") == 2
    )
    assert "--output-file /tmp/executor-base-constraints.txt" in dockerfile
    assert "--output-file /opt/executor-full-constraints.txt" in dockerfile
    assert "COPY --from=python-builder /opt/executor-full-constraints.txt" in dockerfile
    assert dockerfile.count("--constraint /tmp/executor-base-constraints.txt") == 1
    # Workspace sources would install cognis-common editable from /app, which the
    # runtime stages do not copy (ImportError: cognis.json_codec in production).
    assert "--no-cache-dir --no-sources" in dockerfile
    assert "editable workspace installs leak into runtime" in dockerfile
    assert dockerfile.count("--constraint /tmp/executor-full-constraints.txt") == 1
