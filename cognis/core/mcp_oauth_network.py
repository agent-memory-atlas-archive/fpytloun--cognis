"""Controller-owned OAuth destination checks and DNS-pinned HTTP transport."""

from __future__ import annotations

import asyncio
import socket
from ipaddress import ip_address, ip_network

import httpx

from cognis.config import mcp_oauth_trusted_destinations


def resolve_oauth_destination(url: str, *, allow_http_localhost: bool = True) -> str:
    """Validate an OAuth URL and return one checked numeric destination."""
    try:
        parsed = httpx.URL(url)
    except httpx.InvalidURL as exc:
        raise ValueError("OAuth endpoint URL is malformed") from exc
    host = parsed.raw_host.decode("ascii")
    if not host or parsed.userinfo or parsed.fragment:
        raise ValueError("OAuth endpoint requires a host without userinfo or fragment")
    localhost = host in {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme != "https" and not (
        parsed.scheme == "http" and allow_http_localhost and localhost
    ):
        raise ValueError("OAuth endpoints must use https except localhost development URLs")
    port = parsed.port if parsed.port is not None else (443 if parsed.scheme == "https" else 80)
    if not 1 <= port <= 65535:
        raise ValueError("OAuth endpoint port is invalid")
    trusted = mcp_oauth_trusted_destinations().get((host, port), ())
    try:
        addresses = [ip_address(host)]
    except ValueError:
        try:
            addresses = [
                ip_address(info[4][0])
                for info in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
            ]
        except OSError as exc:
            raise ValueError("OAuth endpoint host could not be resolved") from exc
    if not addresses:
        raise ValueError("OAuth endpoint host could not be resolved")
    for candidate in addresses:
        if trusted:
            if parsed.scheme != "https" or not any(
                candidate in ip_network(cidr) for cidr in trusted
            ):
                raise ValueError("OAuth endpoint destination is outside its trusted CIDRs")
        elif candidate.is_loopback:
            if not localhost:
                raise ValueError("OAuth endpoints cannot target loopback aliases")
        elif (
            candidate.is_private
            or candidate.is_link_local
            or candidate.is_reserved
            or candidate.is_multicast
            or candidate.is_unspecified
        ):
            raise ValueError("OAuth endpoints cannot target private or link-local addresses")
    return str(addresses[0])


class OAuthDestinationTransport(httpx.AsyncBaseTransport):
    """Pin every OAuth HTTP request while retaining its TLS and HTTP authority."""

    def __init__(self) -> None:
        self._transports: dict[tuple[str, str, int | None, str], httpx.AsyncHTTPTransport] = {}

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        """Resolve and validate each hop before passing only a numeric IP to HTTPX."""
        try:
            timeout = request.extensions.get("timeout", {}).get("connect", 5.0)
            async with asyncio.timeout(timeout):
                address = await asyncio.to_thread(resolve_oauth_destination, str(request.url))
        except TimeoutError as exc:
            raise httpx.ConnectTimeout(
                "OAuth endpoint DNS resolution timed out", request=request
            ) from exc
        except ValueError as exc:
            raise httpx.ConnectError(str(exc), request=request) from exc
        key = (request.url.scheme, request.url.host, request.url.port, address)
        transport = self._transports.get(key)
        if transport is None:
            # Separate pools prevent TLS reuse between hostnames sharing an IP.
            transport = httpx.AsyncHTTPTransport(trust_env=False, retries=0)
            self._transports[key] = transport
        headers = request.headers.copy()
        headers["Host"] = request.url.netloc.decode("ascii")
        pinned = httpx.Request(
            request.method,
            request.url.copy_with(host=address),
            headers=headers,
            stream=request.stream,
            extensions={**request.extensions, "sni_hostname": request.url.raw_host.decode("ascii")},
        )
        return await transport.handle_async_request(pinned)

    async def aclose(self) -> None:
        """Close every origin-specific connection pool."""
        for transport in self._transports.values():
            await transport.aclose()
