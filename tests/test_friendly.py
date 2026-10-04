import copy
from dataclasses import replace

import httpx
import pytest
from test_client import settings

from kie_mcp.client import KieClient
from kie_mcp.friendly import map_input
from kie_mcp.ledger import GuardError
from kie_mcp.service import KieService

MODEL = "fixture/video"
URL = "https://tempfile.redpandaai.co/input.png"


def contract(fields, required):
    return {
        "paths": {
            "/api/v1/jobs/createTask": {
                "post": {
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["model", "input"],
                                    "properties": {
                                        "model": {"type": "string"},
                                        "input": {
                                            "type": "object",
                                            "properties": fields,
                                            "required": required,
                                            "additionalProperties": False,
                                        },
                                    },
                                }
                            },
                        }
                    }
                }
            }
        },
    }


def video_fields(image=False):
    fields = {
        "prompt": {"type": "string"},
        "duration": {"type": "string", "enum": ["5", "10"], "default": "5"},
        "resolution": {"type": "string", "enum": ["480p", "720p"], "default": "720p"},
    }
    if image:
        fields.update(image_url={"type": "string"}, end_image_url={"type": "string"})
    else:
        fields["aspect_ratio"] = {"type": "string", "enum": ["16:9", "9:16"]}
    return fields


class MediaAPI:
    def __init__(self, schema, price="Each task costs 20 credits (0.10 USD)."):
        self.schema, self.price, self.calls = schema, price, []

    def __call__(self, request):
        self.calls.append(request)
        path = request.url.path
        if path.endswith("/schema"):
            data = {"openapi": self.schema}
        elif path.endswith("/price"):
            data = {"pricingDesc": self.price}
        elif path == "/api/v1/models":
            data = {"models": [{"model": "fixture/unsupported"}, {"model": MODEL}]}
        else:
            raise AssertionError("Friendly preparation must not submit paid tasks")
        if "unsupported/schema" in path:
            data = {"openapi": {"paths": {}}}
        return httpx.Response(200, json={"code": 200, "data": data})


def make_service(tmp_path, http):
    config = replace(settings(), ledger_path=tmp_path / "usage.db", allowed_upload_root=tmp_path)
    return KieService(config, KieClient(config, http_client=http), metadata_interval=0)


async def test_video_preview_maps_live_string_duration_without_reservation(tmp_path):
    api = MediaAPI(contract(video_fields(), ["prompt"]))
    async with httpx.AsyncClient(transport=httpx.MockTransport(api)) as http:
        result = await make_service(tmp_path, http).friendly(
            "generate_video",
            "A boat moves",
            MODEL,
            parameters={"duration": 5, "resolution": "480P", "aspect_ratio": "16:9"},
            dry_run=True,
        )
    assert result["validated_input"]["duration"] == "5"
    assert result["validated_input"]["resolution"] == "480p"
    assert result["confidence"] == "unknown" and result["execution_blocked"]
    assert result["next_step"] == "owner_verified_quote"
    assert not result["reservation_created"]
    assert not (tmp_path / "usage.db").exists()


async def test_image_video_uses_required_first_image_and_preserves_exact_quote_input(
    tmp_path,
    monkeypatch,
):
    from kie_mcp import service as module

    async def public(host):
        return ["8.8.8.8"]

    monkeypatch.setattr(module, "resolve_public", public)
    api = MediaAPI(contract(video_fields(True), ["prompt", "image_url"]))
    async with httpx.AsyncClient(transport=httpx.MockTransport(api)) as http:
        result = await make_service(tmp_path, http).friendly(
            "generate_video",
            "Slow camera movement",
            MODEL,
            image_url=URL,
            parameters={"duration": 5},
            dry_run=True,
        )
    assert result["image_field"] == "image_url"
    assert result["validated_input"]["image_url"] == URL
    assert "end_image_url" not in result["validated_input"]


@pytest.mark.parametrize(
    "operation",
    [
        "edit_image",
        "remove_background",
        "upscale_image",
        "product_image_create",
    ],
)
async def test_image_operations_preview_after_one_validated_upload(
    tmp_path, monkeypatch, operation
):
    from kie_mcp import service as module

    async def public(host):
        return ["8.8.8.8"]

    monkeypatch.setattr(module, "resolve_public", public)
    image = tmp_path / "image.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\nfixture")
    fields = {
        "prompt": {"type": "string"},
        "image_urls": {"type": "array", "items": {"type": "string"}},
    }
    api = MediaAPI(contract(fields, ["image_urls"]))
    uploads = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(api)) as http:
        service = make_service(tmp_path, http)

        async def upload(path, *args):
            uploads.append(path)
            return {"data": {"downloadUrl": URL}}

        monkeypatch.setattr(service.client, "upload_local_file", upload)
        result = await service.friendly(operation, model=MODEL, image_path=str(image), dry_run=True)
    assert result["validated_input"]["image_urls"] == [URL]
    assert uploads == [str(image)]
    assert result["next_step"] == "kie_prepare_task"
    assert not (tmp_path / "usage.db").exists()


