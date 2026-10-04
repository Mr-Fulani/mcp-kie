"""Owner-run client registration: minimal merge, private backup, idempotent updates."""

from __future__ import annotations

import argparse
import json
import os
import uuid
from pathlib import Path

import tomlkit

from .ledger import GuardError

CLIENT_PATHS = {
    "codex": Path.home() / ".codex/config.toml",
    "claude": Path.home() / ".claude.json",
    "grok": Path.home() / ".grok/config.toml",
}


def configure(path: Path, client: str, command: str, *, remove=False, write=False) -> dict:
    if client not in CLIENT_PATHS or not Path(command).is_absolute():
        raise GuardError("Choose a supported client and an absolute launcher path")
    if path.is_symlink():
        raise GuardError("Client configuration symlinks are unsupported")
    before = path.read_bytes() if path.exists() else b""
    if client == "claude":
        document = json.loads(before or b"{}")
        key = "mcpServers"
        entry = {"type": "stdio", "command": command, "args": []}
    else:
        document = tomlkit.parse(before.decode())
        key = "mcp_servers"
        entry = {"command": command, "args": []}
        if client == "grok":
            entry["enabled"] = True
    registrations = document.get(key, {})
    current = registrations.get("kie-media")
    if remove:
        if current is None:
            return {"changed": False, "written": False}
        # Never silently remove an unrelated registration bearing the same name.
        if current.get("command") != command:
            raise GuardError("Existing registration uses another command; owner must review")
        del registrations["kie-media"]
    else:
        if current == entry:
            return {"changed": False, "written": False}
        if current is not None:
            raise GuardError("Existing registration differs; owner must review before replacement")
        if key not in document:
            document[key] = {}
        document[key]["kie-media"] = entry
    if client == "claude":
        rendered = (json.dumps(document, indent=2) + "\n").encode()
    else:
        rendered = tomlkit.dumps(document).encode()
    if not write:
        return {
            "changed": True,
            "written": False,
            "client": client,
            "config_path": str(path),
            "registration": entry if not remove else None,
        }
    path.parent.mkdir(parents=True, exist_ok=True)
    backup = None
    if before:
        backup = path.with_name(path.name + f".kie-backup-{uuid.uuid4().hex}")
        fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(before)
            handle.flush()
            os.fsync(handle.fileno())
    # Check for a concurrent owner edit before replacing the config.
    if (path.read_bytes() if path.exists() else b"") != before:
        raise GuardError("Configuration changed during registration; owner must retry")
    temp = path.with_name(path.name + f".kie-{uuid.uuid4().hex}.tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(rendered)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)
    return {"changed": True, "written": True, "backup": str(backup) if backup else None}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Preview or apply a separate local media MCP entry"
    )
    parser.add_argument("client", choices=CLIENT_PATHS)
    parser.add_argument("--command", required=True, help="Absolute kie-mcp-launch path; no secret")
    parser.add_argument("--config", type=Path)
    parser.add_argument(
        "--apply", action="store_true", help="Owner-authorized config write with backup"
    )
    parser.add_argument("--remove", action="store_true")
    args = parser.parse_args()
    try:
        result = configure(
            args.config or CLIENT_PATHS[args.client],
            args.client,
            args.command,
            remove=args.remove,
            write=args.apply,
        )
        print(json.dumps(result))
    except Exception:
        raise SystemExit("Client registration failed; configuration details withheld.") from None
