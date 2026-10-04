"""Atomic, non-overwriting result publication under an owner-configured root."""

from __future__ import annotations

import os
import re
import uuid
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path

from .ledger import GuardError
from .models import MODEL_ID
from .security import detect_media_type

EXTENSIONS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "audio/wav": ".wav",
    "audio/mpeg": ".mp3",
    "audio/mp4": ".m4a",
    "audio/ogg": ".ogg",
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "video/webm": ".webm",
}


def validate_result_label(label: str | None) -> str | None:
    if label is None:
        return None
    if (
        not isinstance(label, str)
        or not label.strip()
        or len(label.encode("utf-8")) > 48
        or any(not (c.isalnum() or c in " _-") for c in label)
    ):
        raise GuardError("Result label must be short text, not a path")
    return "-".join(label.split())


def result_folder(task_id: str, media_type: str, model: str, created_at=None, label=None) -> str:
    """Generate one bounded directory component; caller labels never supply a path."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", task_id):
        raise GuardError("Invalid task identifier")
    if not isinstance(model, str) or not MODEL_ID.fullmatch(model):
        raise GuardError("Invalid result model identifier")
    if media_type not in EXTENSIONS:
        raise GuardError("Unsupported result media type")
    date = datetime.now(UTC).strftime("%Y-%m-%d")
    if isinstance(created_at, (int, float)) and not isinstance(created_at, bool):
        with suppress(ValueError, OverflowError, OSError):
            date = datetime.fromtimestamp(created_at / 1000, UTC).strftime("%Y-%m-%d")
    parts = [date]
    label = validate_result_label(label)
    if label is not None:
        parts.append(label)
    parts.extend([media_type.split("/", 1)[0], model.replace("/", "-")[:48], task_id])
    folder = "__".join(parts)
    if len(folder.encode("utf-8")) > 255:
        raise GuardError("Generated result folder is too long")
    return folder


def save_result(
    root: Path | None,
    task_id: str,
    data: bytes,
    *,
    model: str | None = None,
    created_at=None,
    label: str | None = None,
) -> str:
    if root is None:
        raise GuardError("Result downloads require an explicit download root")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", task_id):
        raise GuardError("Invalid task identifier")
    media_type = detect_media_type(data)
    suffix = EXTENSIONS[media_type]
    folder = result_folder(task_id, media_type, model, created_at, label) if model else task_id
    root = root.resolve(strict=True)
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    directory = None
    temporary = f".{uuid.uuid4().hex}.part"
    filename = f"{uuid.uuid4().hex}{suffix}"
    try:
        with suppress(FileExistsError):
            os.mkdir(folder, mode=0o700, dir_fd=root_fd)
        directory = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)
        fd = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=directory,
        )
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        # Atomic publish without replacement, unlike rename() which can overwrite.
        os.link(
            temporary, filename, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False
        )
        os.unlink(temporary, dir_fd=directory)
        os.fsync(directory)
        return str(root / folder / filename)
    finally:
        if directory is not None:
            os.close(directory)
        os.close(root_fd)
