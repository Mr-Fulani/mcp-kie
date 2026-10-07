from dataclasses import replace

import httpx
import pytest
from test_friendly import URL, contract, make_service, video_fields

from kie_mcp.ledger import GuardError


@pytest.mark.parametrize(
    "operation", ["product_image_create", "edit_image", "remove_background", "upscale_image"]
)
async def test_image_comparison_without_source_is_provisional_and_cannot_execute(
    tmp_path,
    operation,
):
    api = ComparisonAPI()
    async with httpx.AsyncClient(transport=httpx.MockTransport(api)) as http:
        service = make_service(tmp_path, http)
        result = await service.friendly(operation, "Studio product photo")
        assert result["models"][1]["compatible"]
        assert result["models"][1]["estimated_cost_usd"] == 0.05
        assert result["models"][1]["price_is_provisional"]
        assert result["models"][1]["price_assumptions"] == {"input_images": "one image assumed"}
        assert result["requirements"]["missing_inputs"] == ["image_source"]
        assert not result["requirements"]["image_required_for_comparison"]
        assert result["requirements"]["image_required_for_execution"]
        assert result["next_step"] == "kie_preflight_with_selected_model"
        with pytest.raises(GuardError, match="requires an input image"):
            await service.friendly(operation, model="fixture/m1")
    assert not (tmp_path / "usage.db").exists()
    assert not result["media_uploaded"] and not result["reservation_created"]
    assert all(r.method == "GET" for r in api.calls)


async def test_preflight_reports_missing_data_and_does_not_touch_source(tmp_path):
    api = ComparisonAPI()
    async with httpx.AsyncClient(transport=httpx.MockTransport(api)) as http:
        service = make_service(tmp_path, http)
        generic = await service.preflight("product_image_create")
        missing = await service.preflight("product_image_create", "fixture/m1", "Studio photo")
        provided = await service.preflight(
            "product_image_create",
            "fixture/m1",
            "Studio photo",
            image_path="/not-allowed/does-not-exist.png",
        )
    assert generic["missing_inputs"] == ["image_source", "model"]
    assert missing["status"] == "needs_input"
    assert missing["missing_inputs"] == ["image_source"]
    assert missing["model_requirements"]["required_fields"] == ["image_url"]
    assert missing["estimated_cost_usd"] == 0.05
    assert provided["status"] == "ready_for_preview"
    assert provided["price_is_provisional"]
    assert provided["upload_may_be_required"] and not provided["source_verified"]
    assert not provided["execution_ready"]
    assert not provided["media_uploaded"] and not provided["reservation_created"]
    assert not (tmp_path / "usage.db").exists()
    assert len(api.calls) == 4 and all(r.method == "GET" for r in api.calls)


async def test_preflight_invalid_parameters_report_field_names_without_private_values(tmp_path):
    api = ComparisonAPI()
    private_value = "private-not-an-allowed-resolution"
    async with httpx.AsyncClient(transport=httpx.MockTransport(api)) as http:
        result = await make_service(tmp_path, http).preflight(
            "generate_video",
            "fixture/m3",
            "private prompt",
            image_url=URL,
            parameters={"resolution": private_value},
        )
    assert result["status"] == "needs_parameters"
    assert result["invalid_fields"] == ["resolution"]
    assert private_value not in str(result) and "private prompt" not in str(result)
    assert len(api.calls) == 1 and not (tmp_path / "usage.db").exists()


class ComparisonAPI:
    def __init__(self, model_count=25):
        self.calls = []
        self.model_count = model_count

    def __call__(self, request):
        self.calls.append(request)
        path = request.url.path
        if path == "/api/v1/models":
            data = {
                "models": [
                    {"model": f"fixture/m{i}", "description": "Provider quality claim"}
                    for i in range(self.model_count)
                ]
            }
        elif path.endswith("/schema"):
            i = int(path.split("/")[-2][1:])
            fields = (
                video_fields(True)
                if i == 3
                else {"prompt": {"type": "string"}, "image_url": {"type": "string"}}
            )
            data = {"openapi": contract(fields, ["image_url"])}
        elif path.endswith("/price"):
            i = int(path.split("/")[-2][1:])
            data = {"pricingDesc": "Each task costs 20 credits (0.10 USD)."}
            if i == 0:
                data = {"pricingDesc": "Depends on quality"}
            elif i == 1:
                data = {"pricingDesc": "Each task costs 10 credits (0.05 USD)."}
        elif path.endswith("/success-rate"):
            return httpx.Response(503, json={"code": 503})
        else:
            raise AssertionError("Comparison must use metadata only")
        return httpx.Response(200, json={"code": 200, "data": data})


