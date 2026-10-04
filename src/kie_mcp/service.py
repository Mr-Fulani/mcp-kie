"""Client-agnostic application layer: discovery, immutable approvals, tasks and results."""

from __future__ import annotations

import asyncio
import copy
import time
import uuid
from pathlib import Path

from .client import KieClient
from .comparison import capabilities
from .config import Settings
from .errors import KieAPIError
from .friendly import map_input
from .ledger import GuardError, Ledger, digest
from .models import (
    model_path,
    owner_quote,
    price_estimate,
    resolve_contract,
    validated_payload,
)
from .network import KIE_STORAGE_HOSTS, fetch_bytes, resolve_public, validate_url
from .security import open_upload
from .storage import save_result, validate_result_label


class KieService:
    def __init__(self, settings: Settings, client: KieClient, *, metadata_interval=1.1):
        self.settings = settings
        self.client = client
        self.session = uuid.uuid4().hex
        self.client_name = "stdio-client"
        self.client_version = "unknown"
        self._ledger: Ledger | None = None
        self._metadata_lock = asyncio.Lock()
        self._next_metadata = 0.0
        self.metadata_interval = metadata_interval

    @property
    def ledger(self):
        if self._ledger is None:
            self._ledger = Ledger(self.settings.ledger_path, self.settings.limits)
        return self._ledger

    async def metadata(self, path: str, params=None):
        async with self._metadata_lock:
            await asyncio.sleep(max(0, self._next_metadata - time.monotonic()))
            try:
                payload = await self.client.request("GET", path, params=params)
                data = payload.get("data") if isinstance(payload, dict) else None
                if data is None:
                    raise GuardError("Live KIE metadata is unavailable")
                return data
            finally:
                self._next_metadata = time.monotonic() + self.metadata_interval

    async def search_models(self, query: str = "", task_type: str | None = None):
        params = {"q": query} if query else {}
        if task_type:
            params["taskType"] = task_type
        data = await self.metadata("/api/v1/models", params)
        if not isinstance(data, dict) or not isinstance(data.get("models"), list):
            raise GuardError("Unexpected live model catalog format")
        return data

    async def contract(self, model: str):
        data = await self.metadata(model_path(model, "schema"))
        return resolve_contract(model, data.get("openapi"))

    async def estimate(self, model: str, input_data: dict):
        contract = await self.contract(model)
        return await self.estimate_contract(contract, model, input_data)

    async def estimate_contract(self, contract: dict, model: str, input_data: dict):
        payload = validated_payload(contract, model, input_data)
        pricing = await self.metadata(model_path(model, "price"))
        estimate = price_estimate(model, payload["input"], pricing)
        if estimate["confidence"] == "unknown":
            quote = owner_quote(payload, self.settings.owner_quote_path)
            if quote:
                estimate = quote
        return {
            **estimate,
            "resolved_schema": contract["schema"],
            "schema_digest": contract["schema_digest"],
            "validated_input": payload["input"],
            "endpoint": contract["endpoint"],
            "request_payload": payload,
            "request_digest": digest({"operation": "generation", "payload": payload}),
        }

    async def _validate_media_urls(self, value, key=""):
        if isinstance(value, dict):
            for name, nested in value.items():
                await self._validate_media_urls(nested, name)
        elif isinstance(value, list):
            for nested in value:
                await self._validate_media_urls(nested, key)
        elif isinstance(value, str) and key not in {"prompt", "negative_prompt", "text"}:
            url_field = "url" in key.lower() or key.lower() in {
                "image",
                "images",
                "input_image",
                "first_frame",
                "last_frame",
                "audio",
                "video",
            }
            if url_field or value.startswith(("https://", "http://")):
                # KIE itself resolves generation URLs. An arbitrary remote hostname
                # could rebind after our check, so provider inputs must be hosted by KIE.
                host = validate_url(value, allowed_hosts={"tempfile.redpandaai.co"})
                await resolve_public(host)

    async def prepare(self, model: str, input_data: dict, *, dry_run=False):
        preview = await self.estimate(model, input_data)
        await self._validate_media_urls(preview["validated_input"])
        if dry_run:
            return {**preview, "dry_run": True, "reservation_created": False}
        if preview["confidence"] == "unknown":
            raise GuardError("Unknown pricing: obtain an exact-input owner quote before execution")
        reserved = self.ledger.prepare(
            preview["request_payload"],
            preview["estimated_cost_usd"],
            preview["estimated_credits"],
            preview["pricing_source"],
            self.session,
            client_name=self.client_name,
            client_version=self.client_version,
        )
        return {
            **preview,
            **reserved,
            "dry_run": False,
            "reservation_created": not reserved["duplicate"],
        }

    async def execute(self, approval_id: str, model: str, input_data: dict):
        # Refresh schema and tariff before claiming; never accept client-supplied price or endpoint.
        preview = await self.estimate(model, input_data)
        if preview["confidence"] == "unknown":
            raise GuardError("Pricing is now unknown; execution blocked")
        await self._validate_media_urls(preview["validated_input"])
        # Compare fresh price against the already reserved bound before the atomic claim.
        with self.ledger.connection() as db:
            row = db.execute(
                "SELECT estimated_cost_usd FROM usage WHERE id=?", (approval_id,)
            ).fetchone()
        if row is None or preview["estimated_cost_usd"] > row[0] / 1_000_000:
            raise GuardError("Price exceeds reserved amount; prepare a new approved request")
        claim = self.ledger.claim(approval_id, preview["request_payload"], self.session)
        if not claim["send"]:
            return {**claim, "duplicate": True}
        try:
            payload = await self.client.submit_prepared(preview["request_payload"])
            data = payload.get("data") if isinstance(payload, dict) else None
            task_id = data.get("taskId") if isinstance(data, dict) else None
            if not isinstance(task_id, str) or not task_id:
                self.ledger.submission(approval_id, None)
                raise GuardError(
                    "Submission outcome unknown; reservation retained; do not resubmit"
                )
            self.ledger.submission(approval_id, task_id)
            return {**claim, "status": "submitted", "task_id": task_id, "duplicate": False}
        except KieAPIError as exc:
            definite = {400, 401, 402, 403, 404, 422, 429, 433}
            rejected = exc.status_code in definite or str(exc.api_code) in {
                str(c) for c in definite
            }
            self.ledger.submission(approval_id, None, rejected=rejected)
            raise
        except BaseException:
            # Cancelled process/connection and unknown server responses remain chargeable.
            self.ledger.submission(approval_id, None)
            raise

    async def get_task(self, task_id: str):
        response = await self.client.get_task(task_id)
        data = response.get("data", {})
        if isinstance(data, dict) and data.get("state") in {"success", "fail"}:
            urls = self.result_urls(data)
            self.ledger.reconcile(
                task_id,
                data["state"],
                actual_usd=data.get("costUsd"),
                credits=data.get("creditsConsumed"),
                output_count=len(urls),
            )
        return response

    async def wait(self, task_id: str, timeout: int | None = None):
        deadline = time.monotonic() + min(
            timeout or self.settings.task_timeout, self.settings.task_timeout
        )
        intervals = [2, 3, 5, 8, 10, 15]
        attempt = 0
        while time.monotonic() < deadline:
            payload = await self.get_task(task_id)
            if payload.get("data", {}).get("state") in {"success", "fail"}:
                return payload
            await asyncio.sleep(
                min(intervals[min(attempt, 5)], max(0, deadline - time.monotonic()))
            )
            attempt += 1
        raise GuardError("Task polling timed out; budget liability retained")

    @staticmethod
    def result_urls(data: dict) -> list[str]:
        result = data.get("response") or data.get("resultParsed") or {}
        if not isinstance(result, dict):
            return []
        urls = list(result.get("resultUrls") or [])
        for track in result.get("data") or []:
            if isinstance(track, dict) and track.get("audio_url"):
                urls.append(track["audio_url"])
        return [url for url in urls if isinstance(url, str)]

    async def download(self, task_id: str, index: int = 0, result_label: str | None = None):
        validate_result_label(result_label)
        if self.settings.allowed_download_root is None:
            raise GuardError("Downloads require an owner-configured output root")
        response = await self.get_task(task_id)
        data = response.get("data", {})
        if data.get("state") != "success":
            raise GuardError("Task has not completed successfully")
        urls = self.result_urls(data)
        if not 0 <= index < len(urls):
            raise GuardError("Requested result does not exist")
        content = await fetch_bytes(
            urls[index],
            self.settings.max_download_bytes,
            allowed_hosts=KIE_STORAGE_HOSTS,
        )
        output = save_result(
            self.settings.allowed_download_root,
            task_id,
            content,
            model=data.get("model") or data.get("paramParsed", {}).get("model") or "unknown-model",
            created_at=data.get("createTime"),
            label=result_label,
        )
        return {
            "task_id": task_id,
            "output_path": output,
            "result_url": urls[index],
            "output_folder": str(Path(output).parent),
        }

    async def model_candidates(self, operation: str, has_image: bool, query: str = ""):
        operations = {
            "generate_image",
            "edit_image",
            "generate_video",
            "remove_background",
            "upscale_image",
            "product_image_create",
        }
        if operation not in operations:
            raise GuardError("Unknown friendly operation")
        if operation not in {"generate_image", "generate_video"} and not has_image:
            raise GuardError("This operation requires an input image")
        if operation in {"remove_background", "upscale_image"}:
            return await self.search_models(
                query=query
                or ("remove-background" if operation == "remove_background" else "upscale")
            )
        task_type = (
            ("Image to Video" if has_image else "Text to Video")
            if operation == "generate_video"
            else ("Image to Image" if has_image else "Text to Image")
        )
        return await self.search_models(query=query, task_type=task_type)

    async def compare_models(
        self,
        operation: str,
        prompt: str = "",
        image_path: str | None = None,
        image_url: str | None = None,
        parameters: dict | None = None,
        model_input: dict | None = None,
        *,
        query: str = "",
        cursor: int = 0,
        limit: int = 5,
        include_metrics: bool = False,
    ):
        """Metadata-only comparison: no media fetch/upload, ledger mutation or submission."""
        if cursor < 0 or not 1 <= limit <= 10:
            raise GuardError("Comparison requires cursor >= 0 and limit between 1 and 10")
        if image_path and image_url:
            raise GuardError("Supply one image source")
        if image_path:
            with open_upload(
                image_path, self.settings.allowed_upload_root, self.settings.max_upload_bytes
            ):
                pass
        trusted_url = None
        if image_url and validate_url(image_url) == "tempfile.redpandaai.co":
            trusted_url = image_url
        catalog = await self.model_candidates(operation, bool(image_path or image_url), query)
        entries = catalog["models"]
        rows = []
        for candidate in entries[cursor : cursor + limit]:
            name = candidate["model"]
            row = {
                "model": name,
                "title": candidate.get("title", name),
                "provider": candidate.get("provider"),
                "compatible": False,
                "quality": {
                    "score": None,
                    "source": "provider_catalog",
                    "description": candidate.get("description"),
                },
                "speed": {"expected_seconds": None, "source": "not_verified"},
            }
            try:
                contract = await self.contract(name)
                schema = contract["schema"].get("properties", {}).get("input", {})
                row["capabilities"] = capabilities(schema)
                mapped, image_field, mapping = map_input(
                    schema,
                    parameters or {},
                    prompt,
                    bool(image_path or image_url),
                    trusted_url,
                    operation,
                    model_input,
                )
                preview = await self.estimate_contract(contract, name, mapped)
                row.update(
                    {
                        "compatible": True,
                        "parameter_mapping": mapping,
                        "image_field": image_field,
                        **{
                            key: preview.get(key)
                            for key in (
                                "estimated_cost_usd",
                                "estimated_credits",
                                "confidence",
                                "pricing_source",
                                "pricing_description",
                                "pricing_conditions",
                            )
                        },
                    }
                )
                row["effective_parameters"] = {
                    key: preview["validated_input"].get(info["field"], info.get("default"))
                    for key, info in row["capabilities"].items()
                }
                row["within_task_limit"] = (
                    None
                    if preview["estimated_cost_usd"] is None
                    else preview["estimated_cost_usd"] <= self.settings.limits.task_usd
                )
                row["pricing_requires_owner_quote"] = preview["confidence"] == "unknown"
                if include_metrics:
                    try:
                        row["provider_metrics"] = {
                            "source": "live_kie_success_rate",
                            "data": await self.metadata(model_path(name, "success-rate")),
                        }
                    except (GuardError, KieAPIError):
                        row["provider_metrics"] = {"source": "unavailable"}
            except GuardError as exc:
                row["reason"] = str(exc)
            rows.append(row)
        next_cursor = cursor + limit if cursor + limit < len(entries) else None
        return {
            "operation": operation,
            "selection_required": True,
            "models": rows,
            "catalog_count": len(entries),
            "cursor": cursor,
            "requested_parameters": parameters or {},
            "next_cursor": next_cursor,
            "reservation_created": False,
            "media_uploaded": False,
            "next_step": "call_friendly_tool_with_selected_model",
            "note": "Prices apply to the requested/default parameters. Unknown is not free. "
            "Quality descriptions are provider claims, not measured scores. "
            "Input URLs are not fetched; this comparison is not an executable approval.",
        }

    async def friendly(
        self,
        operation: str,
        prompt: str = "",
        model: str | None = None,
        image_path: str | None = None,
        image_url: str | None = None,
        parameters: dict | None = None,
        *,
        dry_run: bool = False,
        model_input: dict | None = None,
        auto_select: bool = False,
    ):
        """Prepare a single task, never silently execute a chain or a paid request."""
        if image_path and image_url:
            raise GuardError("Supply one image source")
        parameters = copy.deepcopy(parameters or {})
        if model is None and not auto_select:
            return await self.compare_models(
                operation, prompt, image_path, image_url, parameters, model_input
            )
        if image_path:
            with open_upload(
                image_path, self.settings.allowed_upload_root, self.settings.max_upload_bytes
            ):
                pass
        trusted_image_url = None
        if image_url:
            host = validate_url(image_url)
            if host == "tempfile.redpandaai.co":
                await resolve_public(host)
                trusted_image_url = image_url
        has_image = bool(image_path or image_url)
        if (
            operation
            in {
                "edit_image",
                "remove_background",
                "upscale_image",
                "product_image_create",
            }
            and not has_image
        ):
            raise GuardError("This operation requires an input image")
        if model is None:
            catalog = await self.model_candidates(operation, has_image)
            candidates = catalog["models"]
        else:
            candidates = [{"model": model}]
        if not candidates:
            raise GuardError("No suitable live media models found")
        # Metadata-only selection, cheapest verified compatible quote first.
        options = []
        unpriced = []
        for candidate in candidates[:20]:
            name = candidate["model"]
            try:
                contract = await self.contract(name)
                schema = contract["schema"].get("properties", {}).get("input", {})
                data, image_field, mapping = map_input(
                    schema, parameters, prompt, has_image, trusted_image_url, operation, model_input
                )
                preview = await self.estimate_contract(contract, name, data)
            except GuardError:
                if model is not None:
                    raise  # An explicit model must report the actual compatibility problem.
                continue
            if preview["estimated_cost_usd"] is not None:
                options.append((preview["estimated_cost_usd"], name, data, image_field, mapping))
            else:
                unpriced.append((None, name, data, image_field, mapping))
        if not options:
            if dry_run and model is not None and unpriced:
                options = unpriced
            else:
                raise GuardError(
                    "No verified compatible price; preview an explicit model with dry_run=true "
                    "and obtain an exact-input owner quote"
                )
        _, selected, data, image_field, mapping = (
            min(options, key=lambda item: item[0]) if options[0][0] is not None else options[0]
        )
        if trusted_image_url:
            url = trusted_image_url
        elif image_url:
            content = await fetch_bytes(image_url, self.settings.max_upload_bytes)
            upload = await self.client.upload_bytes(content)
            url = upload.get("data", {}).get("downloadUrl")
        elif image_path:
            upload = await self.client.upload_local_file(image_path, "mcp/files", None)
            url = upload.get("data", {}).get("downloadUrl")
        else:
            url = None
        if has_image:
            if not url:
                raise GuardError("Upload did not return a media URL")
            data[image_field] = [url] if isinstance(data[image_field], list) else url
        result = await self.prepare(selected, data, dry_run=dry_run)
        return {
            **result,
            "operation": operation,
            "next_step": (
                "kie_execute_task"
                if not dry_run
                else "owner_verified_quote"
                if result["confidence"] == "unknown"
                else "kie_prepare_task"
            ),
            "execution_blocked": result["confidence"] == "unknown",
            "selected_model": selected,
            "parameter_mapping": mapping,
            "image_field": image_field,
            "selection_scope": "explicit_model" if model else "first_20_catalog_candidates",
        }
