"""Python asset inference, shared preparation, and recoverable failures."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import os
import subprocess
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import psutil
import pytest

from cognis.core.skill_assets import prepare_loaded_skill_assets
from cognis.executor import skill_python
from cognis.executor.runner import ExecutorRunner
from cognis.executor.skill_assets import prepare_skill_assets
from cognis.models.skill import SkillAssetRef
from cognis.models.tool import ExecutorConfig


def bundle(scripts: dict[str, str]) -> dict:
    assets = []
    for name, source in scripts.items():
        content = source.encode()
        assets.append(
            {
                "asset_id": name,
                "filename": name,
                "content_hash": hashlib.sha256(content).hexdigest(),
                "size_bytes": len(content),
                "content_type": "text/x-python",
                "content_b64": base64.b64encode(content).decode(),
            }
        )
    return {
        "owner_email": "test@example.com",
        "skill_id": "python-helper",
        "version_id": "version-one",
        "assets": assets,
    }


def test_pep723_is_authoritative_and_combines_constraints():
    dependencies, constraints = skill_python.script_requirements(
        {
            "one.py": b'# /// script\n# dependencies = ["rich==13.9.4"]\n'
            b'# requires-python = ">=3.12"\n# ///\nimport ignored\n',
            "two.py": b'# /// script\n# dependencies = ["rich<14", "httpx"]\n# ///\n',
        }
    )
    assert dependencies == ["httpx", "rich<14", "rich==13.9.4"]
    assert constraints == [">=3.12"]


def test_import_fallback_excludes_stdlib_neighbors_and_relative_imports(monkeypatch):
    monkeypatch.setattr(
        skill_python.importlib.metadata,
        "packages_distributions",
        lambda: {"custom_import": ["custom-distribution"]},
    )
    dependencies, _ = skill_python.script_requirements(
        {
            "scripts/main.py": b"import os, json, pathlib, helper, PIL, yaml, custom_import\n"
            b"from . import relative\nfrom package.module import value\nimport unfamiliar\n",
            "scripts/helper.py": b"print('local')\n",
            "package/module.py": b"pass\n",
        }
    )
    assert dependencies == ["Pillow", "PyYAML", "custom-distribution", "unfamiliar"]


@pytest.mark.parametrize(
    "source",
    [
        '# /// script\n# dependencies = "rich"\n# ///\n',
        '# /// script\n# dependencies = ["--system"]\n# ///\n',
        "# /// script\n# dependencies = []\n# ///\n" * 2,
        "# /// script\n# dependencies = [\n# ///\n",
    ],
)
def test_invalid_declarations_do_not_fall_back(source):
    with pytest.raises(ValueError):
        skill_python.script_requirements({"bad.py": source.encode()})


@pytest.mark.asyncio
async def test_shared_environment_executes_reuses_and_recovers(tmp_path, monkeypatch):
    monkeypatch.setenv("COGNIS_DATA_DIR", str(tmp_path))
    request = bundle(
        {
            "scripts/one.py": "import sys\nprint(sys.prefix)\n",
            "scripts/two.py": "print('two')\n",
        }
    )
    first, second = await asyncio.gather(
        prepare_skill_assets(request), prepare_skill_assets(request)
    )
    assert first == second
    environment = first["python_environment"]
    assert environment["ready"], environment
    python = Path(environment["python_path"])
    modified = python.lstat().st_mtime_ns
    assert subprocess.run(
        [str(python), first["asset_manifest"][0]["local_path"]],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip() == str(python.parent.parent)
    assert (await prepare_skill_assets(request))["python_environment"] == environment
    assert python.lstat().st_mtime_ns == modified
    python.unlink()
    repaired = await prepare_skill_assets(request)
    assert repaired["python_environment"]["ready"]
    assert python.exists()
    request["version_id"] = "version-two"
    updated = await prepare_skill_assets(request)
    assert updated["python_environment"]["python_path"] == str(python)
    assert updated["asset_manifest"][0]["local_path"] != first["asset_manifest"][0]["local_path"]


@pytest.mark.asyncio
async def test_install_failure_keeps_assets_and_retries(tmp_path, monkeypatch):
    monkeypatch.setenv("COGNIS_DATA_DIR", str(tmp_path))
    request = bundle({"one.py": '# /// script\n# dependencies = ["rich==13.9.4"]\n# ///\n'})
    original = skill_python._run
    calls = []
    fail = True

    async def run(argv, directory_fd=None):
        calls.append(argv)
        if "install" in argv:
            if fail:
                raise RuntimeError("missing compiler")
            return ""
        if "check" in argv:
            return ""
        return await original(argv, directory_fd)

    monkeypatch.setattr(skill_python, "_run", run)
    failed = await prepare_skill_assets(request)
    assert not failed["python_environment"]["ready"]
    assert "missing compiler" in failed["python_environment"]["error"]
    assert Path(failed["asset_manifest"][0]["local_path"]).exists()
    fail = False
    assert (await prepare_skill_assets(request))["python_environment"]["ready"]
    assert len([argv for argv in calls if "install" in argv]) == 2


@pytest.mark.asyncio
async def test_incompatible_python_is_reported_without_running_setup(tmp_path, monkeypatch):
    monkeypatch.setenv("COGNIS_DATA_DIR", str(tmp_path))
    run = AsyncMock()
    monkeypatch.setattr(skill_python, "_run", run)
    result = await prepare_skill_assets(
        bundle({"one.py": '# /// script\n# requires-python = "<3"\n# ///\n'})
    )
    assert not result["python_environment"]["ready"]
    assert "requires-python" in result["python_environment"]["error"]
    run.assert_not_awaited()


@pytest.mark.asyncio
async def test_cancellation_releases_lock_and_reaps_setup(tmp_path, monkeypatch):
    root = tmp_path / "skill"
    root.mkdir()
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    entered = asyncio.Event()

    async def block(argv, directory_fd=None):
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(skill_python, "_run", block)
    task = asyncio.create_task(
        skill_python.prepare_python_environment(root, {"one.py": b""}, descriptor)
    )
    try:
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        monkeypatch.setattr(skill_python, "_run", AsyncMock(side_effect=RuntimeError("retry")))
        result = await asyncio.wait_for(
            skill_python.prepare_python_environment(root, {"one.py": b""}, descriptor), 3
        )
        assert "retry" in result["error"]
    finally:
        os.close(descriptor)


@pytest.mark.asyncio
async def test_real_locked_dependency_install_and_conflict(tmp_path, monkeypatch):
    """Use a local wheel so installation acceptance does not depend on the network."""
    monkeypatch.setenv("COGNIS_DATA_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("UV_OFFLINE", "true")
    wheel = tmp_path / "skill_test_dependency-1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("skill_test_dependency.py", "VALUE = 'installed'\n")
        archive.writestr(
            "skill_test_dependency-1.0.dist-info/METADATA",
            "Metadata-Version: 2.1\nName: skill-test-dependency\nVersion: 1.0\n",
        )
        archive.writestr(
            "skill_test_dependency-1.0.dist-info/WHEEL",
            "Wheel-Version: 1.0\nGenerator: cognis-test\nRoot-Is-Purelib: true\n"
            "Tag: py3-none-any\n",
        )
        archive.writestr("skill_test_dependency-1.0.dist-info/RECORD", "")
    source = (
        "# /// script\n"
        f'# dependencies = ["skill-test-dependency @ {wheel.as_uri()}"]\n'
        "# ///\nfrom skill_test_dependency import VALUE\nprint(VALUE)\n"
    )
    request = bundle({"one.py": source, "two.py": source})
    result = await prepare_skill_assets(request)
    environment = result["python_environment"]
    assert environment["ready"], environment
    for asset in result["asset_manifest"]:
        assert (
            subprocess.run(
                [environment["python_path"], asset["local_path"]],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            == "installed"
        )
    conflict = bundle(
        {
            "one.py": source,
            "two.py": '# /// script\n# dependencies = ["skill-test-dependency==2"]\n# ///\n',
        }
    )
    failed = await prepare_skill_assets(conflict)
    assert not failed["python_environment"]["ready"]
    assert "error" in failed["python_environment"]
    assert (await prepare_skill_assets(request))["python_environment"]["ready"]


@pytest.mark.asyncio
async def test_environment_symlink_cannot_modify_external_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("COGNIS_DATA_DIR", str(tmp_path / "cache"))
    result = await prepare_skill_assets(bundle({"one.py": ""}))
    python = Path(result["python_environment"]["python_path"])
    env = python.parent.parent
    env.rename(env.with_name("saved-environment"))
    external = tmp_path / "external"
    external.mkdir()
    protected = external / "protected"
    protected.write_text("preserve")
    env.symlink_to(external, target_is_directory=True)
    failed = await prepare_skill_assets(bundle({"one.py": ""}))
    assert not failed["python_environment"]["ready"]
    assert "symlink" in failed["python_environment"]["error"]
    assert protected.read_text() == "preserve"


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy", [False, True])
async def test_python_recipe_uses_the_same_shared_interpreter(tmp_path, monkeypatch, legacy):
    monkeypatch.setenv("COGNIS_DATA_DIR", str(tmp_path))
    source = (
        "#!/usr/bin/env python3\nprint('legacy')\n" if legacy else "import sys\nprint(sys.prefix)\n"
    )
    request = bundle({"script.py": source})
    prepared = await prepare_skill_assets(request)
    asset = request["assets"][0]
    content = base64.b64decode(asset["content_b64"])

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url):
            return httpx.Response(200, content=content, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "AsyncClient", Client)
    runner = ExecutorRunner(ExecutorConfig(executor_id="test", controller_token="test"))
    if legacy:
        request.pop("owner_email")
    handler = runner._build_skill_recipe_handler(
        {"mode": "script", "entry": "script.py"},
        [{**asset, "url": "https://assets.test/script.py"}],
        {},
        request,
    )
    result = await handler({}, None)
    expected = (
        "legacy"
        if legacy
        else str(Path(prepared["python_environment"]["python_path"]).parent.parent)
    )
    assert result.strip() == expected


@pytest.mark.asyncio
async def test_parent_swap_cannot_repair_an_external_environment(tmp_path, monkeypatch):
    root = tmp_path / "skill"
    root.mkdir()
    (root / "python-env").mkdir()
    moved = tmp_path / "pinned-skill"
    external = tmp_path / "external"
    (external / "python-env").mkdir(parents=True)
    marker = external / "python-env" / "protected"
    marker.write_text("preserve")
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY)

    def swap(_scripts):
        root.rename(moved)
        root.symlink_to(external, target_is_directory=True)
        return [], []

    monkeypatch.setattr(skill_python, "script_requirements", swap)
    try:
        result = await skill_python.prepare_python_environment(root, {"one.py": b""}, descriptor)
        assert not result["ready"]
        assert "directory changed" in result["error"]
        assert marker.read_text() == "preserve"
        assert sorted(path.name for path in external.iterdir()) == ["python-env"]
        assert (moved / "python-env" / "bin" / "python").exists()
    finally:
        os.close(descriptor)


@pytest.mark.asyncio
async def test_crlf_metadata_retains_pins_and_python_constraint(tmp_path, monkeypatch):
    source = (
        '# /// script\r\n# dependencies = ["rich==13.9.4"]\r\n'
        '# requires-python = "<3"\r\n# ///\r\nimport ignored\r\n'
    )
    assert skill_python.script_requirements({"one.py": source.encode()}) == (
        ["rich==13.9.4"],
        ["<3"],
    )
    monkeypatch.setenv("COGNIS_DATA_DIR", str(tmp_path))
    result = await prepare_skill_assets(bundle({"one.py": source}))
    assert not result["python_environment"]["ready"]
    assert "requires-python" in result["python_environment"]["error"]


@pytest.mark.asyncio
async def test_real_subprocess_cancellation_terminates_process_group(tmp_path):
    marker = tmp_path / "pids.txt"
    source = (
        "import os,subprocess,sys,time; "
        "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); "
        f"open({str(marker)!r},'w').write(str(os.getpid())+' '+str(child.pid)); "
        "time.sleep(60)"
    )
    task = asyncio.create_task(skill_python._run([sys.executable, "-I", "-c", source]))
    try:
        async with asyncio.timeout(10):
            while not marker.exists():
                await asyncio.sleep(0.05)
        pids = [int(value) for value in marker.read_text().split()]
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    for pid in pids:
        try:
            process = psutil.Process(pid)
            assert not process.is_running() or process.status() == psutil.STATUS_ZOMBIE
        except psutil.NoSuchProcess:
            pass


@pytest.mark.asyncio
async def test_older_executor_reports_missing_environment_without_blocking(tmp_path, monkeypatch):
    from cognis.executor.skill_assets import _prepare_skill_assets

    monkeypatch.setenv("COGNIS_DATA_DIR", str(tmp_path))
    request = bundle({"one.py": "print('portable')\n"})
    asset = request["assets"][0]
    ref = SkillAssetRef(
        **{
            key: asset[key]
            for key in ("filename", "asset_id", "content_hash", "size_bytes", "content_type")
        },
        artifact_object_id="portable-bundle",
    )
    result = await prepare_loaded_skill_assets(
        skill_id=request["skill_id"],
        version_id=request["version_id"],
        asset_refs=[ref],
        owner_email=request["owner_email"],
        executor=SimpleNamespace(
            executor_id="older-executor",
            rpc_call=AsyncMock(return_value=_prepare_skill_assets(request)),
        ),
        artifact_store=SimpleNamespace(
            async_load=AsyncMock(
                return_value=(base64.b64decode(asset["content_b64"]), "text/x-python")
            )
        ),
    )
    assert result.assets
    assert result.python_environment is None
    assert "executor did not report environment preparation" in result.warning