async def test_default_choice_is_metadata_only_and_unknown_is_not_free(tmp_path):
    api = ComparisonAPI()
    image = tmp_path / "photo.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\nfixture")
    async with httpx.AsyncClient(transport=httpx.MockTransport(api)) as http:
        service = make_service(tmp_path, http)
        service.settings = replace(
            service.settings, limits=replace(service.settings.limits, task_usd=0.075)
        )
        result = await service.friendly("edit_image", "Studio photo", image_path=str(image))
    assert result["selection_required"] and not result["reservation_created"]
    assert not result["media_uploaded"] and not (tmp_path / "usage.db").exists()
    assert "approval_id" not in result and "request_payload" not in result
    unknown, cheap, expensive = result["models"][:3]
    assert unknown["compatible"] and unknown["estimated_cost_usd"] is None
    assert unknown["risk_ack_required"] and unknown["within_task_limit"] is None
    assert unknown["pricing_warning_ru"] and unknown["risk_reserve_usd"] == 0.075
    assert cheap["within_task_limit"] and not expensive["within_task_limit"]
    assert cheap["quality"]["score"] is None and cheap["speed"]["expected_seconds"] is None
    assert cheap["quality"]["description"] == "Provider quality claim"
    assert result["next_cursor"] == 5
    assert all(r.method == "GET" for r in api.calls)


async def test_comparison_parameters_capabilities_and_unavailable_metrics(tmp_path):
    api = ComparisonAPI()
    async with httpx.AsyncClient(transport=httpx.MockTransport(api)) as http:
        result = await make_service(tmp_path, http).compare_models(
            "generate_video",
            "A boat",
            image_url=URL,
            parameters={"duration": 5, "resolution": "480P"},
            cursor=2,
            limit=2,
            include_metrics=True,
        )
    incompatible, video = result["models"]
    assert not incompatible["compatible"] and "reason" in incompatible
    assert video["compatible"] and video["risk_ack_required"]
    assert video["confidence"] == "unknown" and video["pricing_warning_ru"]
    assert video["effective_parameters"]["duration"] == "5"
    assert video["effective_parameters"]["resolution"] == "480p"
    assert video["capabilities"]["duration"]["enum"] == ["5", "10"]
    assert video["provider_metrics"] == {"source": "unavailable"}


async def test_comparison_can_reach_models_after_twenty_and_filter(tmp_path):
    api = ComparisonAPI()
    async with httpx.AsyncClient(transport=httpx.MockTransport(api)) as http:
        result = await make_service(tmp_path, http).compare_models(
            "edit_image", image_url="https://example.com/photo.png", query="fixture", cursor=21
        )
    assert result["models"][0]["model"] == "fixture/m21"
    assert result["next_cursor"] is None and result["catalog_count"] == 25
    assert api.calls[0].url.params["q"] == "fixture"
    assert api.calls[0].url.params["taskType"] == "Image to Image"
    assert all(r.url.host == "api.kie.ai" for r in api.calls)


@pytest.mark.parametrize(
    "cursor,limit", [(-1, 5), (0, 0), (0, -1), (True, 5), (0, True), (0, 2.5), (0.5, 5)]
)
async def test_invalid_comparison_page_fails_before_metadata(tmp_path, cursor, limit):
    api = ComparisonAPI()
    async with httpx.AsyncClient(transport=httpx.MockTransport(api)) as http:
        with pytest.raises(GuardError):
            await make_service(tmp_path, http).compare_models(
                "generate_image", cursor=cursor, limit=limit
            )
    assert not api.calls


