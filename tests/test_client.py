import base64
import json
import re
from dataclasses import replace

import httpx
import pytest

from kie_mcp.client import KieClient
from kie_mcp.config import Settings


def settings() -> Settings:
    return Settings(
        api_key="test-key",
        api_base="https://api.kie.ai",
        upload_base="https://kieai.redpandaai.co",
        timeout_seconds=10,
        max_retries=0,
        max_upload_bytes=1024,
        allowed_upload_root=None,
        transport="stdio",
    )


@pytest.mark.asyncio
async def test_parse_task() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("createTask"):
            return httpx.Response(
                200, json={"code": 200, "msg": "success", "data": {"taskId": "t1"}}
            )
        return httpx.Response(
            200,
            json={
                "code": 200,
                "msg": "success",
                "data": {
                    "taskId": "t1",
                    "state": "success",
                    "param": '{"model":"demo"}',
                    "resultJson": '{"resultUrls":["https://example.test/a.png"]}',
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = KieClient(settings(), http_client=http)
        with pytest.raises(ValueError, match="disabled"):
            await client.create_task("demo", {"prompt": "hello"})

        task = await client.get_task("t1")
        assert task["data"]["paramParsed"]["model"] == "demo"
        assert task["data"]["resultParsed"]["resultUrls"]


@pytest.mark.asyncio
async def test_rejects_full_url_path() -> None:
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: None)) as http:
        client = KieClient(settings(), http_client=http)
        with pytest.raises(ValueError):
            await client.request("GET", "https://evil.example/path")


@pytest.mark.asyncio
async def test_uploads_use_unique_anonymous_names(tmp_path) -> None:
    media = b"\x89PNG\r\n\x1a\nfixture"
    path = tmp_path / "private-reference.png"
    path.write_bytes(media)
    names = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content
        assert b"private-reference" not in body
        if request.url.path == "/api/file-base64-upload":
            payload = json.loads(body)
            name = payload["fileName"]
            assert base64.b64decode(payload["base64Data"]) == media
        else:
            name = re.search(rb'filename="([^"]+)"', body).group(1).decode()
            assert media in body
            assert name.encode() in body.split(b'name="fileName"')[1]
        assert re.fullmatch(r"media-[0-9a-f]{32}\.png", name)
        names.append(name)
        return httpx.Response(200, json={"code": 200, "data": {"fileName": name}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = KieClient(
            replace(settings(), allowed_upload_root=tmp_path), http_client=http
        )
        for _ in range(3):
            await client.upload_local_file(str(path), "mcp/files", None)
            await client.upload_bytes(media)
            await client.upload_base64(base64.b64encode(media).decode(), "mcp/base64", None)

    assert len(names) == 9
    assert len(set(names)) == len(names)
