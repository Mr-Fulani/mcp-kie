"""Owner-run, offline setup diagnostics. Never writes config, files or the ledger."""

from __future__ import annotations

import argparse
import json
import os
import stat
from pathlib import Path

from .config import Settings
from .launcher import SecretError, configuration_environment, load_secret, secret_source


def inspect_setup(environment: dict[str, str] | None = None, *, check_secret=False) -> dict:
    checks = []

    def add(name, status, message):
        checks.append({"check": name, "status": status, "message": message})

    def report():
        return {
            "ok": not any(c["status"] == "fail" for c in checks),
            "network_used": False,
            "files_written": False,
            "secret_checked": any(
                c["check"] == "media_secret" and c["status"] in {"pass", "fail"} for c in checks
            ),
            "checks": checks,
        }

    if os.name != "posix" or not hasattr(os, "O_NOFOLLOW"):
        add("platform", "fail", "Use macOS, Linux or WSL2; native Windows is unsupported")
        return report()
    add("platform", "pass", "POSIX filesystem guards available")
    try:
        env = configuration_environment(environment)
    except SecretError as exc:
        add("owner_config", "fail", str(exc))
        return report()
    config_path = Path(
        env.get("KIE_OWNER_CONFIG", str(Path.home() / ".config/kie-mcp/config.toml"))
    ).expanduser()
    add(
        "owner_config",
        "pass" if config_path.exists() else "warn",
        "Private owner configuration loaded"
        if config_path.exists()
        else "No owner file; inherited environment/defaults are used",
    )
    try:
        settings = Settings.from_env(env)
    except Exception:
        add(
            "settings",
            "fail",
            "Use absolute paths, finite positive limits/timeouts and valid numbers",
        )
        return report()
    add("transport", "pass" if settings.transport == "stdio" else "fail", "Only stdio is supported")
    add("settings", "pass", "Numeric settings and absolute paths are valid")

    source = secret_source(env)
    source_valid = source in {"macos_keychain", "secret_file", "docker_secret", "env"}
    add("secret_source", "pass" if source_valid else "fail", "Select a supported secret source")
    if source == "env":
        add(
            "secret_storage",
            "warn",
            "Environment secrets are for development; prefer Keychain or a private file",
        )
    protected = [config_path.resolve(), settings.ledger_path.resolve()]
    if settings.owner_quote_path:
        protected.append(settings.owner_quote_path.resolve())
    if source == "secret_file":
        protected.append(
            Path(env.get("KIE_SECRET_FILE", str(Path.home() / ".config/kie-mcp/media.key")))
            .expanduser()
            .resolve()
        )
    elif source == "docker_secret":
        protected.append(Path("/run/secrets/KIE_MCP_API_KEY"))
    roots = (settings.allowed_upload_root, settings.allowed_download_root)
    for name, root in zip(("upload_root", "download_root"), roots, strict=True):
        if root is None:
            add(name, "fail", "Set a dedicated existing directory to enable this operation")
            continue
        try:
            info = root.stat()
            unsafe = (
                not stat.S_ISDIR(info.st_mode)
                or root in {Path(root.anchor), Path.home().resolve()}
                or info.st_uid != os.geteuid()
                or info.st_mode & 0o022
                or any(p.is_relative_to(root) for p in protected)
                or not os.access(root, os.R_OK | os.W_OK | os.X_OK)
            )
            add(
                name,
                "fail" if unsafe else "pass",
                "Use an owned dedicated writable directory, "
                "not home/root or a secrets/ledger directory"
                if unsafe
                else "Dedicated owned directory is available",
            )
        except OSError:
            add(name, "fail", "Create the configured directory with owner-only permissions")
    if all(roots) and (roots[0].is_relative_to(roots[1]) or roots[1].is_relative_to(roots[0])):
        add(
            "root_separation",
            "fail",
            "Upload and download directories must be separate, not nested",
        )
    ledger = settings.ledger_path
    if ledger.is_symlink() or (ledger.exists() and not ledger.is_file()):
        add("ledger_path", "fail", "Ledger must be a regular private file, not a symlink")
    elif ledger.exists() and (
        ledger.stat().st_uid != os.geteuid() or ledger.stat().st_mode & 0o077
    ):
        add("ledger_path", "fail", "Existing ledger must be owned by this user and private")
    else:
        add(
            "ledger_path",
            "pass",
            "Ledger location inspected without opening or creating the database",
        )
    if check_secret and source_valid:
        try:
            load_secret(source, env)
            add("media_secret", "pass", "Separate media secret can be loaded; value withheld")
        except SecretError as exc:
            add("media_secret", "fail", str(exc))
    else:
        add(
            "media_secret",
            "warn",
            "Key was not read; use --check-secret to test loading without displaying it",
        )
    add(
        "provider_policy",
        "warn",
        "Verify KIE-side caps yourself; "
        "offline checks cannot verify key validity or provider policy",
    )
    return report()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check local KIE MCP setup without network or writes"
    )
    parser.add_argument(
        "--check-secret", action="store_true", help="Load but never display the media key"
    )
    parser.add_argument("--json", action="store_true", help="Return a value-free structured report")
    args = parser.parse_args()
    try:
        result = inspect_setup(check_secret=args.check_secret)
    except Exception:
        raise SystemExit("Setup check failed; sensitive details withheld.") from None
    if args.json:
        print(json.dumps(result))
    else:
        for check in result["checks"]:
            print(f"{check['status'].upper()}: {check['check']}: {check['message']}")
    raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
