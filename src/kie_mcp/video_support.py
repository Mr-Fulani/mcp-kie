"""Conservative video duration and video-input capability inspection."""

from __future__ import annotations

import math
import re
from typing import Any


DURATION_FIELD_NAMES = (
    "duration",
    "duration_seconds",
    "duration_sec",
    "duration_in_seconds",
    "video_duration",
    "video_duration_seconds",
    "video_duration_sec",
    "output_duration",
    "output_duration_seconds",
    "output_duration_sec",
    "clip_duration",
    "clip_duration_seconds",
    "durationSeconds",
    "durationInSeconds",
    "videoDuration",
    "videoDurationSeconds",
    "outputDuration",
    "outputDurationSeconds",
    "clipDuration",
    "clipDurationSeconds",
)
VIDEO_INPUT_FIELD_PRIORITY = (
    "reference_video_urls",
    "reference_video_url",
    "input_video_urls",
    "input_video_url",
    "video_urls",
    "video_url",
    "reference_videos",
    "input_videos",
    "input_video",
    "reference_video",
    "videos",
    "video",
)

_VIDEO_NOUN = r"(?:video|clip|movie|ролик|видео)"
_VIDEO_INPUT_INTENT = re.compile(
    r"\b(?:video\s*[-–]?\s*to\s*[-–]?\s*video|v2v)\b|"
    r"\b(?:edit|modify|transform|restyle|rework|continue|extend|improve)\s+"
    r"(?:the\s+)?(?:source|input|existing|original|supplied|provided)?\s*(?:video|clip)\b|"
    r"\b(?:source|input|reference|original)\s+(?:video|clip)\b|"
    r"(?:отредактируй|измени|преобразуй|переработай|обработай|улучши|стилизуй|продолжи)\s+"
    r"(?:исходн\w*\s+)?(?:видео|ролик)",
    re.IGNORECASE,
)
_DURATION_UNITS = r"(?:minutes?|mins?|min|seconds?|secs?|sec|минут\w*|мин|секунд\w*|сек|s)"
_DURATION_UNIT = rf"(?P<unit>{_DURATION_UNITS})"
_DURATION_CAPTURE = (
    rf"(?P<amount>\d{{1,5}}(?:[.,]\d+)?)\s*[- ]?\s*{_DURATION_UNIT}\b"
)
_PROMPT_DURATION_RANGE_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        rf"(?<!\d)(?P<start>\d+(?:[.,]\d+)?)\s*(?P<start_unit>{_DURATION_UNITS})?\s*"
        rf"(?:-|–|to)\s*(?P<end>\d+(?:[.,]\d+)?)\s*(?P<unit>{_DURATION_UNITS})\b"
        rf"(?:\s+long)?\s+{_VIDEO_NOUN}\b",
        rf"\b(?:between|from)\s*(?P<start>\d+(?:[.,]\d+)?)\s*"
        rf"(?P<start_unit>{_DURATION_UNITS})?\s*(?:and|to|-)\s*"
        rf"(?P<end>\d+(?:[.,]\d+)?)\s*(?P<unit>{_DURATION_UNITS})\b"
        rf"[^\n;]{{0,32}}\b{_VIDEO_NOUN}\b",
        rf"\b{_VIDEO_NOUN}\b[^\n;]{{0,32}}?\b(?:between|from)\s*"
        rf"(?P<start>\d+(?:[.,]\d+)?)\s*(?P<start_unit>{_DURATION_UNITS})?\s*"
        rf"(?:and|to|-)\s*(?P<end>\d+(?:[.,]\d+)?)\s*"
        rf"(?P<unit>{_DURATION_UNITS})\b",
        rf"\b(?:между|от)\s*(?P<start>\d+(?:[.,]\d+)?)\s*"
        rf"(?P<start_unit>{_DURATION_UNITS})?\s*(?:и|до)\s*"
        rf"(?P<end>\d+(?:[.,]\d+)?)\s*(?P<unit>{_DURATION_UNITS})\b"
        rf"[^\n;]{{0,32}}\b{_VIDEO_NOUN}\b",
        rf"\b{_VIDEO_NOUN}\b[^\n;]{{0,32}}?\b(?:между|от)\s*"
        rf"(?P<start>\d+(?:[.,]\d+)?)\s*(?P<start_unit>{_DURATION_UNITS})?\s*(?:и|до)\s*"
        rf"(?P<end>\d+(?:[.,]\d+)?)\s*(?P<unit>{_DURATION_UNITS})\b",
    )
)
_PROMPT_DURATION_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        rf"(?<!\d){_DURATION_CAPTURE}(?:\s+long)?\s+{_VIDEO_NOUN}\b",
        rf"(?<!\d){_DURATION_CAPTURE}[\w\s,:-]{{0,32}}\b{_VIDEO_NOUN}\b",
        rf"\b{_VIDEO_NOUN}\b[^\n;]{{0,32}}?(?<!\d){_DURATION_CAPTURE}\b",
        rf"\b(?:duration|length|длительность|длительностью|длиной|хронометраж)"
        rf"\b[^\n;0-9]{{0,24}}(?<!\d){_DURATION_CAPTURE}\b",
    )
)

