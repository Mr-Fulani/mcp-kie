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
