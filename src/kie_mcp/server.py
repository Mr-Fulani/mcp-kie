"""Local stdio MCP facade; all paid media runs through KieService approvals."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from mcp.server.fastmcp import Context, FastMCP

from .catalog import CATALOG, get_catalog_entry, search_catalog
from .client import KieClient, fetch_documentation
from .config import Settings
from .errors import KieAPIError
from .ledger import GuardError
from .network import fetch_bytes
from .security import redact
from .service import KieService

try:
    settings = Settings.from_env()
except Exception:
    raise SystemExit("Invalid owner configuration; sensitive details withheld.") from None
client = KieClient(settings)
service = KieService(settings, client)
mcp = FastMCP(
    "Secure KIE media",
    instructions=(
        "Общайтесь с пользователем по-русски. Перед разрешением на вызов объясняйте "
        "по-русски действие, передачу файлов и возможные расходы; не предлагайте "
        "подтверждать непонятный текст. Для сравнения исходное фото не нужно. "
        "Для видео учитывайте длительность из prompt/duration и показывайте статус "
        "совместимости каждой модели. Для input_type=video показывайте "
        "task_types/is_video_to_video_model отдельно от reference-полей; "
        "видеореференс не гарантирует покадровое редактирование. "
        "После выбора модели вызовите kie_preflight до загрузки/preview/prepare. "
        "Показывайте message_ru, требования, недостающие поля и предварительность цены. "
        "Перед платным выполнением покажите confirmation_summary_ru и параметры. "
        "Медиа-инструменты работают через локальный stdio. Сначала получите живые "
        "модели, схемы и цены. kie_create_task по умолчанию делает dry_run; prepare "
        "резервирует бюджет, execute требует approval_id и неизменённый запрос. "
        "Неизвестная цена требует явного согласия пользователя на риск через "
        "accept_unknown_price=true при подготовке; локально резервируется лимит задачи, "
        "а фактическое списание KIE может быть выше. "
        "После завершения сообщайте USD только если billing_reconciliation.cost_status="
        "reported_by_kie; не переводите кредиты или изменение баланса в USD. "
        "Без model удобные команды возвращают сравнение: покажите варианты и дождитесь "
        "выбора. auto_select=true допустим только при явном поручении выбрать самый "
        "дешёвый вариант среди первых 20 кандидатов. С model команда готовит одну "
        "задачу или preview при dry_run=true; preview по фото/видео может загрузить исходник. "
        "Выполнение, ожидание и скачивание — отдельные шаги. Таймаут ожидания "
        "не является ошибкой генерации: продолжайте проверять тот же task_id без "
        "повторной платной отправки и без нового согласия на запуск. Показывайте "
        "task_progress и polling: статус KIE, время ожидания и следующий шаг; "
        "не придумывайте процент или ETA. Не обходите защиту "
        "через shell, прямые API или другие медиа-навыки."
    ),
    json_response=True,
)


def identity(ctx: Context) -> None:
    params = ctx.session.client_params
    if params:
        service.client_name = params.clientInfo.name[:100]
        service.client_version = params.clientInfo.version[:100]


async def safe_call(coro: Any) -> dict[str, Any]:
    try:
        value = await coro
        result = value if isinstance(value, dict) else {"data": value}
        cleaned = redact(result, settings.api_key)
        # A server-generated result path inside the configured root is intended output.
        for key in ("output_path", "output_folder"):
            output = result.get(key)
            if output and settings.allowed_download_root is not None:
                Path(output).resolve().relative_to(settings.allowed_download_root.resolve())
                cleaned[key] = output
        return cleaned
    except GuardError as exc:
        messages = {
            "This operation requires an input image": (
                "Для обработки нужен исходник: укажите image_path или image_url. "
                "Сравнить модели можно без фото через kie_compare_models."
            ),
            "Supply one image source": "Укажите один исходник: image_path или image_url.",
            "Supply one video source": "Укажите один исходный ролик: video_path или video_url.",
            "Supply the image source once": "Укажите изображение только одним способом.",
            "Supply the video source once": "Укажите видео только одним способом.",
            "Supply either an image input or a video input, not both": (
                "Для generate_video выберите один тип входа: изображение или видео."
            ),
            "input_type must be auto, text, image or video": (
                "input_type должен быть auto, text, image или video."
            ),
            "Text-to-Video cannot include an image or video source": (
                "Для Text-to-Video не передавайте исходное изображение или видео."
            ),
            "Image-to-Video requires an input image": (
                "Для Image-to-Video укажите исходное изображение через image_path или image_url."
            ),
            "Video-to-Video requires an input video": (
                "Для Video-to-Video укажите исходный ролик через video_path или video_url."
            ),
            "Video input is only supported for generate_video": (
                "Входное видео поддерживается только инструментом generate_video."
            ),
            "input_type and video input are only supported for generate_video": (
                "input_type и видеовход доступны только для generate_video."
            ),
            "input_video_duration_seconds requires Video-to-Video input": (
                "input_video_duration_seconds применяется только к Video-to-Video."
            ),
            "input_video_duration_seconds must be a positive number": (
                "Укажите положительную длительность исходного ролика в секундах."
            ),
            "Model has no unambiguous declared video-input field": (
                "В схеме выбранной модели нет однозначного поля для входного видео."
            ),
            "input_type conflicts with the supplied media source": (
                "Выбранный input_type не совпадает с переданным типом исходного файла."
            ),
            "Requested video duration is outside provider-declared limits": (
                "Выбранная длительность выходит за ограничения этой модели KIE."
            ),
            "Input-video duration is outside provider-declared limits": (
                "Длительность исходного ролика превышает опубликованный предел модели KIE."
            ),
            (
                "Input-video duration is required by the "
                "provider limits; run kie_preflight and supply it"
            ): (
                "Схема KIE требует длительность исходного ролика "
                "для проверки лимита; укажите её в kie_preflight."
            ),
            "Input does not satisfy the live model schema": (
                "Данные не соответствуют схеме модели. Вызовите kie_preflight: "
                "он покажет обязательные поля и допустимые параметры."
            ),
            "Unknown friendly operation": "Неизвестная операция; проверьте описание инструмента.",
        }
        return {
            "error": redact(str(exc), settings.api_key),
            "blocked": True,
            "message_ru": messages.get(
                str(exc),
                (
                    "Операция заблокирована защитой Secure KIE MCP. "
                    "Объясните пользователю причину по-русски до следующих действий."
                ),
            ),
        }
    except KieAPIError as exc:
        return {
            **redact(exc.as_dict(), settings.api_key),
            "message_ru": (
                "KIE вернул ошибку. Объясните её по-русски; платный запрос не повторяйте."
            ),
        }
    except Exception:
        return {
            "error": "Operation failed; sensitive details withheld.",
            "message_ru": "Операция не выполнена; чувствительные детали скрыты.",
        }


@mcp.resource("kie://docs/overview")
def docs_overview() -> str:
    return json.dumps(
        {
            "transport": "stdio",
            "api_base": settings.api_base,
            "upload_base": settings.upload_base,
            "paid_flow": "prepare/execute",
            "unknown_pricing": "explicit_user_risk_acknowledgement_required",
            "unknown_price_reserve": "configured_per_task_limit; provider charge may exceed",
            "temporary_results": True,
        }
    )


@mcp.resource("kie://docs/catalog")
def docs_catalog() -> str:
    return json.dumps(CATALOG, ensure_ascii=False)


@mcp.resource("kie://docs/entry/{slug}")
def docs_entry(slug: str) -> str:
    return json.dumps(get_catalog_entry(slug) or {"error": "Unknown documentation slug"})


@mcp.tool()
async def kie_search_docs(query: str, limit: int = 10) -> dict[str, Any]:
    """Поиск в живом официальном индексе документации; офлайн-резерв явно помечается."""
    try:
        raw = await fetch_bytes(
            "https://docs.kie.ai/llms.txt", 2_000_000, allowed_hosts={"docs.kie.ai"}
        )
        import re

        lines = raw.decode("utf-8").splitlines()
        matches = []
        tokens = query.lower().split()
        for line in lines:
            match = re.search(r"\[([^]]+)\]\((https://docs\.kie\.ai/[^)]+)\)", line)
            if match and (not tokens or any(token in line.lower() for token in tokens)):
                matches.append({"title": match[1], "url": match[2]})
        return {"source": "live_docs_index", "results": matches[: max(1, min(limit, 50))]}
    except Exception:
        return {
            "source": "bundled_offline_fallback",
            "results": search_catalog(query, limit),
            "warning": "Live index unavailable; bundled entries may be stale.",
        }


@mcp.tool()
async def kie_get_documentation(slug_or_url: str, max_characters: int = 60_000) -> dict:
    """Прочитать актуальную документацию по slug или HTTPS-ссылке docs.kie.ai."""

    async def get():
        entry = get_catalog_entry(slug_or_url)
        url = entry["url"] if entry else slug_or_url
        text = await fetch_documentation(url)
        limit = max(1000, min(max_characters, 200_000))
        return {"url": url, "content": text[:limit], "truncated": len(text) > limit}

    return await safe_call(get())


@mcp.tool()
async def kie_list_models(query: str = "", task_type: str | None = None) -> dict:
    """Получить живой список моделей KIE; query — поиск, task_type — тип задачи."""
    return await safe_call(service.search_models(query, task_type))


@mcp.tool()
async def kie_get_model_schema(model: str) -> dict:
    """Получить актуальную схему модели: обязательные поля, параметры и ограничения."""
    return await safe_call(service.contract(model))


@mcp.tool()
async def kie_estimate_cost(
    model: str,
    input: dict[str, Any],
    input_video_duration_seconds: float | None = None,
) -> dict:
    """Проверить схему и цену.

    unknown значит, что перед подготовкой потребуется явное согласие на риск.
    """
    return await safe_call(
        service.estimate(
            model,
            input,
            input_video_duration_seconds=input_video_duration_seconds,
        )
    )


@mcp.tool()
async def kie_prepare_task(
    ctx: Context,
    model: str,
    input: dict[str, Any],
    dry_run: bool = False,
    accept_unknown_price: bool = False,
    input_video_duration_seconds: float | None = None,
):
    """Подготовить неизменённый запрос и зарезервировать бюджет.

    Сначала kie_preflight и просмотр модели, параметров, цены по-русски.
    dry_run=true не резервирует деньги и не отправляет платную задачу.
    Для Video-to-Video input_video_duration_seconds — оценка пользователя, не проверенная по файлу;
    значение сохраняется в approval и повторно используется при execute.
    Если confidence=unknown, сначала покажите предупреждение пользователю и дождитесь
    явного согласия на риск. Только после согласия повторите вызов с
    accept_unknown_price=true. Будет зарезервирован лимит одной задачи; списание KIE
    может оказаться выше. Этот вызов только готовит запрос; покажите
    confirmation_summary_ru перед execute.
    """
    identity(ctx)
    return await safe_call(
        service.prepare(
            model,
            input,
            dry_run=dry_run,
            accept_unknown_price=accept_unknown_price,
            input_video_duration_seconds=input_video_duration_seconds,
        )
    )


@mcp.tool()
async def kie_create_task(
    ctx: Context,
    model: str,
    input: dict[str, Any],
    dry_run: bool = True,
    approval_id: str | None = None,
):
    """Просмотр по умолчанию. Для платного запуска подготовьте approval_id.

    При unknown сначала получите явное согласие на риск через kie_prepare_task.
    """
    identity(ctx)
    if dry_run:
        return await safe_call(service.prepare(model, input, dry_run=True))
    if approval_id is None:
        return {
            "error": "Prepare first; approval_id is required for paid execution",
            "message_ru": "Сначала подготовьте запрос: платный запуск требует approval_id.",
            "blocked": True,
        }
    return await safe_call(service.execute(approval_id, model, input))


@mcp.tool()
async def kie_execute_task(ctx: Context, approval_id: str, model: str, input: dict[str, Any]):
    """Выполнить один подготовленный платный запрос с теми же model/input.

    Перед разрешением объясните по-русски модель, параметры и стоимость или риск из prepare.
    При таймауте или неизвестном результате отправки не повторяйте запрос.
    """
    identity(ctx)
    return await safe_call(service.execute(approval_id, model, input))


@mcp.tool()
async def kie_get_task(task_id: str):
    """Получить статус, время с создания и следующий шаг; USD только из costUsd KIE."""
    return await safe_call(service.get_task(task_id))


@mcp.tool()
async def kie_wait_for_task(task_id: str, timeout_seconds: int = 900):
    """Проверять ту же задачу в пределах окна ожидания.

    polling.status=pending означает, что окно закончилось, а задача ещё активна.
    Продолжайте ждать тот же task_id без новой отправки или повторного согласия.
    Показывайте task_progress.message_ru и polling.message_ru. Процент и ETA неизвестны.
    Финальный success позволяет скачать результат; fail требует просмотра ошибки KIE.
    Сообщайте фактический USD только если его вернул KIE.
    """
    return await safe_call(service.wait(task_id, max(1, timeout_seconds)))


@mcp.tool()
async def kie_get_credits():
    """Прочитать баланс KIE без генерации и списания денег."""
    return await safe_call(client.get_credits())


@mcp.tool()
async def kie_upload_local_file(file_path: str):
    """Проверить разрешённую папку, размер и содержимое файла, затем загрузить его в KIE."""
    return await safe_call(client.upload_local_file(file_path, "mcp/files", None))


@mcp.tool()
async def kie_upload_base64(base64_data: str):
    """Проверить размер и содержимое base64, затем временно загрузить медиа в KIE."""
    return await safe_call(client.upload_base64(base64_data, "mcp/base64", None))


@mcp.tool()
async def kie_upload_from_url(file_url: str):
    """Скачать исходник с проверками DNS, перенаправлений и размера, затем загрузить в KIE."""
    return await safe_call(client.upload_from_url(file_url, "mcp/url", None))


@mcp.tool()
async def kie_get_download_url(url: str):
    """Получить временную ссылку для разрешённого хранилища KIE."""
    return await safe_call(client.get_download_url(url))


@mcp.tool()
async def kie_download_result(task_id: str, result_index: int = 0, result_label: str | None = None):
    """Сохранить результат в папку дата/тип/модель/задача.

    result_label — короткая метка, не путь.
    """
    return await safe_call(service.download(task_id, result_index, result_label))


@mcp.tool()
async def kie_compare_models(
    operation: str,
    prompt: str = "",
    image_path: str | None = None,
    image_url: str | None = None,
    parameters: dict | None = None,
    model_input: dict | None = None,
    query: str = "",
    cursor: int = 0,
    limit: int = 5,
    include_metrics: bool = False,
    input_type: Literal["auto", "text", "image", "video"] = "auto",
    video_path: str | None = None,
    video_url: str | None = None,
    input_video_duration_seconds: float | None = None,
):
    """Сравнить живые модели, параметры и цены; фото для сравнения не требуется.

    operation: generate_image, edit_image, generate_video, remove_background,
    upscale_image или product_image_create. parameters: duration, resolution,
    aspect_ratio, output_format, scale, target_resolution. Покажите варианты по-русски
    и дождитесь выбора; next_cursor даёт следующую страницу.
    Сравнение не загружает файлы и не резервирует деньги.
    limit — положительное целое число, по умолчанию 5. Если запрошено больше 10,
    MCP вернёт до 10 моделей без ошибки, effective_limit=10 и next_cursor.
    Для generate_video длительность берётся из duration
    или однозначного указания в prompt; duration_matches перечисляет подходящие модели
    текущей страницы, а duration_support показывает supported,
    unsupported, uncertain или automatic и источник ограничения. Просмотрите все
    страницы next_cursor.
    input_type=video ищет Video-to-Video и модели с видеовходом. Поля task_types,
    is_video_to_video_model и video_input_semantics различают типы кандидатов;
    video_to_video_reference_field означает, что каталог относит модель к V2V,
    а её схема принимает reference-видео. Reference поле не гарантирует покадровое
    редактирование. video_input_matches перечисляет модели на текущей странице.
    input_video_duration_seconds —
    указанная пользователем длительность исходника, файл не анализируется.
    Качество — описание провайдера, не независимая оценка. После выбора вызовите
    kie_preflight до preview/prepare; точный preview может загрузить исходное медиа в KIE.
    """
    return await safe_call(
        service.compare_models(
            operation,
            prompt,
            image_path,
            image_url,
            parameters,
            model_input,
            query=query,
            cursor=cursor,
            limit=limit,
            include_metrics=include_metrics,
            input_type=input_type,
            video_path=video_path,
            video_url=video_url,
            input_video_duration_seconds=input_video_duration_seconds,
        )
    )


@mcp.tool()
async def kie_preflight(
    operation: str,
    model: str | None = None,
    prompt: str = "",
    image_path: str | None = None,
    image_url: str | None = None,
    parameters: dict | None = None,
    model_input: dict | None = None,
    input_type: Literal["auto", "text", "image", "video"] = "auto",
    video_path: str | None = None,
    video_url: str | None = None,
    input_video_duration_seconds: float | None = None,
):
    """Заранее узнать требования и недостающие данные без загрузок и резервирования денег.

    operation как в kie_compare_models; model — выбранная пользователем модель.
    Покажите required_fields, fields, video_input_constraints, duration_support,
    missing_inputs, invalid_fields и message_ru. Для списка моделей используйте
    kie_compare_models; здесь duration_support показывает статус выбранной модели.
    Статус бывает supported, unsupported, uncertain или automatic; последний означает,
    что точную длительность выбирает сама модель.
    input_type=video включает Video-to-Video и видео-референсы.
    Форматы и размеры из описаний провайдера не переводятся автоматически: объясните
    их по-русски. Исходный файл не открывается и не проверяется. Укажите
    input_video_duration_seconds, если схема ограничивает длительность исходника или
    сумму длительностей входа/результата; это пользовательская оценка, не замер файла.
    Цена для входного медиа может быть предварительной; это не разрешение на выполнение.
    Перед последующим preview объясните передачу файла в KIE.
    """
    return await safe_call(
        service.preflight(
            operation,
            model,
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
    )


@mcp.tool()
async def generate_image(
    ctx: Context,
    prompt: str,
    model: str | None = None,
    aspect_ratio: str | None = None,
    resolution: str | None = None,
    output_format: str | None = None,
    dry_run: bool = False,
    model_input: dict | None = None,
    auto_select: bool = False,
    accept_unknown_price: bool = False,
):
    """Без model сравнить варианты; с model подготовить одно изображение или dry_run preview.

    auto_select=true разрешён только при явном поручении выбрать самый дешёвый вариант.
    При unknown покажите предупреждение и дождитесь явного согласия до установки
    accept_unknown_price=true; локальный резерв равен лимиту задачи, цена KIE может быть выше.
    """
    identity(ctx)
    params = {
        k: v
        for k, v in {
            "aspect_ratio": aspect_ratio,
            "resolution": resolution,
            "output_format": output_format,
        }.items()
        if v is not None
    }
    return await safe_call(
        service.friendly(
            "generate_image",
            prompt,
            model,
            parameters=params,
            dry_run=dry_run,
            model_input=model_input,
            auto_select=auto_select,
            accept_unknown_price=accept_unknown_price,
        )
    )


@mcp.tool()
async def edit_image(
    ctx: Context,
    prompt: str,
    image_path: str | None = None,
    image_url: str | None = None,
    model: str | None = None,
    aspect_ratio: str | None = None,
    resolution: str | None = None,
    output_format: str | None = None,
    dry_run: bool = False,
    model_input: dict | None = None,
    auto_select: bool = False,
    accept_unknown_price: bool = False,
):
    """Без model сравнить варианты без фото; с model нужен исходник.

    Сначала kie_preflight; preview может загрузить фото.
    При unknown покажите предупреждение и дождитесь явного согласия до установки
    accept_unknown_price=true; локальный резерв равен лимиту задачи, цена KIE может быть выше.
    """
    identity(ctx)
    params = {
        k: v
        for k, v in {
            "aspect_ratio": aspect_ratio,
            "resolution": resolution,
            "output_format": output_format,
        }.items()
        if v is not None
    }
    return await safe_call(
        service.friendly(
            "edit_image",
            prompt,
            model,
            image_path,
            image_url,
            params,
            dry_run=dry_run,
            model_input=model_input,
            auto_select=auto_select,
            accept_unknown_price=accept_unknown_price,
        )
    )


@mcp.tool()
async def generate_video(
    ctx: Context,
    prompt: str,
    image_path: str | None = None,
    image_url: str | None = None,
    model: str | None = None,
    duration: float | None = None,
    aspect_ratio: str | None = None,
    resolution: str | None = None,
    dry_run: bool = False,
    model_input: dict | None = None,
    auto_select: bool = False,
    accept_unknown_price: bool = False,
    input_type: Literal["auto", "text", "image", "video"] = "auto",
    video_path: str | None = None,
    video_url: str | None = None,
    input_video_duration_seconds: float | None = None,
):
    """Сгенерировать видео по тексту, изображению или входному ролику.

    duration задаётся в секундах; если его нет, MCP ищет однозначную длину в секундах
    или минутах в prompt.
    Без model сначала сравнивает модели и помечает поддержку этой длины; для Video-to-Video
    задайте video_path/video_url или укажите input_type=video при сравнении.
    Перед подготовкой сначала вызовите kie_preflight. Video reference может быть
    условием генерации и не обещает покадрового редактирования. Для комбинированных
    ограничений входа/выхода укажите input_video_duration_seconds; файл локально не измеряется.
    Preview может загрузить исходное изображение/видео в KIE.
    При unknown покажите предупреждение и дождитесь явного согласия до установки
    accept_unknown_price=true; локальный резерв равен лимиту задачи, цена KIE может быть выше.
    """
    identity(ctx)
    params = {
        k: v
        for k, v in {
            "duration": duration,
            "aspect_ratio": aspect_ratio,
            "resolution": resolution,
        }.items()
        if v is not None
    }
    return await safe_call(
        service.friendly(
            "generate_video",
            prompt,
            model,
            image_path,
            image_url,
            params,
            dry_run=dry_run,
            model_input=model_input,
            auto_select=auto_select,
            accept_unknown_price=accept_unknown_price,
            input_type=input_type,
            video_path=video_path,
            video_url=video_url,
            input_video_duration_seconds=input_video_duration_seconds,
        )
    )


@mcp.tool()
async def remove_background(
    ctx: Context,
    image_path: str | None = None,
    image_url: str | None = None,
    model: str | None = None,
    dry_run: bool = False,
    model_input: dict | None = None,
    auto_select: bool = False,
    accept_unknown_price: bool = False,
):
    """Без model сравнить варианты без фото; с model нужен исходник для удаления фона.

    Preview может загрузить фото.
    При unknown покажите предупреждение и дождитесь явного согласия до установки
    accept_unknown_price=true; локальный резерв равен лимиту задачи, цена KIE может быть выше.
    """
    identity(ctx)
    return await safe_call(
        service.friendly(
            "remove_background",
            model=model,
            image_path=image_path,
            image_url=image_url,
            dry_run=dry_run,
            model_input=model_input,
            auto_select=auto_select,
            accept_unknown_price=accept_unknown_price,
        )
    )


@mcp.tool()
async def upscale_image(
    ctx: Context,
    image_path: str | None = None,
    image_url: str | None = None,
    scale: int | None = None,
    target_resolution: str | None = None,
    model: str | None = None,
    dry_run: bool = False,
    model_input: dict | None = None,
    auto_select: bool = False,
    accept_unknown_price: bool = False,
):
    """Без model сравнить варианты без фото; с model нужен исходник для увеличения.

    Preview может загрузить фото.
    При unknown покажите предупреждение и дождитесь явного согласия до установки
    accept_unknown_price=true; локальный резерв равен лимиту задачи, цена KIE может быть выше.
    """
    identity(ctx)
    params = {
        k: v
        for k, v in {"scale": scale, "target_resolution": target_resolution}.items()
        if v is not None
    }
    return await safe_call(
        service.friendly(
            "upscale_image",
            model=model,
            image_path=image_path,
            image_url=image_url,
            parameters=params,
            dry_run=dry_run,
            model_input=model_input,
            auto_select=auto_select,
            accept_unknown_price=accept_unknown_price,
        )
    )


@mcp.tool()
async def product_image_create(
    ctx: Context,
    image_path: str | None = None,
    style: str = "ecommerce",
    background: str = "white",
    aspect_ratio: str = "3:4",
    resolution: str | None = None,
    product_name: str | None = None,
    model: str | None = None,
    output_format: str | None = None,
    dry_run: bool = False,
    model_input: dict | None = None,
    auto_select: bool = False,
    accept_unknown_price: bool = False,
):
    """Фото товара: без model сравнить варианты, исходное фото пока не нужно.

    С выбранным model исходное image_path обязательно. Сначала kie_preflight:
    покажите требования, параметры и цену по-русски. dry_run=true может загрузить
    фото в KIE, но не отправляет платную задачу; предупредите до вызова.
    При unknown покажите предупреждение и дождитесь явного согласия до установки
    accept_unknown_price=true; локальный резерв равен лимиту задачи, цена KIE может быть выше.
    """
    identity(ctx)
    prompt = (
        f"Create a professional {style} product photo of {product_name or 'the product'}. "
        f"Use a {background} background. Preserve the product exactly."
    )
    params = {"aspect_ratio": aspect_ratio}
    if resolution:
        params["resolution"] = resolution
    if output_format:
        params["output_format"] = output_format
    return await safe_call(
        service.friendly(
            "product_image_create",
            prompt,
            model,
            image_path=image_path,
            parameters=params,
            dry_run=dry_run,
            model_input=model_input,
            auto_select=auto_select,
            accept_unknown_price=accept_unknown_price,
        )
    )


def main() -> None:
    if settings.transport != "stdio":
        raise SystemExit("Only local stdio transport is permitted.")
    try:
        settings.require_api_key()
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from None
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
