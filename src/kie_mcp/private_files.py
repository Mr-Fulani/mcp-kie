"""Bounded reads of owner-only local configuration and secrets (POSIX)."""

from __future__ import annotations

import os
import stat
from pathlib import Path


def read_private_file(path: Path, limit: int) -> bytes:
    """Open without following the final symlink; never read a FIFO/device or public file."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.geteuid()
            or stat.S_IMODE(before.st_mode) not in {0o400, 0o600}
            or before.st_size > limit
        ):
            raise ValueError("Private file must be owner-only, regular and bounded")
        data = bytearray()
        while len(data) <= limit:
            chunk = os.read(fd, min(8192, limit + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
        after = os.fstat(fd)
        if len(data) > limit or (before.st_size, before.st_mtime_ns) != (
            after.st_size,
            after.st_mtime_ns,
        ):
            raise ValueError("Private file changed or exceeds its size limit")
        return bytes(data)
    finally:
        os.close(fd)
