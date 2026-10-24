"""Best-effort Python runtime preparation for verified skill bundles."""

from __future__ import annotations

import ast
import asyncio
import contextlib
import fcntl
import importlib.metadata
import json
import os
import re
import shutil
import signal
import stat
import sys
import tomllib
import uuid
from pathlib import Path
from typing import Any

from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet

_INLINE = re.compile(r"(?m)^# /// script$\s(?P<content>(^#(| .*)$\s)+)^# ///$")
_IMPORT_NAMES = {
    "PIL": "Pillow",
    "yaml": "PyYAML",
    "bs4": "beautifulsoup4",
    "cv2": "opencv-python",
    "sklearn": "scikit-learn",
    "dotenv": "python-dotenv",
}


def script_requirements(scripts: dict[str, bytes]) -> tuple[list[str], list[str]]:
    """Read PEP 723 or infer third-party top-level imports without executing code."""
    dependencies: set[str] = set()
    python_constraints: set[str] = set()
    local_names = {Path(name).stem for name in scripts}
    local_names.update(part for name in scripts for part in Path(name).parts[:-1])
    installed_names = importlib.metadata.packages_distributions()
    for name, content in scripts.items():
        source = content.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
        blocks = list(_INLINE.finditer(source))
        if len(blocks) > 1:
            raise ValueError(f"{name}: multiple PEP 723 script blocks")
        if blocks:
            metadata = tomllib.loads(
                "\n".join(
                    line[2:] if line.startswith("# ") else ""
                    for line in blocks[0]["content"].splitlines()
                )
            )
            requirements = metadata.get("dependencies", [])
            if not isinstance(requirements, list) or any(
                not isinstance(item, str) for item in requirements
            ):
                raise ValueError(f"{name}: dependencies must be a list of strings")
            dependencies.update(str(Requirement(item)) for item in requirements)
            constraint = metadata.get("requires-python")
            if constraint is not None:
                python_constraints.add(str(SpecifierSet(constraint)))
            continue
        tree = ast.parse(source, filename=name)
        imports: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
                imports.add(node.module.split(".")[0])
        for module in imports - sys.stdlib_module_names - local_names - {"__future__"}:
            distributions = installed_names.get(module, [])
            distribution = _IMPORT_NAMES.get(module) or (
                distributions[0] if len(distributions) == 1 else module
            )
            dependencies.add(str(Requirement(distribution)))
    return sorted(dependencies), sorted(python_constraints)


