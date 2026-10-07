"""Evidence-labelled summaries for user choice; no invented quality ranking."""

from .friendly import ALIASES, IMAGE_FIELDS, IMAGE_OPERATIONS, OPERATIONS
from .ledger import GuardError
from .video_support import (
    duration_field_name,
    is_duration_field_name,
    video_input_constraints,
    video_input_fields,
)


def operation_requirements(
    operation: str,
    has_image: bool = False,
    has_video: bool = False,
    input_type: str = "auto",
) -> dict:
    if operation not in OPERATIONS:
        raise GuardError("Unknown friendly operation")
    image_required = operation in IMAGE_OPERATIONS or (
        operation == "generate_video" and input_type == "image"
    )
    video_required = operation == "generate_video" and input_type == "video"
    missing_inputs = []
    if image_required and not has_image:
        missing_inputs.append("image_source")
    if video_required and not has_video:
        missing_inputs.append("video_source")
    return {
        "image_required_for_comparison": False,
        "image_required_for_execution": image_required,
        "video_required_for_execution": video_required,
        "missing_inputs": missing_inputs,
        "message_ru": (
            "Для сравнения фото не нужно. Перед обработкой потребуется исходное фото товара."
            if image_required
            else (
                "Для сравнения исходник не нужен. Для Video-to-Video потребуется исходный "
                "ролик; поле video reference само по себе не гарантирует покадровое редактирование."
            )
            if video_required
            else "Для сравнения исходник не нужен. Параметры уточняются по схеме выбранной модели."
        ),
    }


def input_requirements(schema: dict) -> dict:
    return {
        "required_fields": schema.get("required", []),
        "fields": {
            name: {
                key: prop[key]
                for key in (
                    "type",
                    "enum",
                    "default",
                    "minimum",
                    "maximum",
                    "exclusiveMinimum",
                    "exclusiveMaximum",
                    "multipleOf",
                    "minItems",
                    "maxItems",
                    "minLength",
                    "maxLength",
                    "description",
                )
                if key in prop
            }
            for name, prop in schema.get("properties", {}).items()
        },
        "image_fields": [name for name in schema.get("properties", {}) if name in IMAGE_FIELDS],
        "video_fields": video_input_fields(schema),
        "video_input": video_input_constraints(schema),
    }


def confirmation_summary(
    model: str, preview: dict, *, risk_reserve_usd: float | None = None
) -> str:
    cost = preview.get("estimated_cost_usd")
    data = preview.get("validated_input", {})
    parameter_values = [
        f"{key}={data[key]}"
        for key in ("resolution", "quality", "aspect_ratio", "output_format", "duration", "scale")
        if key in data
    ]
    if not any(key.split("=", 1)[0] == "duration" for key in parameter_values):
        parameter_values.extend(
            f"{key}={value}"
            for key, value in data.items()
            if is_duration_field_name(key) and key != "duration"
        )
    input_video_duration = preview.get("input_video_duration_seconds")
    if input_video_duration is not None:
        parameter_values.append(f"input_video_duration_seconds={input_video_duration}")
    params = ", ".join(parameter_values)
    parameter_summary = params or "по схеме модели"
    if cost is None:
        if preview.get("unknown_price_accepted"):
            reserve = preview.get("reserved_cost_usd", risk_reserve_usd)
            reserve_text = f"${reserve:g}" if reserve is not None else "неизвестная сумма"
            return (
                f"Модель: {model}. Параметры: {parameter_summary}. Цена KIE неизвестна. "
                "Вы подтвердили запуск на свой риск. "
                f"В локальном ledger зарезервировано {reserve_text} по лимиту одной задачи; "
                "это не ограничивает списание KIE, которое может быть выше. "
                "Фактическую стоимость после выполнения MCP покажет, только если KIE её вернёт; "
                "иначе точная сумма останется неизвестной. "
                "Запрос подготовлен и отправится только после вызова execute."
            )
        reserve_text = (
            f"${risk_reserve_usd:g}" if risk_reserve_usd is not None else "лимит одной задачи"
        )
        return (
            f"Модель: {model}. Параметры: {parameter_summary}. Цена KIE неизвестна. "
            "Генерация не запущена. Если вы подтвердите риск, локальный ledger "
            f"зарезервирует {reserve_text}; фактическое списание KIE может быть выше. "
            "После выполнения MCP сможет показать фактическую сумму только если KIE её вернёт."
        )
    price_label = (
        "Проверенная владельцем верхняя граница"
        if preview.get("owner_approved")
        else "Ориентировочная стоимость по текущему тарифу KIE"
    )
    return (
        f"Модель: {model}. Параметры: {parameter_summary}. "
        f"{price_label}: ${cost:g}. Фактическое списание может отличаться. "
        "Выполнение отправит запрос в KIE и может списать деньги. "
        "Подтверждение относится только к этому неизменённому запросу."
    )


def capabilities(schema: dict) -> dict:
    fields = schema.get("properties", {})
    result = {}
    for name, aliases in {
        **ALIASES,
        "quality": ("quality", "mode"),
        "generate_audio": ("generate_audio", "sound", "audio"),
    }.items():
        choices = [key for key in aliases if key in fields]
        if choices:
            field = name if name in choices else choices[0]
            prop = fields[field]
            result[name] = {
                "field": field,
                **{
                    k: prop[k]
                    for k in ("type", "enum", "minimum", "maximum", "default", "description")
                    if k in prop
                },
            }
    if "duration" not in result:
        field = duration_field_name(fields)
        if field:
            prop = fields[field]
            result["duration"] = {
                "field": field,
                **{
                    key: prop[key]
                    for key in ("type", "enum", "minimum", "maximum", "default", "description")
                    if key in prop
                },
            }
    return result


def video_capabilities(schema: dict) -> dict:
    return video_input_constraints(schema)
