import multiprocessing
import os
import time
from dataclasses import replace

import pytest

from kie_mcp.ledger import GuardError, Ledger, Limits

PAYLOAD = {"model": "fixture/image", "input": {"prompt": "private prompt"}}


def test_prepare_execute_digest_mismatch_blocked(tmp_path):
    ledger = Ledger(tmp_path / "usage.db", Limits())
    item = ledger.prepare(PAYLOAD, 0.25, 20, "fixture", "s")
    altered = {"model": "expensive", "input": PAYLOAD["input"]}
    with pytest.raises(GuardError, match="digest mismatch"):
        ledger.claim(item["approval_id"], altered, "s")
    assert ledger.claim(item["approval_id"], PAYLOAD, "s")["send"]
    with pytest.raises(GuardError, match="claimed"):
        ledger.claim(item["approval_id"], PAYLOAD, "s")


def test_duplicate_paid_request_idempotent(tmp_path):
    ledger = Ledger(tmp_path / "usage.db", Limits())
    one = ledger.prepare(PAYLOAD, 0.25, 20, "fixture", "s")
    two = ledger.prepare(PAYLOAD, 0.25, 20, "fixture", "s")
    assert two["duplicate"] and one["approval_id"] == two["approval_id"]
    foreign = ledger.prepare(PAYLOAD, 0.25, 20, "fixture", "other")
    assert "approval_id" not in foreign
    ledger.claim(one["approval_id"], PAYLOAD, "s")
    ledger.submission(one["approval_id"], "task-1")
    assert not ledger.claim(one["approval_id"], PAYLOAD, "s")["send"]
    ledger.reconcile("task-1", "success", credits=19)
    assert ledger.prepare(PAYLOAD, 0.25, 20, "fixture", "s")["task_id"] == "task-1"


def test_stale_reservation_reconciliation(tmp_path):
    ledger = Ledger(tmp_path / "usage.db", Limits())
    stale = ledger.prepare(PAYLOAD, 1, None, "fixture", "s", now=time.time() - 1000)
    current = ledger.prepare(PAYLOAD, 1, None, "fixture", "s")
    assert current["approval_id"] != stale["approval_id"]
    ledger.claim(current["approval_id"], PAYLOAD, "s")
    ledger.submission(current["approval_id"], None)
    pending = ledger.prepare(PAYLOAD, 1, None, "fixture", "s", now=time.time() + 2000)
    assert pending["status"] == "unknown"
    assert pending["approval_id"] == current["approval_id"]


def test_unknown_cost_requires_approval(tmp_path):
    ledger = Ledger(tmp_path / "usage.db", Limits())
    with pytest.raises(GuardError, match="Unknown cost"):
        ledger.prepare(PAYLOAD, None, None, "unknown", "s")


def test_policy_cannot_be_raised_by_another_process(tmp_path):
    path = tmp_path / "usage.db"
    Ledger(path, Limits())
    with pytest.raises(GuardError, match="policy differs"):
        Ledger(path, replace(Limits(), daily_usd=100))


def budget_worker(path, barrier, queue, index):
    ledger = Ledger(path, Limits(daily_usd=1))
    barrier.wait(timeout=10)
    try:
        ledger.prepare(
            {"model": "fixture", "input": {"seed": index}}, 0.75, None, "fixture", f"s{index}"
        )
        queue.put("reserved")
    except GuardError:
        queue.put("blocked")


def test_multi_process_daily_budget_atomic(tmp_path):
    path = tmp_path / "usage.db"
    Ledger(path, Limits(daily_usd=1))
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(2)
    queue = context.Queue()
    workers = [
        context.Process(target=budget_worker, args=(path, barrier, queue, i)) for i in range(2)
    ]
    for worker in workers:
        worker.start()
    results = [queue.get(timeout=20) for _ in workers]
    for worker in workers:
        worker.join(timeout=10)
        assert worker.exitcode == 0
    assert sorted(results) == ["blocked", "reserved"]


@pytest.mark.parametrize("value", ["NaN", "Infinity", -1])
def test_invalid_cost_rejected(tmp_path, value):
    with pytest.raises(GuardError):
        Ledger(tmp_path / "usage.db", Limits()).prepare(PAYLOAD, value, None, "fixture", "s")


def duplicate_worker(path, barrier, queue):
    ledger = Ledger(path, Limits())
    barrier.wait(timeout=10)
    prepared = ledger.prepare(PAYLOAD, 0.75, None, "fixture", str(os.getpid()))
    queue.put(prepared["duplicate"])


def test_budget_reservation_race_identical_requests(tmp_path):
    path = tmp_path / "usage.db"
    Ledger(path, Limits())
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(2)
    queue = context.Queue()
    workers = [
        context.Process(target=duplicate_worker, args=(path, barrier, queue)) for _ in range(2)
    ]
    for worker in workers:
        worker.start()
    results = [queue.get(timeout=20) for _ in workers]
    for worker in workers:
        worker.join(timeout=10)
        assert worker.exitcode == 0
    assert sorted(results) == [False, True]
