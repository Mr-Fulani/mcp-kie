import os
from pathlib import Path

import httpx
import pytest

from kie_mcp.ledger import GuardError
from kie_mcp.network import (
    KIE_STORAGE_HOSTS,
    PinnedBackend,
    fetch_bytes,
    public_address,
    resolve_public,
    validate_url,
)
from kie_mcp.storage import save_result


@pytest.mark.parametrize(
    "url",
    [
        "https://localhost/a",
        "https://127.0.0.1/a",
        "https://10.0.0.1/a",
        "https://169.254.169.254/a",
        "https://[::1]/a",
        "https://[fc00::1]/a",
        "https://[fe80::1]/a",
        "https://[::ffff:127.0.0.1]/a",
        "http://example.com/a",
        "https://example.com:8080/a",
        "https://user:pass@example.com/a",
    ],
)
def test_ssrf_private_addresses_blocked(url):
    with pytest.raises(GuardError):
        validate_url(url)


async def test_dns_private_resolution_blocked(monkeypatch):
    import asyncio

    async def lookup(*args, **kwargs):
        return [(2, 1, 6, "", ("8.8.8.8", 443)), (2, 1, 6, "", ("10.0.0.1", 443))]

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", lookup)
    with pytest.raises(GuardError, match="DNS"):
        await resolve_public("public-looking.example")


async def test_connection_uses_validated_numeric_ip(monkeypatch):
    from httpcore._backends.auto import AutoBackend

    from kie_mcp import network

    calls = []

    async def resolve(*args):
        return ["8.8.8.8"]

    async def connect(self, host, port, **kwargs):
        calls.append((host, port))
        return "stream"

    monkeypatch.setattr(network, "resolve_public", resolve)
    monkeypatch.setattr(AutoBackend, "connect_tcp", connect)
    assert await PinnedBackend().connect_tcp("example.com", 443) == "stream"
    assert calls == [("8.8.8.8", 443)]


async def test_redirect_to_private_ip_blocked():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(302, headers={"location": "https://169.254.169.254/secrets"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(GuardError):
            await fetch_bytes("https://example.com/a", 1000, client=client)
    assert len(calls) == 1


async def test_reviewed_kie_result_host_can_be_downloaded():
    requests = []
    content = b"\x89PNG\r\n\x1a\nfixture"

    def handler(request):
        requests.append(request)
        return httpx.Response(200, content=content)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await fetch_bytes(
            "https://tempfile.aiquickdraw.com/result.png",
            1024,
            client=client,
            allowed_hosts=KIE_STORAGE_HOSTS,
        )
    assert result == content
    assert len(requests) == 1
    assert "authorization" not in requests[0].headers


@pytest.mark.parametrize(
    "url",
    [
        "https://tempfile.aiquickdraw.com.attacker.invalid/result.png",
        "https://other.aiquickdraw.com/result.png",
        "https://tempfile.aiquickdraw.com./result.png",
        "http://tempfile.aiquickdraw.com/result.png",
        "https://tempfile.aiquickdraw.com:8443/result.png",
        "https://user:password@tempfile.aiquickdraw.com/result.png",
    ],
)
def test_result_storage_allowlist_remains_exact_https(url):
    with pytest.raises(GuardError):
        validate_url(url, allowed_hosts=KIE_STORAGE_HOSTS)


@pytest.mark.parametrize(
    "target",
    ["https://attacker.invalid/result.png", "https://169.254.169.254/secrets"],
)
async def test_reviewed_result_host_redirect_rechecks_allowlist(target):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(302, headers={"location": target})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(GuardError):
            await fetch_bytes(
                "https://tempfile.aiquickdraw.com/result.png",
                1024,
                client=client,
                allowed_hosts=KIE_STORAGE_HOSTS,
            )
    assert len(requests) == 1


async def test_download_size_limit():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"x" * 100))
    ) as client:
        with pytest.raises(GuardError, match="byte limit"):
            await fetch_bytes("https://example.com/a", 10, client=client)


def test_ipv6_special_ranges_blocked():
    for ip in ["fc00::1", "fe80::1", "::1", "ff02::1", "::", "2001:db8::1"]:
        assert not public_address(ip)


def test_download_atomic_inside_root(tmp_path):
    content = b"\x89PNG\r\n\x1a\nfixture"
    one = Path(save_result(tmp_path, "task_123", content))
    two = Path(save_result(tmp_path, "task_123", content))
    assert one != two and one.read_bytes() == content and two.read_bytes() == content
    assert one.parent == tmp_path / "task_123"
    assert not list(one.parent.glob("*.part"))
    assert os.stat(one).st_mode & 0o777 == 0o600


def test_download_outside_root_blocked(tmp_path):
    with pytest.raises(GuardError):
        save_result(tmp_path, "../../escape", b"\x89PNG\r\n\x1a\nfixture")


def test_download_symlink_escape_blocked(tmp_path):
    root = tmp_path / "results"
    root.mkdir()
    (root / "task").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(OSError):
        save_result(root, "task", b"\x89PNG\r\n\x1a\nfixture")
    assert not list(tmp_path.glob("*.png"))
