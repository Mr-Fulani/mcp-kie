from dataclasses import replace

import httpx
import pytest
from test_client import settings

from kie_mcp.client import KieClient
from kie_mcp.config import Settings
from kie_mcp.security import open_upload, redact

PNG = b"\x89PNG\r\n\x1a\n" + b"fixture"


def test_separate_media_key_required(monkeypatch):
    monkeypatch.delenv("KIE_MCP_API_KEY", raising=False)
    monkeypatch.setenv("KIE_API_KEY", "chat-only-secret")
    config = Settings.from_env()
    with pytest.raises(RuntimeError, match="separate media key"):
        config.require_api_key()
    assert config.api_key is None


def test_media_key_not_in_repr(monkeypatch):
    monkeypatch.setenv("KIE_MCP_API_KEY", "private-media-secret")
    config = Settings.from_env()
    assert config.require_api_key() == "private-media-secret"
    assert "private-media-secret" not in repr(config)


def test_endpoint_configuration_not_agent_controlled(monkeypatch):
    monkeypatch.setenv("KIE_API_BASE", "https://attacker.invalid")
    monkeypatch.setenv("KIE_UPLOAD_BASE", "https://attacker.invalid")
    assert Settings.from_env().api_base == "https://api.kie.ai"
    with pytest.raises(ValueError, match="Unapproved"):
        KieClient(replace(settings(), api_base="https://attacker.invalid"))


def test_upload_allowed_file(tmp_path):
    path = tmp_path / "photo.png"
    path.write_bytes(PNG)
    with open_upload(str(path), tmp_path, 1024) as (handle, mime):
        assert handle.read() == PNG
        assert mime == "image/png"


def test_upload_outside_root_blocked(tmp_path):
    root = tmp_path / "allowed"
    root.mkdir()
    path = tmp_path / "photo.png"
    path.write_bytes(PNG)
    with pytest.raises(ValueError), open_upload(str(path), root, 1024):
        pytest.fail("Opened forbidden file")


def test_upload_dotdot_blocked(tmp_path):
    with (
        pytest.raises(ValueError, match="traversal"),
        open_upload("../photo.png", tmp_path, 1024),
    ):
        pytest.fail("Opened forbidden file")


def test_upload_symlink_escape_blocked(tmp_path):
    root = tmp_path / "allowed"
    root.mkdir()
    path = tmp_path / "photo.png"
    path.write_bytes(PNG)
    (root / "photo.png").symlink_to(path)
    with pytest.raises(ValueError), open_upload(str(root / "photo.png"), root, 1024):
        pytest.fail("Opened forbidden file")


def test_upload_too_large_blocked(tmp_path):
    path = tmp_path / "photo.png"
    path.write_bytes(PNG)
    with pytest.raises(ValueError, match="byte limit"), open_upload(str(path), tmp_path, 4):
        pytest.fail("Opened oversized file")


@pytest.mark.parametrize("name", [".env", "private.pem", "id.key", "archive.zip", "script.py"])
def test_secret_file_extension_blocked(tmp_path, name):
    path = tmp_path / name
    path.write_bytes(PNG)
    with pytest.raises(ValueError, match="filename"), open_upload(str(path), tmp_path, 1024):
        pytest.fail("Opened forbidden file")


def test_fake_media_extension_blocked(tmp_path):
    path = tmp_path / "photo.png"
    path.write_bytes(b"#!/bin/sh\necho secret")
    with pytest.raises(ValueError, match="media type"), open_upload(str(path), tmp_path, 1024):
        pytest.fail("Opened fake media")


@pytest.mark.asyncio
async def test_paid_and_generic_endpoints_blocked():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"code": 200})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = KieClient(settings(), http_client=http)
        for path in ["/api/v1/jobs/createTask", "/codex/v1/responses", "/api/v1/limits"]:
            with pytest.raises(ValueError, match="disabled"):
                await client.request("POST", path, json_body={})
    assert not calls


@pytest.mark.asyncio
async def test_api_key_not_in_error_or_logs(caplog):
    def handler(request):
        return httpx.Response(
            401,
            json={
                "message": "test-key Bearer chat-secret /Users/user/.ssh/id_rsa",
                "Authorization": "Bearer test-key",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = KieClient(settings(), http_client=http)
        with pytest.raises(Exception) as error:
            await client.get_credits()
    assert "test-key" not in str(error.value)
    assert "test-key" not in repr(error.value.as_dict())
    assert "test-key" not in caplog.text
    assert "/Users/user/.ssh" not in str(error.value)


def test_chat_key_redacted(monkeypatch):
    monkeypatch.setenv("KIE_API_KEY", "chat-secret")
    assert redact({"message": "chat-secret"}, "media-secret")["message"] == "[REDACTED]"


@pytest.mark.asyncio
async def test_stdio_only_and_removed_bypass_tools(monkeypatch):
    from kie_mcp import server

    tools = {t.name for t in await server.mcp.list_tools()}
    assert "kie_get_credits" in tools
    assert not tools.intersection(
        {
            "kie_api_request",
            "kie_chat_completions",
            "kie_claude_messages",
            "kie_responses",
            "kie_verify_webhook",
        }
    )
    monkeypatch.setattr(server, "settings", replace(settings(), transport="streamable-http"))
    with pytest.raises(SystemExit, match="stdio"):
        server.main()


def test_symlink_swap_toctou_blocked_or_detected(tmp_path, monkeypatch):
    import os

    from kie_mcp import security

    root = tmp_path / "uploads"
    root.mkdir()
    path = root / "photo.png"
    path.write_bytes(PNG)
    outside = tmp_path / "private.png"
    outside.write_bytes(PNG + b"secret")
    real_open = os.open

    def swapped_open(name, flags, *args, **kwargs):
        if name == "photo.png":
            path.unlink()
            path.symlink_to(outside)
        return real_open(name, flags, *args, **kwargs)

    monkeypatch.setattr(security.os, "open", swapped_open)
    with pytest.raises(OSError), open_upload(str(path), root, 1024):
        pytest.fail("Symlink swap escaped the anchored descriptor")


def test_secret_in_response_key_redacted():
    value = {"private-media-secret": "normal value", "data": {"private-media-secret": 1}}
    assert "private-media-secret" not in repr(redact(value, "private-media-secret"))


def test_camel_case_sensitive_response_keys_redacted():
    value = {"apiKey": "provider-secret", "accessToken": "provider-token"}
    cleaned = redact(value, "media-secret")
    assert cleaned == {"apiKey": "[REDACTED]", "accessToken": "[REDACTED]"}
