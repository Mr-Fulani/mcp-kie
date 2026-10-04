from __future__ import annotations

import math
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from .ledger import Limits


def _env_float(name: str, default: float, env: Mapping[str, str]) -> float:
    value = env.get(name)
    return default if value is None else float(value)


def _env_int(name: str, default: int, env: Mapping[str, str]) -> int:
    value = env.get(name)
    return default if value is None else int(value)


@dataclass(frozen=True, slots=True)
class Settings:
    api_key: str | None = field(repr=False)
    api_base: str
    upload_base: str
    timeout_seconds: float
    max_retries: int
    max_upload_bytes: int
    allowed_upload_root: Path | None
    transport: str
    allowed_download_root: Path | None = None
    ledger_path: Path = field(default_factory=lambda: Path.home() / ".local/share/kie-mcp/usage.db")
    limits: Limits = field(default_factory=Limits)
    task_timeout: int = 900
    max_download_bytes: int = 100 * 1024 * 1024
    owner_quote_path: Path | None = None

    @classmethod
    def from_env(cls, environment: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if environment is None else environment

        def floating(name, default):
            return _env_float(name, default, env)

        def integer(name, default):
            return _env_int(name, default, env)

        def absolute_path(value):
            path = Path(value).expanduser()
            if not path.is_absolute():
                raise ValueError("Configured filesystem paths must be absolute or use ~")
            return path

        allowed_root = env.get("KIE_ALLOWED_UPLOAD_ROOT")
        download_root = env.get("KIE_ALLOWED_DOWNLOAD_ROOT")
        quote_path = env.get("KIE_OWNER_QUOTE_PATH")
        return cls(
            api_key=env.get("KIE_MCP_API_KEY"),
            api_base="https://api.kie.ai",
            upload_base="https://kieai.redpandaai.co",
            timeout_seconds=floating("KIE_TIMEOUT_SECONDS", 120.0),
            max_retries=integer("KIE_MAX_RETRIES", 3),
            max_upload_bytes=integer(
                "KIE_MAX_UPLOAD_BYTES", integer("KIE_MAX_UPLOAD_MB", 50) * 1024 * 1024
            ),
            allowed_upload_root=absolute_path(allowed_root).resolve() if allowed_root else None,
            transport=env.get("KIE_MCP_TRANSPORT", "stdio"),
            allowed_download_root=absolute_path(download_root).resolve() if download_root else None,
            ledger_path=absolute_path(
                env.get("KIE_USAGE_LEDGER_PATH", str(Path.home() / ".local/share/kie-mcp/usage.db"))
            ),
            limits=Limits(
                task_usd=floating("KIE_MAX_TASK_COST_USD", 1),
                session_usd=floating("KIE_MAX_SESSION_COST_USD", 5),
                daily_usd=floating("KIE_MAX_DAILY_COST_USD", 10),
                total_usd=floating("KIE_MAX_TOTAL_COST_USD", 100),
                concurrent=integer("KIE_MAX_CONCURRENT_TASKS", 5),
                approval_ttl=integer("KIE_APPROVAL_TTL_SEC", 300),
                duplicate_ttl=integer("KIE_DUPLICATE_TTL_SEC", 900),
            ),
            task_timeout=integer("KIE_TASK_TIMEOUT_SEC", 900),
            max_download_bytes=integer("KIE_MAX_DOWNLOAD_MB", 100) * 1024 * 1024,
            owner_quote_path=absolute_path(quote_path) if quote_path else None,
        )

    def __post_init__(self):
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("Timeout must be finite and positive")
        if self.max_retries < 0 or any(
            value <= 0
            for value in (self.max_upload_bytes, self.max_download_bytes, self.task_timeout)
        ):
            raise ValueError(
                "Retry count must be nonnegative; byte limits and task timeout positive"
            )

    def require_api_key(self) -> str:
        if not self.api_key or self.api_key == os.getenv("KIE_API_KEY"):
            raise RuntimeError(
                "KIE_MCP_API_KEY is not configured. A separate media key is required."
            )
        return self.api_key