@pytest.mark.parametrize(
    "requested_limit,expected_page_sizes,expected_cursors",
    [
        (11, [11, 11, 3], [0, 11, 22]),
        (20, [20, 5], [0, 20]),
        (100, [100, 25], [0, 100]),
        (1000, [100, 25], [0, 100]),
    ],
)
async def test_larger_comparison_pages_without_skipping_models(
    tmp_path, requested_limit, expected_page_sizes, expected_cursors
):
    model_count = sum(expected_page_sizes)
    api = ComparisonAPI(model_count=model_count)
    async with httpx.AsyncClient(transport=httpx.MockTransport(api)) as http:
        service = make_service(tmp_path, http)
        pages = []
        cursor = 0
        while cursor is not None:
            page = await service.compare_models(
                "edit_image", cursor=cursor, limit=requested_limit
            )
            pages.append(page)
            cursor = page["next_cursor"]
    assert [len(page["models"]) for page in pages] == expected_page_sizes
    assert [page["cursor"] for page in pages] == expected_cursors
    assert [row["model"] for page in pages for row in page["models"]] == [
        f"fixture/m{i}" for i in range(model_count)
    ]
    for page in pages:
        assert page["requested_limit"] == requested_limit
        assert page["effective_limit"] == (100 if requested_limit > 100 else requested_limit)
        assert bool(page["pagination_message_ru"]) == (requested_limit > 100)
        assert not page["reservation_created"] and not page["media_uploaded"]
    assert all(request.method == "GET" for request in api.calls)
    assert not (tmp_path / "usage.db").exists()


async def test_auto_selection_is_explicit_and_ignores_unknown_price(tmp_path, monkeypatch):
    from kie_mcp import service as module

    async def public(host):
        return ["8.8.8.8"]

    monkeypatch.setattr(module, "resolve_public", public)
    api = ComparisonAPI()
    async with httpx.AsyncClient(transport=httpx.MockTransport(api)) as http:
        result = await make_service(tmp_path, http).friendly(
            "edit_image", image_url=URL, auto_select=True
        )
    assert result["selected_model"] == "fixture/m1"
    assert (
        result["reservation_created"] and result["selection_scope"] == "first_20_catalog_candidates"
    )


async def test_each_comparison_refreshes_catalog_schema_and_price(tmp_path):
    api = ComparisonAPI()
    current = {"version": 1}

    def live(request):
        response = api(request)
        payload = response.json()
        if request.url.path == "/api/v1/models":
            payload["data"]["models"] = [
                {"model": "fixture/m1", "title": f"Live version {current['version']}"}
            ]
        elif request.url.path.endswith("/price"):
            payload["data"]["pricingDesc"] = (
                "Each task costs 10 credits (0.05 USD)."
                if current["version"] == 1
                else "Each task costs 20 credits (0.10 USD)."
            )
        elif request.url.path.endswith("/schema"):
            schema = payload["data"]["openapi"]["paths"]["/api/v1/jobs/createTask"]["post"][
                "requestBody"
            ]["content"]["application/json"]["schema"]
            schema["properties"]["input"]["properties"]["output_format"] = {
                "type": "string",
                "enum": ["png"] if current["version"] == 1 else ["webp"],
            }
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(live)) as http:
        service = make_service(tmp_path, http)
        first = await service.compare_models("edit_image", image_url=URL)
        current["version"] = 2
        second = await service.compare_models("edit_image", image_url=URL)
    assert first["models"][0]["title"] == "Live version 1"
    assert second["models"][0]["title"] == "Live version 2"
    assert first["models"][0]["estimated_cost_usd"] == 0.05
    assert second["models"][0]["estimated_cost_usd"] == 0.1
    assert first["models"][0]["capabilities"]["output_format"]["enum"] == ["png"]
    assert second["models"][0]["capabilities"]["output_format"]["enum"] == ["webp"]
    assert len(api.calls) == 6 and not (tmp_path / "usage.db").exists()
