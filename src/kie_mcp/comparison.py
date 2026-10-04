"""Evidence-labelled summaries for user choice; no invented quality ranking."""

from .friendly import ALIASES


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
