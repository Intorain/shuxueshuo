"""Durable calculation accounting, distinct from checkpoints and wall-clock downtime.

A route's PostgreSQL session lock is its lease. PostgreSQL owns attempts, receipts, actual
usage and conservative reservations; a dead process cannot release its budget
by omitting a checkpoint. Supervisor receipts record only the measured worker
operation. Missing receipts reserve an explicit upper bound, never invented
elapsed time. Returned receipts can be reused before any checkpoint exists.
"""

import fcntl
import hashlib
import json
import math
import os
import time
import uuid
from contextlib import contextmanager

from sqlalchemy import text

from .storage import RunNotFound, RunUnavailable


class BudgetConflict(ValueError):
    """A lease, operation identity or configured limit conflicts with durable state."""


class BudgetExhausted(RuntimeError):
    def __init__(self, summary):
        self.summary = summary
        super().__init__("budget.exhausted")


class BudgetPending(RuntimeError):
    def __init__(self, attempt):
        self.attempt = attempt
        super().__init__("budget.receipt_pending")


def _dump(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _seconds(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError("budget.invalid_" + name)
    return float(value)


def _text(value, name):
    if not isinstance(value, str) or not value:
        raise ValueError("budget.invalid_" + name)
    return value


class BudgetLedger:
    """Account for one identity-validated run in the shared PostgreSQL store."""

    def __init__(self, store):
        self._store = store
        self._run_id = store.identity["run_id"]
        self.directory = store.directory / "calculation-budget"
        self.receipts = self.directory / "receipts"
        self._owners = {}
        with store.transaction(write=True):
            self.directory.mkdir(exist_ok=True)
            self.receipts.mkdir(exist_ok=True)

    def _execute(self, db, statement, **parameters):
        return db.execute(text(statement), {**parameters, "run_id": self._run_id})

    @contextmanager
    def _database_lease(self, target, route):
        with self._store._storage.db.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            connection.detach()
            table_id = connection.scalar(text("SELECT 'lesson_runs'::regclass::oid"))
            digest = hashlib.sha256(_dump([table_id, self._run_id, target, route]).encode()).digest()
            key = int.from_bytes(digest[:8], "big", signed=True)
            if not connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": key}):
                raise BudgetConflict("budget.lease_busy")
            try:
                yield connection, connection.scalar(text("SELECT pg_backend_pid()"))
            finally:
                try:
                    connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
                except BaseException:
                    connection.invalidate()
                    raise

    @contextmanager
    def route_lease(self, target, route):
        """Hold nonblocking database and local leases without a long transaction."""
        _text(target, "target")
        _text(route, "route")
        key = hashlib.sha256(_dump([self._run_id, target, route]).encode()).hexdigest()
        with self._database_lease(target, route) as session, (self.directory / (key + ".lock")).open("a+b") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise BudgetConflict("budget.lease_busy") from exc
            owner = uuid.uuid4().hex
            with self._store.transaction(write=True) as db:
                self._execute(db, """INSERT INTO lesson_calculation_leases
                    (run_id,target,route,owner,pid,acquired_at,released)
                    VALUES (:run_id,:target,:route,:owner,:pid,:acquired_at,0)
                    ON CONFLICT(run_id,target,route) DO UPDATE SET owner=excluded.owner,
                    pid=excluded.pid,acquired_at=excluded.acquired_at,released=0""",
                    target=target, route=route, owner=owner, pid=os.getpid(), acquired_at=time.time())
            self._owners[owner] = (target, route, *session)
            try:
                yield owner
            finally:
                self._owners.pop(owner, None)
                try:
                    with self._store.transaction(write=True) as db:
                        self._execute(db, """UPDATE lesson_calculation_leases SET released=1
                            WHERE run_id=:run_id AND target=:target AND route=:route AND owner=:owner""",
                            target=target, route=route, owner=owner)
                except (RunNotFound, RunUnavailable):
                    pass
                finally:
                    fcntl.flock(lock, fcntl.LOCK_UN)

    def _require_owner(self, db, target, route, owner):
        lease = self._owners.get(owner)
        if lease is None or lease[:2] != (target, route):
            raise BudgetConflict("budget.lease_not_owned")
        if lease[2].scalar(text("SELECT pg_backend_pid()")) != lease[3]:
            raise BudgetConflict("budget.lease_stale")
        saved = self._execute(db, """SELECT owner,released FROM lesson_calculation_leases
            WHERE run_id=:run_id AND target=:target AND route=:route""",
            target=target, route=route).mappings().one_or_none()
        if saved is None or saved["owner"] != owner or saved["released"]:
            raise BudgetConflict("budget.lease_stale")

    def configure(self, target, route, bucket, limit_seconds, *, initial_seconds=0):
        """Configure once; initial usage imports a pre-ledger checkpoint only once."""
        _text(target, "target")
        _text(route, "route")
        if bucket not in ("solve", "verification", "selection", "interaction"):
            raise ValueError("budget.invalid_bucket")
        limit_seconds = _seconds(limit_seconds, "limit_seconds")
        initial_seconds = _seconds(initial_seconds, "initial_seconds")
        with self._store.transaction(write=True) as db:
            row = self._execute(db, """SELECT limit_seconds FROM lesson_calculation_budgets
                WHERE run_id=:run_id AND target=:target AND route=:route AND bucket=:bucket""",
                target=target, route=route, bucket=bucket).one_or_none()
            if row is not None and row[0] != limit_seconds:
                raise BudgetConflict("budget.limit_mismatch")
            self._execute(db, """INSERT INTO lesson_calculation_budgets
                (run_id,target,route,bucket,limit_seconds,initial_seconds)
                VALUES (:run_id,:target,:route,:bucket,:limit_seconds,:initial_seconds)
                ON CONFLICT(run_id,target,route,bucket) DO NOTHING""",
                target=target, route=route, bucket=bucket,
                limit_seconds=limit_seconds, initial_seconds=initial_seconds)
            return self._summary(db, target, route, bucket)

    def _receipt_path(self, attempt_id):
        return self.receipts / (attempt_id + ".json")

    def _attempt(self, row):
        value = {key: item for key, item in row.items() if key not in {"run_id", "sequence"}}
        value["receipt"] = json.loads(value["receipt"]) if value["receipt"] is not None else None
        value["receipt_path"] = str(self._receipt_path(value["attempt_id"]))
        return value

    def _summary(self, db, target, route, bucket):
        budget = self._execute(db, """SELECT * FROM lesson_calculation_budgets
            WHERE run_id=:run_id AND target=:target AND route=:route AND bucket=:bucket""",
            target=target, route=route, bucket=bucket).mappings().one_or_none()
        if budget is None:
            raise ValueError("budget.not_configured")
        rows = self._execute(db, """SELECT * FROM lesson_calculation_attempts
            WHERE run_id=:run_id AND target=:target AND route=:route AND bucket=:bucket ORDER BY sequence""",
            target=target, route=route, bucket=bucket).mappings().all()
        actual = budget["initial_seconds"] + sum(row["elapsed_seconds"] for row in rows)
        reserved = sum(row["reserved_upper_seconds"] for row in rows)
        operations = []
        for row in rows:
            receipt = json.loads(row["receipt"]) if row["receipt"] is not None else None
            operations.append({key: row[key] for key in (
                "attempt_id", "operation_key", "input_hash", "ordinal", "owner", "status",
                "allowance_seconds", "elapsed_seconds", "reserved_upper_seconds",
            )} | {"outcome": receipt["status"] if receipt else None,
                  "error": receipt.get("error") if receipt else None})
        return {"limit_seconds": budget["limit_seconds"], "initial_seconds": budget["initial_seconds"],
                "actual_seconds": actual, "used_seconds": actual + reserved,
                "reserved_upper_seconds": reserved,
                "remaining_seconds": max(0.0, budget["limit_seconds"] - actual - reserved),
                "operations": operations}

    def summary(self, target, route, bucket):
        with self._store.transaction() as db:
            return self._summary(db, target, route, bucket)

    @staticmethod
    def _validate_receipt(receipt, attempt_id):
        if not isinstance(receipt, dict) or receipt.get("schema_version") != "bounded-calculation-receipt/v1":
            raise ValueError("budget.invalid_receipt_schema")
        if receipt.get("attempt_id") != attempt_id:
            raise BudgetConflict("budget.receipt_attempt_mismatch")
        if receipt.get("status") not in ("returned", "timeout", "worker_error", "parent_lost"):
            raise ValueError("budget.invalid_receipt_status")
        _seconds(receipt.get("elapsed_seconds"), "receipt_elapsed_seconds")
        if receipt["status"] == "returned" and "result" not in receipt:
            raise ValueError("budget.missing_receipt_result")
        _dump(receipt)

    def _settle(self, db, row, receipt):
        self._validate_receipt(receipt, row["attempt_id"])
        encoded = _dump(receipt)
        if row["receipt"] is not None:
            if row["receipt"] != encoded:
                raise BudgetConflict("budget.receipt_reuse_mismatch")
            return
        self._execute(db, """UPDATE lesson_calculation_attempts
            SET status='settled',elapsed_seconds=:elapsed_seconds,reserved_upper_seconds=0,receipt=:receipt
            WHERE run_id=:run_id AND attempt_id=:attempt_id""",
            elapsed_seconds=receipt["elapsed_seconds"], receipt=encoded, attempt_id=row["attempt_id"])

    def _read_receipt(self, row):
        path = self._receipt_path(row["attempt_id"])
        try:
            return json.loads(path.read_text())
        except FileNotFoundError:
            return None

    def recover(self, target, route, owner):
        """Import completed work or retain an explicit unknown upper reservation."""
        with self._store.transaction(write=True) as db:
            self._require_owner(db, target, route, owner)
            rows = self._execute(db, """SELECT * FROM lesson_calculation_attempts
                WHERE run_id=:run_id AND target=:target AND route=:route AND status!='settled'
                ORDER BY sequence""", target=target, route=route).mappings().all()
            recovered = []
            for row in rows:
                receipt = self._read_receipt(row)
                if receipt is not None:
                    self._settle(db, row, receipt)
                elif row["owner"] != owner:
                    self._execute(db, """UPDATE lesson_calculation_attempts SET status='interrupted_unknown'
                        WHERE run_id=:run_id AND attempt_id=:attempt_id""", attempt_id=row["attempt_id"])
                updated = self._execute(db, """SELECT * FROM lesson_calculation_attempts
                    WHERE run_id=:run_id AND attempt_id=:attempt_id""",
                    attempt_id=row["attempt_id"]).mappings().one()
                recovered.append(self._attempt(updated))
            buckets = self._execute(db, """SELECT bucket FROM lesson_calculation_budgets
                WHERE run_id=:run_id AND target=:target AND route=:route ORDER BY bucket""",
                target=target, route=route).scalars().all()
            summaries = {bucket: self._summary(db, target, route, bucket) for bucket in buckets}
            return {"recovered": recovered, "summaries": summaries}

    def begin(self, target, route, bucket, operation_key, input_hash, owner, *, allowance_seconds=None):
        """Reserve before launch; replay an existing terminal receipt without calculation.

        ``allowance_seconds`` caps one attempt below the bucket's remainder, so
        an interrupted attempt reserves only what it could actually have used.
        """
        _text(operation_key, "operation_key")
        _text(input_hash, "input_hash")
        exhausted = None
        with self._store.transaction(write=True) as db:
            self._require_owner(db, target, route, owner)
            previous = self._execute(db, """SELECT * FROM lesson_calculation_attempts
                WHERE run_id=:run_id AND target=:target AND route=:route AND bucket=:bucket
                AND operation_key=:operation_key ORDER BY ordinal DESC LIMIT 1""",
                target=target, route=route, bucket=bucket, operation_key=operation_key).mappings().one_or_none()
            ordinal = 1
            if previous is not None:
                if previous["input_hash"] != input_hash:
                    raise BudgetConflict("budget.operation_input_mismatch")
                ordinal = previous["ordinal"] + 1
                if previous["receipt"] is None:
                    receipt = self._read_receipt(previous)
                    if receipt is not None:
                        self._settle(db, previous, receipt)
                        previous = self._execute(db, """SELECT * FROM lesson_calculation_attempts
                            WHERE run_id=:run_id AND attempt_id=:attempt_id""",
                            attempt_id=previous["attempt_id"]).mappings().one()
                    else:
                        raise BudgetPending(self._attempt(previous))
                receipt = json.loads(previous["receipt"])
                if receipt["status"] != "parent_lost":
                    summary = self._summary(db, target, route, bucket)
                    return {**self._attempt(previous), "reused": True,
                            "remaining_seconds": summary["remaining_seconds"], "summary": summary}
            summary = self._summary(db, target, route, bucket)
            remaining = summary["remaining_seconds"]
            if remaining <= 0:
                exhausted = BudgetExhausted(summary)
            else:
                if allowance_seconds is not None:
                    remaining = min(remaining, _seconds(allowance_seconds, "allowance_seconds"))
                attempt_id = uuid.uuid4().hex
                row = self._execute(db, """INSERT INTO lesson_calculation_attempts
                    (run_id,attempt_id,target,route,bucket,operation_key,input_hash,ordinal,owner,status,
                     allowance_seconds,elapsed_seconds,reserved_upper_seconds,receipt)
                    VALUES (:run_id,:attempt_id,:target,:route,:bucket,:operation_key,:input_hash,:ordinal,:owner,
                            'pending',:allowance_seconds,0,:allowance_seconds,NULL) RETURNING *""",
                    attempt_id=attempt_id, target=target, route=route, bucket=bucket,
                    operation_key=operation_key, input_hash=input_hash, ordinal=ordinal,
                    owner=owner, allowance_seconds=remaining).mappings().one()
                summary = self._summary(db, target, route, bucket)
                result = {**self._attempt(row), "reused": False, "remaining_seconds": remaining, "summary": summary}
        if exhausted is not None:
            raise exhausted
        return result

    def finish(self, attempt_id, owner, receipt=None):
        """Settle exactly once. Durable receipt reuse does not depend on its file surviving."""
        with self._store.transaction(write=True) as db:
            row = self._execute(db, """SELECT * FROM lesson_calculation_attempts
                WHERE run_id=:run_id AND attempt_id=:attempt_id""",
                attempt_id=attempt_id).mappings().one_or_none()
            if row is None:
                raise ValueError("budget.unknown_attempt")
            self._require_owner(db, row["target"], row["route"], owner)
            if receipt is None:
                receipt = json.loads(row["receipt"]) if row["receipt"] is not None else self._read_receipt(row)
            if receipt is None:
                raise BudgetPending(self._attempt(row))
            self._settle(db, row, receipt)
            summary = self._summary(db, row["target"], row["route"], row["bucket"])
            return {"receipt": receipt, "summary": summary}
