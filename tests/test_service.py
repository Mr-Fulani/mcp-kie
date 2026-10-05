import asyncio
import json
import os
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from test_client import settings

from kie_mcp.client import KieClient
from kie_mcp.errors import KieAPIError
from kie_mcp.launcher import SecretError, child_environment, load_secret
from kie_mcp.ledger import GuardError, digest
from kie_mcp.models import inline_refs, owner_quote, price_estimate
from kie_mcp.registration import configure
from kie_mcp.service import KieService

MODEL = "fixture/image"
SCHEMA = {
    "paths": {
        "/api/v1/jobs/createTask": {
            "post": {
                "requestBody": {
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["model", "input"],
                                "properties": {
                                    "model": {"type": "string", "enum": [MODEL]},
                                    "input": {"$ref": "#/components/schemas/input%20schema"},
                                },
                                "additionalProperties": False,
                            }
                        }
                    }
                }
            }
        }
    },
    "components": {
        "schemas": {
            "input schema": {
                "type": "object",
                "properties": {"prompt": {"type": "string", "minLength": 1}},
                "required": ["prompt"],
                "additionalProperties": False,
            }
        }
    },
}


class FakeKie:
    def __init__(self, mode="normal"):
        self.calls = []
        self.mode = mode

    def __call__(self, request):
        self.calls.append(request)
        path = request.url.path
        if path.endswith("/schema"):
            data = {"model": MODEL, "openapi": SCHEMA}
        elif path.endswith("/price"):
            data = {"model": MODEL, "pricingDesc": "Each image costs 20 credits (0.10 USD)."}
            if self.mode == "unknown-price":
                data["pricingDesc"] = "Depends on resolution and duration"
        elif path == "/api/v1/models":
            data = {"models": [{"model": MODEL, "taskType": ["Text to Image"]}]}
        elif path.endswith("createTask"):
            if self.mode == "timeout":
                raise httpx.ReadTimeout("ambiguous", request=request)
            if self.mode == "401":
                return httpx.Response(200, json={"code": 401, "msg": "test-key rejected"})
            data = {"taskId": "task_1"}
        elif path.endswith("recordInfo"):
            result_url = (
                "https://evil.example/result.png"
                if self.mode == "evil-result"
                else "https://example.com/result.png"
            )
            data = {
                "taskId": "task_1",
                "state": "success",
                "model": MODEL,
                "createTime": 1791072000000,
                "creditsConsumed": 18,
                "costUsd": 0.09,
                "resultJson": json.dumps({"resultUrls": [result_url]}),
            }
        else:
            raise AssertionError(f"Unexpected mock path {path}")
        return httpx.Response(200, json={"code": 200, "data": data})


def make_service(tmp_path, http):
    config = replace(settings(), ledger_path=tmp_path / "usage.db", allowed_download_root=tmp_path)
    return KieService(config, KieClient(config, http_client=http), metadata_interval=0)


async def test_dry_run_never_reserves_or_submits(tmp_path):
    api = FakeKie()
    async with httpx.AsyncClient(transport=httpx.MockTransport(api)) as http:
        service = make_service(tmp_path, http)
        preview = await service.prepare(MODEL, {"prompt": "private"}, dry_run=True)
    assert preview["estimated_cost_usd"] == 0.1
    assert preview["confidence"] == "estimated"
    assert (
        "Ориентировочная стоимость по текущему тарифу KIE: $0.1"
        in preview["confirmation_summary_ru"]
    )
    assert "может списать деньги" in preview["confirmation_summary_ru"]
    assert "private" not in preview["confirmation_summary_ru"]
    assert not (tmp_path / "usage.db").exists()
    assert all("createTask" not in str(r.url) for r in api.calls)


