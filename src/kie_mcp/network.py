"""HTTPS URL validation and DNS-pinned connections; no proxies or implicit redirects."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
import ssl
from urllib.parse import urljoin, urlsplit

import httpcore
import httpx
from httpcore._backends.auto import AutoBackend

from .ledger import GuardError

# Explicit owner-reviewed hosts returned for completed KIE tasks. Keep
# this list explicit so a task response cannot turn result download into a
# general-purpose public URL fetch.
KIE_STORAGE_HOSTS = {"tempfile.redpandaai.co", "file.kie.ai", "tempfile.aiquickdraw.com"}


def public_address(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast and not ip.is_reserved


def validate_url(url: str, *, allowed_hosts: set[str] | None = None) -> str:
    try:
        parsed = urlsplit(url)
        host = parsed.hostname
        port = parsed.port
    except ValueError:
        raise GuardError("Invalid HTTPS URL") from None
    if (
        parsed.scheme != "https"
        or not host
        or parsed.username
        or parsed.password
        or port not in {None, 443}
        or parsed.fragment
        or "\\" in url
        or host.lower().rstrip(".") == "localhost"
        or host.endswith(".localhost")
    ):
        raise GuardError("Only public HTTPS URLs without credentials are permitted")
    if allowed_hosts is not None and host not in allowed_hosts:
        raise GuardError("URL host is outside the network allowlist")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        if not public_address(host):
            raise GuardError("Private or special network addresses are blocked")
    return host


async def resolve_public(host: str, port: int = 443) -> list[str]:
    records = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    addresses = sorted({record[4][0] for record in records})
    if not addresses or not all(public_address(ip) for ip in addresses):
        raise GuardError("DNS resolved to a private or special network address")
    return addresses


class PinnedBackend(AutoBackend):
    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        if port != 443:
            raise GuardError("Only HTTPS port 443 is permitted")
        addresses = await asyncio.wait_for(resolve_public(host, port), timeout=timeout or 30)
        # Connect directly to a checked numeric address. TLS still uses the original
        # hostname from httpcore's connection for SNI and certificate verification.
        return await super().connect_tcp(
            addresses[0],
            port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )

    async def connect_unix_socket(self, *args, **kwargs):
        raise GuardError("Unix socket network connections are disabled")


class PinnedTransport(httpx.AsyncHTTPTransport):
    def __init__(self):
        super().__init__(trust_env=False)
        # httpx transport adapter backed by httpcore's supported network_backend.
        # These packages are locked; revalidate this bridge on dependency updates.
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=ssl.create_default_context(),
            network_backend=PinnedBackend(),
            retries=0,
            max_connections=10,
        )


def safe_http_client(timeout: float = 30) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=PinnedTransport(), timeout=timeout, follow_redirects=False, trust_env=False
    )


async def fetch_bytes(
    url: str,
    max_bytes: int,
    *,
    client: httpx.AsyncClient | None = None,
    allowed_hosts: set[str] | None = None,
    redirects: int = 3,
) -> bytes:
    if max_bytes <= 0:
        raise GuardError("Invalid download byte limit")
    if client is None:
        async with safe_http_client() as http:
            return await fetch_bytes(
                url, max_bytes, client=http, allowed_hosts=allowed_hosts, redirects=redirects
            )
    for hop in range(redirects + 1):
        validate_url(url, allowed_hosts=allowed_hosts)
        async with client.stream("GET", url, follow_redirects=False) as response:
            if response.status_code in {301, 302, 303, 307, 308}:
                target = response.headers.get("location")
                if target is None or hop == redirects:
                    raise GuardError("Remote redirect limit reached or target missing")
                url = urljoin(url, target)
                continue
            response.raise_for_status()
            length = response.headers.get("content-length")
            if length and int(length) > max_bytes:
                raise GuardError("Remote file exceeds byte limit")
            result = bytearray()
            async for chunk in response.aiter_bytes():
                if len(result) + len(chunk) > max_bytes:
                    raise GuardError("Remote file exceeds byte limit")
                result.extend(chunk)
            return bytes(result)
    raise GuardError("Remote redirect limit reached")
