"""Live model contracts and conservative, operation-specific price resolution."""

from __future__ import annotations

import copy
import json
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from jsonschema import Draft202012Validator

from .ledger import GuardError, digest, money
from .pricing import reviewed_tariff

MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*(?:/[A-Za-z0-9][A-Za-z0-9_.-]*)?")


def model_path(model: str, suffix: str) -> str:
    if not MODEL_ID.fullmatch(model) or suffix not in {"schema", "price", "success-rate"}:
        raise GuardError("Invalid model identifier or metadata operation")
    return f"/api/v1/models/{model}/{suffix}"


def inline_refs(value: Any, document: dict, stack: tuple[str, ...] = (), depth=0) -> Any:
    if depth > 50:
        raise GuardError("Schema nesting limit exceeded")
    if isinstance(value, list):
        return [inline_refs(v, document, stack, depth + 1) for v in value]
    if not isinstance(value, dict):
        return value
    if "$ref" in value:
        ref = value["$ref"]
        if not isinstance(ref, str) or not ref.startswith("#/") or ref in stack:
            raise GuardError("External or recursive schema references are unsupported")
        target = document
        try:
            for token in ref[2:].split("/"):
                key = unquote(token).replace("~1", "/").replace("~0", "~")
                target = target[key]
        except (KeyError, TypeError):
            raise GuardError("Unresolved local schema reference") from None
        return inline_refs(
            {**target, **{k: v for k, v in value.items() if k != "$ref"}},
            document,
            (*stack, ref),
            depth + 1,
        )
    if "$dynamicRef" in value or "$recursiveRef" in value:
        raise GuardError("Dynamic schema references are unsupported")
    return {k: inline_refs(v, document, stack, depth + 1) for k, v in value.items()}


def resolve_contract(model: str, document: dict | None) -> dict:
    if not isinstance(document, dict):
        raise GuardError("Live model schema is unavailable; no request can be prepared")
    operation = document.get("paths", {}).get("/api/v1/jobs/createTask", {}).get("post")
    if not operation:
        raise GuardError("Only unified asynchronous media models are supported")
    operation = inline_refs(operation, document)
    schema = (
        operation.get("requestBody", {})
        .get("content", {})
        .get("application/json", {})
        .get("schema")
    )
    if not isinstance(schema, dict):
        raise GuardError("Live JSON request schema is unavailable")
    Draft202012Validator.check_schema(schema)
    # Explicit local media policy also applies if provider schema allows more fields.
    return {
        "model": model,
        "endpoint": "/api/v1/jobs/createTask",
        "schema": schema,
        "schema_digest": digest(schema),
    }


def apply_defaults(value: Any, schema: dict) -> Any:
    result = copy.deepcopy(value)
    if isinstance(result, dict):
        properties = schema.get("properties", {})
        for key, prop in properties.items():
            if key not in result and "default" in prop and not prop.get("deprecated", False):
                result[key] = copy.deepcopy(prop["default"])
            if key in result:
                result[key] = apply_defaults(result[key], prop)
    return result


def validated_payload(contract: dict, model: str, input_data: dict) -> dict:
    payload = apply_defaults({"model": model, "input": input_data}, contract["schema"])
    # Callbacks and provider-specific top-level escape hatches are not part of local Phase 1.
    payload = {k: v for k, v in payload.items() if k in {"model", "input"}}
    if payload["model"] != model:
        raise GuardError("Model mismatch")
    errors = list(Draft202012Validator(contract["schema"]).iter_errors(payload))
    if errors:
        # Avoid jsonschema's error message: it embeds the private prompt/input value.
        raise GuardError("Input does not satisfy the live model schema")
    digest(payload)  # Also reject NaN/Infinity and non-JSON values.
    return payload


def price_estimate(model: str, input_data: dict, pricing: dict) -> dict:
    """Do not infer a global USD/credit rate, or guess conditions from free prose."""
    result = {
        "model": model,
        "estimated_cost_usd": None,
        "estimated_credits": None,
        "pricing_source": f"live_kie_metadata:{model_path(model, 'price')}",
        "confidence": "unknown",
        "pricing_description": pricing.get("pricingDesc"),
    }
    description = pricing.get("pricingDesc")
    if not isinstance(description, str):
        return result
    reviewed = reviewed_tariff(model, input_data, description)
    if reviewed:
        return {**result, **reviewed}
    # Only complete, unconditional single-output tariffs in a narrow grammar are accepted.
    pattern = (
        r"(?:Each image|Each generation|Each task) costs "
        r"(?P<credits>\d+(?:\.\d+)?) credits "
        r"\((?:\$(?P<dollar>\d+(?:\.\d+)?)|(?P<usd>\d+(?:\.\d+)?) USD)\)\.?"
    )
    match = re.fullmatch(pattern, description.strip(), re.IGNORECASE)
    # Variable-priced operations require an owner-verified exact-input quote below.
    variables = {
        "duration",
        "resolution",
        "quality",
        "n",
        "num_images",
        "num_outputs",
        "image_size",
        "size",
        "output_count",
        "batch_size",
    }
    neutral_inputs = {"prompt", "negative_prompt", "aspect_ratio", "image_url", "image_urls"}
    if (
        match
        and not variables.intersection(input_data)
        and set(input_data).issubset(neutral_inputs)
    ):
        cost = float(match.group("dollar") or match.group("usd"))
        result.update(
            estimated_cost_usd=cost,
            estimated_credits=float(match.group("credits")),
            confidence="estimated",
        )
    return result


def owner_quote(payload: dict, path: Path | None) -> dict | None:
    """Optional explicit owner authorization for unknown cost, bound to an exact request."""
    if path is None:
        return None
    # This is owner configuration, never a tool argument. Files must be private.
    if path.is_symlink() or path.stat().st_mode & 0o077 or path.stat().st_size > 100_000:
        raise GuardError("Owner quote file must be private, bounded and not a symlink")
    quote = json.loads(path.read_text())
    expected = digest({"operation": "generation", "payload": payload})
    if quote.get("request_digest") != expected or quote.get("expires_at", 0) <= time.time():
        return None
    if not quote.get("approved_by_owner") or not quote.get("pricing_source"):
        return None
    amount = money(quote["max_cost_usd"]) / 1_000_000
    return {
        "model": payload["model"],
        "estimated_cost_usd": amount,
        "estimated_credits": quote.get("estimated_credits"),
        "pricing_source": "owner_verified_quote:" + str(quote["pricing_source"])[:200],
        "confidence": "estimated",
        "owner_approved": True,
    }
