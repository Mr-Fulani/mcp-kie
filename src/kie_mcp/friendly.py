"""Conservative mappings from friendly arguments to declared live schema fields."""

from __future__ import annotations

import copy
import math
import re

from .ledger import GuardError
from .video_support import (
    DURATION_FIELD_NAMES,
    duration_field_name,
    is_duration_field_name,
    selected_video_field,
)

ALIASES = {
    "aspect_ratio": ("aspect_ratio", "aspectRatio"),
    "duration": DURATION_FIELD_NAMES,
    "resolution": ("resolution",),
    "output_format": ("output_format", "outputFormat"),
    "scale": ("scale", "upscale_factor", "scale_factor"),
    "target_resolution": ("target_resolution", "resolution"),
}
IMAGE_FIELDS = {
    "image",
    "images",
    "input_image",
    "image_url",
    "image_urls",
    "input_image_url",
    "input_image_urls",
    "image_input",
    "input_urls",
    "first_frame",
    "first_frame_url",
    "start_image_url",
}

IMAGE_OPERATIONS = {"edit_image", "remove_background", "upscale_image", "product_image_create"}
OPERATIONS = IMAGE_OPERATIONS | {"generate_image", "generate_video"}


def field_value(value, schema: dict):
    """Only lossless type/enum normalization; final JSON Schema validation is mandatory."""
    if schema.get("type") == "string" and type(value) is int:
        value = str(value)
    enum = schema.get("enum", [])
    if isinstance(value, str) and value not in enum:
        matches = [v for v in enum if isinstance(v, str) and v.casefold() == value.casefold()]
        if len(matches) == 1:
            value = matches[0]
    return value


def duration_field_value(value, schema: dict, normalized):
    """Map numeric seconds to the live string format without guessing enum values."""
    if schema.get("type") != "string":
        return normalized
    if isinstance(value, bool):
        return normalized
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return normalized
    if not math.isfinite(seconds):
        return normalized
    enum = schema.get("enum")
    if not isinstance(enum, list):
        return f"{seconds:g}"
    matches = []
    for choice in enum:
        if not isinstance(choice, str):
            continue
        match = re.fullmatch(
            r"\s*(-?\d+(?:\.\d+)?)\s*(?:s|sec(?:onds?)?|secs?)?\s*",
            choice,
            re.IGNORECASE,
        )
        if match and float(match.group(1)) == seconds:
            matches.append(choice)
    return matches[0] if len(matches) == 1 else normalized


def map_input(
    schema: dict,
    parameters: dict,
    prompt: str,
    has_image: bool,
    image_url: str | None,
    operation: str,
    model_input: dict | None = None,
    *,
    has_video: bool = False,
    video_url: str | None = None,
) -> tuple[dict, str | None, dict]:
    fields = schema.get("properties", {})
    if not fields or any(k in schema for k in ("oneOf", "anyOf", "allOf")):
        raise GuardError("Complex input schema requires explicit low-level input")
    if has_image and has_video:
        raise GuardError("Supply one friendly media source at a time")
    data = copy.deepcopy(model_input or {})
    if any(k not in fields for k in data):
        raise GuardError("Model input contains fields absent from the live schema")
    mapping = {}
    for key, value in parameters.items():
        canonical_key = "duration" if is_duration_field_name(key) else key
        aliases = ALIASES.get(canonical_key, (key,))
        targets = [k for k in aliases if k in fields]
        if not targets and canonical_key == "duration":
            inferred = duration_field_name(fields)
            targets = [inferred] if inferred else []
        target = (
            key
            if key in fields and canonical_key == "duration"
            else key
            if key in targets
            else targets[0]
            if len(targets) == 1
            else None
        )
        if target is None:
            raise GuardError("Friendly parameter is unsupported or ambiguous in the live schema")
        if target in data:
            raise GuardError("Supply each model parameter once")
        data[target] = field_value(value, fields[target])
        if canonical_key == "duration":
            data[target] = duration_field_value(value, fields[target], data[target])
        mapping[key] = target
    if "prompt" in fields:
        if "prompt" in data:
            raise GuardError("Use the friendly prompt argument")
        data["prompt"] = prompt or {
            "remove_background": "Remove the background. Preserve the subject exactly.",
            "upscale_image": "Upscale and enhance clarity. Preserve all subject details.",
        }.get(operation, "")
    elif prompt:
        raise GuardError("This live model has no prompt field")
    image_field = None
    if has_image:
        candidates = [k for k in fields if k in IMAGE_FIELDS]
        required = [k for k in candidates if k in schema.get("required", [])]
        choices = required or candidates
        if len(choices) != 1:
            raise GuardError("Ambiguous image fields require explicit low-level input")
        image_field = choices[0]
        if image_field in data:
            if image_url is not None:
                raise GuardError("Supply the image source once")
        else:
            url = image_url or "https://tempfile.redpandaai.co/pending-upload"
            data[image_field] = [url] if fields[image_field].get("type") == "array" else url
    if has_video:
        video_field = selected_video_field(schema, model_input)
        if video_field is None:
            raise GuardError("Model has no unambiguous declared video-input field")
        if video_field in data:
            if video_url is not None:
                raise GuardError("Supply the video source once")
        else:
            url = video_url or "https://tempfile.redpandaai.co/pending-upload"
            data[video_field] = [url] if fields[video_field].get("type") == "array" else url
    return data, image_field, mapping
