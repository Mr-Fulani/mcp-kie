"""Local file validation and secret-safe output for the stdio media boundary."""

from __future__ import annotations

import io
import os
import re
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, BinaryIO

MEDIA_SUFFIXES = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".gif",
    ".mp4",
    ".webm",
    ".mov",
    ".mp3",
    ".wav",
    ".m4a",
    ".ogg",
}

_SENSITIVE_KEY_MARKERS = ("authorization", "apikey", "secret", "token", "password")


def _sensitive_key(value: Any) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", str(value).lower())
    return any(marker in normalized for marker in _SENSITIVE_KEY_MARKERS)


def validate_name(name: str) -> None:
    path = Path(name)
    if path.name != name or path.suffix.lower() not in MEDIA_SUFFIXES:
        raise ValueError("Unsupported media filename")


def detect_media_type(data: bytes) -> str:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    if data.startswith(b"RIFF") and data[8:12] == b"WAVE":
        return "audio/wav"
    if data.startswith(b"OggS"):
        return "audio/ogg"
    if data.startswith(b"ID3") or (len(data) > 1 and data[0] == 255 and data[1] & 224 == 224):
        return "audio/mpeg"
    if len(data) >= 12 and data[4:8] == b"ftyp":
        brand = data[8:12]
        if brand == b"qt  ":
            return "video/quicktime"
        if brand in {b"M4A ", b"M4B "}:
            return "audio/mp4"
        if brand in {b"isom", b"iso2", b"mp41", b"mp42", b"avc1", b"M4V "}:
            return "video/mp4"
    if data.startswith(b"\x1a\x45\xdf\xa3") and b"webm" in data[:4096]:
        return "video/webm"
    raise ValueError("Content is not an allowed media type")


def validate_upload_path(file_path: str, root: Path | None) -> Path:
    if root is None:
        raise ValueError("Local upload is disabled; configure an explicit upload root")
    supplied = Path(file_path).expanduser()
    if ".." in supplied.parts:
        raise ValueError("Parent traversal is forbidden")
    validate_name(supplied.name)
    if not supplied.is_absolute():
        supplied = root / supplied
    try:
        resolved = supplied.resolve(strict=True)
        resolved.relative_to(root.resolve(strict=True))
    except (OSError, ValueError):
        raise ValueError("File is outside upload root or unavailable") from None
    return resolved


@contextmanager
def open_upload(
    file_path: str, root: Path | None, max_bytes: int
) -> Iterator[tuple[BinaryIO, str]]:
    path = validate_upload_path(file_path, root)
    if root is None:
        raise ValueError("Upload root is required")
    # Traverse using anchored directory descriptors; never reopen a validated path by name.
    relative = path.relative_to(root.resolve(strict=True))
    directory = os.open(root.resolve(strict=True), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    file_fd = None
    try:
        for component in relative.parts[:-1]:
            child = os.open(
                component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory
            )
            os.close(directory)
            directory = child
        file_fd = os.open(
            relative.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
        )
        info = os.fstat(file_fd)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("Upload must be a regular file")
        if max_bytes <= 0 or info.st_size > max_bytes:
            raise ValueError("Upload exceeds byte limit")
        with os.fdopen(file_fd, "rb") as handle:
            file_fd = None
            content = handle.read(max_bytes + 1)
        if len(content) > max_bytes:
            raise ValueError("Upload exceeds byte limit")
        mime_type = detect_media_type(content)
        # Bounded snapshot prevents source mutation while multipart is transmitted.
        with io.BytesIO(content) as snapshot:
            yield snapshot, mime_type
    finally:
        if file_fd is not None:
            os.close(file_fd)
        os.close(directory)


def redact(value: Any, media_key: str | None = None) -> Any:
    secrets = [media_key, os.getenv("KIE_API_KEY")]
    secrets.extend(
        v
        for k, v in os.environ.items()
        if _sensitive_key(k)
    )
    if isinstance(value, dict):
        return {
            redact(k, media_key): "[REDACTED]"
            if _sensitive_key(k)
            else redact(v, media_key)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact(v, media_key) for v in value]
    if isinstance(value, str):
        for secret in sorted({s for s in secrets if s}, key=len, reverse=True):
            value = value.replace(secret, "[REDACTED]")
        value = re.sub(r'(?i)Bearer\s+[^\s"\',]+', "Bearer [REDACTED]", value)
        value = re.sub(r'/(?:Users|home|etc|private|tmp)/[^\s"\']*', "[REDACTED]", value)
    return value
