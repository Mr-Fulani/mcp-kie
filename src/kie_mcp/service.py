"""Client-agnostic application layer: discovery, immutable approvals, tasks and results."""

from __future__ import annotations

import asyncio
import copy
import math
import time
import uuid
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .client import KieClient
from .comparison import (
    capabilities,
    confirmation_summary,
    input_requirements,
    operation_requirements,
    video_capabilities,
)
from .config import Settings
from .errors import KieAPIError
from .friendly import IMAGE_FIELDS, IMAGE_OPERATIONS, map_input
from .ledger import GuardError, Ledger, digest
from .models import (
    apply_defaults,
    model_path,
    owner_quote,
    price_estimate,
    resolve_contract,
    validated_payload,
)
from .network import KIE_STORAGE_HOSTS, fetch_bytes, resolve_public, validate_url
from .security import open_upload
from .storage import save_result, validate_result_label
from .video_support import (
    duration_field_name,
    duration_support,
    has_video_input_payload,
    is_duration_field_name,
    normalize_duration_request,
    prompt_requests_video_input,
    selected_video_field,
)


def _resolve_input_type(
    input_type: str,
    image_path: str | None,
    image_url: str | None,
    video_path: str | None,
    video_url: str | None,
    model_input: dict | None,
) -> tuple[str, bool, bool]:
    if input_type not in {"auto", "text", "image", "video"}:
        raise GuardError("input_type must be auto, text, image or video")
    model_input = model_input or {}
    has_image_source = bool(image_path or image_url) or any(
        key in IMAGE_FIELDS for key in model_input
    )
    has_video_source = bool(video_path or video_url) or has_video_input_payload(model_input)
    if has_image_source and has_video_source:
        raise GuardError("Supply either an image input or a video input, not both")
    detected = "video" if has_video_source else "image" if has_image_source else "text"
    selected = detected if input_type == "auto" else input_type
    if input_type != "auto" and detected != "text" and detected != selected:
        raise GuardError("input_type conflicts with the supplied media source")
    if selected == "text" and (has_image_source or has_video_source):
        raise GuardError("Text-to-Video cannot include an image or video source")
    return selected, has_image_source, has_video_source


def _normalize_input_video_duration(value: int | float | str | None) -> int | float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise GuardError("input_video_duration_seconds must be a positive number")
    try:
        normalized = float(value)
    except (TypeError, ValueError):
        raise GuardError("input_video_duration_seconds must be a positive number") from None
    if not math.isfinite(normalized) or normalized <= 0:
        raise GuardError("input_video_duration_seconds must be a positive number")
    return int(normalized) if normalized.is_integer() else normalized


def _model_input_has_image(model_input: dict | None) -> bool:
    return any(key in IMAGE_FIELDS for key in (model_input or {}))


def _duration_intent_message_ru(intent: dict) -> str:
    status = intent.get("status")
    if status == "ambiguous":
        values = ", ".join(f"{value} с" for value in intent.get("values", []))
        return (
            f"В промте найдены разные варианты длительности: {values}. "
            "Укажите одну длительность в параметре duration или уточните промт."
        )
    if status == "conflict":
        return (
            "Длительность в промте, параметре duration и/или model_input расходится. "
            "Оставьте одно одинаковое значение."
        )
    if status == "invalid":
        return "Не удалось прочитать duration как число секунд. Укажите длительность числом."
    return ""


def _duration_support_message_ru(info: dict | None, seconds: int | float | None) -> str | None:
    if not info:
        return None
    duration_text = (
        f"{seconds:g} с"
        if isinstance(seconds, (int, float)) and not isinstance(seconds, bool)
        else "значение по схеме модели"
    )
    status = info.get("status")
    if status == "supported":
        sources = set((info.get("source") or "").split("+"))
        if "provider_description" in sources and sources.intersection(
            {"schema_enum", "schema_range"}
        ):
            return f"Машинная схема и описание KIE допускают длительность {duration_text}."
        if "provider_description" in sources:
            return (
                f"В описании KIE указана поддержка длительности {duration_text}; "
                "машинная схема сама по себе её не подтверждает."
            )
        return f"Машинная схема KIE допускает длительность {duration_text}."
    if status == "unsupported":
        if info.get("maximum_input_video_duration_seconds") is not None:
            return "Длительность исходного ролика превышает опубликованный предел KIE."
        return f"Ограничения KIE не допускают запрошенную длительность {duration_text}."
    if status == "automatic":
        return "Модель выберет длительность сама; точное число секунд не гарантируется."
    if status == "uncertain":
        if "Input-video duration is needed" in (info.get("reason") or ""):
            return (
                "Для проверки ограничения видеовхода нужна длительность исходного ролика. "
                "Укажите её; файл локально измеряться не будет."
            )
        return "Ограничение этой длительности не подтверждено схемой или описанием KIE."
    return None


def _validation_rejects_duration(errors) -> bool:
    def mentions(error) -> bool:
        if any(is_duration_field_name(str(component)) for component in error.absolute_path):
            return True
        return any(mentions(child) for child in getattr(error, "context", ()))

    return any(mentions(error) for error in errors)


def _source_duration_assumptions(
    input_type: str,
    has_image_source: bool,
    has_video_source: bool,
    input_video_duration_seconds: int | float | None,
) -> tuple[bool, dict]:
    assumptions: dict[str, Any] = {}
    provisional = False
    if input_type == "image":
        provisional = True
        assumptions["input_images"] = 1 if has_image_source else "one image assumed"
    elif input_type == "video":
        provisional = True
        assumptions["input_videos"] = 1 if has_video_source else "one reference video assumed"
        assumptions["input_video_duration_seconds"] = (
            input_video_duration_seconds if input_video_duration_seconds is not None else "unknown"
        )
        assumptions["provider_video_input_pricing"] = "not generally verified"
    return provisional, assumptions


def _candidate_task_types(candidate: dict) -> list[str]:
    labels = []
    for key in ("taskTypes", "task_types", "taskType", "task_type", "discovered_task_types"):
        value = candidate.get(key)
        values = [value] if isinstance(value, str) else value if isinstance(value, list) else []
        labels.extend(item for item in values if isinstance(item, str) and item not in labels)
    return labels


