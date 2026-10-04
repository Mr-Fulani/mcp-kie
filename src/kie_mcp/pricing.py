"""Reviewed live prose tariffs for a small set of personal-use media contracts.

Numbers come from current metadata, never a cached price or global credit/USD rate.
Full descriptions and permitted input conditions must match; new prose fails closed.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal

from .ledger import money

NUMBER = r"\d+(?:\.\d+)?"
DISCOUNT = (
    rf"(?:\nHigh-tier top-ups \(\+10% bonus\) bring effective pricing down to "
    rf"(?:~|≈ )?(?:US )?\${NUMBER}(?:/s)?(?: per (?:output image|image|upscale))?"
    rf"(?: at (?:480p|720p|1080p))?"
    rf"(?:, (?:~|≈ )?\${NUMBER}/s at 720p, and (?:~|≈ )?\${NUMBER}/s at 1080p)?\.)?"
)
IMAGE_PATTERNS = {
    "google/nano-banana": (
        rf"Nano Banana API costs (?P<credits>{NUMBER}) credits per image "
        rf"\(~\$(?P<usd>{NUMBER})\)\."
    ),
    "google/nano-banana-edit": (
        rf"Nano Banana API costs (?P<credits>{NUMBER}) credits per image "
        rf"\(~\$(?P<usd>{NUMBER})\)\."
    ),
    "recraft/remove-background": (
        rf"Kie\.ai Recraft Remove-Background: (?P<credits>{NUMBER}) credits? "
        rf"\(\$(?P<usd>{NUMBER})\) per output image\."
    ),
    "recraft/crisp-upscale": (
        rf"Recraft Crisp Upscale: (?P<credits>{NUMBER}) credits per upscale "
        rf"\(~US \$(?P<usd>{NUMBER})\)\."
    ),
    "z-image": (
        rf"flat (?P<credits>{NUMBER}) Kie credits per image "
        rf"\(≈ \$(?P<usd>{NUMBER})\) — simple, all-inclusive pricing\."
    ),
}
VIDEO_MODELS = {"bytedance/v1-lite-text-to-video", "bytedance/v1-lite-image-to-video"}
VIDEO_PATTERN = (
    rf"For Seedance V1 Lite, generating 1 second of video costs about "
    rf"(?P<c480>{NUMBER}) credits \(\$(?P<u480>{NUMBER})\) at 480p, "
    rf"(?P<c720>{NUMBER}) credits \(\$(?P<u720>{NUMBER})\) at 720p, and "
    rf"(?P<c1080>{NUMBER}) credits \(\$(?P<u1080>{NUMBER})\) at 1080p\."
)
MINI_PATTERN = (
    rf"480p — (?P<cv480>{NUMBER}) credits/s \(\$(?P<uv480>{NUMBER})/s, with video\) "
    rf"\| (?P<c480>{NUMBER}) credits/s \(\$(?P<u480>{NUMBER})/s, no video\)\n"
    rf"720p — (?P<cv720>{NUMBER}) credits/s \(\$(?P<uv720>{NUMBER})/s, with video\) "
    rf"\| (?P<c720>{NUMBER}) credits/s \(\$(?P<u720>{NUMBER})/s, no video\)\n\n"
    r"🔸Note🔸: “With video input” has a lower unit price due to a different calculation "
    r"method: No video = Price × Output;  With video = Price × \(Input \+ Output\)\n\n"
    r"High-tier top-ups \(\+10% bonus\) bring effective pricing down to ~90% of the "
    r"above price\n\n🎉 Limited-time discount: Seedance 2\.0 Mini is now available at a "
    r"reduced price until October 7, 06:00 \(UTC\)\."
)
# Reviewed promotion from the 2026-10-04 live catalog. Stale prose must not extend it.
MINI_PROMOTION_END = datetime(2026, 10, 7, 6, tzinfo=UTC)


def reviewed_tariff(
    model: str, input_data: dict, description: str, *, now: datetime | None = None
) -> dict | None:
    if model in IMAGE_PATTERNS:
        if model.startswith("recraft/"):
            allowed = {"image"}
            if not isinstance(input_data.get("image"), str) or not input_data["image"]:
                return None
        else:
            allowed = {"prompt", "aspect_ratio", "nsfw_checker"}
            if not isinstance(input_data.get("prompt"), str) or not input_data["prompt"]:
                return None
            if model.startswith("google/"):
                allowed.add("output_format")
                if input_data.get("output_format", "png") not in {"png", "jpeg"}:
                    return None
            if model.endswith("-edit"):
                allowed.add("image_urls")
                images = input_data.get("image_urls")
                if (
                    not isinstance(images, list)
                    or len(images) != 1
                    or not isinstance(images[0], str)
                ):
                    return None
        if not set(input_data).issubset(allowed):
            return None
        match = re.fullmatch(IMAGE_PATTERNS[model] + DISCOUNT, description.strip())
        if not match:
            return None
        usd, credits = Decimal(match["usd"]), Decimal(match["credits"])
        conditions = {"output_count": 1}
    elif model == "bytedance/seedance-2-mini":
        allowed = {
            "prompt",
            "duration",
            "resolution",
            "aspect_ratio",
            "generate_audio",
            "nsfw_checker",
            "first_frame_url",
        }
        duration, resolution = input_data.get("duration"), input_data.get("resolution")
        if (
            (now or datetime.now(UTC)) >= MINI_PROMOTION_END
            or not set(input_data).issubset(allowed)
            or type(duration) is not int
            or not 4 <= duration <= 15
            or resolution not in {"480p", "720p"}
            or input_data.get("generate_audio") is not False
            or not isinstance(input_data.get("prompt"), str)
            or not input_data["prompt"]
        ):
            return None
        if "first_frame_url" in input_data and (
            not isinstance(input_data["first_frame_url"], str) or not input_data["first_frame_url"]
        ):
            return None
        match = re.fullmatch(MINI_PATTERN, description.strip())
        if not match:
            return None
        suffix = resolution[:-1]
        # Input video changes the billing duration; those fields are deliberately rejected.
        usd = Decimal(match[f"u{suffix}"]) * duration
        credits = Decimal(match[f"c{suffix}"]) * duration
        conditions = {
            "duration_seconds": duration,
            "resolution": resolution,
            "output_count": 1,
            "video_input": False,
            "generate_audio": False,
            "tariff_valid_until": MINI_PROMOTION_END.isoformat(),
        }
    elif model in VIDEO_MODELS:
        allowed = {
            "prompt",
            "duration",
            "resolution",
            "camera_fixed",
            "seed",
            "enable_safety_checker",
            "nsfw_checker",
        }
        if model.endswith("image-to-video"):
            allowed.add("image_url")
            if not isinstance(input_data.get("image_url"), str) or not input_data["image_url"]:
                return None
        else:
            allowed.add("aspect_ratio")
        duration = input_data.get("duration")
        resolution = input_data.get("resolution")
        if (
            not set(input_data).issubset(allowed)
            or duration not in {"5", "10"}
            or resolution not in {"480p", "720p", "1080p"}
            or not isinstance(input_data.get("prompt"), str)
            or not input_data["prompt"]
        ):
            return None
        match = re.fullmatch(VIDEO_PATTERN + DISCOUNT, description.strip())
        if not match:
            return None
        suffix = resolution[:-1]
        usd = Decimal(match[f"u{suffix}"]) * int(duration)
        credits = Decimal(match[f"c{suffix}"]) * int(duration)
        conditions = {
            "duration_seconds": int(duration),
            "resolution": resolution,
            "output_count": 1,
        }
    else:
        return None
    if usd <= 0 or credits <= 0:
        return None
    return {
        "estimated_cost_usd": money(usd) / 1_000_000,
        "estimated_credits": float(credits),
        "confidence": "estimated",
        "pricing_rule": "reviewed_live_tariff_v1",
        "pricing_conditions": conditions,
    }
