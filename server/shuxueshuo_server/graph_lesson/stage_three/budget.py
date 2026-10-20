"""Durable calculation accounting, distinct from checkpoints and wall-clock downtime.

A route's kernel file lock is its lease. SQLite owns attempts, receipts, actual
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
import sqlite3
import time
import uuid
from contextlib import closing, contextmanager


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
    """Add calculation tables to one already identity-validated EventStore."""

    def __init__(self, store):
        self.directory = store.directory / "calculation-budget"
        self.directory.mkdir(exist_ok=True)
        self.receipts = self.directory / "receipts"
        self.receipts.mkdir(exist_ok=True)
        self._store_connect = store._connect
        self._owners = {}
        with closing(self._connect()) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS calculation_budgets (
                    target TEXT NOT NULL, route TEXT NOT NULL, bucket TEXT NOT NULL,
                    limit_seconds REAL NOT NULL, initial_seconds REAL NOT NULL,
                    PRIMARY KEY(target, route, bucket));
                CREATE TABLE IF NOT EXISTS calculation_leases (
                    target TEXT NOT NULL, route TEXT NOT NULL, owner TEXT NOT NULL,
                    pid INTEGER NOT NULL, acquired_at REAL NOT NULL, released INTEGER NOT NULL,
                    PRIMARY KEY(target, route));
                CREATE TABLE IF NOT EXISTS calculation_attempts (
                    attempt_id TEXT PRIMARY KEY, target TEXT NOT NULL, route TEXT NOT NULL,
                    bucket TEXT NOT NULL, operation_key TEXT NOT NULL, input_hash TEXT NOT NULL,
                    ordinal INTEGER NOT NULL, owner TEXT NOT NULL, status TEXT NOT NULL,
                    allowance_seconds REAL NOT NULL, elapsed_seconds REAL NOT NULL,
                    reserved_upper_seconds REAL NOT NULL, receipt TEXT,
                    UNIQUE(target, route, bucket, operation_key, ordinal));
            """)

    def _connect(self):
        db = self._store_connect()
        db.row_factory = sqlite3.Row
        return db

    @contextmanager
    def route_lease(self, target, route):
        """Hold a nonblocking kernel lease; process exit/SIGKILL releases it."""
        _text(target, "target")
        _text(route, "route")
        key = hashlib.sha256(_dump([target, route]).encode()).hexdigest()
        with (self.directory / (key + ".lock")).open("a+b") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise BudgetConflict("budget.lease_busy") from exc
            owner = uuid.uuid4().hex
            with closing(self._connect()) as db:
                db.execute("BEGIN IMMEDIATE")
                db.execute("""INSERT INTO calculation_leases VALUES (?,?,?,?,?,0)
                              ON CONFLICT(target,route) DO UPDATE SET owner=excluded.owner,
                              pid=excluded.pid, acquired_at=excluded.acquired_at,released=0""",
                           (target, route, owner, os.getpid(), time.time()))
                db.commit()
            self._owners[owner] = (target, route)
            try:
                yield owner
            finally:
                self._owners.pop(owner, None)
                try:
                    with closing(self._connect()) as db:
                        db.execute("UPDATE calculation_leases SET released=1 WHERE target=? AND route=? AND owner=?",
                                   (target, route, owner))
                finally:
                    fcntl.flock(lock, fcntl.LOCK_UN)

    def _require_owner(self, db, target, route, owner):
        if self._owners.get(owner) != (target, route):
            raise BudgetConflict("budget.lease_not_owned")
        saved = db.execute("SELECT owner,released FROM calculation_leases WHERE target=? AND route=?",
                           (target, route)).fetchone()
        if saved is None or saved["owner"] != owner or saved["released"]:
            raise BudgetConflict("budget.lease_stale")

    def configure(self, target, route, bucket, limit_seconds, *, initial_seconds=0):
        """Configure once; initial usage imports a pre-ledger checkpoint only once."""
        _text(target, "target")
        _text(route, "route")
        if bucket not in ("solve", "verification", "selection"):
            raise ValueError("budget.invalid_bucket")
        limit_seconds = _seconds(limit_seconds, "limit_seconds")
        initial_seconds = _seconds(initial_seconds, "initial_seconds")
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT limit_seconds FROM calculation_budgets WHERE target=? AND route=? AND bucket=?",
                             (target, route, bucket)).fetchone()
            if row and row[0] != limit_seconds:
                raise BudgetConflict("budget.limit_mismatch")
            db.execute("INSERT OR IGNORE INTO calculation_budgets VALUES (?,?,?,?,?)",
                       (target, route, bucket, limit_seconds, initial_seconds))
            db.commit()
            return self._summary(db, target, route, bucket)

    def _receipt_path(self, attempt_id):
        return self.receipts / (attempt_id + ".json")

    def _attempt(self, row):
        value = dict(row)
        value["receipt"] = json.loads(value["receipt"]) if value["receipt"] is not None else None
        value["receipt_path"] = str(self._receipt_path(value["attempt_id"]))
        return value

    def _summary(self, db, target, route, bucket):
        budget = db.execute("SELECT * FROM calculation_budgets WHERE target=? AND route=? AND bucket=?",
                            (target, route, bucket)).fetchone()
        if budget is None:
            raise ValueError("budget.not_configured")
        rows = db.execute("""SELECT rowid,* FROM calculation_attempts WHERE target=? AND route=? AND bucket=?
                             ORDER BY rowid""", (target, route, bucket)).fetchall()
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
        with closing(self._connect()) as db:
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
        db.execute("""UPDATE calculation_attempts SET status='settled',elapsed_seconds=?,
                      reserved_upper_seconds=0,receipt=? WHERE attempt_id=?""",
                   (receipt["elapsed_seconds"], encoded, row["attempt_id"]))

    def _read_receipt(self, row):
        path = self._receipt_path(row["attempt_id"])
        try:
            return json.loads(path.read_text())
        except FileNotFoundError:
            return None

    def recover(self, target, route, owner):
        """Import completed work or retain an explicit unknown upper reservation."""
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            self._require_owner(db, target, route, owner)
            rows = db.execute("SELECT * FROM calculation_attempts WHERE target=? AND route=? AND status!='settled'",
                              (target, route)).fetchall()
            recovered = []
            for row in rows:
                receipt = self._read_receipt(row)
                if receipt is not None:
                    self._settle(db, row, receipt)
                elif row["owner"] != owner:
                    db.execute("UPDATE calculation_attempts SET status='interrupted_unknown' WHERE attempt_id=?",
                               (row["attempt_id"],))
                updated = db.execute("SELECT * FROM calculation_attempts WHERE attempt_id=?",
                                     (row["attempt_id"],)).fetchone()
                recovered.append(self._attempt(updated))
            buckets = [row[0] for row in db.execute(
                "SELECT bucket FROM calculation_budgets WHERE target=? AND route=?", (target, route))]
            summaries = {bucket: self._summary(db, target, route, bucket) for bucket in buckets}
            db.commit()
            return {"recovered": recovered, "summaries": summaries}

    def begin(self, target, route, bucket, operation_key, input_hash, owner):
        """Reserve before launch; replay an existing terminal receipt without calculation."""
        _text(operation_key, "operation_key")
        _text(input_hash, "input_hash")
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            self._require_owner(db, target, route, owner)
            previous = db.execute("""SELECT * FROM calculation_attempts
                WHERE target=? AND route=? AND bucket=? AND operation_key=? ORDER BY ordinal DESC LIMIT 1""",
                                  (target, route, bucket, operation_key)).fetchone()
            ordinal = 1
            if previous is not None:
                if previous["input_hash"] != input_hash:
                    raise BudgetConflict("budget.operation_input_mismatch")
                ordinal = previous["ordinal"] + 1
                if previous["receipt"] is None:
                    receipt = self._read_receipt(previous)
                    if receipt is not None:
                        self._settle(db, previous, receipt)
                        previous = db.execute("SELECT * FROM calculation_attempts WHERE attempt_id=?",
                                              (previous["attempt_id"],)).fetchone()
                    else:
                        raise BudgetPending(self._attempt(previous))
                receipt = json.loads(previous["receipt"])
                if receipt["status"] != "parent_lost":
                    summary = self._summary(db, target, route, bucket)
                    db.commit()
                    return {**self._attempt(previous), "reused": True,
                            "remaining_seconds": summary["remaining_seconds"], "summary": summary}
            summary = self._summary(db, target, route, bucket)
            remaining = summary["remaining_seconds"]
            if remaining <= 0:
                # A receipt imported above must remain settled even if its
                # parent-lost attempt exhausted the allowance before retry.
                db.commit()
                raise BudgetExhausted(summary)
            attempt_id = uuid.uuid4().hex
            db.execute("INSERT INTO calculation_attempts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,NULL)",
                       (attempt_id, target, route, bucket, operation_key, input_hash, ordinal, owner,
                        "pending", remaining, 0.0, remaining))
            row = db.execute("SELECT * FROM calculation_attempts WHERE attempt_id=?", (attempt_id,)).fetchone()
            summary = self._summary(db, target, route, bucket)
            db.commit()
            return {**self._attempt(row), "reused": False, "remaining_seconds": remaining, "summary": summary}

    def finish(self, attempt_id, owner, receipt=None):
        """Settle exactly once. Durable receipt reuse does not depend on its file surviving."""
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM calculation_attempts WHERE attempt_id=?", (attempt_id,)).fetchone()
            if row is None:
                raise ValueError("budget.unknown_attempt")
            self._require_owner(db, row["target"], row["route"], owner)
            if receipt is None:
                receipt = json.loads(row["receipt"]) if row["receipt"] is not None else self._read_receipt(row)
            if receipt is None:
                raise BudgetPending(self._attempt(row))
            self._settle(db, row, receipt)
            summary = self._summary(db, row["target"], row["route"], row["bucket"])
            db.commit()
            return {"receipt": receipt, "summary": summary}
