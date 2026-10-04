import json
import os
import sys
from pathlib import Path

import pytest

from kie_mcp.config import Settings
from kie_mcp.doctor import inspect_setup
from kie_mcp.launcher import SecretError, configuration_environment, load_secret
from kie_mcp.private_files import read_private_file


def setup_owner(tmp_path):
    uploads, results = tmp_path / "uploads", tmp_path / "results"
    uploads.mkdir(mode=0o700)
    results.mkdir(mode=0o700)
    secret = tmp_path / "media.key"
    secret.write_text("offline-media-secret\n")
    secret.chmod(0o600)
    config = tmp_path / "config.toml"
    values = {
        "KIE_SECRET_SOURCE": "secret_file",
        "KIE_SECRET_FILE": str(secret),
        "KIE_ALLOWED_UPLOAD_ROOT": str(uploads),
        "KIE_ALLOWED_DOWNLOAD_ROOT": str(results),
        "KIE_USAGE_LEDGER_PATH": str(tmp_path / "ledger" / "usage.db"),
    }
    config.write_text(
        "[environment]\n" + "\n".join(f"{k}={json.dumps(v)}" for k, v in values.items())
    )
    config.chmod(0o600)
    return {"KIE_OWNER_CONFIG": str(config)}, secret


def test_doctor_is_offline_read_only_and_never_prints_key(tmp_path, monkeypatch):
    env, secret = setup_owner(tmp_path)
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    result = inspect_setup(env)
    assert result["ok"] and not result["secret_checked"]
    assert not result["network_used"] and not result["files_written"]
    assert "offline-media-secret" not in repr(result)
    import kie_mcp.doctor as module

    real_load = module.load_secret
    calls = []

    def loaded(source, environment):
        calls.append(source)
        return real_load(source, environment)

    monkeypatch.setattr(module, "load_secret", loaded)
    result = inspect_setup(env, check_secret=True)
    assert result["ok"] and calls == ["secret_file"]
    assert secret.read_text().strip() not in repr(result)
    assert before == {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert not (tmp_path / "ledger").exists()


@pytest.mark.parametrize("mode", [0o600, 0o400])
def test_private_secret_file_loads_without_chat_fallback(tmp_path, mode):
    env, secret = setup_owner(tmp_path)
    secret.chmod(mode)
    effective = configuration_environment(env)
    assert load_secret("secret_file", effective) == "offline-media-secret"
    effective["KIE_API_KEY"] = "offline-media-secret"
    with pytest.raises(SecretError, match="separate media key"):
        load_secret("secret_file", effective)


@pytest.mark.parametrize("kind", ["public", "symlink", "oversize", "fifo", "directory"])
def test_private_secret_file_rejects_unsafe_files_without_leaking(tmp_path, kind):
    path = tmp_path / "key"
    if kind == "fifo":
        os.mkfifo(path, 0o600)
    elif kind == "directory":
        path.mkdir()
    elif kind == "symlink":
        target = tmp_path / "target"
        target.write_text("private-media-secret")
        path.symlink_to(target)
    else:
        path.write_text("private-media-secret" if kind == "public" else "x" * 16_385)
        path.chmod(0o644 if kind == "public" else 0o600)
    with pytest.raises(SecretError) as exc:
        load_secret("secret_file", {"KIE_SECRET_FILE": str(path)})
    assert "private-media-secret" not in str(exc.value)


def test_private_reader_rejects_another_owner(tmp_path, monkeypatch):
    _, secret = setup_owner(tmp_path)
    monkeypatch.setattr("kie_mcp.private_files.os.geteuid", lambda: secret.stat().st_uid + 1)
    with pytest.raises(ValueError):
        read_private_file(secret, 16_384)


@pytest.mark.parametrize(
    "content",
    [
        '[environment]\nKIE_MCP_API_KEY="private-key"\n',
        "[enviroment]\nKIE_MAX_TASK_COST_USD=1\n",
        "[environment]\nKIE_MAX_TASK_COST_USD=true\n",
        "[environment]\nKIE_UNKNOWN_OPTION=1\n",
        '[environment]\nKIE_MAX_TASK_COST_USD="1"\n[extra]\nsecret="private-key"\n',
    ],
)
def test_owner_config_rejects_typos_secrets_and_wrong_types(tmp_path, content):
    path = tmp_path / "config.toml"
    path.write_text(content)
    path.chmod(0o600)
    with pytest.raises(SecretError) as exc:
        configuration_environment({"KIE_OWNER_CONFIG": str(path)})
    assert "private-key" not in str(exc.value)


def test_explicit_missing_config_does_not_silently_use_defaults(tmp_path):
    with pytest.raises(SecretError, match="does not exist"):
        configuration_environment({"KIE_OWNER_CONFIG": str(tmp_path / "missing.toml")})


def test_tilde_owner_path_is_expanded_without_mutating_environment(tmp_path, monkeypatch):
    env, _ = setup_owner(tmp_path)
    monkeypatch.setattr(
        os.path,
        "expanduser",
        lambda path: str(tmp_path) + path[1:] if path == "~" or path.startswith("~/") else path,
    )
    env["KIE_OWNER_CONFIG"] = "~/config.toml"
    original = env.copy()
    effective = configuration_environment(env)
    assert effective["KIE_SECRET_SOURCE"] == "secret_file" and env == original


@pytest.mark.parametrize(
    "name,value",
    [
        ("KIE_TIMEOUT_SECONDS", "nan"),
        ("KIE_TIMEOUT_SECONDS", "inf"),
        ("KIE_MAX_RETRIES", "-1"),
        ("KIE_MAX_UPLOAD_MB", "0"),
        ("KIE_MAX_DOWNLOAD_MB", "-1"),
        ("KIE_TASK_TIMEOUT_SEC", "0"),
        ("KIE_ALLOWED_UPLOAD_ROOT", "relative/uploads"),
        ("KIE_USAGE_LEDGER_PATH", "relative/usage.db"),
    ],
)
def test_invalid_startup_settings_fail_without_input_echo(name, value):
    with pytest.raises(ValueError):
        Settings.from_env({name: value})


def test_doctor_rejects_secret_inside_media_root(tmp_path):
    env, secret = setup_owner(tmp_path)
    config = Path(env["KIE_OWNER_CONFIG"])
    content = config.read_text().replace(str(tmp_path / "uploads"), str(tmp_path))
    config.write_text(content)
    result = inspect_setup(env)
    assert not result["ok"]
    assert any(c["check"] == "upload_root" and c["status"] == "fail" for c in result["checks"])
    assert secret.read_text().strip() not in repr(result)


async def test_fresh_stdio_launcher_with_independent_owner_file(tmp_path):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    config_env, _ = setup_owner(tmp_path)
    env = dict(os.environ, **config_env)
    env.pop("KIE_MCP_API_KEY", None)
    env.pop("KIE_API_KEY", None)
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "kie_mcp.launcher"],
        env=env,
    )
    async with stdio_client(parameters) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        listed = await session.list_tools()
    assert "kie_compare_models" in {t.name for t in listed.tools}
    assert not (tmp_path / "ledger").exists()
