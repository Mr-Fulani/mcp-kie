import asyncio
from types import SimpleNamespace

import pytest
from test_client import settings

import kie_mcp.service as service_module
from kie_mcp.service import KieService


class TaskClient:
    def __init__(self, states):
        self.states = iter(states)
        self.calls = []

    async def get_task(self, task_id):
        self.calls.append(task_id)
        return {"code": 200, "data": {
            "taskId": task_id, "state": next(self.states), "createTime": 100000,
            "creditsConsumed": 32.8,
        }}


def task_service(monkeypatch, states):
    clock = SimpleNamespace(now=0.0)
    monkeypatch.setattr(service_module, "time", SimpleNamespace(
        monotonic=lambda: clock.now, time=lambda: 160.0,
    ))

    async def sleep(seconds):
        clock.now += seconds

    monkeypatch.setattr(service_module, "asyncio", SimpleNamespace(sleep=sleep, Lock=asyncio.Lock))
    client = TaskClient(states)
    service = KieService(settings(), client)
    reconciled = []
    service._ledger = SimpleNamespace(reconcile=lambda *a, **kw: reconciled.append((a, kw)))
    return service, client, reconciled


@pytest.mark.parametrize("state", ["waiting", "queuing", "generating", "new_provider_state"])
async def test_wait_timeout_keeps_last_state_and_does_not_release_or_resubmit(monkeypatch, state):
    service, client, reconciled = task_service(monkeypatch, [state, state])
    result = await service.wait("task_1", timeout=1)
    assert result["data"]["state"] == state
    assert result["polling"]["status"] == "pending"
    assert result["polling"]["timed_out"]
    assert result["polling"]["waited_seconds"] == 1
    assert result["polling"]["budget_liability_retained"]
    assert result["polling"]["resubmit_allowed"] is False
    assert result["task_progress"]["elapsed_seconds"] == 60
    assert result["task_progress"]["next_step"] == "kie_wait_for_task"
    assert result["task_progress"]["eta_seconds"] is None
    assert "blocked" not in result and "error" not in result
    assert client.calls == ["task_1", "task_1"]
    assert reconciled == []


@pytest.mark.parametrize("state,next_step", [
    ("success", "kie_download_result"), ("fail", "review_provider_error"),
])
async def test_completion_at_deadline_is_returned_and_reconciled(monkeypatch, state, next_step):
    service, client, reconciled = task_service(monkeypatch, ["waiting", state])
    result = await service.wait("task_1", timeout=1)
    assert result["polling"]["status"] == "complete"
    assert not result["polling"]["timed_out"]
    assert result["task_progress"]["terminal"]
    assert result["task_progress"]["next_step"] == next_step
    assert result["billing_reconciliation"]["reported_cost_usd"] is None
    assert len(reconciled) == 1
    assert client.calls == ["task_1", "task_1"]


async def test_provider_error_is_not_disguised_as_pending(monkeypatch):
    service, _, reconciled = task_service(monkeypatch, [])

    async def get_task(task_id):
        raise RuntimeError("provider unavailable")

    service.client.get_task = get_task
    with pytest.raises(RuntimeError, match="provider unavailable"):
        await service.wait("task_1", timeout=1)
    assert reconciled == []


def test_progress_uses_completion_time_and_never_invents_eta():
    progress = KieService.task_progress("task_1", {
        "state": "success", "createTime": 100000, "completeTime": 917000,
    })
    assert progress["elapsed_seconds"] == 817
    assert progress["progress_percent"] is None
    assert progress["queue_position"] is None
    assert progress["eta_seconds"] is None


@pytest.mark.parametrize("created", [None, "100000", True, float("nan"), float("inf")])
def test_invalid_provider_timestamp_is_reported_as_unknown(created):
    assert KieService.task_progress("task_1", {
        "state": "waiting", "createTime": created,
    })["elapsed_seconds"] is None