async def test_router_skips_unsupported_api_family_without_aborting(tmp_path):
    api = MediaAPI(contract({"prompt": {"type": "string"}}, ["prompt"]))
    async with httpx.AsyncClient(transport=httpx.MockTransport(api)) as http:
        result = await make_service(tmp_path, http).friendly(
            "generate_image", "A boat", auto_select=True
        )
    assert result["selected_model"] == MODEL
    assert result["next_step"] == "kie_execute_task"


async def test_explicit_unsupported_parameter_fails_before_upload(tmp_path):
    fields = video_fields(True)
    api = MediaAPI(contract(fields, ["prompt", "image_url"]))
    image = tmp_path / "image.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\nfixture")
    async with httpx.AsyncClient(transport=httpx.MockTransport(api)) as http:
        service = make_service(tmp_path, http)
        with pytest.raises(GuardError, match="unsupported or ambiguous"):
            await service.friendly(
                "generate_video",
                "A boat",
                MODEL,
                image_path=str(image),
                parameters={"aspect_ratio": "16:9"},
                dry_run=True,
            )
    assert not (tmp_path / "usage.db").exists()


async def test_unknown_video_price_still_blocks_preparation(tmp_path):
    api = MediaAPI(contract(video_fields(), ["prompt"]))
    async with httpx.AsyncClient(transport=httpx.MockTransport(api)) as http:
        with pytest.raises(GuardError, match="No verified compatible price"):
            await make_service(tmp_path, http).friendly("generate_video", "A boat", MODEL)
    assert not (tmp_path / "usage.db").exists()


def test_aliases_are_schema_bound_and_model_parameters_do_not_override():
    schema = {
        "properties": {
            "scale_factor": {"type": "integer"},
            "resolution": {"type": "string"},
            "camera_fixed": {"type": "boolean"},
        }
    }
    original = copy.deepcopy(schema)
    data, _, mapping = map_input(
        schema,
        {"scale": 2, "target_resolution": "4K"},
        "",
        False,
        None,
        "upscale_image",
        {"camera_fixed": True},
    )
    assert data == {"scale_factor": 2, "resolution": "4K", "camera_fixed": True}
    assert mapping == {"scale": "scale_factor", "target_resolution": "resolution"}
    assert schema == original
    with pytest.raises(GuardError, match="once"):
        map_input(schema, {"scale": 2}, "", False, None, "upscale_image", {"scale_factor": 4})
    with pytest.raises(GuardError, match="absent"):
        map_input(schema, {}, "", False, None, "upscale_image", {"invented": True})


def test_multiple_required_images_fail_instead_of_guessing():
    schema = {
        "properties": {"image_url": {}, "first_frame_url": {}},
        "required": ["image_url", "first_frame_url"],
    }
    with pytest.raises(GuardError, match="Ambiguous"):
        map_input(schema, {}, "", True, URL, "generate_video")


@pytest.mark.parametrize(
    "operation,query", [("remove_background", "remove-background"), ("upscale_image", "upscale")]
)
async def test_dedicated_operation_discovery_avoids_generic_edits(
    tmp_path, monkeypatch, operation, query
):
    from kie_mcp import service as module

    async def public(host):
        return ["8.8.8.8"]

    monkeypatch.setattr(module, "resolve_public", public)
    api = MediaAPI(contract({"image_url": {"type": "string"}}, ["image_url"]))
    async with httpx.AsyncClient(transport=httpx.MockTransport(api)) as http:
        result = await make_service(tmp_path, http).friendly(
            operation, image_url=URL, dry_run=True, auto_select=True
        )
    discovery = next(r for r in api.calls if r.url.path == "/api/v1/models")
    assert discovery.url.params.get("q") == query
    assert "taskType" not in discovery.url.params
    assert result["selected_model"] == MODEL


async def test_stdio_friendly_arguments_are_discoverable(tmp_path):
    import os
    import sys

    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    env = dict(os.environ, KIE_MCP_API_KEY="offline-test-key", KIE_MCP_TRANSPORT="stdio")
    params = StdioServerParameters(command=sys.executable, args=["-m", "kie_mcp.server"], env=env)
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        listed = await session.list_tools()
    friendly = {
        "generate_image",
        "edit_image",
        "generate_video",
        "remove_background",
        "upscale_image",
        "product_image_create",
    }
    schemas = {t.name: t.inputSchema for t in listed.tools if t.name in friendly}
    assert schemas.keys() == friendly
    assert all(
        {"dry_run", "model_input", "auto_select"} <= s["properties"].keys()
        for s in schemas.values()
    )
    assert "output_format" in schemas["edit_image"]["properties"]
    all_schemas = {t.name: t.inputSchema for t in listed.tools}
    assert "kie_compare_models" in all_schemas
    assert "result_label" in all_schemas["kie_download_result"]["properties"]
    assert all(s["properties"]["auto_select"]["default"] is False for s in schemas.values())
