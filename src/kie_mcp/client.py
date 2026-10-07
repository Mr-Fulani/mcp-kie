from __future__ import annotations

import asyncio
import base64
import binascii
import json
import secrets
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

import httpx

from .config import Settings
from .errors import KieAPIError
from .models import MODEL_ID
from .network import KIE_STORAGE_HOSTS, fetch_bytes, safe_http_client, validate_url
from .security import detect_media_type, open_upload, redact, validate_upload_path

BaseName = Literal["api", "upload"]


def _parse_json_string(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


class KieClient:
    def __init__(
        self,
        settings: Settings,
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        if settings.api_base != "https://api.kie.ai":
            raise ValueError("Unapproved API endpoint")
        if settings.upload_base != "https://kieai.redpandaai.co":
            raise ValueError("Unapproved upload endpoint")
        self.settings = settings
        self._owns_client = http_client is None
        self._client = http_client or safe_http_client(settings.timeout_seconds)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _base_url(self, base: BaseName) -> str:
        return self.settings.api_base if base == "api" else self.settings.upload_base

    def _headers(self, *, content_type: str | None = "application/json") -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self.settings.require_api_key()}"}
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    @staticmethod
    def _validate_relative_path(path: str) -> str:
        if not path.startswith("/") or path.startswith("//"):
            raise ValueError("path must be an absolute API path beginning with one '/'")
        parsed = urlparse(path)
        if parsed.scheme or parsed.netloc:
            raise ValueError("full URLs are not accepted; pass a relative KIE API path")
        return path

    @staticmethod
    def _decode_response(response: httpx.Response) -> Any:
        content_type = response.headers.get("content-type", "")
        if "text/event-stream" in content_type:
            events: list[Any] = []
            for line in response.text.splitlines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if not data or data == "[DONE]":
                    continue
                try:
                    events.append(json.loads(data))
                except json.JSONDecodeError:
                    events.append(data)
            return {"stream": True, "events": events}

        try:
            return response.json()
        except (json.JSONDecodeError, ValueError):
            return {"text": response.text, "content_type": content_type}

    async def request(
        self,
        method: str,
        path: str,
        *,
        base: BaseName = "api",
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | list[Any] | None = None,
        files: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        _paid: bool = False,
    ) -> Any:
        # No arbitrary API path can bypass future budget/approval controls.
        allowed = {
            ("GET", "api", "/api/v1/chat/credit"),
            ("GET", "api", "/api/v1/jobs/recordInfo"),
            ("POST", "api", "/api/v1/common/download-url"),
            ("POST", "upload", "/api/file-stream-upload"),
            ("POST", "upload", "/api/file-base64-upload"),
        }
        metadata = path.removeprefix("/api/v1/models/")
        name, _, suffix = metadata.rpartition("/")
        live_metadata = (
            method.upper() == "GET"
            and base == "api"
            and (
                path == "/api/v1/models"
                or (
                    path.startswith("/api/v1/models/")
                    and MODEL_ID.fullmatch(name)
                    and suffix in {"schema", "price", "success-rate"}
                )
            )
        )
        paid_submission = _paid and (method.upper(), base, path) == (
            "POST",
            "api",
            "/api/v1/jobs/createTask",
        )
        if (
            (method.upper(), base, path) not in allowed
            and not live_metadata
            and not paid_submission
        ):
            raise ValueError("Endpoint disabled until its security controls are implemented")
        path = self._validate_relative_path(path)
        method = method.upper()
        if method not in {"GET", "POST"}:
            raise ValueError("only GET and POST are allowed")

        headers = self._headers(content_type=None if files else "application/json")
        url = f"{self._base_url(base)}{path}"

        attempts = 0 if paid_submission else self.settings.max_retries
        for attempt in range(attempts + 1):
            try:
                response = await self._client.request(
                    method,
                    url,
                    headers=headers,
                    params=params,
                    json=json_body,
                    files=files,
                    data=data,
                    follow_redirects=False,
                )
                payload = redact(self._decode_response(response), self.settings.api_key)
                api_code = payload.get("code") if isinstance(payload, dict) else None
                if response.is_success and api_code in {None, 200, "200"}:
                    return payload

                retryable = (
                    response.status_code == 429
                    or response.status_code >= 500
                    or str(api_code) in {"429", "500", "502", "503", "504"}
                )
                error = KieAPIError(
                    message=self._message_from_payload(payload, response.reason_phrase),
                    status_code=response.status_code,
                    api_code=payload.get("code") if isinstance(payload, dict) else None,
                    details=payload,
                    retryable=retryable,
                )
                if not retryable or attempt >= attempts:
                    raise error
                await asyncio.sleep(self._retry_delay(response, attempt))
            except (httpx.TimeoutException, httpx.NetworkError):
                if attempt >= attempts:
                    raise KieAPIError(
                        message="KIE API network request failed",
                        details=None,
                        retryable=True,
                    ) from None
                await asyncio.sleep(min(2**attempt + secrets.randbelow(1000) / 1000, 10.0))

        raise KieAPIError(message="KIE API request failed", details=None)

    @staticmethod
    def _message_from_payload(payload: Any, fallback: str) -> str:
        if isinstance(payload, dict):
            for key in ("msg", "message", "error"):
                value = payload.get(key)
                if isinstance(value, str) and value:
                    return value
        return fallback or "KIE API request failed"

    @staticmethod
    def _retry_delay(response: httpx.Response, attempt: int) -> float:
        retry_after = response.headers.get("retry-after")
        if retry_after:
            try:
                return min(float(retry_after), 30.0)
            except ValueError:
                pass
        return min(2**attempt + secrets.randbelow(1000) / 1000, 10.0)

    async def create_task(
        self, model: str, input_data: dict[str, Any], callback_url: str | None = None
    ) -> Any:
        body: dict[str, Any] = {"model": model, "input": input_data}
        if callback_url:
            body["callBackUrl"] = callback_url
        raise ValueError("Direct generation disabled; use prepare/execute")

    async def submit_prepared(self, payload: dict[str, Any]) -> Any:
        # Internal service path only; not exposed as an MCP tool.
        return await self.request("POST", "/api/v1/jobs/createTask", json_body=payload, _paid=True)

    async def get_task(self, task_id: str, *, parse_json_fields: bool = True) -> Any:
        payload = await self.request("GET", "/api/v1/jobs/recordInfo", params={"taskId": task_id})
        if parse_json_fields and isinstance(payload, dict):
            data = payload.get("data")
            if isinstance(data, dict):
                if "param" in data:
                    data["paramParsed"] = _parse_json_string(data["param"])
                if "resultJson" in data:
                    data["resultParsed"] = _parse_json_string(data["resultJson"])
        return payload

    async def get_credits(self) -> Any:
        return await self.request("GET", "/api/v1/chat/credit")

    async def get_download_url(self, url: str) -> Any:
        validate_url(url, allowed_hosts=KIE_STORAGE_HOSTS)
        return await self.request("POST", "/api/v1/common/download-url", json_body={"url": url})

    async def upload_from_url(self, file_url: str, upload_path: str, file_name: str | None) -> Any:
        content = await fetch_bytes(file_url, self.settings.max_upload_bytes)
        return await self.upload_bytes(content, "mcp/url")

    async def upload_bytes(self, content: bytes, upload_path: str = "mcp/files") -> Any:
        if len(content) > self.settings.max_upload_bytes:
            raise ValueError("Upload exceeds byte limit")
        mime_type = detect_media_type(content)
        from .storage import EXTENSIONS

        name = "media-" + secrets.token_hex(16) + EXTENSIONS[mime_type]
        return await self.request(
            "POST",
            "/api/file-stream-upload",
            base="upload",
            files={"file": (name, content, mime_type)},
            data={"uploadPath": upload_path, "fileName": name},
        )

    async def upload_base64(self, base64_data: str, upload_path: str, file_name: str | None) -> Any:
        encoded = base64_data.split(",", 1)[1] if base64_data.startswith("data:") else base64_data
        if len(encoded) > 4 * ((self.settings.max_upload_bytes + 2) // 3):
            raise ValueError("Upload exceeds byte limit")
        try:
            decoded = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError):
            raise ValueError("Invalid base64 media") from None
        if len(decoded) > self.settings.max_upload_bytes:
            raise ValueError("Upload exceeds byte limit")
        detect_media_type(decoded)
        if file_name:
            validate_upload_path_name(file_name)
        from .storage import EXTENSIONS

        mime_type = detect_media_type(decoded)
        body: dict[str, Any] = {
            "base64Data": encoded,
            "uploadPath": "mcp/base64",
            "fileName": "media-" + secrets.token_hex(16) + EXTENSIONS[mime_type],
        }
        return await self.request("POST", "/api/file-base64-upload", base="upload", json_body=body)

    def validate_local_upload(self, file_path: str) -> Path:
        return validate_upload_path(file_path, self.settings.allowed_upload_root)

    async def upload_local_file(
        self, file_path: str, upload_path: str, file_name: str | None
    ) -> Any:
        if file_name:
            validate_upload_path_name(file_name)
        with open_upload(
            file_path, self.settings.allowed_upload_root, self.settings.max_upload_bytes
        ) as (handle, mime_type):
            from .storage import EXTENSIONS

            name = "media-" + secrets.token_hex(16) + EXTENSIONS[mime_type]
            files = {"file": (name, handle, mime_type)}
            return await self.request(
                "POST",
                "/api/file-stream-upload",
                base="upload",
                files=files,
                data={"uploadPath": "mcp/files", "fileName": name},
            )


def validate_upload_path_name(name: str) -> None:
    # Caller names are not used remotely; reject secret/disallowed suffixes nevertheless.
    from .security import validate_name

    validate_name(name)


async def fetch_documentation(url: str, timeout_seconds: float = 30.0) -> str:
    validate_url(url, allowed_hosts={"docs.kie.ai"})
    if not urlparse(url).path.endswith(".md"):
        raise ValueError("documentation URL must point to a .md document")
    async with safe_http_client(timeout_seconds) as client:
        content = await fetch_bytes(url, 2_000_000, client=client, allowed_hosts={"docs.kie.ai"})
        return content.decode("utf-8")
