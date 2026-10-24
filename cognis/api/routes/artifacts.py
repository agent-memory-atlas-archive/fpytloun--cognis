"""Generic artifact upload and signed serving routes."""

from __future__ import annotations

import hashlib
import mimetypes
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Annotated, Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, File, Form, Query, Request, UploadFile
from fastapi.responses import RedirectResponse, Response, StreamingResponse
from pydantic import BaseModel

from cognis.api.common import api_exception, forbid_mutation_for_viewer, require_current_user
from cognis.api.models import ArtifactRevisionsResponse, ArtifactRevisionSummary
from cognis.artifacts import preview as artifact_preview
from cognis.artifacts.store import sanitize_artifact_filename
from cognis.core.content_refs import (
    build_deliverable_public_url,
    get_accessible_deliverable_ref,
    get_deliverable_ref_unscoped,
    is_deliverable_ref,
)
from cognis.core.deliverable_links import (
    DeliverableShareUnavailable,
    signed_deliverable_view_link,
)
from cognis.core.project_access import can_project_read_artifact
from cognis.models.artifact import ArtifactKind
from cognis.rendering.deliverables import DeliverableRenderError, render_standalone_shell
from cognis.store.queries import (
    create_artifact_record,
    get_artifact_lineage_summary,
    get_artifact_record,
    get_skill_asset_by_artifact_object,
    list_artifact_lineage,
)

router = APIRouter(prefix="/api/v1/artifacts", tags=["artifacts"])

ArtifactURLMode = Literal["download", "view"]


class ArtifactShareRequest(BaseModel):
    agent_id: str
    action: Literal["grant", "revoke"]


@router.post("/{artifact_id}/share")
async def share_artifact(
    artifact_id: str, body: ArtifactShareRequest, request: Request
) -> dict[str, str]:
    """The human owner may also share legacy publications with unknown agent provenance."""
    from cognis.api.common import require_session_user

    user = require_session_user(request)
    forbid_mutation_for_viewer(request)
    from cognis.core.artifact_sharing import set_artifact_share

    async with request.app.state.session_factory() as session:
        try:
            await set_artifact_share(
                session,
                owner_email=user.email,
                owner_agent_id=None,
                content_ref=artifact_id,
                grantee_agent_id=body.agent_id,
                revoke=body.action == "revoke",
            )
        except ValueError:
            raise api_exception(404, "not_found", "Artifact or recipient not found") from None
        await session.commit()
    return {"status": "updated"}


TEXT_PREVIEW_MAX_BYTES = artifact_preview.TEXT_PREVIEW_MAX_BYTES
ARTIFACT_VIEWER_CSP = (
    "sandbox allow-scripts allow-same-origin allow-downloads; default-src 'none'; "
    "script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; "
    "img-src 'self' data:; font-src 'self' data:; media-src 'self' data:"
)


def _kind_for_content_type(content_type: str) -> ArtifactKind:
    if content_type.startswith("image/"):
        return ArtifactKind.IMAGE
    if content_type.startswith("audio/"):
        return ArtifactKind.AUDIO
    if content_type.startswith("video/"):
        return ArtifactKind.VIDEO
    if content_type == "application/pdf":
        return ArtifactKind.PDF
    return ArtifactKind.FILE


def _is_expired(row: object, *, now: datetime | None = None) -> bool:
    expires_at = getattr(row, "expires_at", None)
    if not isinstance(expires_at, datetime):
        return False
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return expires_at <= (now or datetime.now(UTC))


def _clamp_ttl_to_artifact_expiry(row: object, requested_ttl_seconds: int) -> int:
    expires_at = getattr(row, "expires_at", None)
    if expires_at is None:
        return requested_ttl_seconds
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    remaining_seconds = int((expires_at - datetime.now(UTC)).total_seconds())
    return max(60, min(requested_ttl_seconds, remaining_seconds))


def _text_preview_payload(*, filename: str, content_type: str, content: bytes) -> dict[str, object]:
    return artifact_preview.artifact_preview_payload(
        filename=filename, content_type=content_type, content=content
    )


def _assert_view_allowed(filename: str, content_type: str) -> None:
    if not artifact_preview.supports_artifact_view(filename, content_type):
        raise api_exception(415, "unsupported_media_type", "Artifact cannot be previewed")


