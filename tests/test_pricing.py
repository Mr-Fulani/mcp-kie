import copy
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from kie_mcp.models import apply_defaults, price_estimate
from kie_mcp.pricing import reviewed_tariff

VIDEO = (
    "For Seedance V1 Lite, generating 1 second of video costs about 2 credits ($0.010) "
    "at 480p, 4.5 credits ($0.0225) at 720p, and 10 credits ($0.050) at 1080p."
)
VIDEO_BONUS = (
    "\nHigh-tier top-ups (+10% bonus) bring effective pricing down to ~$0.009/s at 480p, "
    "~$0.020/s at 720p, and ~$0.045/s at 1080p."
)
TARIFFS = {
    "google/nano-banana": "Nano Banana API costs 4 credits per image (~$0.02).",
    "google/nano-banana-edit": "Nano Banana API costs 4 credits per image (~$0.02).",
    "recraft/remove-background": (
        "Kie.ai Recraft Remove-Background: 1 credit ($0.005) per output image."
    ),
    "recraft/crisp-upscale": "Recraft Crisp Upscale: 0.5 credits per upscale (~US $0.0025).",
    "z-image": "flat 0.8 Kie credits per image (≈ $0.004) — simple, all-inclusive pricing.",
}


def estimate(model, data, prose):
    return price_estimate(model, data, {"pricingDesc": prose})


@pytest.mark.parametrize(
    "model", ["bytedance/v1-lite-text-to-video", "bytedance/v1-lite-image-to-video"]
)
@pytest.mark.parametrize("duration", ["5", "10"])
@pytest.mark.parametrize(
    "resolution,usd,credits", [("480p", 0.01, 2), ("720p", 0.0225, 4.5), ("1080p", 0.05, 10)]
)
@pytest.mark.parametrize("bonus", ["", VIDEO_BONUS])
def test_seedance_live_tariff_conditions(model, duration, resolution, usd, credits, bonus):
    data = {"prompt": "Boat", "duration": duration, "resolution": resolution}
    if "image-to-video" in model:
        data["image_url"] = "https://tempfile.redpandaai.co/image.png"
        data["seed"] = -1
    r = estimate(model, data, VIDEO + bonus)
    assert r["confidence"] == "estimated"
    assert r["estimated_cost_usd"] == pytest.approx(usd * int(duration))
    assert r["estimated_credits"] == credits * int(duration)
    assert r["pricing_conditions"]["duration_seconds"] == int(duration)


@pytest.mark.parametrize(
    "model,usd,credits,data,bonus",
    [
        (
            "google/nano-banana",
            0.02,
            4,
            {"prompt": "Boat", "output_format": "png"},
            "\nHigh-tier top-ups (+10% bonus) bring effective pricing down to ~$0.018 per image.",
        ),
        (
            "google/nano-banana-edit",
            0.02,
            4,
            {
                "prompt": "Boat",
                "image_urls": ["https://tempfile.redpandaai.co/a.png"],
                "aspect_ratio": "3:4",
            },
            "",
        ),
        (
            "recraft/remove-background",
            0.005,
            1,
            {"image": "https://tempfile.redpandaai.co/a.png"},
            "\nHigh-tier top-ups (+10% bonus) bring effective pricing down to "
            "~$0.0045 per output image.",
        ),
        (
            "recraft/crisp-upscale",
            0.0025,
            0.5,
            {"image": "https://tempfile.redpandaai.co/a.png"},
            "\nHigh-tier top-ups (+10% bonus) bring effective pricing down to "
            "~US $0.0023 per upscale.",
        ),
        (
            "z-image",
            0.004,
            0.8,
            {"prompt": "Boat", "aspect_ratio": "1:1"},
            "\nHigh-tier top-ups (+10% bonus) bring effective pricing down to ≈ $0.0036 per image.",
        ),
    ],
)
def test_live_image_tariffs_ignore_bonus(model, usd, credits, data, bonus):
    r = estimate(model, data, TARIFFS[model] + bonus)
    assert r["estimated_cost_usd"] == usd and r["estimated_credits"] == credits


@pytest.mark.parametrize(
    "change",
    [
        {"duration": "15"},
        {"resolution": "4K"},
        {"num_outputs": 2},
        {"quality": "pro"},
        {"end_image_url": "https://tempfile.redpandaai.co/end.png"},
        {"input_video": "url"},
    ],
)
def test_unreviewed_video_parameters_block_estimation(change):
    data = {"prompt": "Boat", "duration": "5", "resolution": "480p", **change}
    assert estimate("bytedance/v1-lite-text-to-video", data, VIDEO)["confidence"] == "unknown"


