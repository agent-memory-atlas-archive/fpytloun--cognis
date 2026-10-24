"""Render Towncrier fragments into one shared release index and Markdown exports."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import TypedDict

ROOT = Path(__file__).resolve().parents[1]
INDEX = Path("ui/src/lib/generated/changelog.json")
HEADER = re.compile(r"^## \[(\d+\.\d+\.\d+)\] - (Unreleased|\d{4}-\d{2}-\d{2})$", re.MULTILINE)
VERSION = re.compile(r"^\d+\.\d+\.\d+$")


class Release(TypedDict):
    """Portable release record consumed by the UI and release exporters."""

    version: str
    date: str
    markdown: str


def version_key(version: str) -> tuple[int, ...]:
    """Compare the stable three-component release versions used by Cognis."""
    if not VERSION.fullmatch(version):
        raise ValueError(f"Expected a stable version such as 0.18.0, got {version!r}")
    return tuple(map(int, version.split(".")))


def parse_releases(markdown: str) -> list[Release]:
    """Read release sections without reinterpreting their Markdown bodies."""
    headers = list(HEADER.finditer(markdown))
    releases: list[Release] = []
    for index, header in enumerate(headers):
        end = headers[index + 1].start() if index + 1 < len(headers) else len(markdown)
        releases.append(
            {
                "version": header[1],
                "date": header[2],
                "markdown": markdown[header.end() : end].strip(),
            }
        )
    if not releases:
        raise ValueError("No release sections found")
    versions = [version_key(release["version"]) for release in releases]
    if versions != sorted(set(versions), reverse=True):
        raise ValueError("Release versions must be unique and newest first")
    return releases


def validate_fragments(root: Path, config: dict) -> list[Path]:
    """Fail on misspelled categories, empty notes, and nested release headings."""
    settings = config["tool"]["towncrier"]
    ignored = set(settings["ignore"])
    categories = {item["directory"] for item in settings["type"]}
    fragments: list[Path] = []
    for path in sorted((root / settings["directory"]).iterdir()):
        if path.name in ignored:
            continue
        if not path.is_file() or not re.fullmatch(
            r"[a-z0-9][a-z0-9-]*\.(" + "|".join(sorted(categories)) + r")\.md", path.name
        ):
            raise ValueError(f"Invalid changelog fragment: {path.name}")
        text = path.read_text(encoding="utf-8").strip()
        if not text or re.search(r"^(?:#|[-*] )", text, re.MULTILINE):
            raise ValueError(f"Write prose without headings or bullet prefixes: {path.name}")
        fragments.append(path)
    return fragments


def build_index(root: Path) -> dict:
    """Use Towncrier for previews and the finalized changelog for history."""
    config = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    releases = parse_releases((root / "CHANGELOG.md").read_text(encoding="utf-8"))
    fragments = validate_fragments(root, config)
    if fragments:
        upcoming = config["tool"]["cognis"]["changelog"]["next_version"]
        if version_key(upcoming) <= version_key(releases[0]["version"]):
            raise ValueError("next_version must be newer than the latest finalized release")
        draft = subprocess.run(
            [
                sys.executable,
                "-m",
                "towncrier",
                "build",
                "--draft",
                "--version",
                upcoming,
                "--date",
                "Unreleased",
            ],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
        releases = parse_releases(draft.stdout) + releases
    return {"schema_version": 1, "releases": releases}


def export_notes(releases: list[Release], version: str, since: str | None = None) -> str:
    """Export an exact release or an exclusive-lower/inclusive-upper range."""
    upper = version_key(version)
    if not any(item["version"] == version for item in releases):
        raise ValueError(f"Unknown release: {version}")
    lower = version_key(since) if since else None
    if lower is not None and lower >= upper:
        raise ValueError("--since must be older than --version")
    selected = [
        item
        for item in releases
        if (lower < version_key(item["version"]) <= upper if lower else item["version"] == version)
    ]
    return (
        "\n\n".join(
            f"## [{item['version']}] - {item['date']}\n\n{item['markdown']}" for item in selected
        )
        + "\n"
    )


def main() -> int:
    """Generate, verify, or export the canonical release material."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail if the committed index is stale")
    parser.add_argument("--version", help="Export Markdown for this release instead of writing")
    parser.add_argument("--since", help="Include all changes after this version through --version")
    args = parser.parse_args()
    if args.since and not args.version:
        parser.error("--since requires --version")
    try:
        index = build_index(ROOT)
        if args.version:
            sys.stdout.write(export_notes(index["releases"], args.version, args.since))
            return 0
        content = json.dumps(index, ensure_ascii=False, indent=2) + "\n"
        target = ROOT / INDEX
        if args.check:
            if not target.exists() or target.read_text(encoding="utf-8") != content:
                raise ValueError("Release index is stale; run uv run python scripts/changelog.py")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
    except (ValueError, subprocess.CalledProcessError) as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
