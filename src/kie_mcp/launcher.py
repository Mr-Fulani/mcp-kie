"""Secret-loading launcher; fixed Keychain command and secret only in child environment."""

from __future__ import annotations

import os
import re

# Fixed Keychain helper; no tool-supplied commands.
import subprocess  # nosec B404
import sys
import tomllib
from pathlib import Path

from .config import Settings
from .private_files import read_private_file


class SecretError(RuntimeError):
    pass


def load_secret(source: str, environment: dict[str, str] | None = None) -> str:
    env = os.environ if environment is None else environment
    try:
        if source == "macos_keychain":
            if sys.platform != "darwin":
                raise SecretError("macOS Keychain requires macOS")
            service = env.get("KIE_KEYCHAIN_SERVICE", "kie-mcp-media")
            account = env.get("KIE_KEYCHAIN_ACCOUNT", "media")
            if any(
                not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.@ -]{0,127}", label)
                for label in (service, account)
            ):
                raise SecretError("Invalid owner Keychain label")
            # Fixed executable/operation, shell=False; secret never appears in argv.
            # Fixed argv; owner labels validated above.
            result = subprocess.run(  # nosec B603
                ["/usr/bin/security", "find-generic-password", "-s", service, "-a", account, "-w"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=10,
            )
            if result.returncode != 0:
                raise SecretError("Media secret unavailable in macOS Keychain")
            key = result.stdout.decode().strip()
        elif source == "env":
            key = env.get("KIE_MCP_API_KEY", "")
        elif source == "docker_secret":
            path = Path("/run/secrets/KIE_MCP_API_KEY")
            key = path.read_text().strip()
        elif source == "secret_file":
            path = Path(
                env.get("KIE_SECRET_FILE", str(Path.home() / ".config/kie-mcp/media.key"))
            ).expanduser()
            if not path.is_absolute():
                raise SecretError("KIE_SECRET_FILE must be an absolute path")
            try:
                key = read_private_file(path, 16_384).decode().strip()
            except Exception:
                raise SecretError(
                    "Media key file must exist, belong to this user, be mode 0600/0400 "
                    "and not be a symlink"
                ) from None
        else:
            raise SecretError(
                "Unsupported secret source; use macos_keychain, secret_file, docker_secret or env"
            )
        if not key or key == env.get("KIE_API_KEY"):
            raise SecretError("A separate media key is required")
        if len(key.encode()) > 16_384 or any(c.isspace() or ord(c) < 32 for c in key):
            raise SecretError("Media key must be a bounded single token")
        return key
    except SecretError:
        raise
    except Exception:
        raise SecretError("Media secret loading failed; sensitive details withheld") from None


OWNER_ENV_NAMES = {
    "KIE_SECRET_SOURCE",
    "KIE_SECRET_FILE",
    "KIE_KEYCHAIN_SERVICE",
    "KIE_KEYCHAIN_ACCOUNT",
    "KIE_ALLOWED_UPLOAD_ROOT",
    "KIE_ALLOWED_DOWNLOAD_ROOT",
    "KIE_MAX_UPLOAD_MB",
    "KIE_MAX_DOWNLOAD_MB",
    "KIE_MAX_TASK_COST_USD",
    "KIE_MAX_SESSION_COST_USD",
    "KIE_MAX_DAILY_COST_USD",
    "KIE_MAX_TOTAL_COST_USD",
    "KIE_MAX_CONCURRENT_TASKS",
    "KIE_TASK_TIMEOUT_SEC",
    "KIE_TIMEOUT_SECONDS",
    "KIE_MAX_RETRIES",
    "KIE_USAGE_LEDGER_PATH",
    "KIE_OWNER_QUOTE_PATH",
    "KIE_APPROVAL_TTL_SEC",
    "KIE_DUPLICATE_TTL_SEC",
}


def configuration_environment(environment: dict[str, str] | None = None) -> dict[str, str]:
    """Load nonsecret owner settings without fetching a key or modifying the process env."""
    env = dict(os.environ if environment is None else environment)
    path = Path(
        env.get("KIE_OWNER_CONFIG", str(Path.home() / ".config/kie-mcp/config.toml"))
    ).expanduser()
    if not path.is_absolute():
        raise SecretError("KIE_OWNER_CONFIG must be an absolute path")
    if path.exists() or path.is_symlink():
        try:
            document = tomllib.loads(read_private_file(path, 100_000).decode())
        except Exception:
            raise SecretError(
                "Owner configuration must be valid TOML, owner-only and not a symlink"
            ) from None
        config = document.get("environment")
        if (
            set(document) != {"environment"}
            or not isinstance(config, dict)
            or set(config) - OWNER_ENV_NAMES
            or any(type(v) not in {str, int, float} for v in config.values())
        ):
            raise SecretError(
                "Owner configuration contains unsupported names; secrets are forbidden"
            )
        env.update({name: str(value) for name, value in config.items()})
    elif "KIE_OWNER_CONFIG" in env:
        raise SecretError("Explicit KIE_OWNER_CONFIG file does not exist")
    return env


def secret_source(environment: dict[str, str]) -> str:
    return environment.get(
        "KIE_SECRET_SOURCE", "macos_keychain" if sys.platform == "darwin" else "env"
    )


def child_environment() -> dict[str, str]:
    env = configuration_environment()
    source = secret_source(env)
    key = load_secret(source, env)
    env.pop("KIE_API_KEY", None)
    env["KIE_MCP_API_KEY"] = key
    # The source selector is nonsecret; its mode value does not contain a credential.
    env.update({"KIE_SECRET_SOURCE": "env"})  # nosec B105
    return env


def main() -> None:
    try:
        if os.name != "posix":
            raise SecretError("Use macOS, Linux or WSL2; native Windows is unsupported")
        env = child_environment()
        if Settings.from_env(env).transport != "stdio":
            raise SecretError("Only local stdio transport is supported")
        # Required stdio process replacement: executable/module are fixed, secret only in env.
        os.execve(  # nosec B606
            sys.executable, [sys.executable, "-m", "kie_mcp.server"], env
        )
    except SecretError as exc:
        raise SystemExit(f"KIE MCP launch failed: {exc}. Run kie-mcp-doctor.") from None
    except Exception:
        raise SystemExit(
            "KIE MCP launch failed; run kie-mcp-doctor to verify secret and configuration."
        ) from None


if __name__ == "__main__":
    main()
