"""Authenticated, metadata-only command palette transport."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request, Response
from sqlalchemy.exc import DBAPIError

from cognis.api.common import api_exception, require_current_user
from cognis.core.palette import InvalidPaletteCursor, Kind, PaletteAdmission, PalettePage

router = APIRouter(prefix="/api/v1/search", tags=["search"])


@router.get("/palette", response_model=PalettePage)
async def palette_search(
    request: Request,
    response: Response,
    q: str = Query(default="", max_length=160),
    cursor: str | None = Query(default=None, max_length=2048),
    limit: int = Query(default=20, ge=1, le=40),
    types: list[Kind] | None = Query(default=None, max_length=7),
) -> PalettePage:
    """Return one ranked keyset page; never invoke external search or payload reads."""
    user = require_current_user(request)
    response.headers["Cache-Control"] = "no-store"
    admission: PaletteAdmission = request.app.state.palette_admission
    try:
        async with request.app.state.session_factory() as session:
            return await admission.run(
                session, user.email, q, cursor=cursor, limit=limit, kinds=types
            )
    except InvalidPaletteCursor as exc:
        raise api_exception(400, "invalid_cursor", str(exc)) from exc
    except BlockingIOError as exc:
        raise api_exception(429, "search_busy", "Search is busy. Try again shortly.") from exc
    except TimeoutError as exc:
        raise api_exception(
            503, "search_timeout", "Search took too long. Refine your query."
        ) from exc
    except DBAPIError as exc:
        if (
            getattr(exc.orig, "sqlstate", None) != "57014"
            and getattr(exc.orig, "sqlite_errorcode", None) != 9
        ):
            raise
        raise api_exception(
            503, "search_timeout", "Search took too long. Refine your query."
        ) from exc
