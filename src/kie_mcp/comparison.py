"""Evidence-labelled summaries for user choice; no invented quality ranking."""

from .friendly import ALIASES, IMAGE_FIELDS, IMAGE_OPERATIONS, OPERATIONS
from .ledger import GuardError


def operation_requirements(operation: str, has_image: bool = False) -> dict:
    if operation not in OPERATIONS:
        raise GuardError("Unknown friendly operation")
    required = operation in IMAGE_OPERATIONS
    return {
        "image_required_for_comparison": False,
        "image_required_for_execution": required,
        "missing_inputs": ["image_source"] if required and not has_image else [],
        "message_ru": (
            "Для сравнения фото не нужно. Перед обработкой потребуется исходное фото товара."
            if required
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
    }


def confirmation_summary(model: str, preview: dict) -> str:
    cost = preview.get("estimated_cost_usd")
    if cost is None:
        return f"Модель: {model}. Цена неизвестна; платный запуск заблокирован."
    data = preview.get("validated_input", {})
    params = ", ".join(
        f"{key}={data[key]}"
        for key in ("resolution", "quality", "aspect_ratio", "output_format", "duration", "scale")
        if key in data
    )
    return (
        f"Модель: {model}. Параметры: {params or 'по схеме модели'}. "
        f"Расчётная стоимость запроса: ${cost:g}. "
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
    return result
