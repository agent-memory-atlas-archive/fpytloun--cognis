from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
EXPECTED_IMAGES = {
    "mnemory": "ghcr.io/fpytloun/mnemory:latest",
    "intaris": "ghcr.io/fpytloun/intaris:latest",
}
RELEVANT_DOCS = (
    ROOT / "README.md",
    ROOT / "docs" / "guide",
    ROOT / "docs" / "specs",
)


def _markdown_files() -> list[Path]:
    files = [RELEVANT_DOCS[0]]
    for location in RELEVANT_DOCS[1:]:
        files.extend(location.rglob("*.md"))
    return files


def test_compose_and_example_use_published_companion_images() -> None:
    compose = yaml.safe_load((ROOT / "compose.local.yml").read_text(encoding="utf-8"))
    for service, image in EXPECTED_IMAGES.items():
        assert compose["services"][service]["image"] == f"${{{service.upper()}_IMAGE:-{image}}}"

    env = (ROOT / ".env.local.example").read_text(encoding="utf-8")
    for service, image in EXPECTED_IMAGES.items():
        assert f"{service.upper()}_IMAGE={image}" in env


def test_local_compose_docs_use_only_the_public_ghcr_image_references() -> None:
    documents = "\n".join(path.read_text(encoding="utf-8") for path in _markdown_files())
    for service, image in EXPECTED_IMAGES.items():
        assert image in documents
        assert f"ghcr.io/fpytloun/{service}:<tag>" in documents
        assert f"genunix/{service}" not in documents
        assert f"docker.io/{service}" not in documents

    for image_name in ("cognis", "cognis-executor"):
        assert f"genunix/{image_name}" not in documents
        assert f"docker.io/{image_name}" not in documents

    assert "ghcr.io/fpytloun/mnemory" in documents
    assert "ghcr.io/fpytloun/intaris" in documents
    assert "ghcr.io/fpytloun/cognis" in documents
    assert "ghcr.io/fpytloun/cognis-executor" in documents
