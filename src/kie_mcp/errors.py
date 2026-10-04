from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class KieAPIError(Exception):
    message: str
    status_code: int | None = None
    api_code: int | str | None = None
    details: Any = None
    retryable: bool = False

    def __str__(self) -> str:
        parts = [self.message]
        if self.status_code is not None:
            parts.append(f"HTTP {self.status_code}")
        if self.api_code is not None:
            parts.append(f"API code {self.api_code}")
        return " | ".join(parts)

    def as_dict(self) -> dict[str, Any]:
        return {
            "error": self.message,
            "status_code": self.status_code,
            "api_code": self.api_code,
            "details": self.details,
            "retryable": self.retryable,
        }