def _artifact_viewer_response(
    *,
    artifact_id: str,
    filename: str,
    content_type: str,
    content: bytes,
    standalone_url: str,
) -> Response:
    kind = artifact_preview.classify_artifact_preview(filename, content_type)
    if kind not in {"csv", "markdown", "mermaid", "text"}:
        effective_content_type = (
            "text/html" if kind == "html" else "application/pdf" if kind == "pdf" else content_type
        )
        headers = _artifact_response_headers(
            filename=filename,
            content_type=effective_content_type,
            content_length=len(content),
            mode="view",
        )
        return Response(content=content, media_type=effective_content_type, headers=headers)
    payload = artifact_preview.artifact_preview_payload(
        filename=filename,
        content_type=content_type,
        content=content,
    )
    row = SimpleNamespace(
        content=str(payload.get("content") or ""),
        deliverable_id=artifact_id,
        format="rich",
        rich_payload=artifact_preview.artifact_preview_rich_payload(payload),
        title=filename,
    )
    try:
        document = render_standalone_shell(
            row,
            media_base="",
            standalone_url=standalone_url,
            pdf_url="",
        ).encode()
    except DeliverableRenderError as exc:
        raise api_exception(
            503, "preview_unavailable", "Artifact preview assets are unavailable"
        ) from exc
    return Response(
        content=document,
        media_type="text/html; charset=utf-8",
        headers={
            "Cache-Control": "private, max-age=60",
            "Content-Length": str(len(document)),
            "Content-Disposition": f"inline; filename*=UTF-8''{quote(filename, safe='')}",
            "Content-Security-Policy": ARTIFACT_VIEWER_CSP,
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
        },
    )