_RANGE_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\[\s*(\d+(?:\.\d+)?)\s*,\s*(\d+(?:\.\d+)?)\s*\]",
        r"\b(?:from|between)\s*(\d+(?:\.\d+)?)\s*(?:s|sec(?:onds?)?)?\s*(?:to|and|-)\s*(\d+(?:\.\d+)?)\s*(?:s|sec(?:onds?)?)\b",
        r"\b(\d+(?:\.\d+)?)\s*(?:s|sec)?\s*-\s*(\d+(?:\.\d+)?)\s*(?:s|sec(?:onds?)?)\b",
        r"\((\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\)",
        r"\b(\d+(?:\.\d+)?)\s*(?:s|sec)?\s*(?:to|-)\s*(\d+(?:\.\d+)?)\b",
    )
)
_DESCRIPTION_VALUES = re.compile(
    r"\b(?:optional|available|valid|supported)\s+(?:duration\s+)?"
    r"(?:values|options)\s*(?:are|:|=)\s*([\d\s,;/andor]+)",
    re.IGNORECASE,
)
_DESCRIPTION_VALUES_DIRECT = re.compile(
    r"\b(?:optional|available|valid|supported)\s+(?:output\s+)?"
    r"(?:durations?|lengths?)\s*(?:are|:|=)\s*([\d\s,;/andor]+)",
    re.IGNORECASE,
)
_VIDEO_TOTAL_LIMIT = re.compile(
    r"total duration[^.\n]{0,80}?(?:not exceed(?:ing)?|<=|at most|up to)\s*"
    r"(\d+(?:\.\d+)?)\s*(?:s|sec(?:onds?)?)?",
    re.IGNORECASE,
)
_DESCRIPTION_MAXIMUM = re.compile(
    r"\b(?:maximum|max(?:imum)?(?:\s+of)?|up to|at most|no more than|"
    r"not exceed(?:ing)?|no longer than|less than or equal to|<=)\s*"
    r"(\d+(?:\.\d+)?)\s*(?:seconds?|secs?|sec|s)\b",
    re.IGNORECASE,
)
_COMBINED_DURATION_LIMITS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"input(?: video)? duration\s*(?:plus|\+|and)\s*output(?: video)? duration"
        r"[^.\n]{0,64}?(?:<=|at most|not exceed(?:ing)?|no more than)\s*"
        r"(\d+(?:\.\d+)?)\s*(?:s|sec(?:onds?)?)?",
        r"(?:combined|total) duration[^.\n]{0,96}?(?:input|source|reference)"
        r"[^.\n]{0,64}?(?:output|generated)[^.\n]{0,64}?"
        r"(?:<=|at most|not exceed(?:ing)?|no more than)\s*"
        r"(\d+(?:\.\d+)?)\s*(?:s|sec(?:onds?)?)?",
        r"(?:input|source|reference)(?: video)?[^.\n]{0,48}?"
        r"(?:plus|\+|and)[^.\n]{0,48}?(?:output|generated)(?: video)?"
        r"[^.\n]{0,64}?(?:total duration|combined duration|<=|at most|not exceed(?:ing)?|no more than)"
        r"[^.\n]{0,32}?(\d+(?:\.\d+)?)\s*(?:s|sec(?:onds?)?)?",
    )
)


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        result = float(value)
        return result if math.isfinite(result) else None
    if isinstance(value, str):
        match = re.fullmatch(
            r"\s*(-?\d+(?:\.\d+)?)\s*(?:s|sec(?:onds?)?|secs?)?\s*", value, re.I
        )
        if match:
            try:
                result = float(match.group(1))
            except ValueError:
                return None
            return result if math.isfinite(result) else None
    return None


