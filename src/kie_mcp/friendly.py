"""Conservative mappings from friendly arguments to declared live schema fields."""

from __future__ import annotations

import copy

from .ledger import GuardError

ALIASES = {
    "aspect_ratio": ("aspect_ratio", "aspectRatio"),
    "duration": ("duration", "duration_seconds"),
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
    "first_frame",
    "first_frame_url",
    "start_image_url",
}


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


def map_input(
    schema: dict,
    parameters: dict,
    prompt: str,
    has_image: bool,
    image_url: str | None,
    operation: str,
    model_input: dict | None = None,
) -> tuple[dict, str | None, dict]:
    fields = schema.get("properties", {})
    if not fields or any(k in schema for k in ("oneOf", "anyOf", "allOf")):
        raise GuardError("Complex input schema requires explicit low-level input")
    data = copy.deepcopy(model_input or {})
    if any(k not in fields for k in data):
        raise GuardError("Model input contains fields absent from the live schema")
    mapping = {}
    for key, value in parameters.items():
        aliases = ALIASES.get(key, (key,))
        targets = [k for k in aliases if k in fields]
        target = key if key in targets else (targets[0] if len(targets) == 1 else None)
        if target is None:
            raise GuardError("Friendly parameter is unsupported or ambiguous in the live schema")
        if target in data:
            raise GuardError("Supply each model parameter once")
        data[target] = field_value(value, fields[target])
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
            raise GuardError("Use one friendly image source")
        url = image_url or "https://tempfile.redpandaai.co/pending-upload"
        data[image_field] = [url] if fields[image_field].get("type") == "array" else url
    return data, image_field, mapping