async def test_prepare_execute_poll_download(tmp_path, monkeypatch):
    from kie_mcp import service as module

    async def download(*args, **kwargs):
        return b"\x89PNG\r\n\x1a\nfixture"

    monkeypatch.setattr(module, "fetch_bytes", download)
    api = FakeKie()
    async with httpx.AsyncClient(transport=httpx.MockTransport(api)) as http:
        service = make_service(tmp_path, http)
        prepared = await service.prepare(MODEL, {"prompt": "private"})
        executed = await service.execute(prepared["approval_id"], MODEL, {"prompt": "private"})
        assert executed["task_id"] == "task_1"
        repeated = await service.execute(prepared["approval_id"], MODEL, {"prompt": "private"})
        assert repeated["duplicate"]
        terminal = await service.wait("task_1")
        assert terminal["data"]["state"] == "success"
        output = await service.download("task_1", result_label="studio")
        assert (
            Path(output["output_folder"]).name == "2026-10-04__studio__image__fixture-image__task_1"
        )
        assert Path(output["output_path"]).parent == Path(output["output_folder"])
        assert Path(output["output_path"]).read_bytes().startswith(b"\x89PNG")
        with service.ledger.connection() as db:
            row = db.execute("SELECT * FROM usage").fetchone()
            assert row["actual_cost_usd"] == 90000 and row["actual_credits"] == 18
            assert row["estimated_cost_usd"] == 100000
            assert "private" not in repr(dict(row))
    assert sum(r.url.path.endswith("createTask") for r in api.calls) == 1


async def test_result_download_restricts_storage_hosts(tmp_path):
    api = FakeKie("evil-result")
    async with httpx.AsyncClient(transport=httpx.MockTransport(api)) as http:
        service = make_service(tmp_path, http)
        with pytest.raises(GuardError, match="allowlist"):
            await service.download("task_1")


async def test_unknown_price_requires_acknowledgement_before_reservation(tmp_path):
    api = FakeKie("unknown-price")
    async with httpx.AsyncClient(transport=httpx.MockTransport(api)) as http:
        service = make_service(tmp_path, http)
        preview = await service.prepare(MODEL, {"prompt": "private"}, dry_run=True)
        assert preview["confidence"] == "unknown"
        guarded = await service.prepare(MODEL, {"prompt": "private"})
        assert guarded["risk_ack_required"]
        assert not guarded["risk_acknowledged"]
        assert not guarded["reservation_created"]
        assert guarded["execution_blocked"]
        assert guarded["next_step"] == "confirm_unknown_price"
    assert not (tmp_path / "usage.db").exists()


async def test_ambiguous_paid_request_never_retried(tmp_path):
    api = FakeKie("timeout")
    async with httpx.AsyncClient(transport=httpx.MockTransport(api)) as http:
        service = make_service(tmp_path, http)
        prepared = await service.prepare(MODEL, {"prompt": "private"})
        with pytest.raises(KieAPIError):
            await service.execute(prepared["approval_id"], MODEL, {"prompt": "private"})
        with pytest.raises(GuardError, match="claimed"):
            await service.execute(prepared["approval_id"], MODEL, {"prompt": "private"})
        with service.ledger.connection() as db:
            assert db.execute("SELECT status FROM usage").fetchone()[0] == "unknown"
    assert sum(r.url.path.endswith("createTask") for r in api.calls) == 1


async def test_business_code_rejection_not_http_success(tmp_path):
    api = FakeKie("401")
    async with httpx.AsyncClient(transport=httpx.MockTransport(api)) as http:
        service = make_service(tmp_path, http)
        prepared = await service.prepare(MODEL, {"prompt": "private"})
        with pytest.raises(KieAPIError) as error:
            await service.execute(prepared["approval_id"], MODEL, {"prompt": "private"})
        assert "test-key" not in str(error.value)
        with service.ledger.connection() as db:
            assert db.execute("SELECT status FROM usage").fetchone()[0] == "rejected"
    assert sum(r.url.path.endswith("createTask") for r in api.calls) == 1


async def test_schema_validation_does_not_echo_private_input(tmp_path):
    async with httpx.AsyncClient(transport=httpx.MockTransport(FakeKie())) as http:
        with pytest.raises(GuardError) as error:
            await make_service(tmp_path, http).prepare(MODEL, {"prompt": "", "secret": "sensitive"})
    assert "sensitive" not in str(error.value)


def test_external_schema_refs_blocked():
    with pytest.raises(GuardError):
        inline_refs({"$ref": "https://127.0.0.1/secret"}, {})


def test_variable_price_unknown_without_verified_conditions():
    assert (
        price_estimate(
            MODEL, {"resolution": "4K"}, {"pricingDesc": "Each image costs 20 credits (0.10 USD)."}
        )["confidence"]
        == "unknown"
    )


