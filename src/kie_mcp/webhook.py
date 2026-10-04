from __future__ import annotations

import base64
import hashlib
import hmac
import time
from collections.abc import Mapping
from typing import Any


def create_webhook_signature(task_id: str, timestamp: int, secret: str) -> str:
    payload = f"{task_id}.{timestamp}".encode()
    digest = hmac.new(secret.encode(), payload, hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def verify_webhook_signature(
    *,
    body: Mapping[str, Any],
    timestamp: str | int,
    signature: str,
    secret: str,
    max_age_seconds: int = 300,
    now: int | None = None,
) -> dict[str, Any]:
    task_id = body.get("taskId") or body.get("task_id")
    if not isinstance(task_id, str) or not task_id:
        return {"valid": False, "reason": "callback body does not contain taskId/task_id"}

    try:
        timestamp_int = int(timestamp)
    except (TypeError, ValueError):
        return {"valid": False, "reason": "invalid webhook timestamp"}

    current = int(time.time()) if now is None else now
    age = abs(current - timestamp_int)
    if max_age_seconds >= 0 and age > max_age_seconds:
        return {
            "valid": False,
            "reason": "webhook timestamp is outside the allowed replay window",
            "age_seconds": age,
        }

    expected = create_webhook_signature(task_id, timestamp_int, secret)
    valid = hmac.compare_digest(expected, signature)
    return {
        "valid": valid,
        "reason": "signature matched" if valid else "signature mismatch",
        "task_id": task_id,
        "age_seconds": age,
    }