@pytest.mark.parametrize(
    "prose",
    [
        VIDEO + " Extra image surcharge $1.",
        VIDEO + "\nNew policy.",
        VIDEO.replace("costs about", "costs at least"),
        VIDEO.replace("1 second", "1 frame"),
        VIDEO.replace("2 credits", "0 credits"),
    ],
)
def test_unknown_or_changed_prose_fails_closed(prose):
    r = estimate(
        "bytedance/v1-lite-text-to-video",
        {"prompt": "Boat", "duration": "5", "resolution": "480p"},
        prose,
    )
    assert r["confidence"] == "unknown"


def test_updated_live_numbers_not_cached_and_round_up_microdollars():
    prose = VIDEO.replace("$0.010", "$0.01000001")
    r = estimate(
        "bytedance/v1-lite-text-to-video",
        {"prompt": "Boat", "duration": "5", "resolution": "480p"},
        prose,
    )
    assert r["estimated_cost_usd"] == 0.050001
    assert r["estimated_credits"] == 10
    assert estimate("other/video", {"duration": "5"}, VIDEO)["confidence"] == "unknown"


@pytest.mark.parametrize(
    "extra", [{"n": 2}, {"resolution": "4K"}, {"image_size": "3:4"}, {"image_urls": ["a", "b"]}]
)
def test_unreviewed_image_combinations_require_owner_quote(extra):
    data = {"prompt": "Boat", "image_urls": ["https://tempfile.redpandaai.co/a.png"], **extra}
    assert (
        estimate("google/nano-banana-edit", data, TARIFFS["google/nano-banana-edit"])["confidence"]
        == "unknown"
    )


def test_no_implicit_deprecated_default_but_explicit_legacy_value_preserved():
    schema = {
        "properties": {
            "aspect_ratio": {"default": "1:1"},
            "image_size": {"default": "1:1", "deprecated": True},
        }
    }
    before = copy.deepcopy(schema)
    assert apply_defaults({"aspect_ratio": "3:4"}, schema) == {"aspect_ratio": "3:4"}
    assert apply_defaults({"image_size": "3:4"}, schema) == {
        "image_size": "3:4",
        "aspect_ratio": "1:1",
    }
    assert schema == before


MINI_PRICE = json.loads(
    (Path(__file__).parent / "fixtures/seedance-mini-price-2026-10-04.json").read_text()
)["pricingDesc"]
MINI_NOW = datetime(2026, 10, 4, tzinfo=UTC)


@pytest.mark.parametrize("frame", [False, True])
@pytest.mark.parametrize("resolution,usd,credits", [("480p", 0.019, 3.8), ("720p", 0.041, 8.2)])
def test_mini_tariff_without_input_video_from_captured_live_metadata(
    frame, resolution, usd, credits
):
    data = {
        "prompt": "Boat moves",
        "duration": 4,
        "resolution": resolution,
        "generate_audio": False,
    }
    if frame:
        data["first_frame_url"] = "https://tempfile.redpandaai.co/a.png"
    result = reviewed_tariff("bytedance/seedance-2-mini", data, MINI_PRICE, now=MINI_NOW)
    assert result["estimated_cost_usd"] == pytest.approx(usd * 4)
    assert result["estimated_credits"] == pytest.approx(credits * 4)


@pytest.mark.parametrize(
    "extra",
    [
        {"reference_video_urls": ["https://tempfile.redpandaai.co/a.mp4"]},
        {"last_frame_url": "https://tempfile.redpandaai.co/a.png"},
        {"reference_audio_urls": []},
        {"web_search": True},
        {"generate_audio": True},
        {"duration": -1},
        {"duration": 3},
        {"duration": 16},
        {"duration": "4"},
        {"resolution": "1080p"},
    ],
)
def test_mini_unknown_billing_modes_block(extra):
    data = {
        "prompt": "Boat moves",
        "duration": 4,
        "resolution": "480p",
        "generate_audio": False,
        **extra,
    }
    assert reviewed_tariff("bytedance/seedance-2-mini", data, MINI_PRICE, now=MINI_NOW) is None


def test_mini_expired_promotion_or_changed_prose_blocks():
    data = {"prompt": "Boat moves", "duration": 4, "resolution": "480p", "generate_audio": False}
    expired = datetime(2026, 10, 7, 6, tzinfo=UTC)
    assert reviewed_tariff("bytedance/seedance-2-mini", data, MINI_PRICE, now=expired) is None
    assert (
        reviewed_tariff("bytedance/seedance-2-mini", data, MINI_PRICE + " Fee $1.", now=MINI_NOW)
        is None
    )
