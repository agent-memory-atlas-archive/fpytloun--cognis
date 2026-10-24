"""Bounded human artifact editing and durable file creation."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from cognis.artifacts.preview import classify_artifact_preview
from cognis.artifacts.store import sanitize_artifact_filename
from cognis.core.artifact_revisions import (
    ContentActor,
    authorize_artifact_revision_target,
    write_artifact_document,
)
from cognis.core.document_sharing import owned_document
from cognis.store.models import ArtifactRecordRow

EDIT_MAX_BYTES = 1024 * 1024
UPLOAD_MAX_BYTES = 20 * 1024 * 1024


class TextArtifactRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=240)
    content: str = Field(max_length=EDIT_MAX_BYTES)
    mime_type: str = Field(
        default="text/plain", min_length=1, max_length=150, pattern=r"^[\w.+-]+/[\w.+-]+$"
    )
    project_id: str | None = None
    agent_ids: list[str] | None = Field(default=None, max_length=100)


class EditableArtifact(BaseModel):
    artifact_id: str
    filename: str
    mime_type: str
    content: str


def is_editable(filename: str, mime_type: str, size: int) -> bool:
    """Keep editing limited to full UTF-8 source, never a truncated preview."""
    return size <= EDIT_MAX_BYTES and classify_artifact_preview(filename, mime_type) in {
        "text",
        "markdown",
        "html",
        "csv",
        "mermaid",
    }


async def editable_content(
    session_factory: Any, artifact_store: Any, owner: str, ref: str
) -> EditableArtifact:
    """Load complete source only after owner and write authorization."""
    async with session_factory() as session:
        row = await owned_document(session, "artifact", ref, owner)
        assert isinstance(row, ArtifactRecordRow)
        await authorize_artifact_revision_target(
            session, ContentActor(owner, None, None, None, human=True), ref
        )
        if not is_editable(row.filename, row.mime_type, row.size_bytes):
            raise ValueError("This format or file size cannot be edited in the browser.")
    content, _mime = await artifact_store.async_load(row.namespace, row.object_id, row.filename)
    if len(content) > EDIT_MAX_BYTES or b"\x00" in content:
        raise ValueError("This file cannot be edited as text.")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("Only UTF-8 text files can be edited.") from exc
    return EditableArtifact(
        artifact_id=ref, filename=row.filename, mime_type=row.mime_type, content=text
    )


async def save_human_artifact(
    session_factory: Any,
    artifact_store: Any,
    owner: str,
    *,
    filename: str,
    mime_type: str,
    content: bytes,
    supersedes: str | None = None,
    project_id: str | None = None,
    agent_ids: list[str] | None = None,
) -> str:
    """Use the canonical two-transaction revision writer, with human provenance."""
    filename = sanitize_artifact_filename(filename)
    if len(content) > UPLOAD_MAX_BYTES:
        raise ValueError("Files must be 20 MB or smaller.")
    if supersedes:
        async with session_factory() as session:
            target = await owned_document(session, "artifact", supersedes, owner)
            assert isinstance(target, ArtifactRecordRow)
            if not is_editable(target.filename, target.mime_type, target.size_bytes):
                raise ValueError("This file cannot be edited in the browser.")
            if mime_type != target.mime_type or not is_editable(filename, mime_type, len(content)):
                raise ValueError("Editing must preserve the file format and remain within 1 MB.")
        try:
            content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("Only UTF-8 text files can be edited.") from exc
    row, _view = await write_artifact_document(
        session_factory=session_factory,
        artifact_store=artifact_store,
        actor=ContentActor(owner, None, None, None, human=True),
        content=content,
        filename=filename,
        mime_type=mime_type,
        kind="image" if mime_type.startswith("image/") else "file",
        purpose="user_artifact",
        supersedes=supersedes,
        project_id=project_id,
        agent_ids=agent_ids,
    )
    return str(row.artifact_id)