def _normalized_field_name(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower().replace("-", "_")


def is_duration_field_name(name: str) -> bool:
    """Recognize output-duration names without mistaking source duration for output."""
    normalized = _normalized_field_name(name)
    tokens = set(normalized.split("_"))
    if tokens.intersection(
        {
            "input",
            "source",
            "reference",
            "original",
            "unit",
            "mode",
            "format",
            "type",
            "min",
            "minimum",
            "max",
            "maximum",
            "limit",
            "frame",
            "frames",
            "ms",
            "millisecond",
            "milliseconds",
            "minute",
            "minutes",
        }
    ):
        return False
    if "duration" in tokens:
        return True
    if "length" not in tokens:
        return False
    return normalized == "length" or bool(
        tokens.intersection(
            {"video", "clip", "output", "target", "generation", "seconds", "second", "sec"}
        )
    )


def duration_field_name(properties: dict) -> str | None:
    """Find a declared output-duration field, including common provider aliases."""
    for name in DURATION_FIELD_NAMES:
        if isinstance(properties.get(name), dict):
            return name
    candidates = []
    for name, prop in properties.items():
        if not isinstance(name, str) or not is_duration_field_name(name) or not isinstance(prop, dict):
            continue
        enum = prop.get("enum")
        numeric_enum = isinstance(enum, list) and any(
            _number(value) is not None for value in enum
        )
        description = prop.get("description", "")
        described_duration = isinstance(description, str) and bool(
            re.search(r"\b(?:duration|length)\b", description, re.I)
        )
        if prop.get("type") in {"integer", "number"} or numeric_enum or described_duration:
            candidates.append(name)
    return candidates[0] if len(candidates) == 1 else None


def _duration_field(properties: dict) -> tuple[str | None, dict]:
    field = duration_field_name(properties)
    return (field, properties[field]) if field else (None, {})


def looks_like_video_input_field(name: str, prop: dict | None = None) -> bool:
    """Recognize declared video source fields while excluding output controls."""
    normalized = _normalized_field_name(name)
    if "video" not in normalized:
        return False
    if any(token in normalized for token in ("duration", "resolution", "format", "fps", "quality")):
        return False
    if any(
        token in normalized.split("_")
        for token in (
            "output",
            "result",
            "generated",
            "render",
            "rendered",
            "export",
            "final",
            "response",
            "preview",
            "thumbnail",
        )
    ):
        return False
    if isinstance(prop, dict):
        description = prop.get("description", "")
        if isinstance(description, str) and re.search(
            r"\b(?:output|result|generated|rendered)\s+(?:video|clip|media|url)\b",
            description,
            re.I,
        ):
            return False
    if normalized in VIDEO_INPUT_FIELD_PRIORITY:
        return True
    if not isinstance(prop, dict):
        return any(token in normalized for token in ("url", "input", "reference", "source"))
    prop_type = prop.get("type")
    items = prop.get("items")
    is_uri = prop.get("format") == "uri" or (
        prop_type == "array" and isinstance(items, dict) and items.get("format") == "uri"
    )
    description = prop.get("description", "")
    description_mentions_input = isinstance(description, str) and bool(
        re.search(r"\b(?:input|reference|source|video urls?)\b", description, re.I)
    )
    return prop_type in {"string", "array"} and (
        is_uri
        or any(token in normalized for token in ("url", "input", "reference", "source"))
        or description_mentions_input
    )


def video_input_fields(schema: dict) -> list[str]:
    properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
    found = [
        name
        for name, prop in properties.items()
        if looks_like_video_input_field(name, prop)
    ]
    priorities = {name: index for index, name in enumerate(VIDEO_INPUT_FIELD_PRIORITY)}
    return sorted(found, key=lambda name: (priorities.get(name, len(priorities)), name))


def has_video_input_payload(value: Any) -> bool:
    if isinstance(value, dict):
        return any(
            looks_like_video_input_field(name) or has_video_input_payload(nested)
            for name, nested in value.items()
        )
    if isinstance(value, list):
        return any(has_video_input_payload(item) for item in value)
    return False


def selected_video_field(schema: dict, model_input: dict | None = None) -> str | None:
    properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
    supplied = [
        name
        for name in (model_input or {})
        if name in properties and looks_like_video_input_field(name, properties[name])
    ]
    if len(supplied) == 1:
        return supplied[0]
    if len(supplied) > 1:
        return None
    choices = video_input_fields(schema)
    required = [name for name in choices if name in schema.get("required", [])]
    return (required or choices or [None])[0]


def parse_prompt_duration(prompt: str) -> dict:
    """Extract explicit video durations expressed in seconds or minutes."""
    if not isinstance(prompt, str) or not prompt.strip():
        return {"status": "not_found", "seconds": None, "values": []}
    range_values: set[int | float] = set()
    for pattern in _PROMPT_DURATION_RANGE_PATTERNS:
        for match in pattern.finditer(prompt):
            end_unit = match.group("unit").lower()
            start_unit = (match.group("start_unit") or end_unit).lower()
            for group, unit in (("start", start_unit), ("end", end_unit)):
                factor = 60 if unit.startswith(("min", "мин")) else 1
                value = float(match.group(group).replace(",", ".")) * factor
                if value > 0:
                    range_values.add(int(value) if value.is_integer() else value)
    if range_values:
        values = sorted(range_values)
        return {"status": "ambiguous", "seconds": None, "values": values}
    found: set[int | float] = set()
    for pattern in _PROMPT_DURATION_PATTERNS:
        for match in pattern.finditer(prompt):
            amount = float(match.group("amount").replace(",", "."))
            unit = match.group("unit").lower()
            seconds = amount * 60 if unit.startswith(("min", "мин")) else amount
            if seconds > 0:
                found.add(int(seconds) if seconds.is_integer() else seconds)
    values = sorted(found)
    if not values:
        return {"status": "not_found", "seconds": None, "values": []}
    if len(values) > 1:
        return {"status": "ambiguous", "seconds": None, "values": values}
    return {"status": "parsed", "seconds": values[0], "values": values}


def prompt_requests_video_input(prompt: str) -> bool:
    """Detect an explicit Video-to-Video instruction when no file was attached yet."""
    return bool(isinstance(prompt, str) and _VIDEO_INPUT_INTENT.search(prompt))


def normalize_duration_request(
    parameters: dict | None, prompt: str, model_input: dict | None = None
) -> tuple[dict, dict]:
    """Use one explicit duration argument or infer one unambiguous prompt duration."""
    result = dict(parameters or {})
    low_level = model_input or {}
    parameter_name = next((name for name in result if is_duration_field_name(name)), None)
    model_input_name = next((name for name in low_level if is_duration_field_name(name)), None)
    inferred = parse_prompt_duration(prompt)
    if parameter_name and model_input_name:
        return result, {
            "status": "conflict",
            "seconds": None,
            "source": None,
            "values": inferred["values"],
            "reason": "Duration was supplied in both parameters and model_input.",
        }
    explicit_name = parameter_name or model_input_name
    explicit_raw = (
        result.get(parameter_name)
        if parameter_name
        else low_level.get(model_input_name)
        if model_input_name
        else None
    )
    explicit = _number(explicit_raw) if explicit_name else None
    intent = {
        "status": ("explicit" if explicit is not None else "invalid")
        if explicit_name
        else inferred["status"],
        "seconds": explicit if explicit_name else inferred["seconds"],
        "source": (
            "parameter"
            if parameter_name
            else "model_input"
            if model_input_name
            else "prompt"
            if inferred["status"] == "parsed"
            else None
        ),
        "values": inferred["values"],
    }
    if explicit_name and inferred["status"] == "parsed" and explicit != inferred["seconds"]:
        intent.update(status="conflict", seconds=None)
    elif explicit_name and inferred["status"] == "ambiguous" and explicit not in inferred["values"]:
        intent.update(status="conflict", seconds=None)
    elif not explicit_name and inferred["status"] == "parsed":
        result["duration"] = inferred["seconds"]
    return result, intent


def _description_ranges(description: str) -> list[tuple[float, float]]:
    normalized = description.replace("–", "-").replace("—", "-").replace("−", "-")
    ranges: set[tuple[float, float]] = set()
    for pattern in _RANGE_PATTERNS:
        for match in pattern.finditer(normalized):
            low, high = float(match.group(1)), float(match.group(2))
            if 0 < low <= high <= 3600:
                ranges.add((low, high))
    min_match = re.search(r"\b(?:min(?:imum)?)\s*:?\s*(\d+(?:\.\d+)?)", normalized, re.I)
    max_match = re.search(r"\b(?:max(?:imum)?)\s*:?\s*(\d+(?:\.\d+)?)", normalized, re.I)
    if min_match and max_match:
        low, high = float(min_match.group(1)), float(max_match.group(1))
        if 0 < low <= high <= 3600:
            ranges.add((low, high))
    return sorted(ranges)


def _description_values(description: str) -> list[float]:
    match = _DESCRIPTION_VALUES.search(description) or _DESCRIPTION_VALUES_DIRECT.search(
        description
    )
    if not match:
        return []
    values = [float(item) for item in re.findall(r"(?<![\w.])-?\d+(?:\.\d+)?", match.group(1))]
    return sorted(set(value for value in values if 0 < value <= 3600))


def _description_maximum(description: str) -> float | None:
    # A source-video-only cap is not an output-duration guarantee.
    if re.search(
        r"\b(?:input|source|reference)\s+(?:video\s+)?(?:duration|length)\b",
        description,
        re.I,
    ) and not re.search(r"\b(?:output|generated)\s+(?:video\s+)?(?:duration|length)\b", description, re.I):
        return None
    match = _DESCRIPTION_MAXIMUM.search(description)
    return float(match.group(1)) if match else None


def _description_combined_limit(description: str) -> float | None:
    normalized = description.replace("≤", "<=").replace("–", "-").replace("—", "-")
    values = [
        float(match.group(1))
        for pattern in _COMBINED_DURATION_LIMITS
        if (match := pattern.search(normalized))
    ]
    return min(values) if values else None


def video_input_constraints(schema: dict) -> dict:
    fields = video_input_fields(schema)
    properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
    details = []
    for name in fields:
        prop = properties[name]
        description = prop.get("description", "")
        max_total = None
        if isinstance(description, str):
            match = _VIDEO_TOTAL_LIMIT.search(
                description.replace("≤", "<=").replace("–", "-").replace("—", "-")
            )
            if match:
                max_total = float(match.group(1))
        details.append(
            {
                "field": name,
                "type": prop.get("type"),
                "max_items": prop.get("maxItems"),
                "max_total_duration_seconds": max_total,
                "combined_max_input_output_duration_seconds": (
                    _description_combined_limit(description)
                    if isinstance(description, str)
                    else None
                ),
                "description": description or None,
            }
        )
    return {"supported": bool(fields), "fields": details}


def duration_support(
    schema: dict,
    requested_seconds: Any,
    *,
    has_video_input: bool = False,
    input_video_duration_seconds: Any = None,
    resolution: str | None = None,
) -> dict:
    """Return supported/unsupported/uncertain using machine constraints and explicit prose."""
    requested = _number(requested_seconds)
    properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
    field, prop = _duration_field(properties)
    description = prop.get("description", "")
    description = description if isinstance(description, str) else ""
    video_descriptions = [
        item.get("description", "")
        for name, item in properties.items()
        if name in video_input_fields(schema)
        and isinstance(item.get("description", ""), str)
    ]
    constraint_descriptions = [description, *video_descriptions]
    normalized_descriptions = [
        value.replace("≤", "<=").replace("–", "-").replace("—", "-")
        for value in constraint_descriptions
    ]
    combined_limits = [
        limit
        for text in normalized_descriptions
        if (limit := _description_combined_limit(text)) is not None
    ]
    combined_limit = min(combined_limits) if combined_limits else None
    input_limits = []
    input_limit_fields = []
    for name in video_input_fields(schema):
        item_description = properties[name].get("description", "")
        if not isinstance(item_description, str):
            continue
        match = _VIDEO_TOTAL_LIMIT.search(
            item_description.replace("≤", "<=").replace("–", "-").replace("—", "-")
        )
        if match:
            input_limits.append(float(match.group(1)))
            input_limit_fields.append(name)
    input_limit = min(input_limits) if input_limits else None
    input_duration = _number(input_video_duration_seconds)
    if has_video_input and input_limit is not None and input_duration is not None:
        if input_duration > input_limit:
            return {
                "status": "unsupported",
                "field": input_limit_fields[0] if input_limit_fields else None,
                "source": "provider_description",
                "maximum_input_video_duration_seconds": input_limit,
                "input_video_duration_seconds": input_duration,
                "reason": "Input-video duration exceeds the provider's input limit.",
            }
    if requested is None:
        if has_video_input and input_limit is not None and input_duration is None:
            return {
                "status": "uncertain",
                "field": input_limit_fields[0] if input_limit_fields else None,
                "source": "provider_description",
                "maximum_input_video_duration_seconds": input_limit,
                "reason": "Input-video duration is needed to check the provider's input-video limit.",
            }
        if has_video_input and combined_limit is not None:
            return {
                "status": "uncertain",
                "field": field,
                "source": "provider_description",
                "combined_max_seconds": combined_limit,
                "reason": (
                    "Input-video duration is needed to check the provider's combined input/output limit."
                    if input_duration is None
                    else "Output duration is not specified, so the provider's combined limit cannot be checked."
                ),
            }
        return {"status": "unspecified", "source": None, "reason": None}
    if field is None:
        return {
            "status": "uncertain",
            "source": None,
            "reason": "The live schema has no declared output-duration field.",
        }
    if requested == -1:
        if has_video_input and combined_limit is not None:
            return {
                "status": "uncertain",
                "field": field,
                "source": "provider_description",
                "combined_max_seconds": combined_limit,
                "input_video_duration_seconds": input_duration,
                "reason": (
                    "Input-video duration is needed to check the provider's combined input/output limit."
                    if input_duration is None
                    else "Automatic output duration cannot be checked against the provider's combined limit."
                ),
            }
        if has_video_input and input_limit is not None and input_duration is None:
            return {
                "status": "uncertain",
                "field": input_limit_fields[0] if input_limit_fields else field,
                "source": "provider_description",
                "maximum_input_video_duration_seconds": input_limit,
                "reason": "Input-video duration is needed to check the provider's input-video limit.",
            }
        return {
            "status": "automatic",
            "field": field,
            "source": "schema_value",
            "reason": "The schema accepted the -1 duration sentinel; exact output length is not guaranteed.",
        }

    sources: list[str] = []
    allowed_values: list[float] | None = None
    enum = prop.get("enum")
    if isinstance(enum, list):
        numeric_enum = sorted(set(number for item in enum if (number := _number(item)) is not None and number > 0))
        if numeric_enum:
            allowed_values = numeric_enum
            sources.append("schema_enum")
            if requested not in numeric_enum:
                return {
                    "status": "unsupported",
                    "field": field,
                    "source": "schema_enum",
                    "allowed_values_seconds": numeric_enum,
                    "reason": "Requested duration is outside the live schema enum.",
                }

    lower = _number(prop.get("minimum"))
    upper = _number(prop.get("maximum"))
    exclusive_lower = _number(prop.get("exclusiveMinimum"))
    exclusive_upper = _number(prop.get("exclusiveMaximum"))
    step = _number(prop.get("multipleOf"))
    if (
        lower is not None
        or upper is not None
        or exclusive_lower is not None
        or exclusive_upper is not None
        or step is not None
    ):
        sources.append("schema_range")
        if (
            (lower is not None and requested < lower)
            or (upper is not None and requested > upper)
            or (exclusive_lower is not None and requested <= exclusive_lower)
            or (exclusive_upper is not None and requested >= exclusive_upper)
        ):
            return {
                "status": "unsupported",
                "field": field,
                "source": "schema_range",
                "minimum_seconds": lower if lower is not None else exclusive_lower,
                "maximum_seconds": upper if upper is not None else exclusive_upper,
                "reason": "Requested duration is outside the live schema range.",
            }
        if step and not math.isclose(requested / step, round(requested / step)):
            return {
                "status": "unsupported",
                "field": field,
                "source": "schema_range",
                "reason": "Requested duration does not match the live schema step.",
            }

    description_values = _description_values(description)
    description_ranges = _description_ranges(description)
    description_maximum = _description_maximum(description)
    if description_values:
        sources.append("provider_description")
        if requested not in description_values:
            return {
                "status": "unsupported",
                "field": field,
                "source": "provider_description",
                "allowed_values_seconds": description_values,
                "reason": "Requested duration is outside the values described by the provider.",
            }
    if description_ranges:
        distinct_ranges = set(description_ranges)
        if len(distinct_ranges) == 1:
            low, high = next(iter(distinct_ranges))
            sources.append("provider_description")
            if requested < low or requested > high:
                return {
                    "status": "unsupported",
                    "field": field,
                    "source": "provider_description",
                    "minimum_seconds": low,
                    "maximum_seconds": high,
                    "reason": "Requested duration is outside the provider-described range.",
                }
        elif not (lower is not None and upper is not None):
            return {
                "status": "uncertain",
                "field": field,
                "source": "provider_description",
                "reason": "The provider description contains conflicting duration ranges.",
            }
    if description_maximum is not None:
        if requested > description_maximum:
            return {
                "status": "unsupported",
                "field": field,
                "source": "provider_description",
                "maximum_seconds": description_maximum,
                "reason": "Requested duration exceeds the maximum stated by the provider.",
            }
        if requested == description_maximum or sources:
            sources.append("provider_description")

    # Cross-field limits in prose are not represented by JSON Schema conditionals.
    if has_video_input and any(
        re.search(
            r"(?:duration(?: parameter)?|output duration)[^.]*"
            r"(?:ignored|will not take effect)",
            text,
            re.IGNORECASE,
        )
        for text in normalized_descriptions
    ):
        return {
            "status": "unsupported",
            "field": field,
            "source": "provider_description",
            "reason": "The provider says output duration is chosen automatically when video input is used.",
        }
    if has_video_input and combined_limit is not None:
        if input_duration is None:
            if requested >= combined_limit:
                return {
                    "status": "unsupported",
                    "field": field,
                    "source": "provider_description",
                    "combined_max_seconds": combined_limit,
                    "reason": "A video input plus this output duration would exceed the provider's combined limit.",
                }
            return {
                "status": "uncertain",
                "field": field,
                "source": "provider_description",
                "combined_max_seconds": combined_limit,
                "reason": "Input-video duration is needed to check the provider's combined input/output limit.",
            }
        if input_duration <= 0 or input_duration + requested > combined_limit:
            return {
                "status": "unsupported",
                "field": field,
                "source": "provider_description",
                "combined_max_seconds": combined_limit,
                "input_video_duration_seconds": input_duration,
                "reason": "Input-video duration plus requested output exceeds the provider's combined limit.",
            }

    if has_video_input and input_limit is not None and input_duration is None:
        return {
            "status": "uncertain",
            "field": input_limit_fields[0] if input_limit_fields else field,
            "source": "provider_description",
            "maximum_input_video_duration_seconds": input_limit,
            "reason": "Input-video duration is needed to check the provider's input-video limit.",
        }

    if description_maximum is not None and requested < description_maximum and not sources:
        return {
            "status": "uncertain",
            "field": field,
            "source": "provider_description",
            "maximum_seconds": description_maximum,
            "reason": "The provider gives a maximum duration but does not publish the supported values or minimum.",
        }
    if not sources:
        return {
            "status": "uncertain",
            "field": field,
            "source": None,
            "reason": "The live schema does not publish machine-readable or recognizable duration limits.",
        }

    source = "+".join(dict.fromkeys(sources))
    return {
        "status": "supported",
        "field": field,
        "source": source,
        "allowed_values_seconds": allowed_values,
        "minimum_seconds": lower if lower is not None else (description_ranges[0][0] if description_ranges else None),
        "maximum_seconds": upper if upper is not None else (description_ranges[0][1] if description_ranges else description_maximum),
        "input_video_duration_seconds": _number(input_video_duration_seconds),
        "reason": None,
    }