def test_exact_input_owner_quote(tmp_path):
    payload = {"model": MODEL, "input": {"prompt": "private"}}
    path = tmp_path / "quote.json"
    import time

    path.write_text(
        json.dumps(
            {
                "request_digest": digest({"operation": "generation", "payload": payload}),
                "expires_at": time.time() + 300,
                "approved_by_owner": True,
                "max_cost_usd": 0.2,
                "pricing_source": "owner verified official price for these exact parameters",
            }
        )
    )
    path.chmod(0o600)
    assert owner_quote(payload, path)["estimated_cost_usd"] == 0.2
    assert owner_quote({"model": MODEL, "input": {"prompt": "altered"}}, path) is None


def test_secret_not_in_argv_or_child_error(monkeypatch, capsys):
    from kie_mcp import launcher

    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(returncode=0, stdout=b"private-media-secret\n")

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(launcher.subprocess, "run", run)
    monkeypatch.setenv("KIE_SECRET_SOURCE", "macos_keychain")
    monkeypatch.setenv("KIE_API_KEY", "chat-only-secret")
    env = child_environment()
    assert env["KIE_MCP_API_KEY"] == "private-media-secret"
    assert "KIE_API_KEY" not in env
    assert "private-media-secret" not in repr(calls)
    assert "private-media-secret" not in capsys.readouterr().out

    def failure(*args, **kwargs):
        raise RuntimeError("private-media-secret")

    monkeypatch.setattr(launcher.subprocess, "run", failure)
    with pytest.raises(SecretError) as error:
        load_secret("macos_keychain")
    assert "private-media-secret" not in str(error.value)


@pytest.mark.parametrize("client,suffix", [("codex", "toml"), ("grok", "toml"), ("claude", "json")])
def test_client_config_update_is_idempotent(tmp_path, client, suffix):
    path = tmp_path / f"config.{suffix}"
    if suffix == "toml":
        before = '# owner comment\nmodel = "existing"\n[model_providers.keep]\nname = "keep"\n'
    else:
        before = '{"existingProvider": "keep", "projects": {"/example": {}}}'
    path.write_text(before)
    command = "/absolute/kie-mcp-launch"
    assert not configure(path, client, command)["written"]
    assert path.read_text() == before
    changed = configure(path, client, command, write=True)
    assert Path(changed["backup"]).read_text() == before
    after = path.read_bytes()
    assert not configure(path, client, command, write=True)["changed"]
    assert path.read_bytes() == after
    assert "keep" in path.read_text()
    configure(path, client, command, remove=True, write=True)
    assert "kie-media" not in path.read_text() and "keep" in path.read_text()


async def test_friendly_model_router_prepares_without_paid_submission(tmp_path):
    api = FakeKie()
    async with httpx.AsyncClient(transport=httpx.MockTransport(api)) as http:
        result = await make_service(tmp_path, http).friendly(
            "generate_image", "private", auto_select=True
        )
    assert result["selected_model"] == MODEL
    assert result["next_step"] == "kie_execute_task"
    assert all("createTask" not in str(r.url) for r in api.calls)


async def test_stdio_protocol_with_fake_key():
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    env = dict(os.environ)
    env["KIE_MCP_API_KEY"] = "offline-protocol-test-key"
    env["KIE_MCP_TRANSPORT"] = "stdio"
    params = StdioServerParameters(command=sys.executable, args=["-m", "kie_mcp.server"], env=env)
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await asyncio.wait_for(session.initialize(), timeout=15)
        tools = await session.list_tools()
        names = {tool.name for tool in tools.tools}
        assert {"kie_prepare_task", "kie_execute_task", "product_image_create"} <= names
        assert "kie_api_request" not in names


def test_private_owner_config_has_no_secret_fields(tmp_path, monkeypatch):
    path = tmp_path / "owner.toml"
    path.write_text('[environment]\nKIE_SECRET_SOURCE="env"\nKIE_MAX_DAILY_COST_USD="3"\n')
    path.chmod(0o600)
    monkeypatch.setenv("KIE_OWNER_CONFIG", str(path))
    monkeypatch.setenv("KIE_MCP_API_KEY", "private-media-secret")
    assert child_environment()["KIE_MAX_DAILY_COST_USD"] == "3"
    path.write_text('[environment]\nKIE_MCP_API_KEY="forbidden"\n')
    with pytest.raises(SecretError, match="secrets are forbidden"):
        child_environment()
