from __future__ import annotations

import base64
import json
import zlib
from importlib.resources import files
from typing import Any


def load_catalog() -> list[dict[str, Any]]:
    resource = files("kie_mcp.data").joinpath("docs_catalog.b85")
    compressed = base64.b85decode(resource.read_bytes())
    return json.loads(zlib.decompress(compressed))


CATALOG = load_catalog()
BY_SLUG = {entry["slug"]: entry for entry in CATALOG}


def search_catalog(query: str, limit: int = 10) -> list[dict[str, Any]]:
    query = query.strip().lower()
    if not query:
        return CATALOG[: max(1, min(limit, 50))]

    tokens = [token for token in query.replace("/", " ").replace("-", " ").split() if token]
    scored: list[tuple[int, dict[str, Any]]] = []
    for entry in CATALOG:
        haystack = " ".join(
            [
                entry["title"],
                entry["slug"],
                entry["category"],
                entry["kind"],
                entry["path"],
            ]
        ).lower()
        score = 0
        if query in haystack:
            score += 20
        score += sum(4 for token in tokens if token in haystack)
        if entry["title"].lower().startswith(query):
            score += 8
        if score:
            scored.append((score, entry))

    scored.sort(key=lambda item: (-item[0], item[1]["title"].lower()))
    return [entry for _, entry in scored[: max(1, min(limit, 50))]]


def get_catalog_entry(slug: str) -> dict[str, Any] | None:
    return BY_SLUG.get(slug)
