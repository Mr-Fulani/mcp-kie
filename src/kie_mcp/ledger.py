"""Transactional budgets and immutable approvals shared by local MCP processes."""

from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal
from pathlib import Path
from typing import Any


class GuardError(ValueError):
    """Safe, user-facing policy failure without request contents."""


def digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


def money(value: Any) -> int:
    amount = Decimal(str(value))
    if not amount.is_finite() or amount < 0:
        raise GuardError("Cost must be a finite nonnegative number")
    return int((amount * 1_000_000).to_integral_value(rounding=ROUND_CEILING))


@dataclass(frozen=True)
class Limits:
    task_usd: float = 1.0
    session_usd: float = 5.0
    daily_usd: float = 10.0
    total_usd: float = 100.0
    concurrent: int = 5
    approval_ttl: int = 300
    duplicate_ttl: int = 900

    def __post_init__(self):
        for amount in (self.task_usd, self.session_usd, self.daily_usd, self.total_usd):
            if money(amount) <= 0:
                raise GuardError("Budget limits must be positive")
        if min(self.concurrent, self.approval_ttl, self.duplicate_ttl) <= 0:
            raise GuardError("Concurrency and TTL limits must be positive")


class Ledger:
    def __init__(self, path: Path, limits: Limits):
        self.path = path
        self.limits = limits
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if path.is_symlink():
            raise GuardError("Ledger symlinks are forbidden")
        fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        with self.connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS policy (id INTEGER PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS usage (
                    id TEXT PRIMARY KEY, created_at REAL NOT NULL, day TEXT NOT NULL,
                    client_name TEXT NOT NULL, client_version TEXT NOT NULL,
                    agent_session_id TEXT NOT NULL, mcp_process_id INTEGER NOT NULL,
                    correlation_id TEXT NOT NULL, operation TEXT NOT NULL, model TEXT NOT NULL,
                    provider_task_id TEXT, fingerprint TEXT NOT NULL, status TEXT NOT NULL,
                    estimated_cost_usd INTEGER NOT NULL, estimated_credits REAL,
                    actual_cost_usd INTEGER, actual_credits REAL, pricing_source TEXT NOT NULL,
                    unknown_price_accepted INTEGER NOT NULL DEFAULT 0,
                    input_video_duration_seconds REAL,
                    input_hash TEXT NOT NULL, output_count INTEGER NOT NULL DEFAULT 0,
                    expires_at REAL NOT NULL, submitted_at REAL
                );
                CREATE INDEX IF NOT EXISTS usage_fingerprint ON usage(fingerprint);
                CREATE UNIQUE INDEX IF NOT EXISTS usage_task ON usage(provider_task_id)
                    WHERE provider_task_id IS NOT NULL;
            """)
        with self.transaction() as db:
            columns = {row["name"] for row in db.execute("PRAGMA table_info(usage)")}
            if "unknown_price_accepted" not in columns:
                db.execute(
                    "ALTER TABLE usage ADD COLUMN unknown_price_accepted "
                    "INTEGER NOT NULL DEFAULT 0"
                )
            if "input_video_duration_seconds" not in columns:
                db.execute(
                    "ALTER TABLE usage ADD COLUMN input_video_duration_seconds REAL"
                )
            policy = json.dumps(limits.__dict__, sort_keys=True)
            db.execute("INSERT OR IGNORE INTO policy VALUES (1, ?)", (policy,))
            if db.execute("SELECT value FROM policy WHERE id=1").fetchone()[0] != policy:
                raise GuardError("Shared ledger policy differs; owner must reconcile configuration")

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=10000")
        try:
            yield db
        finally:
            db.close()

    @contextmanager
    def transaction(self):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
            except BaseException:
                db.rollback()
                raise
            else:
                db.commit()

    def _expire(self, db, now):
        # Only never-submitted preparations can expire. Ambiguous sends retain liability.
        db.execute(
            "UPDATE usage SET status='expired' WHERE status='prepared' AND expires_at <= ?",
            (now,),
        )

    @staticmethod
    def _public(row, session):
        item = dict(row)
        owns_approval = item["agent_session_id"] == session
        unknown_price_accepted = owns_approval and bool(
            item.get("unknown_price_accepted", 0)
        )
        reserved_cost = item["estimated_cost_usd"] / 1_000_000
        result = {
            "status": item["status"],
            "request_digest": item["fingerprint"],
            "task_id": item["provider_task_id"],
            "expires_at": item["expires_at"],
            "estimated_cost_usd": None if unknown_price_accepted else reserved_cost,
            "reserved_cost_usd": reserved_cost,
            "estimated_credits": item["estimated_credits"],
            "pricing_source": item["pricing_source"],
            "unknown_price_accepted": unknown_price_accepted,
        }
        if owns_approval:
            result["approval_id"] = item["id"]
            result["input_video_duration_seconds"] = item.get(
                "input_video_duration_seconds"
            )
        return result

    def prepare(
        self,
        payload: dict[str, Any],
        cost_usd: Any,
        credits: float | None,
        pricing_source: str,
        session: str,
        *,
        client_name="unknown",
        client_version="unknown",
        operation="generation",
        unknown_price_accepted: bool = False,
        input_video_duration_seconds: float | None = None,
        now: float | None = None,
    ) -> dict[str, Any]:
        if type(unknown_price_accepted) is not bool:
            raise GuardError("Unknown-price acceptance must be an explicit boolean")
        if input_video_duration_seconds is not None:
            if (
                isinstance(input_video_duration_seconds, bool)
                or not isinstance(input_video_duration_seconds, (int, float))
                or not math.isfinite(float(input_video_duration_seconds))
                or input_video_duration_seconds <= 0
            ):
                raise GuardError("Invalid input-video duration assumption")
            input_video_duration_seconds = float(input_video_duration_seconds)
        if cost_usd is None:
            raise GuardError(
                "Unknown cost requires an explicit liability reserve before preparation"
            )
        cost = money(cost_usd)
        if unknown_price_accepted and cost != money(self.limits.task_usd):
            raise GuardError("Unknown-price acceptance must reserve the full per-task limit")
        if credits is not None and (not math.isfinite(credits) or credits < 0):
            raise GuardError("Invalid credit estimate")
        if cost > money(self.limits.task_usd):
            raise GuardError("Generation blocked: estimated cost exceeds per-task limit")
        fingerprint = digest({"operation": operation, "payload": payload})
        now = time.time() if now is None else now
        day = time.strftime("%Y-%m-%d", time.gmtime(now))
        with self.transaction() as db:
            self._expire(db, now)
            row = db.execute(
                "SELECT * FROM usage WHERE fingerprint=? AND "
                "(status IN ('prepared','submitting','submitted','unknown') OR "
                "(status='success' AND created_at>?)) ORDER BY created_at DESC LIMIT 1",
                (fingerprint, now - self.limits.duplicate_ttl),
            ).fetchone()
            if row:
                if row["input_video_duration_seconds"] != input_video_duration_seconds:
                    raise GuardError(
                        "The same request is already prepared with a different input-video duration assumption"
                    )
                if (
                    unknown_price_accepted
                    and not row["unknown_price_accepted"]
                    and row["status"] == "prepared"
                    and row["agent_session_id"] == session
                ):
                    old_cost = row["estimated_cost_usd"]
                    upgraded_cost = max(old_cost, cost)
                    additional = upgraded_cost - old_cost
                    if additional:
                        self._check_budget_caps(db, session, row["day"], additional)
                    db.execute(
                        "UPDATE usage SET estimated_cost_usd=?,estimated_credits=NULL,"
                        "pricing_source=?,unknown_price_accepted=1 "
                        "WHERE id=? AND status='prepared'",
                        (upgraded_cost, pricing_source, row["id"]),
                    )
                    row = db.execute("SELECT * FROM usage WHERE id=?", (row["id"],)).fetchone()
                return {**self._public(row, session), "duplicate": True}
            active = db.execute(
                "SELECT count(*) FROM usage WHERE status IN "
                "('prepared','submitting','submitted','unknown')"
            ).fetchone()[0]
            if active >= self.limits.concurrent:
                raise GuardError("Concurrent task limit reached")
            self._check_budget_caps(db, session, day, cost)
            approval = uuid.uuid4().hex
            db.execute(
                "INSERT INTO usage (id,created_at,day,client_name,client_version,agent_session_id,"
                "mcp_process_id,correlation_id,operation,model,fingerprint,status,"
                "estimated_cost_usd,estimated_credits,pricing_source,unknown_price_accepted,"
                "input_video_duration_seconds,input_hash,expires_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,'prepared',?,?,?,?,?,?,?)",
                (
                    approval,
                    now,
                    day,
                    client_name[:100],
                    client_version[:100],
                    session,
                    os.getpid(),
                    uuid.uuid4().hex,
                    operation,
                    payload["model"],
                    fingerprint,
                    cost,
                    credits,
                    pricing_source,
                    int(unknown_price_accepted),
                    input_video_duration_seconds,
                    digest(payload.get("input", {})),
                    now + self.limits.approval_ttl,
                ),
            )
            row = db.execute("SELECT * FROM usage WHERE id=?", (approval,)).fetchone()
            return {**self._public(row, session), "duplicate": False}

    def _check_budget_caps(self, db, session: str, day: str, additional_cost: int) -> None:
        for query, args, cap, label in (
            (
                "SELECT COALESCE(SUM(COALESCE(actual_cost_usd,estimated_cost_usd)),0) "
                "FROM usage WHERE status NOT IN ('expired','rejected') AND agent_session_id=?",
                (session,),
                self.limits.session_usd,
                "session",
            ),
            (
                "SELECT COALESCE(SUM(COALESCE(actual_cost_usd,estimated_cost_usd)),0) "
                "FROM usage WHERE status NOT IN ('expired','rejected') "
                "AND (day=? OR status IN ('submitting','submitted','unknown'))",
                (day,),
                self.limits.daily_usd,
                "daily",
            ),
            (
                "SELECT COALESCE(SUM(COALESCE(actual_cost_usd,estimated_cost_usd)),0) "
                "FROM usage WHERE status NOT IN ('expired','rejected')",
                (),
                self.limits.total_usd,
                "total",
            ),
        ):
            spent = db.execute(query, args).fetchone()[0]
            if spent + additional_cost > money(cap):
                raise GuardError(f"Generation blocked: {label} budget exceeded")

    def claim(
        self, approval: str, payload: dict[str, Any], session: str, *, operation="generation"
    ):
        fingerprint = digest({"operation": operation, "payload": payload})
        with self.transaction() as db:
            row = db.execute("SELECT * FROM usage WHERE id=?", (approval,)).fetchone()
            if not row or row["agent_session_id"] != session:
                raise GuardError("Unknown approval for this session")
            if row["fingerprint"] != fingerprint:
                raise GuardError("Prepare/execute request digest mismatch")
            if row["status"] in {"submitted", "success", "fail"}:
                return {**self._public(row, session), "send": False}
            if row["status"] != "prepared" or row["expires_at"] <= time.time():
                raise GuardError("Approval expired, already claimed, or awaiting reconciliation")
            db.execute(
                "UPDATE usage SET status='submitting',submitted_at=? WHERE id=?",
                (time.time(), approval),
            )
            return {**self._public(row, session), "send": True}

    def submission(self, approval: str, task_id: str | None, *, rejected=False):
        with self.transaction() as db:
            status = "rejected" if rejected else ("submitted" if task_id else "unknown")
            db.execute(
                "UPDATE usage SET status=?,provider_task_id=? WHERE id=? AND status='submitting'",
                (status, task_id, approval),
            )

    def reconcile(self, task_id: str, state: str, *, actual_usd=None, credits=None, output_count=0):
        if state not in {"success", "fail"}:
            return
        actual = money(actual_usd) if actual_usd is not None else None
        if credits is not None and (not math.isfinite(float(credits)) or float(credits) < 0):
            raise GuardError("Invalid actual credits")
        with self.transaction() as db:
            db.execute(
                "UPDATE usage SET status=?,actual_cost_usd=COALESCE(?,actual_cost_usd),"
                "actual_credits=COALESCE(?,actual_credits),output_count=? WHERE provider_task_id=?",
                (state, actual, credits, output_count, task_id),
            )
