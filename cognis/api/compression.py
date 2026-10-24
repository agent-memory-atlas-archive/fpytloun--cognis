"""Response compression for buffered API payloads.

Only complete single-message bodies are compressed. Streaming responses
(SSE, NDJSON, file downloads, proxied streams) pass through untouched so
compression never delays incremental delivery. Static UI assets are served
with build-time sidecar encodings by ``cognis.ui_assets.SPAMiddleware``.
"""

from __future__ import annotations

import asyncio
import gzip
import hashlib

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_COMPRESSIBLE_PREFIXES = (
    "application/json",
    "application/problem+json",
    "application/javascript",
    "application/xml",
    "text/plain",
    "text/html",
    "text/css",
    "text/markdown",
    "image/svg+xml",
)
_DEFAULT_MINIMUM_SIZE = 1024
_DEFAULT_COMPRESS_LEVEL = 5
# Larger bodies are compressed off the event loop.
_THREAD_OFFLOAD_THRESHOLD = 256 * 1024


def _accepts_gzip(accept_encoding: str) -> bool:
    for part in accept_encoding.split(","):
        token, _, params = part.strip().partition(";")
        if token.strip().lower() not in {"gzip", "*"}:
            continue
        quality = params.strip().lower()
        if quality.startswith("q="):
            try:
                return float(quality[2:]) > 0
            except ValueError:
                return False
        return True
    return False


_CONDITIONAL_GET_PATHS = (
    "/api/v1/conversations/sidebar",
    "/api/v1/agents",
    "/api/v1/user-preferences",
    "/api/v1/projects",
)


def _etag_matches(if_none_match: str, etag: str) -> bool:
    if if_none_match.strip() == "*":
        return True
    candidates = {part.strip().removeprefix("W/") for part in if_none_match.split(",")}
    return etag.removeprefix("W/") in candidates


class ConditionalJsonGetMiddleware:
    """Weak ETags + 304 for frequently re-read JSON lists.

    The sidebar, agent, preference, and project lists are re-fetched on every
    focus/reconnect but rarely change. Responses get a content-hash ETag with
    ``Cache-Control: private, no-cache`` (always revalidated, never served
    stale), so an unchanged list costs a tiny 304 instead of the full body.
    Server work is unchanged; this saves bytes on slow links.
    """

    def __init__(self, app: ASGIApp, *, paths: tuple[str, ...] = _CONDITIONAL_GET_PATHS) -> None:
        self.app = app
        self.paths = paths

    def _applies(self, scope: Scope) -> bool:
        if scope["type"] != "http" or scope.get("method") != "GET":
            return False
        return scope.get("path", "") in self.paths

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not self._applies(scope):
            await self.app(scope, receive, send)
            return
        if_none_match = Headers(scope=scope).get("if-none-match", "")
        start_message: Message | None = None
        passthrough = False

        async def send_wrapper(message: Message) -> None:
            nonlocal start_message, passthrough
            if message["type"] == "http.response.start":
                headers = Headers(raw=message["headers"])
                if (
                    message.get("status") != 200
                    or "etag" in headers
                    or "cache-control" in headers
                    or not headers.get("content-type", "").startswith("application/json")
                ):
                    passthrough = True
                    await send(message)
                    return
                start_message = message
                return
            if passthrough or start_message is None or message["type"] != "http.response.body":
                await send(message)
                return
            pending_start, start_message = start_message, None
            passthrough = True
            body = message.get("body", b"")
            if message.get("more_body", False):
                await send(pending_start)
                await send(message)
                return
            etag = 'W/"' + hashlib.blake2b(body, digest_size=16).hexdigest() + '"'
            headers = MutableHeaders(raw=pending_start["headers"])
            headers["ETag"] = etag
            headers["Cache-Control"] = "private, no-cache"
            if if_none_match and _etag_matches(if_none_match, etag):
                not_modified = MutableHeaders()
                not_modified["ETag"] = etag
                not_modified["Cache-Control"] = "private, no-cache"
                # The 200 may be gzip-encoded (outer middleware); keep the
                # variation metadata on the matching 304.
                not_modified["Vary"] = "Accept-Encoding"
                await send(
                    {"type": "http.response.start", "status": 304, "headers": not_modified.raw}
                )
                await send({"type": "http.response.body", "body": b"", "more_body": False})
                return
            await send(pending_start)
            await send(message)

        await self.app(scope, receive, send_wrapper)


class BufferedGZipMiddleware:
    """Gzip complete HTTP responses whose content type is compressible."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        minimum_size: int = _DEFAULT_MINIMUM_SIZE,
        compresslevel: int = _DEFAULT_COMPRESS_LEVEL,
    ) -> None:
        self.app = app
        self.minimum_size = minimum_size
        self.compresslevel = compresslevel

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_headers = Headers(scope=scope)
        if request_headers.get("range") or not _accepts_gzip(
            request_headers.get("accept-encoding", "")
        ):
            await self.app(scope, receive, send)
            return

        start_message: Message | None = None
        passthrough = False

        async def send_wrapper(message: Message) -> None:
            nonlocal start_message, passthrough
            message_type = message["type"]
            if message_type == "http.response.start":
                headers = Headers(raw=message["headers"])
                content_type = headers.get("content-type", "").lower()
                if (
                    "content-encoding" in headers
                    or not content_type.startswith(_COMPRESSIBLE_PREFIXES)
                    or message.get("status", 200) in {204, 304}
                ):
                    passthrough = True
                    await send(message)
                    return
                start_message = message
                return
            if passthrough or start_message is None:
                await send(message)
                return
            if message_type != "http.response.body":
                pending_start, start_message = start_message, None
                passthrough = True
                await send(pending_start)
                await send(message)
                return

            pending_start, start_message = start_message, None
            passthrough = True
            body = message.get("body", b"")
            if message.get("more_body", False) or len(body) < self.minimum_size:
                # Streaming or small response: forward unchanged.
                await send(pending_start)
                await send(message)
                return
            if len(body) >= _THREAD_OFFLOAD_THRESHOLD:
                compressed = await asyncio.to_thread(gzip.compress, body, self.compresslevel)
            else:
                compressed = gzip.compress(body, self.compresslevel)
            headers = MutableHeaders(raw=pending_start["headers"])
            headers.add_vary_header("Accept-Encoding")
            if len(compressed) >= len(body):
                await send(pending_start)
                await send(message)
                return
            headers["Content-Encoding"] = "gzip"
            headers["Content-Length"] = str(len(compressed))
            if "etag" in headers and not headers["etag"].startswith("W/"):
                headers["ETag"] = f"W/{headers['etag']}"
            await send(pending_start)
            await send({"type": "http.response.body", "body": compressed, "more_body": False})

        await self.app(scope, receive, send_wrapper)