async def _run(argv: list[str], directory_fd: int | None = None) -> str:
    """Run infrastructure commands without shell expansion; reap on cancellation."""
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT"}
    }
    env["UV_PYTHON_DOWNLOADS"] = "never"
    pass_fds: tuple[int, ...] = ()
    if directory_fd is not None:
        # fchdir before exec pins subprocess resolution without preexec_fn or /proc assumptions.
        argv = [
            sys.executable,
            "-I",
            "-c",
            "import os,sys; os.fchdir(int(sys.argv[1])); os.execvp(sys.argv[2], sys.argv[2:])",
            str(directory_fd),
            *argv,
        ]
        pass_fds = (directory_fd,)
    process = await asyncio.create_subprocess_exec(
        *argv,
        env=env,
        cwd="/",
        start_new_session=True,
        pass_fds=pass_fds,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await process.communicate()
    except BaseException:
        if process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            await process.wait()
        raise
    if process.returncode:
        raise RuntimeError(
            f"{Path(argv[0]).name} exited {process.returncode}: "
            + stderr.decode(errors="replace")[-4000:]
        )
    return stdout.decode(errors="replace")


async def _create_environment(directory_fd: int) -> None:
    """Replace only the Cognis-owned environment, never follow a directory symlink."""
    try:
        info = os.stat("python-env", dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        info = None
    if info is not None:
        if stat.S_ISLNK(info.st_mode):
            raise ValueError("Skill Python environment must not be a symlink")
        retired = f".broken-python-env-{uuid.uuid4().hex}"
        os.rename("python-env", retired, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
        if stat.S_ISDIR(info.st_mode):
            cleanup = asyncio.create_task(
                asyncio.to_thread(shutil.rmtree, retired, dir_fd=directory_fd)
            )
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                await cleanup
                raise
        else:
            os.unlink(retired, dir_fd=directory_fd)
    uv = shutil.which("uv")
    if uv:
        await _run(
            [uv, "--no-config", "venv", "--python", sys.executable, "python-env"], directory_fd
        )
    else:
        await _run([sys.executable, "-I", "-m", "venv", "python-env"], directory_fd)


async def _install(dependencies: list[str], directory_fd: int) -> None:
    python = "python-env/bin/python"
    uv = shutil.which("uv")
    if uv:
        await _run(
            [uv, "--no-config", "pip", "install", "--python", python, *dependencies], directory_fd
        )
    else:
        await _run([python, "-I", "-m", "ensurepip"], directory_fd)
        await _run(
            [
                str(python),
                "-I",
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                *dependencies,
            ],
            directory_fd,
        )


async def _check(directory_fd: int) -> None:
    python = "python-env/bin/python"
    uv = shutil.which("uv")
    if uv:
        await _run([uv, "--no-config", "pip", "check", "--python", python], directory_fd)
    else:
        await _run([python, "-I", "-m", "pip", "check"], directory_fd)


async def prepare_python_environment(
    skill_root: Path, scripts: dict[str, bytes], directory_fd: int
) -> dict[str, Any]:
    """Reconcile one owner/skill environment, retaining useful diagnostics on failure."""
    python = skill_root / "python-env" / "bin" / "python"
    result: dict[str, Any] = {"ready": False, "python_path": str(python)}
    descriptor = os.open(
        ".python-env.lock",
        os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW,
        mode=0o600,
        dir_fd=directory_fd,
    )
    try:
        async with asyncio.timeout(90):
            # flock also serializes different executor processes using the same cache.
            while True:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    await asyncio.sleep(0.1)
            dependencies, constraints = await asyncio.to_thread(script_requirements, scripts)
            result["dependencies"] = dependencies
            version = ".".join(map(str, sys.version_info[:3]))
            if any(version not in SpecifierSet(item) for item in constraints):
                raise ValueError(
                    f"Executor Python {version} does not satisfy requires-python {constraints}"
                )
            env_path = python.parent.parent
            try:
                info = os.stat("python-env", dir_fd=directory_fd, follow_symlinks=False)
            except FileNotFoundError:
                info = None
            if info is not None and stat.S_ISLNK(info.st_mode):
                raise ValueError("Skill Python environment must not be a symlink")
            healthy = False
            try:
                details = json.loads(
                    await _run(
                        [
                            "./python-env/bin/python",
                            "-I",
                            "-c",
                            "import json,sys; print(json.dumps([sys.prefix, list(sys.version_info[:3])]))",
                        ],
                        directory_fd,
                    )
                )
                healthy = Path(details[0]) == env_path and details[1] == list(sys.version_info[:3])
            except (OSError, RuntimeError, ValueError, IndexError, TypeError):
                pass
            if not healthy:
                await _create_environment(directory_fd)
            if dependencies:
                await _install(dependencies, directory_fd)
                try:
                    await _check(directory_fd)
                except RuntimeError:
                    # Stale or corrupted package metadata gets one clean repair attempt.
                    await _create_environment(directory_fd)
                    await _install(dependencies, directory_fd)
                    await _check(directory_fd)
            actual = os.stat(skill_root, follow_symlinks=False)
            pinned = os.fstat(directory_fd)
            if (actual.st_dev, actual.st_ino) != (pinned.st_dev, pinned.st_ino):
                raise ValueError("Skill cache directory changed during environment preparation")
            result["ready"] = True
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"[:4500]
    finally:
        os.close(descriptor)
    return result