def _is_video_to_video_model(task_types: list[str]) -> bool:
    return any(
        "video to video" in label.casefold().replace("-", " ").replace("_", " ")
        or "v2v" in label.casefold()
        for label in task_types
    )


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

    async def estimate(
        self,
        model: str,
        input_data: dict,
        *,
        input_video_duration_seconds: int | float | None = None,
    ):
        input_video_duration_seconds = _normalize_input_video_duration(input_video_duration_seconds)
        contract = await self.contract(model)
        return await self.estimate_contract(
            contract,
            model,
            input_data,
            input_video_duration_seconds=input_video_duration_seconds,
        )

    def unknown_price_warning_ru(
        self, *, acknowledged: bool = False, reserved_cost_usd: float | None = None
    ) -> str:
        reserve = self.settings.limits.task_usd if reserved_cost_usd is None else reserved_cost_usd
        if acknowledged:
            return (
                "Цена KIE остаётся неизвестной. Вы подтвердили запуск на свой риск. "
                f"В локальном ledger зарезервировано ${reserve:g} по лимиту одной задачи; "
                "фактическое списание KIE может быть выше. После завершения MCP покажет "
                "фактическую сумму только если KIE её вернёт; иначе она останется неизвестной. "
                "Задача подготовлена и отправится только после отдельного вызова execute "
                "с этим approval_id."
            )
        return (
            "MCP не смог определить цену по текущим данным KIE. "
            f"После явного согласия локальный ledger зарезервирует ${reserve:g} "
            "по лимиту одной задачи. Этот резерв не ограничивает списание провайдера: "
            "фактическая цена KIE может быть выше. После завершения MCP покажет "
            "фактическую сумму только если KIE её вернёт; иначе она останется неизвестной. "
            "Генерация пока не запущена."
        )

    async def estimate_contract(
        self,
        contract: dict,
        model: str,
        input_data: dict,
        *,
        input_video_duration_seconds: int | float | None = None,
    ):
        payload = validated_payload(contract, model, input_data)
        input_schema = contract["schema"].get("properties", {}).get("input", {})
        duration_field = next(
            (name for name in payload["input"] if is_duration_field_name(name)), None
        )
        duration_info = None
        has_video_input = has_video_input_payload(payload["input"])
        if duration_field is not None or has_video_input:
            duration_info = duration_support(
                input_schema,
                payload["input"].get(duration_field) if duration_field else None,
                has_video_input=has_video_input,
                input_video_duration_seconds=input_video_duration_seconds,
            )
            if duration_info["status"] == "unsupported":
                if duration_info.get("maximum_input_video_duration_seconds") is not None:
                    raise GuardError("Input-video duration is outside provider-declared limits")
                raise GuardError("Requested video duration is outside provider-declared limits")
        pricing = await self.metadata(model_path(model, "price"))
        estimate = price_estimate(model, payload["input"], pricing)
        if estimate["confidence"] == "unknown":
            quote = owner_quote(payload, self.settings.owner_quote_path)
            if quote:
                estimate = quote
        unknown = estimate["confidence"] == "unknown"
        risk_reserve = self.settings.limits.task_usd if unknown else None
        preview = {
            **estimate,
            "validated_input": payload["input"],
            "input_video_duration_seconds": input_video_duration_seconds,
            "risk_ack_required": unknown,
            "risk_reserve_usd": risk_reserve,
        }
        return {
            **estimate,
            "confirmation_summary_ru": confirmation_summary(
                model,
                preview,
                risk_reserve_usd=risk_reserve,
            ),
            "risk_ack_required": unknown,
            "risk_reserve_usd": risk_reserve,
            "pricing_warning_ru": self.unknown_price_warning_ru() if unknown else None,
            "duration_support": duration_info,
            "duration_warning_ru": (
                "Точная длительность не подтверждена схемой KIE; проверьте ограничение модели."
                if duration_info and duration_info["status"] in {"uncertain", "automatic"}
                else "Ограничение длительности прочитано из "
                "описания провайдера, а не из машинного диапазона."
                if duration_info and "provider_description" in (duration_info.get("source") or "")
                else None
            ),
            "duration_support_message_ru": _duration_support_message_ru(
                duration_info,
                payload["input"].get(duration_field) if duration_field else None,
            ),
            "input_video_duration_verified": False
            if input_video_duration_seconds is not None
            else None,
            "input_video_duration_seconds": input_video_duration_seconds,
            "input_video_duration_note_ru": (
                "Длительность исходного ролика указана пользователем и локально не проверена."
                if input_video_duration_seconds is not None
                else None
            ),
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

    async def prepare(
        self,
        model: str,
        input_data: dict,
        *,
        dry_run=False,
        accept_unknown_price: bool = False,
        input_video_duration_seconds: int | float | None = None,
    ):
        if type(accept_unknown_price) is not bool:
            raise GuardError("Unknown-price acceptance must be an explicit boolean")
        input_video_duration_seconds = _normalize_input_video_duration(input_video_duration_seconds)
        preview = await self.estimate(
            model,
            input_data,
            input_video_duration_seconds=input_video_duration_seconds,
        )
        duration_info = preview.get("duration_support")
        if (
            duration_info
            and duration_info.get("status") == "uncertain"
            and "Input-video duration is needed" in (duration_info.get("reason") or "")
        ):
            raise GuardError(
                "Input-video duration is required by the "
                "provider limits; run kie_preflight and supply it"
            )
        await self._validate_media_urls(preview["validated_input"])
        unknown = preview["confidence"] == "unknown"
        if dry_run:
            return {
                **preview,
                "dry_run": True,
                "reservation_created": False,
                "risk_acknowledged": False,
                "execution_blocked": unknown,
                "next_step": "confirm_unknown_price" if unknown else "kie_prepare_task",
                "message_ru": self.unknown_price_warning_ru() if unknown else None,
            }
        if unknown and not accept_unknown_price:
            return {
                **preview,
                "dry_run": False,
                "reservation_created": False,
                "risk_ack_required": True,
                "risk_acknowledged": False,
                "execution_blocked": True,
                "next_step": "confirm_unknown_price",
                "message_ru": self.unknown_price_warning_ru(),
            }
        risk_accepted = unknown and accept_unknown_price
        reserve_cost = (
            self.settings.limits.task_usd if risk_accepted else preview["estimated_cost_usd"]
        )
        reserved = self.ledger.prepare(
            preview["request_payload"],
            reserve_cost,
            preview["estimated_credits"],
            preview["pricing_source"],
            self.session,
            client_name=self.client_name,
            client_version=self.client_version,
            unknown_price_accepted=risk_accepted,
            input_video_duration_seconds=input_video_duration_seconds,
        )
        owns_approval = bool(reserved.get("approval_id"))
        risk_acknowledged = owns_approval and bool(reserved.get("unknown_price_accepted"))
        can_execute = owns_approval and reserved.get("status") == "prepared"
        result_preview = {
            **preview,
            "unknown_price_accepted": risk_acknowledged,
            "reserved_cost_usd": reserved.get("reserved_cost_usd"),
        }
        if can_execute:
            summary = confirmation_summary(
                model,
                result_preview,
                risk_reserve_usd=(reserved.get("reserved_cost_usd") if risk_accepted else None),
            )
        elif not owns_approval:
            summary = (
                f"Модель: {model}. Совпадающий запрос уже зарегистрирован другой "
                "MCP-сессией. Эта сессия не получила approval_id, повторная отправка "
                "заблокирована. Сначала сверьте состояние исходного запроса."
            )
        else:
            summary = (
                f"Модель: {model}. Совпадающий запрос уже имеет статус "
                f"{reserved.get('status')}; повторная платная отправка заблокирована."
            )
        risk_ack_required = unknown and not risk_acknowledged and owns_approval and can_execute
        execution_blocked = not can_execute or (unknown and not risk_acknowledged)
        if not owns_approval:
            message_ru = (
                "Совпадающий запрос уже зарегистрирован другой MCP-сессией. "
                "Повторная отправка не выполняется; сначала сверьте исходный запрос."
            )
            next_step = "reconcile_existing_request"
        elif not can_execute:
            message_ru = (
                f"Совпадающий запрос уже имеет статус {reserved.get('status')}; "
                "повторная платная отправка не выполняется."
            )
            next_step = (
                "kie_wait_for_task"
                if reserved.get("status") == "submitted" and reserved.get("task_id")
                else "reconcile_existing_request"
            )
        elif unknown and not risk_acknowledged:
            message_ru = self.unknown_price_warning_ru()
            next_step = "confirm_unknown_price"
        else:
            message_ru = (
                self.unknown_price_warning_ru(
                    acknowledged=risk_acknowledged,
                    reserved_cost_usd=reserved.get("reserved_cost_usd"),
                )
                if unknown
                else None
            )
            next_step = "kie_execute_task"
        if not unknown:
            pricing_warning_ru = None
        elif can_execute:
            pricing_warning_ru = self.unknown_price_warning_ru(
                acknowledged=risk_acknowledged,
                reserved_cost_usd=reserved.get("reserved_cost_usd"),
            )
        else:
            reserved_amount = reserved.get("reserved_cost_usd")
            reserved_text = (
                f"${reserved_amount:g}" if reserved_amount is not None else "неизвестная сумма"
            )
            pricing_warning_ru = (
                "Цена KIE остаётся неизвестной. В локальном ledger числится резерв "
                f"{reserved_text}; он не ограничивает списание провайдера, которое "
                f"может быть выше. Совпадающий запрос имеет статус {reserved.get('status')}; "
                "повторная отправка заблокирована."
            )
        return {
            **preview,
            **reserved,
            "estimated_cost_usd": preview["estimated_cost_usd"],
            "risk_ack_required": risk_ack_required,
            "risk_acknowledged": risk_acknowledged,
            "risk_reserve_usd": reserved.get("reserved_cost_usd") if risk_accepted else None,
            "pricing_warning_ru": pricing_warning_ru,
            "confirmation_summary_ru": summary,
            "execution_blocked": execution_blocked,
            "next_step": next_step,
            "message_ru": message_ru,
            "dry_run": False,
            "reservation_created": not reserved["duplicate"],
        }

    async def execute(self, approval_id: str, model: str, input_data: dict):
        with self.ledger.connection() as db:
            row = db.execute(
                "SELECT estimated_cost_usd,unknown_price_accepted,input_video_duration_seconds "
                "FROM usage WHERE id=? AND agent_session_id=?",
                (approval_id, self.session),
            ).fetchone()
        if row is None:
            raise GuardError("Unknown approval for this session")
        input_video_duration_seconds = row["input_video_duration_seconds"]
        # Refresh schema and tariff before claiming; never accept client-supplied price or endpoint.
        preview = await self.estimate(
            model,
            input_data,
            input_video_duration_seconds=input_video_duration_seconds,
        )
        await self._validate_media_urls(preview["validated_input"])
        # Compare a known fresh price against the reservation before the atomic claim.
        risk_accepted = bool(row["unknown_price_accepted"])
        if preview["confidence"] == "unknown" and not risk_accepted:
            raise GuardError(
                "Price is unknown and this approval has no explicit risk acceptance; "
                "prepare again after the user confirms"
            )
        reserved_cost = row["estimated_cost_usd"] / 1_000_000
        if (
            preview["estimated_cost_usd"] is not None
            and preview["estimated_cost_usd"] > reserved_cost
        ):
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
            response = dict(response)
            reported_cost = data.get("costUsd")
            reported_credits = data.get("creditsConsumed")
            response["billing_reconciliation"] = {
                "source": "kie_task_response",
                "reported_cost_usd": reported_cost,
                "reported_credits_consumed": reported_credits,
                "cost_status": (
                    "reported_by_kie" if reported_cost is not None else "not_reported_by_kie"
                ),
                "message_ru": (
                    "KIE сообщил сумму в USD. MCP сверяет её с локальным ledger, если задача "
                    "была создана через этот ledger."
                    if reported_cost is not None
                    else "KIE не вернул фактическую стоимость в "
                    "USD. Резерв ledger не является ценой; "
                    "не выводите её из числа кредитов или изменения баланса."
                ),
            }
        response = dict(response)
        response["task_progress"] = self.task_progress(task_id, data)
        return response

    @staticmethod
    def task_progress(task_id: str, data: dict) -> dict:
        state = data.get("state")
        terminal = state in {"success", "fail"}
        created = data.get("createTime")
        elapsed = None
        if (
            isinstance(created, (int, float))
            and not isinstance(created, bool)
            and math.isfinite(created)
            and created > 0
        ):
            finished = data.get("completeTime") if terminal else None
            end = time.time()
            if (
                isinstance(finished, (int, float))
                and not isinstance(finished, bool)
                and math.isfinite(finished)
                and finished > 0
            ):
                end = finished / 1000
            elapsed = max(0, round(end - created / 1000))
        descriptions = {
            "waiting": "Задача в очереди KIE.",
            "queuing": "Задача в очереди KIE.",
            "generating": "KIE генерирует результат.",
            "success": "Генерация завершена. Результат можно скачать.",
            "fail": "KIE сообщил ошибку генерации. Проверьте failCode и failMsg.",
        }
        message = descriptions.get(
            state, "KIE вернул неизвестный статус; готовность не подтверждена."
        )
        if elapsed is not None:
            message += f" С момента создания задачи: {elapsed} с."
        if not terminal:
            message += (
                " KIE не сообщает процент, позицию в очереди или время до готовности."
                " Проверяйте эту же задачу; не отправляйте новую генерацию."
            )
        return {
            "task_id": task_id,
            "provider_state": state,
            "terminal": terminal,
            "elapsed_seconds": elapsed,
            "progress_percent": None,
            "queue_position": None,
            "eta_seconds": None,
            "next_step": "kie_download_result"
            if state == "success"
            else ("review_provider_error" if state == "fail" else "kie_wait_for_task"),
            "retry_after_seconds": None if terminal else 15,
            "resubmit_allowed": False,
            "message_ru": message,
        }

    async def wait(self, task_id: str, timeout: int | None = None):
        started = time.monotonic()
        deadline = started + min(timeout or self.settings.task_timeout, self.settings.task_timeout)
        intervals = [2, 3, 5, 8, 10, 15]
        attempt = 0
        while True:
            # Poll once more at the deadline so completion during the last sleep is visible.
            payload = await self.get_task(task_id)
            terminal = payload.get("data", {}).get("state") in {"success", "fail"}
            elapsed = max(0, time.monotonic() - started)
            timed_out = not terminal and time.monotonic() >= deadline
            if terminal or timed_out:
                result = dict(payload)
                result["polling"] = {
                    "status": "complete" if terminal else "pending",
                    "timed_out": timed_out,
                    "waited_seconds": round(elapsed, 2),
                    "poll_count": attempt + 1,
                    "task_id": task_id,
                    "budget_liability_retained": not terminal,
                    "resubmit_allowed": False,
                    "message_ru": (
                        "Проверка завершена: KIE вернул итоговый статус."
                        if terminal
                        else "Время одной проверки истекло; "
                        "задача продолжает оставаться активной в KIE. "
                        "Это не ошибка генерации и не разрешение на повторный запуск. "
                        "Продолжите kie_wait_for_task или kie_get_task с тем же task_id. "
                        "Дополнительного согласия на платный запуск не требуется; "
                        "локальный резерв сохраняется."
                    ),
                }
                return result
            await asyncio.sleep(
                min(intervals[min(attempt, 5)], max(0, deadline - time.monotonic()))
            )
            attempt += 1

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

    async def model_candidates(
        self,
        operation: str,
        has_image: bool,
        query: str = "",
        *,
        has_video: bool = False,
    ):
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
        if operation == "generate_video" and has_video:
            task_types = ("Video to Video", "Text to Video", "Image to Video")
            models_by_name: dict[str, dict] = {}
            failed_categories = []
            for task_type in task_types:
                try:
                    catalog = await self.search_models(query=query, task_type=task_type)
                except (GuardError, KieAPIError):
                    failed_categories.append(task_type)
                    continue
                for candidate in catalog["models"]:
                    name = candidate.get("model")
                    if isinstance(name, str) and name:
                        item = models_by_name.setdefault(
                            name, {**candidate, "discovered_task_types": []}
                        )
                        labels = item["discovered_task_types"]
                        if task_type not in labels:
                            labels.append(task_type)
            if not models_by_name:
                raise GuardError("Live video-input model catalog is unavailable")
            return {
                "models": list(models_by_name.values()),
                "catalog_complete": not failed_categories,
                "failed_categories": failed_categories,
            }
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
        input_type: str = "auto",
        video_path: str | None = None,
        video_url: str | None = None,
        input_video_duration_seconds: int | float | None = None,
    ):
        """Metadata-only comparison: no media fetch/upload, ledger mutation or submission."""
        if type(cursor) is not int or cursor < 0 or type(limit) is not int or limit < 1:
            raise GuardError("Comparison requires an integer cursor >= 0 and integer limit >= 1")
        requested_limit = limit
        limit = min(limit, 10)
        if operation != "generate_video" and (video_path or video_url or input_type != "auto"):
            raise GuardError("input_type and video input are only supported for generate_video")
        if image_path and image_url:
            raise GuardError("Supply one image source")
        if video_path and video_url:
            raise GuardError("Supply one video source")
        parameters = copy.deepcopy(parameters or {})
        duration_intent = {"status": "not_applicable", "seconds": None, "values": []}
        if operation == "generate_video":
            parameters, duration_intent = normalize_duration_request(
                parameters, prompt, model_input
            )
            if duration_intent["status"] in {"ambiguous", "conflict", "invalid"}:
                return {
                    "operation": operation,
                    "selection_required": True,
                    "status": "needs_clarification",
                    "duration_request": duration_intent,
                    "message_ru": _duration_intent_message_ru(duration_intent),
                    "models": [],
                    "reservation_created": False,
                    "media_uploaded": False,
                    "next_step": "clarify_duration",
                }
        input_video_duration_seconds = _normalize_input_video_duration(input_video_duration_seconds)
        if (
            operation == "generate_video"
            and input_type == "auto"
            and not (image_path or image_url or video_path or video_url)
            and not (
                has_video_input_payload(model_input or {}) or _model_input_has_image(model_input)
            )
            and prompt_requests_video_input(prompt)
        ):
            input_type = "video"
        selected_input_type, has_image, has_video = _resolve_input_type(
            input_type,
            image_path,
            image_url,
            video_path,
            video_url,
            model_input,
        )
        if input_video_duration_seconds is not None and selected_input_type != "video":
            raise GuardError("input_video_duration_seconds requires Video-to-Video input")
        if operation != "generate_video" and selected_input_type == "video":
            raise GuardError("Video input is only supported for generate_video")
        if (image_path or image_url) and _model_input_has_image(model_input):
            raise GuardError("Supply the image source once")
        if (video_path or video_url) and has_video_input_payload(model_input or {}):
            raise GuardError("Supply the video source once")
        trusted_image_url = None
        if image_url and validate_url(image_url) == "tempfile.redpandaai.co":
            trusted_image_url = image_url
        trusted_video_url = None
        if video_url and validate_url(video_url) == "tempfile.redpandaai.co":
            trusted_video_url = video_url
        requirements = operation_requirements(
            operation,
            has_image,
            has_video,
            selected_input_type,
        )
        comparison_has_image = selected_input_type == "image" or operation in IMAGE_OPERATIONS
        comparison_has_video = operation == "generate_video" and selected_input_type == "video"
        price_input_type = (
            selected_input_type
            if operation == "generate_video"
            else "image"
            if operation in IMAGE_OPERATIONS
            else "text"
        )
        price_is_provisional, price_assumptions = _source_duration_assumptions(
            price_input_type,
            has_image,
            has_video,
            input_video_duration_seconds,
        )
        if price_input_type == "image" and trusted_image_url:
            price_is_provisional, price_assumptions = False, {}
        catalog = await self.model_candidates(
            operation,
            selected_input_type == "image" or operation in IMAGE_OPERATIONS,
            query,
            has_video=comparison_has_video,
        )
        entries = catalog["models"]
        rows = []
        for candidate in entries[cursor : cursor + limit]:
            name = candidate["model"]
            candidate_types = _candidate_task_types(candidate)
            is_v2v_model = _is_video_to_video_model(candidate_types)
            row = {
                "model": name,
                "title": candidate.get("title", name),
                "provider": candidate.get("provider"),
                "task_types": candidate_types,
                "is_video_to_video_model": is_v2v_model if candidate_types else None,
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
                video_field = (
                    selected_video_field(schema, model_input) if comparison_has_video else None
                )
                if comparison_has_video:
                    row["video_field"] = video_field
                    row["video_input_semantics"] = (
                        "video_to_video_reference_field"
                        if is_v2v_model and video_field and "reference" in video_field.lower()
                        else "video_to_video"
                        if is_v2v_model and video_field
                        else "video_to_video_category_no_detected_input_field"
                        if is_v2v_model
                        else "reference_field"
                        if video_field and "reference" in video_field.lower()
                        else "declared_video_input"
                        if video_field
                        else None
                    )
                row["capabilities"] = capabilities(schema)
                row["requirements"] = input_requirements(schema)
                row["price_is_provisional"] = price_is_provisional
                row["price_assumptions"] = price_assumptions
                row["input_type"] = selected_input_type
                requested_seconds = duration_intent.get("seconds")
                duration_info = None
                if operation == "generate_video" and (
                    requested_seconds is not None or comparison_has_video
                ):
                    duration_info = duration_support(
                        schema,
                        requested_seconds,
                        has_video_input=comparison_has_video,
                        input_video_duration_seconds=input_video_duration_seconds,
                    )
                    row["duration_support"] = duration_info
                    row["duration_support_status"] = duration_info["status"]
                    row["duration_support_message_ru"] = _duration_support_message_ru(
                        duration_info, requested_seconds
                    )
                    if duration_info["status"] == "unsupported":
                        row["reason"] = duration_info.get("reason")
                        rows.append(row)
                        continue
                mapped, image_field, mapping = map_input(
                    schema,
                    parameters,
                    prompt,
                    comparison_has_image,
                    trusted_image_url,
                    operation,
                    model_input,
                    has_video=comparison_has_video,
                    video_url=trusted_video_url,
                )
                mapped = apply_defaults(mapped, schema)
                schema_errors = list(Draft202012Validator(schema).iter_errors(mapped))
                if (
                    schema_errors
                    and requested_seconds is not None
                    and _validation_rejects_duration(schema_errors)
                ):
                    duration_field = duration_field_name(schema.get("properties", {}))
                    duration_info = {
                        "status": "unsupported",
                        "field": duration_field,
                        "source": "live_schema_validation",
                        "reason": "The full live schema rejects this "
                        "duration with the selected parameters.",
                    }
                    row["duration_support"] = duration_info
                    row["duration_support_status"] = "unsupported"
                    row["duration_support_message_ru"] = _duration_support_message_ru(
                        duration_info, requested_seconds
                    )
                    row["reason"] = duration_info["reason"]
                    rows.append(row)
                    continue
                preview = await self.estimate_contract(
                    contract,
                    name,
                    mapped,
                    input_video_duration_seconds=input_video_duration_seconds,
                )
                if preview.get("duration_support") is not None:
                    row["duration_support"] = preview["duration_support"]
                    row["duration_support_status"] = preview["duration_support"]["status"]
                    row["duration_support_message_ru"] = _duration_support_message_ru(
                        preview["duration_support"], requested_seconds
                    )
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
                unknown = preview["confidence"] == "unknown"
                row["risk_ack_required"] = unknown
                row["risk_reserve_usd"] = self.settings.limits.task_usd if unknown else None
                row["pricing_warning_ru"] = self.unknown_price_warning_ru() if unknown else None
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
        message_ru = "Выберите модель. Сравнение не загружает файлы и не резервирует деньги."
        pagination_message_ru = (
            f"Запрошено моделей: {requested_limit}. Размер страницы ограничен 10 моделями; "
            "для следующих моделей используйте next_cursor."
            if requested_limit > limit
            else None
        )
        video_input_matches = None
        if comparison_has_video:
            reference_semantics = {
                "reference_field",
                "video_to_video_reference_field",
            }
            video_input_matches = {
                "video_to_video_catalog_model_ids": [
                    row["model"] for row in rows if row.get("is_video_to_video_model") is True
                ],
                "compatible_video_to_video_model_ids": [
                    row["model"]
                    for row in rows
                    if row.get("compatible") and row.get("is_video_to_video_model") is True
                ],
                "compatible_reference_field_model_ids": [
                    row["model"]
                    for row in rows
                    if row.get("compatible")
                    and row.get("video_input_semantics") in reference_semantics
                ],
                "reference_field_model_ids": [
                    row["model"]
                    for row in rows
                    if row.get("video_input_semantics") in reference_semantics
                ],
                "video_to_video_reference_field_model_ids": [
                    row["model"]
                    for row in rows
                    if row.get("video_input_semantics") == "video_to_video_reference_field"
                ],
                "compatible_other_video_input_model_ids": [
                    row["model"]
                    for row in rows
                    if row.get("compatible")
                    and row.get("video_input_semantics") == "declared_video_input"
                ],
                "cursor": cursor,
                "next_cursor": next_cursor,
            }
        duration_matches = None
        if operation == "generate_video" and duration_intent.get("seconds") is not None:
            duration_matches = {
                "requested_seconds": duration_intent["seconds"],
                "supported_model_ids": [
                    row["model"]
                    for row in rows
                    if row.get("compatible") and row.get("duration_support_status") == "supported"
                ],
                "uncertain_model_ids": [
                    row["model"]
                    for row in rows
                    if row.get("compatible") and row.get("duration_support_status") == "uncertain"
                ],
                "automatic_duration_model_ids": [
                    row["model"]
                    for row in rows
                    if row.get("compatible") and row.get("duration_support_status") == "automatic"
                ],
                "unsupported_model_ids": [
                    row["model"]
                    for row in rows
                    if row.get("duration_support_status") == "unsupported"
                ],
                "unclassified_model_ids": [
                    row["model"] for row in rows if row.get("duration_support_status") is None
                ],
                "cursor": cursor,
                "next_cursor": next_cursor,
            }
            duration_matches["supported_count"] = len(duration_matches["supported_model_ids"])
            message_ru += (
                f" Для запроса {duration_intent['seconds']:g} с каждая строка показывает "
                "duration_support: supported, unsupported, uncertain или automatic "
                "и источник ограничения. "
                f"На этой странице подтверждено моделей: {duration_matches['supported_count']}. "
                "Полный список просматривается страницами через next_cursor."
            )
        if comparison_has_video:
            message_ru += (
                " В каждой строке указаны task_types и различаются модели каталога "
                "Video-to-Video, поля reference-видео и прочие объявленные видеовходы. "
                "Само поле reference не подтверждает покадровое редактирование."
            )
        if not catalog.get("catalog_complete", True):
            message_ru += (
                " Каталог неполон: часть типов задач KIE не удалось прочитать, "
                "поэтому в текущих результатах могут отсутствовать подходящие модели."
            )
        if price_is_provisional:
            if price_input_type == "video":
                message_ru += (
                    " Цена предварительная: фактическую длительность исходного ролика "
                    "и тариф для видеовхода может потребоваться уточнить."
                )
            else:
                message_ru += " Цена предварительная и предполагает один входной файл."
        message_ru += (
            " После выбора вызовите kie_preflight. Точный preview может передать исходник в KIE."
        )
        if any(row.get("risk_ack_required") for row in rows):
            message_ru += (
                " Для моделей с неизвестной ценой инструмент покажет отдельное "
                "предупреждение; подготовка возможна только после явного согласия "
                "пользователя на риск."
            )
        return {
            "operation": operation,
            "input_type": selected_input_type,
            "selection_required": True,
            "requirements": requirements,
            "duration_request": duration_intent,
            "duration_matches": duration_matches,
            "video_input_matches": video_input_matches,
            "message_ru": message_ru,
            "models": rows,
            "catalog_count": len(entries),
            "cursor": cursor,
            "requested_limit": requested_limit,
            "effective_limit": limit,
            "pagination_message_ru": pagination_message_ru,
            "requested_parameters": parameters,
            "next_cursor": next_cursor,
            "catalog_complete": catalog.get("catalog_complete", True),
            "failed_categories": catalog.get("failed_categories", []),
            "reservation_created": False,
            "media_uploaded": False,
            "next_step": "kie_preflight_with_selected_model",
            "note": "Prices apply to the requested/default parameters. Unknown is not free. "
            "Quality descriptions are provider claims, not measured scores. "
            "Input URLs are not fetched; this comparison is not an executable approval.",
        }

    async def preflight(
        self,
        operation: str,
        model: str | None = None,
        prompt: str = "",
        image_path: str | None = None,
        image_url: str | None = None,
        parameters: dict | None = None,
        model_input: dict | None = None,
        *,
        input_type: str = "auto",
        video_path: str | None = None,
        video_url: str | None = None,
        input_video_duration_seconds: int | float | None = None,
    ):
        """Read-only requirements check; never open/fetch/upload media or reserve budget."""
        if operation != "generate_video" and (video_path or video_url or input_type != "auto"):
            raise GuardError("input_type and video input are only supported for generate_video")
        if image_path and image_url:
            raise GuardError("Supply one image source")
        if video_path and video_url:
            raise GuardError("Supply one video source")
        parameters = copy.deepcopy(parameters or {})
        duration_intent = {"status": "not_applicable", "seconds": None, "values": []}
        if operation == "generate_video":
            parameters, duration_intent = normalize_duration_request(
                parameters, prompt, model_input
            )
            if duration_intent["status"] in {"ambiguous", "conflict", "invalid"}:
                return {
                    "operation": operation,
                    "model": model,
                    "status": "needs_parameters",
                    "duration_request": duration_intent,
                    "missing_inputs": [],
                    "reservation_created": False,
                    "media_uploaded": False,
                    "source_verified": False,
                    "execution_ready": False,
                    "message_ru": _duration_intent_message_ru(duration_intent),
                    "next_step": "clarify_duration",
                }
        input_video_duration_seconds = _normalize_input_video_duration(input_video_duration_seconds)
        if (
            operation == "generate_video"
            and input_type == "auto"
            and not (image_path or image_url or video_path or video_url)
            and not (
                has_video_input_payload(model_input or {}) or _model_input_has_image(model_input)
            )
            and prompt_requests_video_input(prompt)
        ):
            input_type = "video"
        selected_input_type, has_image, has_video = _resolve_input_type(
            input_type,
            image_path,
            image_url,
            video_path,
            video_url,
            model_input,
        )
        if input_video_duration_seconds is not None and selected_input_type != "video":
            raise GuardError("input_video_duration_seconds requires Video-to-Video input")
        if operation != "generate_video" and selected_input_type == "video":
            raise GuardError("Video input is only supported for generate_video")
        if (image_path or image_url) and _model_input_has_image(model_input):
            raise GuardError("Supply the image source once")
        if (video_path or video_url) and has_video_input_payload(model_input or {}):
            raise GuardError("Supply the video source once")
        requirements = operation_requirements(
            operation,
            has_image,
            has_video,
            selected_input_type,
        )
        result = {
            "operation": operation,
            "model": model,
            "input_type": selected_input_type,
            "duration_request": duration_intent,
            "requirements": requirements,
            "missing_inputs": list(requirements["missing_inputs"]),
            "reservation_created": False,
            "media_uploaded": False,
            "source_verified": False,
            "execution_ready": False,
            "upload_may_be_required": has_image or has_video,
            "input_video_duration_seconds": input_video_duration_seconds,
            "input_video_duration_verified": False,
            "message_ru": (
                "Это предварительная проверка без открытия/загрузки файлов и без списания денег. "
                "Наличие, формат и размер исходника ещё не проверены. Точный preview "
                "может передать исходник в KIE; объясните это пользователю до вызова. "
                "Покажите модель, параметры и цену по-русски перед платным запуском."
            ),
        }
        if model is not None:
            contract = await self.contract(model)
            schema = contract["schema"].get("properties", {}).get("input", {})
            result["model_requirements"] = input_requirements(schema)
            result["video_input_constraints"] = video_capabilities(schema)
            result["local_upload_max_bytes"] = self.settings.max_upload_bytes
            comparison_has_image = selected_input_type == "image" or operation in IMAGE_OPERATIONS
            comparison_has_video = operation == "generate_video" and selected_input_type == "video"
            requested_seconds = duration_intent.get("seconds")
            duration_info = None
            if operation == "generate_video" and (
                requested_seconds is not None or comparison_has_video
            ):
                duration_info = duration_support(
                    schema,
                    requested_seconds,
                    has_video_input=comparison_has_video,
                    input_video_duration_seconds=input_video_duration_seconds,
                )
                result["duration_support"] = duration_info
                result["duration_support_status"] = duration_info["status"]
                result["duration_support_message_ru"] = _duration_support_message_ru(
                    duration_info, requested_seconds
                )
                if duration_info["status"] == "unsupported":
                    result["reason"] = duration_info.get("reason")
                elif duration_info[
                    "status"
                ] == "uncertain" and "Input-video duration is needed" in (
                    duration_info.get("reason") or ""
                ):
                    result["missing_inputs"].append("input_video_duration_seconds")
            try:
                data, image_field, _ = map_input(
                    schema,
                    parameters,
                    prompt,
                    comparison_has_image,
                    None,
                    operation,
                    model_input,
                    has_video=comparison_has_video,
                )
                data = apply_defaults(data, schema)
                missing = [key for key in schema.get("required", []) if key not in data]
                result["missing_inputs"].extend(missing)
                errors = list(Draft202012Validator(schema).iter_errors(data))
                result["invalid_fields"] = sorted(
                    {
                        str(error.path[0]) if error.path else "input"
                        for error in errors
                        if error.validator != "required"
                    }
                )
                if (
                    errors
                    and requested_seconds is not None
                    and _validation_rejects_duration(errors)
                ):
                    duration_field = duration_field_name(schema.get("properties", {}))
                    duration_info = {
                        "status": "unsupported",
                        "field": duration_field,
                        "source": "live_schema_validation",
                        "reason": "The full live schema rejects this "
                        "duration with the selected parameters.",
                    }
                    result["duration_support"] = duration_info
                    result["duration_support_status"] = "unsupported"
                    result["duration_support_message_ru"] = _duration_support_message_ru(
                        duration_info, requested_seconds
                    )
                    result["reason"] = duration_info["reason"]
                if not errors and not result.get("reason"):
                    preview = await self.estimate_contract(
                        contract,
                        model,
                        data,
                        input_video_duration_seconds=input_video_duration_seconds,
                    )
                    result.update(
                        {
                            key: preview.get(key)
                            for key in (
                                "estimated_cost_usd",
                                "estimated_credits",
                                "confidence",
                                "pricing_source",
                            )
                        }
                    )
                    unknown = preview["confidence"] == "unknown"
                    result["risk_ack_required"] = unknown
                    result["risk_reserve_usd"] = self.settings.limits.task_usd if unknown else None
                    result["pricing_warning_ru"] = (
                        self.unknown_price_warning_ru() if unknown else None
                    )
                    if unknown:
                        result["message_ru"] += (
                            " Цена не определена. Подготовка возможна только после "
                            "явного согласия пользователя на риск."
                        )
                    result["effective_parameters"] = {
                        key: data.get(info["field"], info.get("default"))
                        for key, info in capabilities(schema).items()
                    }
                    price_input_type = (
                        selected_input_type
                        if operation == "generate_video"
                        else "image"
                        if operation in IMAGE_OPERATIONS
                        else "text"
                    )
                    price_provisional, price_assumptions = _source_duration_assumptions(
                        price_input_type,
                        has_image,
                        has_video,
                        input_video_duration_seconds,
                    )
                    result["price_is_provisional"] = price_provisional
                    result["price_assumptions"] = price_assumptions
                    resolved_duration_info = preview.get("duration_support") or duration_info
                    result["duration_support"] = resolved_duration_info
                    if (
                        resolved_duration_info
                        and resolved_duration_info.get("status") == "uncertain"
                        and "Input-video duration is needed"
                        in (resolved_duration_info.get("reason") or "")
                        and "input_video_duration_seconds" not in result["missing_inputs"]
                    ):
                        result["missing_inputs"].append("input_video_duration_seconds")
                    result["duration_support_message_ru"] = _duration_support_message_ru(
                        result["duration_support"], requested_seconds
                    )
                    result["duration_warning_ru"] = (
                        "Точная длительность не подтверждена схемой или описанием KIE."
                        if resolved_duration_info
                        and resolved_duration_info["status"] == "uncertain"
                        else "Модель выберет длительность сама; "
                        "запрошенное число секунд не гарантируется."
                        if resolved_duration_info
                        and resolved_duration_info["status"] == "automatic"
                        else None
                    )
                    result["input_video_duration_note_ru"] = (
                        "Длительность исходного ролика указана "
                        "пользователем и локально не проверена."
                        if comparison_has_video and input_video_duration_seconds is not None
                        else None
                    )
            except GuardError as exc:
                result["reason"] = str(exc)
                result["message_ru"] += " Параметры нельзя сопоставить со схемой выбранной модели."
        else:
            result["missing_inputs"].append("model")
        result["status"] = (
            "needs_input"
            if result["missing_inputs"]
            else "needs_parameters"
            if result.get("invalid_fields") or result.get("reason")
            else "ready_for_preview"
        )
        result["next_step"] = (
            "supply_missing_inputs"
            if result["status"] == "needs_input"
            else "review_parameters"
            if result["status"] == "needs_parameters"
            else "confirm_unknown_price"
            if result.get("risk_ack_required")
            else "friendly_tool_dry_run"
        )
        return result

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
        accept_unknown_price: bool = False,
        input_type: str = "auto",
        video_path: str | None = None,
        video_url: str | None = None,
        input_video_duration_seconds: int | float | None = None,
    ):
        """Prepare a single task, never silently execute a chain or a paid request."""
        if type(accept_unknown_price) is not bool:
            raise GuardError("Unknown-price acceptance must be an explicit boolean")
        if image_path and image_url:
            raise GuardError("Supply one image source")
        if video_path and video_url:
            raise GuardError("Supply one video source")
        if operation != "generate_video" and (video_path or video_url or input_type != "auto"):
            raise GuardError("input_type and video input are only supported for generate_video")
        parameters = copy.deepcopy(parameters or {})
        duration_intent = {"status": "not_applicable", "seconds": None, "values": []}
        if operation == "generate_video":
            parameters, duration_intent = normalize_duration_request(
                parameters, prompt, model_input
            )
            if duration_intent["status"] in {"ambiguous", "conflict", "invalid"}:
                return {
                    "operation": operation,
                    "status": "needs_clarification",
                    "duration_request": duration_intent,
                    "message_ru": _duration_intent_message_ru(duration_intent),
                    "reservation_created": False,
                    "media_uploaded": False,
                    "execution_blocked": True,
                    "next_step": "clarify_duration",
                }
        input_video_duration_seconds = _normalize_input_video_duration(input_video_duration_seconds)
        if (
            operation == "generate_video"
            and input_type == "auto"
            and not (image_path or image_url or video_path or video_url)
            and not (
                has_video_input_payload(model_input or {}) or _model_input_has_image(model_input)
            )
            and prompt_requests_video_input(prompt)
        ):
            input_type = "video"
        if model is None and not auto_select:
            return await self.compare_models(
                operation,
                prompt,
                image_path,
                image_url,
                parameters,
                model_input,
                input_type=input_type,
                video_path=video_path,
                video_url=video_url,
                input_video_duration_seconds=input_video_duration_seconds,
            )
        selected_input_type, has_image, has_video = _resolve_input_type(
            input_type,
            image_path,
            image_url,
            video_path,
            video_url,
            model_input,
        )
        if input_video_duration_seconds is not None and selected_input_type != "video":
            raise GuardError("input_video_duration_seconds requires Video-to-Video input")
        if operation != "generate_video" and selected_input_type == "video":
            raise GuardError("Video input is only supported for generate_video")
        if (image_path or image_url) and _model_input_has_image(model_input):
            raise GuardError("Supply the image source once")
        if (video_path or video_url) and has_video_input_payload(model_input or {}):
            raise GuardError("Supply the video source once")
        comparison_has_image = selected_input_type == "image" or operation in IMAGE_OPERATIONS
        comparison_has_video = operation == "generate_video" and selected_input_type == "video"
        if operation in IMAGE_OPERATIONS and not has_image:
            raise GuardError("This operation requires an input image")
        if operation == "generate_video" and selected_input_type in {"image", "video"}:
            if selected_input_type == "image" and not has_image:
                raise GuardError("Image-to-Video requires an input image")
            if selected_input_type == "video" and not has_video:
                raise GuardError("Video-to-Video requires an input video")
        if image_path:
            with open_upload(
                image_path, self.settings.allowed_upload_root, self.settings.max_upload_bytes
            ):
                pass
        if video_path:
            with open_upload(
                video_path, self.settings.allowed_upload_root, self.settings.max_upload_bytes
            ):
                pass
        trusted_image_url = None
        if image_url:
            host = validate_url(image_url)
            if host == "tempfile.redpandaai.co":
                await resolve_public(host)
                trusted_image_url = image_url
        trusted_video_url = None
        if video_url:
            host = validate_url(video_url)
            if host == "tempfile.redpandaai.co":
                await resolve_public(host)
                trusted_video_url = video_url
        if model is None:
            catalog = await self.model_candidates(
                operation,
                selected_input_type == "image" or operation in IMAGE_OPERATIONS,
                has_video=comparison_has_video,
            )
            candidates = catalog["models"]
            if auto_select and not catalog.get("catalog_complete", True):
                return {
                    "operation": operation,
                    "input_type": selected_input_type,
                    "status": "catalog_incomplete",
                    "selection_required": True,
                    "failed_categories": catalog.get("failed_categories", []),
                    "catalog_complete": False,
                    "models": [item.get("model") for item in candidates[:20]],
                    "reservation_created": False,
                    "media_uploaded": False,
                    "execution_blocked": True,
                    "message_ru": (
                        "Автоматический выбор остановлен: KIE не вернул полный список "
                        "категорий моделей. Сравните доступные варианты через "
                        "kie_compare_models после восстановления недоступных категорий. "
                        "Ничего не загружено и не зарезервировано."
                    ),
                    "next_step": "kie_compare_models",
                }
        else:
            candidates = [{"model": model}]
        if not candidates:
            raise GuardError("No suitable live media models found")
        # Select only models whose live schema supports the requested duration.
        options = []
        unpriced = []
        over_limit = []
        uncertain_video_constraints = []
        for candidate in candidates[:20]:
            name = candidate["model"]
            try:
                contract = await self.contract(name)
                schema = contract["schema"].get("properties", {}).get("input", {})
                requested_seconds = duration_intent.get("seconds")
                duration_info = None
                if operation == "generate_video" and (
                    requested_seconds is not None or comparison_has_video
                ):
                    duration_info = duration_support(
                        schema,
                        requested_seconds,
                        has_video_input=comparison_has_video,
                        input_video_duration_seconds=input_video_duration_seconds,
                    )
                    if duration_info["status"] == "unsupported":
                        if model is not None:
                            if (
                                duration_info.get("maximum_input_video_duration_seconds")
                                is not None
                            ):
                                raise GuardError(
                                    "Input-video duration is outside provider-declared limits"
                                )
                            raise GuardError(
                                "Requested video duration is outside provider-declared limits"
                            )
                        continue
                    if model is None:
                        status = duration_info["status"]
                        if requested_seconds == -1:
                            if status not in {"automatic", "supported"}:
                                if comparison_has_video and status == "uncertain":
                                    uncertain_video_constraints.append((name, duration_info))
                                continue
                        elif requested_seconds is not None and status != "supported":
                            if comparison_has_video and status == "uncertain":
                                uncertain_video_constraints.append((name, duration_info))
                            continue
                        elif comparison_has_video and status == "uncertain":
                            uncertain_video_constraints.append((name, duration_info))
                            continue
                data, image_field, mapping = map_input(
                    schema,
                    parameters,
                    prompt,
                    comparison_has_image,
                    trusted_image_url,
                    operation,
                    model_input,
                    has_video=comparison_has_video,
                    video_url=trusted_video_url,
                )
                data = apply_defaults(data, schema)
                schema_errors = list(Draft202012Validator(schema).iter_errors(data))
                if (
                    schema_errors
                    and requested_seconds is not None
                    and _validation_rejects_duration(schema_errors)
                ):
                    raise GuardError("Requested video duration is outside provider-declared limits")
                preview = await self.estimate_contract(
                    contract,
                    name,
                    data,
                    input_video_duration_seconds=input_video_duration_seconds,
                )
            except GuardError:
                if model is not None:
                    raise  # An explicit model must report the actual compatibility problem.
                continue
            if duration_info is None:
                duration_info = preview.get("duration_support")
            if preview["estimated_cost_usd"] is not None:
                option = (
                    preview["estimated_cost_usd"],
                    name,
                    data,
                    image_field,
                    mapping,
                    preview,
                    duration_info,
                    contract,
                )
                if preview["estimated_cost_usd"] > self.settings.limits.task_usd:
                    over_limit.append(option)
                else:
                    options.append(option)
            else:
                unpriced.append(
                    (
                        None,
                        name,
                        data,
                        image_field,
                        mapping,
                        preview,
                        duration_info,
                        contract,
                    )
                )
        if not options:
            if model is not None and unpriced:
                if not accept_unknown_price or dry_run:
                    _, selected, data, image_field, mapping, preview, duration_info, contract = (
                        unpriced[0]
                    )
                    source_duration_missing = (
                        comparison_has_video
                        and duration_info is not None
                        and duration_info.get("status") == "uncertain"
                        and "Input-video duration is needed" in (duration_info.get("reason") or "")
                    )
                    price_input_type = (
                        selected_input_type
                        if operation == "generate_video"
                        else "image"
                        if operation in IMAGE_OPERATIONS
                        else "text"
                    )
                    provisional, assumptions = _source_duration_assumptions(
                        price_input_type,
                        has_image,
                        has_video,
                        input_video_duration_seconds,
                    )
                    if price_input_type == "image" and trusted_image_url:
                        provisional, assumptions = False, {}
                    return {
                        "model": selected,
                        "selected_model": selected,
                        "operation": operation,
                        "input_type": selected_input_type,
                        "estimated_cost_usd": None,
                        "estimated_credits": None,
                        "confidence": "unknown",
                        "pricing_source": preview["pricing_source"],
                        "pricing_description": preview["pricing_description"],
                        "pricing_conditions": preview.get("pricing_conditions"),
                        "effective_parameters": {
                            key: data.get(info["field"], info.get("default"))
                            for key, info in capabilities(
                                contract["schema"].get("properties", {}).get("input", {})
                            ).items()
                        },
                        "price_is_provisional": provisional,
                        "price_assumptions": assumptions,
                        "duration_request": duration_intent,
                        "duration_support": duration_info,
                        "duration_support_message_ru": _duration_support_message_ru(
                            duration_info, duration_intent.get("seconds")
                        ),
                        "video_input_constraints": video_capabilities(
                            contract["schema"].get("properties", {}).get("input", {})
                        ),
                        "risk_ack_required": True,
                        "risk_acknowledged": False,
                        "risk_reserve_usd": self.settings.limits.task_usd,
                        "missing_inputs": (
                            ["input_video_duration_seconds"] if source_duration_missing else []
                        ),
                        "pricing_warning_ru": self.unknown_price_warning_ru(),
                        "confirmation_summary_ru": preview["confirmation_summary_ru"],
                        "message_ru": (
                            self.unknown_price_warning_ru()
                            + (
                                " Для проверки лимита KIE дополнительно нужна длительность "
                                "исходного ролика в секундах."
                                if source_duration_missing
                                else ""
                            )
                            + " Загрузка исходника не выполнялась."
                        ),
                        "dry_run": dry_run,
                        "reservation_created": False,
                        "execution_blocked": True,
                        "next_step": (
                            "supply_input_video_duration_seconds"
                            if source_duration_missing
                            else "confirm_unknown_price"
                        ),
                        "media_uploaded": False,
                        "parameter_mapping": mapping,
                        "image_field": image_field,
                        "video_field": (
                            selected_video_field(
                                contract["schema"].get("properties", {}).get("input", {}),
                                model_input,
                            )
                            if comparison_has_video
                            else None
                        ),
                        "selection_scope": "explicit_model",
                    }
                options = unpriced
            elif model is None and unpriced:
                unknown_models = []
                for (
                    _,
                    name,
                    data,
                    _image_field,
                    _mapping,
                    preview,
                    duration_info,
                    contract,
                ) in unpriced:
                    schema = contract["schema"].get("properties", {}).get("input", {})
                    price_input_type = (
                        selected_input_type
                        if operation == "generate_video"
                        else "image"
                        if operation in IMAGE_OPERATIONS
                        else "text"
                    )
                    provisional, assumptions = _source_duration_assumptions(
                        price_input_type,
                        has_image,
                        has_video,
                        input_video_duration_seconds,
                    )
                    if price_input_type == "image" and trusted_image_url:
                        provisional, assumptions = False, {}
                    unknown_models.append(
                        {
                            "model": name,
                            "compatible": True,
                            "duration_support": duration_info,
                            "duration_support_status": (
                                duration_info.get("status") if duration_info else None
                            ),
                            "duration_support_message_ru": _duration_support_message_ru(
                                duration_info, duration_intent.get("seconds")
                            ),
                            "estimated_cost_usd": None,
                            "confidence": "unknown",
                            "pricing_source": preview["pricing_source"],
                            "pricing_description": preview.get("pricing_description"),
                            "pricing_conditions": preview.get("pricing_conditions"),
                            "effective_parameters": {
                                key: data.get(info["field"], info.get("default"))
                                for key, info in capabilities(schema).items()
                            },
                            "price_is_provisional": provisional,
                            "price_assumptions": assumptions,
                            "risk_ack_required": True,
                            "risk_reserve_usd": self.settings.limits.task_usd,
                            "pricing_warning_ru": self.unknown_price_warning_ru(),
                            "video_field": (
                                selected_video_field(schema, model_input)
                                if comparison_has_video
                                else None
                            ),
                        }
                    )
                over_limit_models = [
                    {
                        "model": item[1],
                        "estimated_cost_usd": item[0],
                        "confidence": item[5]["confidence"],
                        "pricing_source": item[5]["pricing_source"],
                        "duration_support": item[6],
                    }
                    for item in over_limit
                ]
                return {
                    "operation": operation,
                    "input_type": selected_input_type,
                    "status": "unknown_price_options",
                    "selection_required": True,
                    "duration_request": duration_intent,
                    "models": unknown_models,
                    "over_task_limit_models": over_limit_models,
                    "catalog_complete": catalog.get("catalog_complete", True)
                    if model is None
                    else None,
                    "failed_categories": catalog.get("failed_categories", [])
                    if model is None
                    else [],
                    "risk_ack_required": True,
                    "risk_reserve_usd": self.settings.limits.task_usd,
                    "pricing_warning_ru": self.unknown_price_warning_ru(),
                    "reservation_created": False,
                    "media_uploaded": False,
                    "execution_blocked": True,
                    "message_ru": (
                        "Автоматический выбор остановлен: у совместимых моделей цена не "
                        "определена. Выберите модель явно; подготовка возможна только после "
                        "отдельного согласия на риск. Локальный резерв равен лимиту одной "
                        "задачи, а списание KIE может быть выше. Исходник не загружен."
                    ),
                    "next_step": "select_model_then_confirm_unknown_price",
                }
            elif over_limit:
                over_limit_models = [
                    {
                        "model": item[1],
                        "estimated_cost_usd": item[0],
                        "confidence": item[5]["confidence"],
                        "pricing_source": item[5]["pricing_source"],
                        "duration_support": item[6],
                    }
                    for item in over_limit
                ]
                return {
                    "operation": operation,
                    "input_type": selected_input_type,
                    "status": "over_task_limit",
                    "selection_required": True,
                    "duration_request": duration_intent,
                    "models": over_limit_models,
                    "catalog_complete": catalog.get("catalog_complete", True)
                    if model is None
                    else None,
                    "failed_categories": catalog.get("failed_categories", [])
                    if model is None
                    else [],
                    "task_limit_usd": self.settings.limits.task_usd,
                    "reservation_created": False,
                    "media_uploaded": False,
                    "execution_blocked": True,
                    "message_ru": (
                        "Оценка проверенных совместимых моделей превышает локальный "
                        "лимит одной задачи. Запрос и исходник не отправлялись. Выберите "
                        "другую модель или параметры с более низкой оценкой."
                    ),
                    "next_step": "kie_compare_models",
                }
            elif model is None and comparison_has_video and uncertain_video_constraints:
                missing_duration = any(
                    "Input-video duration is needed" in (info.get("reason") or "")
                    for _, info in uncertain_video_constraints
                )
                return {
                    "operation": operation,
                    "input_type": selected_input_type,
                    "status": "video_input_constraints_uncertain",
                    "selection_required": True,
                    "duration_request": duration_intent,
                    "models": [
                        {
                            "model": name,
                            "duration_support": info,
                            "duration_support_status": info.get("status"),
                            "duration_support_message_ru": _duration_support_message_ru(
                                info, duration_intent.get("seconds")
                            ),
                        }
                        for name, info in uncertain_video_constraints
                    ],
                    "missing_inputs": (
                        ["input_video_duration_seconds"] if missing_duration else []
                    ),
                    "catalog_complete": catalog.get("catalog_complete", True),
                    "failed_categories": catalog.get("failed_categories", []),
                    "reservation_created": False,
                    "media_uploaded": False,
                    "execution_blocked": True,
                    "message_ru": (
                        "Автоматический выбор остановлен: ограничения входного видео "
                        "для этих моделей не подтверждены. Укажите input_video_duration_seconds, "
                        "если его требует схема, или выберите модель после kie_compare_models "
                        "и kie_preflight. Исходник не загружен."
                    ),
                    "next_step": (
                        "supply_input_video_duration" if missing_duration else "kie_compare_models"
                    ),
                }
            else:
                if operation == "generate_video" and duration_intent.get("seconds") is not None:
                    return {
                        "operation": operation,
                        "input_type": selected_input_type,
                        "status": "no_confirmed_duration_match",
                        "duration_request": duration_intent,
                        "selection_required": True,
                        "models": [],
                        "catalog_complete": catalog.get("catalog_complete", True)
                        if model is None
                        else None,
                        "failed_categories": catalog.get("failed_categories", [])
                        if model is None
                        else [],
                        "reservation_created": False,
                        "media_uploaded": False,
                        "execution_blocked": True,
                        "message_ru": (
                            "Среди первых 20 кандидатов каталога не найдено модели с "
                            "подтверждённой поддержкой этой длительности и известной ценой. "
                            "Вызовите "
                            "kie_compare_models и просмотрите страницы next_cursor; "
                            "ограничения с неопределённым статусом не считаются подтверждёнными."
                        ),
                        "next_step": "kie_compare_models",
                    }
                raise GuardError(
                    "No verified compatible price for automatic selection; choose a model "
                    "explicitly before accepting unknown-price risk"
                )
        (
            _,
            selected,
            data,
            image_field,
            mapping,
            selected_preview,
            selected_duration_info,
            selected_contract,
        ) = min(options, key=lambda item: item[0]) if options[0][0] is not None else options[0]
        selected_schema = selected_contract["schema"].get("properties", {}).get("input", {})
        selected_duration_info = selected_preview.get("duration_support") or selected_duration_info
        if (
            comparison_has_video
            and selected_duration_info
            and selected_duration_info.get("status") == "uncertain"
            and "Input-video duration is needed" in (selected_duration_info.get("reason") or "")
        ):
            price_input_type = "video"
            provisional, assumptions = _source_duration_assumptions(
                price_input_type,
                has_image,
                has_video,
                input_video_duration_seconds,
            )
            unknown = selected_preview.get("confidence") == "unknown"
            return {
                "operation": operation,
                "model": selected,
                "selected_model": selected,
                "input_type": selected_input_type,
                "status": "needs_input",
                "missing_inputs": ["input_video_duration_seconds"],
                "duration_request": duration_intent,
                "duration_support": selected_duration_info,
                "duration_support_message_ru": _duration_support_message_ru(
                    selected_duration_info, duration_intent.get("seconds")
                ),
                "estimated_cost_usd": selected_preview.get("estimated_cost_usd"),
                "estimated_credits": selected_preview.get("estimated_credits"),
                "confidence": selected_preview.get("confidence"),
                "pricing_source": selected_preview.get("pricing_source"),
                "price_is_provisional": provisional,
                "price_assumptions": assumptions,
                "risk_ack_required": unknown and not accept_unknown_price,
                "risk_acknowledged": unknown and accept_unknown_price,
                "risk_reserve_usd": (self.settings.limits.task_usd if unknown else None),
                "pricing_warning_ru": selected_preview.get("pricing_warning_ru"),
                "confirmation_summary_ru": selected_preview.get("confirmation_summary_ru"),
                "reservation_created": False,
                "media_uploaded": False,
                "execution_blocked": True,
                "message_ru": (
                    "KIE требует длительность исходного ролика для проверки лимита. "
                    "Укажите её в секундах; MCP не измеряет файл. Генерация и загрузка "
                    "не выполнялись."
                ),
                "next_step": "supply_input_video_duration_seconds",
            }
        if selected_input_type == "image" and (image_path or image_url):
            if trusted_image_url:
                url = trusted_image_url
            elif image_url:
                content = await fetch_bytes(image_url, self.settings.max_upload_bytes)
                upload = await self.client.upload_bytes(content)
                url = upload.get("data", {}).get("downloadUrl")
            else:
                upload = await self.client.upload_local_file(image_path, "mcp/files", None)
                url = upload.get("data", {}).get("downloadUrl")
            if not url or image_field is None:
                raise GuardError("Upload did not return a media URL")
            data[image_field] = [url] if isinstance(data[image_field], list) else url
        video_field = None
        if comparison_has_video:
            video_field = selected_video_field(selected_schema, model_input)
            if video_field is None:
                raise GuardError("Model has no unambiguous declared video-input field")
            if video_path or video_url:
                if trusted_video_url:
                    url = trusted_video_url
                elif video_url:
                    content = await fetch_bytes(video_url, self.settings.max_upload_bytes)
                    upload = await self.client.upload_bytes(content)
                    url = upload.get("data", {}).get("downloadUrl")
                else:
                    upload = await self.client.upload_local_file(video_path, "mcp/files", None)
                    url = upload.get("data", {}).get("downloadUrl")
                if not url:
                    raise GuardError("Video upload did not return a media URL")
                data[video_field] = [url] if isinstance(data[video_field], list) else url
        result = await self.prepare(
            selected,
            data,
            dry_run=dry_run,
            accept_unknown_price=accept_unknown_price,
            input_video_duration_seconds=input_video_duration_seconds,
        )
        risk_ack_required = bool(result.get("risk_ack_required"))
        price_input_type = (
            selected_input_type
            if operation == "generate_video"
            else "image"
            if operation in IMAGE_OPERATIONS
            else "text"
        )
        provisional, assumptions = _source_duration_assumptions(
            price_input_type,
            has_image,
            has_video,
            input_video_duration_seconds,
        )
        if price_input_type == "image" and trusted_image_url:
            provisional, assumptions = False, {}
        return {
            **result,
            "operation": operation,
            "input_type": selected_input_type,
            "duration_request": duration_intent,
            "duration_support": result.get("duration_support") or selected_duration_info,
            "video_input_constraints": video_capabilities(selected_schema),
            "input_video_duration_note_ru": (
                "Длительность исходного ролика указана пользователем и локально не проверена."
                if comparison_has_video and input_video_duration_seconds is not None
                else None
            ),
            "price_is_provisional": provisional,
            "price_assumptions": assumptions,
            "next_step": result.get("next_step")
            or ("kie_prepare_task" if dry_run else "kie_execute_task"),
            "execution_blocked": bool(result.get("execution_blocked", risk_ack_required)),
            "selected_model": selected,
            "parameter_mapping": mapping,
            "image_field": image_field,
            "video_field": video_field,
            "selection_scope": "explicit_model" if model else "first_20_catalog_candidates",
            "catalog_complete": catalog.get("catalog_complete", True) if model is None else None,
            "failed_categories": catalog.get("failed_categories", []) if model is None else [],
        }