def _artifact_response_headers(
    *,
    filename: str,
    content_type: str,
    content_length: int,
    mode: ArtifactURLMode,
) -> dict[str, str]:
    headers = {
        "Cache-Control": "private, max-age=60",
        "Content-Length": str(content_length),
        "X-Content-Type-Options": "nosniff",
    }
    if mode == "view":
        _assert_view_allowed(filename, content_type)
        headers["Content-Disposition"] = f"inline; filename*=UTF-8''{quote(filename, safe='')}"
        headers["Referrer-Policy"] = "no-referrer"
        if artifact_preview.classify_artifact_preview(filename, content_type) == "html":
            headers["Content-Security-Policy"] = (
                "sandbox allow-scripts; "
                "default-src 'none'; "
                "connect-src 'none'; "
                "img-src data: blob:; "
                "style-src 'unsafe-inline'; "
                "script-src 'unsafe-inline'; "
                "font-src data:; "
                "media-src data: blob:;"
            )
        return headers
    if not content_type.startswith("image/"):
        headers["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(filename, safe='')}"
    return headers


@router.post("/upload")
async def upload_artifact(
    request: Request,
    file: Annotated[UploadFile, File(...)],
    purpose: Annotated[str, Form()] = "chat_input",
) -> dict[str, object]:
    forbid_mutation_for_viewer(request)
    user = require_current_user(request)
    artifact_store = request.app.state.artifact_store

    content = await file.read()
    content_hash = hashlib.sha256(content).hexdigest()
    max_size = artifact_store._config.max_size_bytes  # noqa: SLF001
    if len(content) > max_size:
        raise api_exception(400, "validation_error", "Artifact too large")

    artifact_id = artifact_store.generate_id("att")
    filename = sanitize_artifact_filename(file.filename, default="attachment")
    content_type = (
        file.content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
    )
    kind = _kind_for_content_type(content_type)

    await artifact_store.async_save(
        "attachments",
        artifact_id,
        filename,
        content,
        content_type,
        owner_email=user.email,
    )

    async with request.app.state.session_factory() as session:
        await create_artifact_record(
            session,
            artifact_id=artifact_id,
            namespace="attachments",
            object_id=artifact_id,
            filename=filename,
            owner_email=user.email,
            purpose=purpose,
            kind=kind.value,
            mime_type=content_type,
            size_bytes=len(content),
            status="temporary",
            expires_at=datetime.now(UTC) + timedelta(hours=24),
            content_hash=content_hash,
        )
        await session.commit()

    signed_url = await artifact_store.async_get_public_url("attachments", artifact_id, filename)
    return {
        "artifact_id": artifact_id,
        "kind": kind.value,
        "mime_type": content_type,
        "filename": filename,
        "size_bytes": len(content),
        "url": signed_url,
    }


async def _project_reader_may_read(request: Request, row: Any, user_email: str) -> bool:
    async with request.app.state.session_factory() as session:
        return await can_project_read_artifact(session, row, user_email)


@router.get("/{artifact_id}/revisions", response_model=ArtifactRevisionsResponse)
async def artifact_revisions(request: Request, artifact_id: str) -> ArtifactRevisionsResponse:
    """List live revisions of an artifact document that the current user may read.

    Only metadata is returned; each revision is opened by its own exact ID.
    """

    user = require_current_user(request)
    async with request.app.state.session_factory() as session:
        row = await get_artifact_record(session, artifact_id)
        if (
            row is None
            or row.status == "deleted"
            or _is_expired(row)
            or not await _person_may_read_artifact(session, row, user.email)
        ):
            raise api_exception(404, "not_found", "Artifact not found")
        summary = await get_artifact_lineage_summary(session, row)
        revisions = [
            ArtifactRevisionSummary(
                artifact_id=item.artifact_id,
                revision=int(item.revision or 1),
                filename=item.filename,
                mime_type=item.mime_type,
                size_bytes=int(item.size_bytes or 0),
                owner_email=item.owner_email,
                project_id=item.project_id,
                created_at=item.created_at,
                is_latest=item.artifact_id == summary.latest_artifact_id,
            )
            for item in await list_artifact_lineage(session, summary.lineage_id)
            if await _person_may_read_artifact(session, item, user.email)
        ]
    return ArtifactRevisionsResponse(
        lineage_id=summary.lineage_id,
        latest_artifact_id=summary.latest_artifact_id,
        latest_revision=summary.latest_revision,
        revisions=revisions,
    )


async def _person_may_read_artifact(session: Any, row: Any, user_email: str) -> bool:
    return row.owner_email == user_email or await can_project_read_artifact(
        session, row, user_email
    )


@router.get("/{artifact_id}/signed-url")
async def get_signed_url(
    request: Request,
    artifact_id: str,
    ttl_seconds: int = Query(default=3600, ge=60, le=7 * 24 * 3600),
    mode: ArtifactURLMode = Query(default="download"),
) -> dict[str, object]:
    user = require_current_user(request)
    artifact_store = request.app.state.artifact_store
    if is_deliverable_ref(artifact_id):
        async with request.app.state.session_factory() as session:
            ref = await get_accessible_deliverable_ref(
                session,
                artifact_store,
                artifact_id,
                user.email,
            )
        if ref is None:
            raise api_exception(404, "not_found", "Artifact not found")
        if mode == "view":
            _assert_view_allowed(ref.filename, ref.mime_type)
        url = build_deliverable_public_url(
            artifact_store,
            ref,
            ttl_seconds=ttl_seconds,
            mode=mode,
        )
        return {
            "artifact_id": artifact_id,
            "deliverable_id": artifact_id,
            "source": "deliverable",
            "virtual": True,
            "url": url,
            "mode": mode,
            "filename": ref.filename,
            "mime_type": ref.mime_type,
            "size_bytes": ref.size_bytes,
            "expires_at": (datetime.now(UTC) + timedelta(seconds=ttl_seconds)).isoformat(),
        }
    async with request.app.state.session_factory() as session:
        row = await get_artifact_record(session, artifact_id)
    if row is None or row.status == "deleted" or _is_expired(row):
        raise api_exception(404, "not_found", "Artifact not found")
    if (
        row.owner_email
        and row.owner_email != user.email
        and not await _project_reader_may_read(request, row, user.email)
    ):
        raise api_exception(404, "not_found", "Artifact not found")
    if mode == "view":
        _assert_view_allowed(row.filename, row.mime_type)
    ttl_seconds = _clamp_ttl_to_artifact_expiry(row, ttl_seconds)
    url = await artifact_store.async_get_public_url(
        row.namespace,
        row.object_id,
        row.filename,
        ttl_seconds=ttl_seconds,
        mode=mode,
    )
    return {
        "artifact_id": artifact_id,
        "url": url,
        "mode": mode,
        "expires_at": (datetime.now(UTC) + timedelta(seconds=ttl_seconds)).isoformat(),
    }


@router.get("/{artifact_id}/text-preview")
async def get_text_preview(request: Request, artifact_id: str) -> dict[str, object]:
    user = require_current_user(request)
    artifact_store = request.app.state.artifact_store
    if is_deliverable_ref(artifact_id):
        async with request.app.state.session_factory() as session:
            ref = await get_accessible_deliverable_ref(
                session, artifact_store, artifact_id, user.email
            )
        if ref is None:
            raise api_exception(404, "not_found", "Artifact not found")
        return {
            "artifact_id": artifact_id,
            **_text_preview_payload(
                filename=ref.filename,
                content_type=ref.mime_type,
                content=ref.content_bytes,
            ),
        }

    async with request.app.state.session_factory() as session:
        row = await get_artifact_record(session, artifact_id)
    if row is None or row.status == "deleted" or _is_expired(row):
        raise api_exception(404, "not_found", "Artifact not found")
    if (
        row.owner_email
        and row.owner_email != user.email
        and not await _project_reader_may_read(request, row, user.email)
    ):
        raise api_exception(404, "not_found", "Artifact not found")
    content, content_type = await artifact_store.async_load(
        row.namespace, row.object_id, row.filename
    )
    return {
        "artifact_id": artifact_id,
        **_text_preview_payload(
            filename=row.filename,
            content_type=content_type,
            content=content,
        ),
    }


@router.get("/virtual/deliverables/view/{deliverable_id}/{filename:path}")
async def serve_signed_deliverable_view(
    request: Request,
    deliverable_id: str,
    filename: str,
    exp: int,
    sig: str,
) -> Response:
    return await _serve_signed_deliverable(
        request,
        deliverable_id=deliverable_id,
        filename=filename,
        exp=exp,
        sig=sig,
        mode="view",
    )


@router.get("/virtual/deliverables/{deliverable_id}/{filename:path}")
async def serve_signed_deliverable(
    request: Request,
    deliverable_id: str,
    filename: str,
    exp: int,
    sig: str,
) -> Response:
    return await _serve_signed_deliverable(
        request,
        deliverable_id=deliverable_id,
        filename=filename,
        exp=exp,
        sig=sig,
        mode="download",
    )


async def _serve_signed_deliverable(
    request: Request,
    *,
    deliverable_id: str,
    filename: str,
    exp: int,
    sig: str,
    mode: ArtifactURLMode,
) -> Response:
    artifact_store = request.app.state.artifact_store
    if not artifact_store.verify_signed_request(
        "deliverables",
        deliverable_id,
        filename,
        exp=exp,
        sig=sig,
        mode=mode,
    ):
        if (
            mode == "view"
            and exp < int(time.time())
            and (request.cookies.get("cognis_session") or request.headers.get("Authorization"))
            and artifact_store.verify_signed_request(
                "deliverables",
                deliverable_id,
                filename,
                exp=exp,
                sig=sig,
                mode="view",
                allow_expired=True,
            )
        ):
            return RedirectResponse(
                f"/api/v1/deliverables/{quote(deliverable_id, safe='')}/view?expired_link=true",
                status_code=307,
                headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
            )
        raise api_exception(403, "forbidden", "Invalid or expired artifact signature")
    async with request.app.state.session_factory() as session:
        ref = await get_deliverable_ref_unscoped(session, artifact_store, deliverable_id)
    if ref is None or ref.filename != filename:
        raise api_exception(404, "not_found", "Artifact not found")
    if mode == "view":
        # Preserve the canonical payload, media and exports without renewing
        # the already verified deliverable-view capability.
        try:
            link = signed_deliverable_view_link(
                artifact_store,
                deliverable_id,
                base_url=str(request.base_url).rstrip("/"),
                expires_at=exp,
            )
        except DeliverableShareUnavailable as exc:
            raise api_exception(403, "forbidden", str(exc)) from exc
        return RedirectResponse(
            url=link.url.removeprefix(str(request.base_url).rstrip("/")),
            status_code=307,
            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
        )
    headers = _artifact_response_headers(
        filename=ref.filename,
        content_type=ref.mime_type,
        content_length=ref.size_bytes,
        mode=mode,
    )
    return Response(content=ref.content_bytes, media_type=ref.mime_type, headers=headers)


@router.get("/content/{namespace}/{object_id}/{filename:path}")
async def serve_signed_artifact(
    request: Request,
    namespace: str,
    object_id: str,
    filename: str,
    exp: int,
    sig: str,
) -> Response:
    return await _serve_signed_artifact(
        request,
        namespace=namespace,
        object_id=object_id,
        filename=filename,
        exp=exp,
        sig=sig,
        mode="download",
    )


@router.get("/view/{namespace}/{object_id}/{filename:path}")
async def serve_signed_artifact_view(
    request: Request,
    namespace: str,
    object_id: str,
    filename: str,
    exp: int,
    sig: str,
) -> Response:
    return await _serve_signed_artifact(
        request,
        namespace=namespace,
        object_id=object_id,
        filename=filename,
        exp=exp,
        sig=sig,
        mode="view",
    )


async def _serve_signed_artifact(
    request: Request,
    *,
    namespace: str,
    object_id: str,
    filename: str,
    exp: int,
    sig: str,
    mode: ArtifactURLMode,
) -> Response:
    artifact_store = request.app.state.artifact_store
    if not artifact_store.verify_signed_request(
        namespace, object_id, filename, exp=exp, sig=sig, mode=mode
    ):
        raise api_exception(403, "forbidden", "Invalid or expired artifact signature")
    async with request.app.state.session_factory() as session:
        artifact_row = await get_artifact_record(session, object_id)
        skill_asset_row = None
        if artifact_row is None and namespace == "skills":
            skill_asset_row = await get_skill_asset_by_artifact_object(
                session,
                artifact_namespace=namespace,
                artifact_object_id=object_id,
                filename=filename,
            )
        row: object = artifact_row or skill_asset_row
        if row is None and namespace == "avatars" and filename == "image":
            from cognis.core.avatar_access import get_current_agent_avatar_reference

            # The signature is the access capability, issued only after agent-use
            # authorization. Recheck the current link and storage ownership.
            row = await get_current_agent_avatar_reference(session, artifact_store, object_id)
    if row is None:
        raise api_exception(404, "not_found", "Artifact not found")
    if getattr(row, "status", None) == "deleted" or _is_expired(row):
        raise api_exception(404, "not_found", "Artifact not found")
    if (
        getattr(row, "namespace", None) != namespace
        and getattr(row, "artifact_namespace", None) != namespace
    ):
        raise api_exception(404, "not_found", "Artifact not found")
    if (
        getattr(row, "object_id", None) != object_id
        and getattr(row, "artifact_object_id", None) != object_id
    ):
        raise api_exception(404, "not_found", "Artifact not found")
    if getattr(row, "filename", None) != filename:
        raise api_exception(404, "not_found", "Artifact not found")
    if getattr(row, "mime_type", "").startswith("video/"):
        from cognis.artifacts.ranges import parse_byte_range

        size_bytes = getattr(row, "size_bytes", None)
        mime_type = getattr(row, "mime_type", "")
        if not isinstance(size_bytes, int):
            raise api_exception(404, "not_found", "Artifact not found")
        try:
            start, end, partial = parse_byte_range(request.headers.get("range"), size_bytes)
        except ValueError:
            return Response(status_code=416, headers={"Content-Range": f"bytes */{size_bytes}"})
        headers = _artifact_response_headers(
            filename=filename,
            content_type=mime_type,
            content_length=end - start + 1,
            mode=mode,
        )
        headers["Accept-Ranges"] = "bytes"
        if partial:
            headers["Content-Range"] = f"bytes {start}-{end}/{size_bytes}"
        return StreamingResponse(
            artifact_store.async_read_range(namespace, object_id, filename, start, end),
            media_type=mime_type,
            status_code=206 if partial else 200,
            headers=headers,
        )
    content, content_type = await artifact_store.async_load(namespace, object_id, filename)
    if mode == "view":
        return _artifact_viewer_response(
            artifact_id=object_id,
            filename=filename,
            content_type=content_type,
            content=content,
            standalone_url=str(request.url),
        )
    headers = _artifact_response_headers(
        filename=filename,
        content_type=content_type,
        content_length=len(content),
        mode=mode,
    )
    return Response(
        content=content,
        media_type=content_type,
        headers=headers,
    )
