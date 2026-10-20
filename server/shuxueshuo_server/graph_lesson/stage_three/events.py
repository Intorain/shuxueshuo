"""A durable event stream and execution state committed in one SQLite transaction.

There is no browser callback in the write path. Readers observe only committed
state, and a retry of the same logical commit cannot repeat a business event.
"""

import fcntl
import json
import logging
import math
import os
import re
import shutil
import sqlite3
from contextlib import closing
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

from shuxueshuo_server.problem_understanding.identity import revision

from .checkpoint import atomic_write, export_json, identity_value, validate_checkpoint
from .contracts import ROOT
from .revision_manifest import math_step_hash, validate_revision_ref
from .storage_validation import validate_schema

_LOG = logging.getLogger(__name__)
INTERACTION_PROTOCOL = "graph-step-interaction/v1"
_STORAGE_VERSION = "3"
_EXPORT_GENERATION = re.compile(r"[0-9]+-[0-9]+-[a-f0-9]{64}-[a-f0-9]{64}\Z")


def _sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _prune_export_generations(current):
    """Best-effort GC after durable publication, with the export lock held.

    Only generated sibling directories belong to us. Never follow symlinks or
    remove unrelated files. A failed/partial cleanup is retried by the next
    export and must not turn a successfully solved route into an error.
    """
    parent = current.parent
    try:
        if parent.is_symlink():
            return
        for stale in parent.iterdir():
            if (stale == current or not _EXPORT_GENERATION.fullmatch(stale.name)
                    or stale.is_symlink() or not stale.is_dir()):
                continue
            try:
                shutil.rmtree(stale)
            except OSError:
                _LOG.warning("Could not remove stale debug export %s; will retry on the next export", stale,
                             exc_info=True)
        _sync_directory(parent)
    except OSError:
        _LOG.warning("Could not finish debug export cleanup in %s; will retry on the next export", parent,
                     exc_info=True)


def goal_unavailable(value):
    return bool(value) and (value["status"] == "conflict" or value.get("available") is False
                           or value.get("reason") == "route_consistency_undecidable")


class CursorExpired(ValueError):
    def __init__(self, minimum_seq):
        self.minimum_seq = minimum_seq
        super().__init__("events.cursor_expired")


def _dump(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _validate(name, value):
    validate_schema(ROOT / "internal/schemas" / name, value)


def _compact_receipt(result):
    """Historical receipts identify commits; only checkpoints own resumable state."""
    checkpoint = result.get("checkpoint")
    if checkpoint is not None:
        result["checkpoint"] = {key: checkpoint[key] for key in (
            "contract", "run_id", "lesson_version", "input_sha256", "revisions", "target_ref", "route_id",
            "revisions_ref", "status", "commit_id", "last_seq",
        ) if key in checkpoint}
    return result


class EventStore:
    """One run, many independently checkpointed target/route pairs."""

    def __init__(self, directory, identity, *, create=False):
        self.directory = Path(directory)
        self.path = self.directory / "events.sqlite3"
        self.identity = identity_value(identity)
        if create:
            self.directory.mkdir(parents=True, exist_ok=True)
            # Exclusive reservation prevents accidentally adopting an old run.
            with self.path.open("xb"):
                pass
            with closing(self._connect()) as db:
                db.executescript("""
                    CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                    CREATE TABLE commits (id TEXT PRIMARY KEY, digest TEXT NOT NULL, result TEXT NOT NULL);
                    CREATE TABLE checkpoints (target TEXT NOT NULL, route TEXT NOT NULL, value TEXT NOT NULL,
                                              PRIMARY KEY(target, route));
                    CREATE TABLE steps (target TEXT NOT NULL, route TEXT NOT NULL, step TEXT NOT NULL,
                                        ordinal INTEGER NOT NULL, value TEXT NOT NULL,
                                        PRIMARY KEY(target, route, step), UNIQUE(target, route, ordinal));
                    CREATE TABLE events (seq INTEGER PRIMARY KEY, value TEXT NOT NULL);
                    CREATE TABLE goals (target TEXT PRIMARY KEY, value TEXT NOT NULL);
                    CREATE TABLE handoffs (target TEXT NOT NULL, route TEXT NOT NULL, value TEXT NOT NULL,
                                           PRIMARY KEY(target, route));
                    CREATE TABLE qa (target TEXT NOT NULL, route TEXT NOT NULL, step TEXT NOT NULL, value TEXT NOT NULL,
                                     PRIMARY KEY(target, route, step));
                """)
                db.execute("BEGIN IMMEDIATE")
                db.executemany("INSERT INTO metadata VALUES (?,?)", [
                    ("identity", _dump(self.identity)), ("last_seq", "0"), ("minimum_seq", "1"),
                ])
                db.commit()
        elif not self.path.is_file():
            raise FileNotFoundError(self.path)
        with closing(self._connect()) as db:
            saved = json.loads(db.execute("SELECT value FROM metadata WHERE key='identity'").fetchone()[0])
        if saved != self.identity:
            raise ValueError("checkpoint.identity_mismatch")
        self._migrate_storage()

    def _connect(self):
        db = sqlite3.connect(self.path, isolation_level=None, timeout=10)
        db.execute("PRAGMA synchronous=FULL")
        db.execute("PRAGMA journal_mode=WAL")
        return db

    def _migrate_storage(self):
        """Apply versioned migrations once, with all data and DDL in one transaction."""
        with closing(self._connect()) as db:
            version = db.execute("SELECT value FROM metadata WHERE key='storage_version'").fetchone()
            if version and version[0] == _STORAGE_VERSION:
                return
            db.execute("BEGIN IMMEDIATE")
            try:
                # Another opener may have completed the migration while this
                # connection waited for the write lock.
                version = db.execute("SELECT value FROM metadata WHERE key='storage_version'").fetchone()
                if version and version[0] == _STORAGE_VERSION:
                    db.rollback()
                    return
                if version is not None and version[0] not in {"1", "2"}:
                    raise ValueError("events.unsupported_storage_version")
                if version is None or version[0] == "1":
                    # v2: backfill retained selection and compact historical receipts.
                    db.execute("""CREATE TABLE IF NOT EXISTS selection_chunks (
                        target TEXT NOT NULL, kind TEXT NOT NULL, seq INTEGER NOT NULL, value TEXT NOT NULL,
                        PRIMARY KEY(target,kind))""")
                    db.execute("""CREATE TABLE IF NOT EXISTS step_summaries (
                        target TEXT NOT NULL, route TEXT NOT NULL, step TEXT NOT NULL,
                        ordinal INTEGER NOT NULL, hash TEXT NOT NULL, PRIMARY KEY(target,route,step),
                        UNIQUE(target,route,ordinal))""")
                    for commit_id, raw in db.execute("SELECT id,result FROM commits").fetchall():
                        result = json.loads(raw)
                        for event in result["events"]:
                            self._put_selection(db, event)
                        compact = _compact_receipt(result)
                        db.execute("UPDATE commits SET result=? WHERE id=?", (_dump(compact), commit_id))
                    for target, route, step, ordinal, raw in db.execute("SELECT * FROM steps").fetchall():
                        value = json.loads(raw)
                        db.execute("INSERT OR REPLACE INTO step_summaries VALUES (?,?,?,?,?)",
                                   (target, route, step, ordinal, value["math_step_sha256"]))
                # v3 also adopts databases written by the unversioned interaction
                # implementation. Existing tables and their committed rows survive.
                db.execute("""CREATE TABLE IF NOT EXISTS interaction_states (
                    target TEXT NOT NULL, route TEXT NOT NULL, step TEXT NOT NULL, ordinal INTEGER NOT NULL,
                    hash TEXT NOT NULL, status TEXT NOT NULL, interaction_id TEXT,
                    PRIMARY KEY(target, route, step))""")
                db.execute("""CREATE TABLE IF NOT EXISTS interactions (
                    interaction_id TEXT PRIMARY KEY, target TEXT NOT NULL, route TEXT NOT NULL,
                    ordinal INTEGER NOT NULL, value TEXT NOT NULL)""")
                db.execute("INSERT OR REPLACE INTO metadata VALUES ('storage_version',?)", (_STORAGE_VERSION,))
                db.commit()
            except BaseException:
                db.rollback()
                raise

    @staticmethod
    def _put_selection(db, event):
        payload = event["payload"]
        if event["type"] != "lesson.chunk_ready" or payload.get("kind") not in {"D1", "D2", "D3", "D4"}:
            return
        value = {"target_ref": event["target_ref"], "kind": payload["kind"], "chunk": payload["chunk"]}
        db.execute("""INSERT INTO selection_chunks VALUES (?,?,?,?)
            ON CONFLICT(target,kind) DO UPDATE SET seq=excluded.seq,value=excluded.value
            WHERE excluded.seq > selection_chunks.seq""",
            (event["target_ref"], payload["kind"], event["seq"], _dump(value)))

    @staticmethod
    def _watermark(db):
        return int(db.execute("SELECT value FROM metadata WHERE key='last_seq'").fetchone()[0])

    def _append_event(self, db, commit_id, spec):
        event = {
            "contract": "graph-stage-three-event/v1", "stream_id": self.identity["run_id"],
            "run_id": self.identity["run_id"], "lesson_version": self.identity["lesson_version"],
            "seq": self._watermark(db) + 1, "target_ref": spec.get("target_ref"),
            "route_id": spec.get("route_id"), "type": spec["type"], "payload": deepcopy(spec["payload"]),
        }
        event["event_id"] = revision({"run_id": self.identity["run_id"], "commit_id": commit_id,
                                      "seq": event["seq"], "event": spec})
        _validate("graph-stage-three-event-v1.schema.json", event)
        db.execute("INSERT INTO events VALUES (?,?)", (event["seq"], _dump(event)))
        self._put_selection(db, event)
        db.execute("UPDATE metadata SET value=? WHERE key='last_seq'", (str(event["seq"]),))
        return event

    def _transaction(self, commit_id, request, mutate, *, before_commit=None, after_commit=None):
        if not isinstance(commit_id, str) or not commit_id:
            raise ValueError("events.invalid_commit_id")
        digest = revision(request)
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                previous = db.execute("SELECT digest,result FROM commits WHERE id=?", (commit_id,)).fetchone()
                if previous:
                    if previous[0] != digest:
                        raise ValueError("events.commit_reuse_mismatch")
                    db.rollback()
                    return _compact_receipt(json.loads(previous[1]))
                first = self._watermark(db)
                result = _compact_receipt(mutate(db) or {})
                result.update(commit_id=commit_id, last_seq=self._watermark(db))
                result["events"] = [json.loads(row[0]) for row in db.execute(
                    "SELECT value FROM events WHERE seq>? ORDER BY seq", (first,),
                )]
                db.execute("INSERT INTO commits VALUES (?,?,?)", (commit_id, digest, _dump(result)))
                if before_commit:
                    before_commit()
                db.commit()
            except BaseException:
                db.rollback()
                raise
        if after_commit:
            after_commit()
        return result

    def _steps(self, db, target, route):
        return [json.loads(row[0]) for row in db.execute(
            "SELECT value FROM steps WHERE target=? AND route=? ORDER BY ordinal", (target, route),
        )]

    def _checkpoint(self, db, target, route):
        row = db.execute("SELECT value FROM checkpoints WHERE target=? AND route=?", (target, route)).fetchone()
        return json.loads(row[0]) if row else None

    def _put_checkpoint(self, db, checkpoint, commit_id):
        value = deepcopy(checkpoint)
        value["commit_id"], value["last_seq"] = commit_id, self._watermark(db)
        value["math_steps"] = [dict(zip(("step_id", "ordinal", "math_step_sha256"), row, strict=True))
                               for row in db.execute(
                                   "SELECT step,ordinal,hash FROM step_summaries WHERE target=? AND route=? ORDER BY ordinal",
                                   (value["target_ref"], value["route_id"]),
                               )]
        validate_checkpoint(value, self.identity)
        db.execute("INSERT INTO checkpoints VALUES (?,?,?) ON CONFLICT(target,route) DO UPDATE SET value=excluded.value",
                   (value["target_ref"], value["route_id"], _dump(value)))
        return value

    def _put_step(self, db, step):
        version = "v2" if step.get("contract") == "graph-math-step/v2" else "v1"
        _validate(f"graph-math-step-{version}.schema.json", step)
        for key in ("run_id", "lesson_version"):
            if step[key] != self.identity[key]:
                raise ValueError("events.step_identity_mismatch")
        try:
            validate_revision_ref(step, self.identity["revisions"])
        except ValueError as exc:
            raise ValueError("events.step_identity_mismatch") from exc
        if step["math_step_sha256"] != math_step_hash(step, self.identity["revisions"]):
            raise ValueError("events.step_hash_mismatch")
        target, route, step_id = step["target_ref"], step["route_id"], step["step_id"]
        previous = db.execute("SELECT value FROM steps WHERE target=? AND route=? AND step=?",
                              (target, route, step_id)).fetchone()
        if previous:
            if json.loads(previous[0]) != step:
                raise ValueError("events.immutable_step")
            return False
        count = db.execute("SELECT COUNT(*) FROM steps WHERE target=? AND route=?", (target, route)).fetchone()[0]
        if step["ordinal"] != count + 1:
            raise ValueError("events.noncontiguous_step")
        db.execute("INSERT INTO steps VALUES (?,?,?,?,?)", (target, route, step_id, step["ordinal"], _dump(step)))
        db.execute("INSERT INTO step_summaries VALUES (?,?,?,?,?)",
                   (target, route, step_id, step["ordinal"], step["math_step_sha256"]))
        return True

    def _put_goal(self, db, target, value):
        if goal_unavailable(self._goal(db, target)) and not goal_unavailable(value):
            raise ValueError("events.invalid_goal_reactivation")
        db.execute("INSERT INTO goals VALUES (?,?) ON CONFLICT(target) DO UPDATE SET value=excluded.value",
                   (target, _dump(value)))
        if goal_unavailable(value):
            for route, raw in db.execute("SELECT route,value FROM handoffs WHERE target=?", (target,)).fetchall():
                task = json.loads(raw)
                task.update(available=False, status="cancelled", cancellation_reason=value.get("reason"))
                db.execute("UPDATE handoffs SET value=? WHERE target=? AND route=?", (_dump(task), target, route))

    def _goal(self, db, target):
        row = db.execute("SELECT value FROM goals WHERE target=?", (target,)).fetchone()
        return json.loads(row[0]) if row else None

    # --- Step interactions -------------------------------------------------------

    def enable_interactions(self, registry, *, revision, engine_revision, budget=None):
        """Freeze this run's interaction rules once; later runs may use newer files."""
        settings = {"protocol": INTERACTION_PROTOCOL, "registry": registry, "revision": revision,
                    "engine_revision": engine_revision}
        if budget is not None:
            if (set(budget) != {"group_seconds", "route_seconds"}
                    or any(isinstance(value, bool) or not isinstance(value, (int, float))
                           or not math.isfinite(value) or value <= 0 for value in budget.values())):
                raise ValueError("events.invalid_interaction_budget")
            settings["budget"] = {key: float(value) for key, value in budget.items()}
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                previous = db.execute("SELECT value FROM metadata WHERE key='interactions'").fetchone()
                if previous is not None and json.loads(previous[0]) != settings:
                    raise ValueError("events.interaction_settings_changed")
                if db.execute("SELECT COUNT(*) FROM steps").fetchone()[0] and previous is None:
                    raise ValueError("events.interactions_after_math")
                db.execute("INSERT OR IGNORE INTO metadata VALUES ('interactions',?)", (_dump(settings),))
                db.commit()
            except BaseException:
                db.rollback()
                raise

    @staticmethod
    def _interaction_settings(db):
        row = db.execute("SELECT value FROM metadata WHERE key='interactions'").fetchone()
        return json.loads(row[0]) if row else None

    def interaction_settings(self):
        """``None`` for runs recorded before step interactions existed."""
        with closing(self._connect()) as db:
            return self._interaction_settings(db)

    def has_pending_interactions(self):
        with closing(self._connect()) as db:
            return db.execute("SELECT 1 FROM interaction_states WHERE status='pending' LIMIT 1").fetchone() is not None

    def commit_watermark(self):
        """A cheap change token including checkpoint-only commits without an event."""
        with closing(self._connect()) as db:
            return db.execute("SELECT COALESCE(MAX(rowid),0) FROM commits").fetchone()[0]

    @staticmethod
    def _interaction_failure_key(target, route):
        return "interaction_failure:" + revision([target, route])

    @classmethod
    def _interaction_failure(cls, db, target, route):
        row = db.execute("SELECT value FROM metadata WHERE key=?",
                         (cls._interaction_failure_key(target, route),)).fetchone()
        return json.loads(row[0]) if row else {"count": 0, "disabled": False, "last_error": None}

    def interaction_failure(self, target, route):
        """Consecutive scheduler failures; disabled routes stay read-only on resume."""
        with closing(self._connect()) as db:
            return self._interaction_failure(db, target, route)

    @staticmethod
    def _interaction_attempt(target, route, attempt_id):
        if any(not isinstance(value, str) or not value for value in (target, route, attempt_id)):
            raise ValueError("events.invalid_interaction_attempt")
        return {"target": target, "route": route, "attempt_id": attempt_id}

    def record_interaction_failure(self, target, route, diagnostic, *, pending_steps, attempt_id, limit=3,
                                   before_commit=None, after_commit=None):
        """Count one invocation once, atomically close pending cards at the limit.

        The invocation identity, not a possibly changing exception message, is
        the idempotency key. Its first diagnostic remains the authoritative one.
        """
        from .interaction import readonly_chunk

        request = self._interaction_attempt(target, route, attempt_id)
        if type(limit) is not int or limit < 1 or not isinstance(diagnostic, dict):
            raise ValueError("events.invalid_interaction_failure")
        if not isinstance(pending_steps, list) or any(
            not isinstance(step, dict) or set(step) != {"step_id", "math_step_sha256"}
            or not isinstance(step["step_id"], str) or not step["step_id"]
            or not isinstance(step["math_step_sha256"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", step["math_step_sha256"]) for step in pending_steps
        ):
            raise ValueError("events.invalid_interaction_pending_steps")
        observed = {(step["step_id"], step["math_step_sha256"]) for step in pending_steps}
        if len({step_id for step_id, _ in observed}) != len(pending_steps):
            raise ValueError("events.invalid_interaction_pending_steps")
        commit_id = "interaction-failure:" + revision(request)
        request.update(limit=limit, pending_steps=[{"step_id": step_id, "math_step_sha256": math_hash}
                                                  for step_id, math_hash in sorted(observed)])

        def mutate(db):
            failure = self._interaction_failure(db, target, route)
            pending = db.execute("SELECT step,hash FROM interaction_states WHERE target=? AND route=? "
                                 "AND status='pending' ORDER BY ordinal", (target, route)).fetchall()
            # Another scheduler may have resolved the observed cards while
            # mathematics appended new ones. A late error for the old cards
            # must not spend the new cards' failure allowance.
            if failure["disabled"] or not observed.intersection(pending):
                return {**failure, "resolved_count": 0}
            failure = {"count": failure["count"] + 1, "disabled": failure["count"] + 1 >= limit,
                       "last_error": deepcopy(diagnostic)}
            db.execute("INSERT OR REPLACE INTO metadata VALUES (?,?)",
                       (self._interaction_failure_key(target, route), _dump(failure)))
            resolved = 0
            if failure["disabled"]:
                settings = self._interaction_settings(db)
                for step_id, math_hash in pending:
                    seed = {key: self.identity[key] for key in ("run_id", "lesson_version")}
                    seed.update(target_ref=target, route_id=route, step_id=step_id, math_step_sha256=math_hash)
                    resolved += self._put_interaction(db, commit_id, readonly_chunk(
                        [seed], settings["revision"], "scheduler_error"),
                        [{"result": "readonly", "reason": "scheduler_error", "scheduler_error": diagnostic}])
            return {**failure, "resolved_count": resolved}

        return self._transaction(commit_id, request, mutate, before_commit=before_commit, after_commit=after_commit)

    def clear_interaction_failure(self, target, route, *, attempt_id):
        """Clear recoverable failures after a successful pass, never reopen a route."""
        request = self._interaction_attempt(target, route, attempt_id)
        failure = self.interaction_failure(target, route)
        if failure["count"] == 0 or failure["disabled"]:
            return failure

        def mutate(db):
            current = self._interaction_failure(db, target, route)
            if current["disabled"] or current["count"] == 0:
                return current
            cleared = {"count": 0, "disabled": False, "last_error": None}
            db.execute("INSERT OR REPLACE INTO metadata VALUES (?,?)",
                       (self._interaction_failure_key(target, route), _dump(cleared)))
            return cleared

        return self._transaction("interaction-recovered:" + revision(request), request, mutate)

    def _put_interaction(self, db, commit_id, chunk, diagnostics):
        from .interaction import chunk_sha256, validate_chunk

        validate_chunk(chunk)
        settings = self._interaction_settings(db)
        if settings is None:
            raise ValueError("events.interactions_disabled")
        if (chunk["run_id"], chunk["lesson_version"]) != (self.identity["run_id"], self.identity["lesson_version"]):
            raise ValueError("events.interaction_identity_mismatch")
        if chunk["interaction_revision"] != settings["revision"]:
            raise ValueError("events.interaction_revision_mismatch")
        if chunk["interaction_sha256"] != chunk_sha256(chunk):
            raise ValueError("events.interaction_hash_mismatch")
        target, route, identifier = chunk["target_ref"], chunk["route_id"], chunk["interaction_id"]
        previous = db.execute("SELECT value FROM interactions WHERE interaction_id=?", (identifier,)).fetchone()
        if previous:
            saved = json.loads(previous[0])
            if saved["chunk"] != chunk and saved.get("request_sha256") != chunk["interaction_sha256"]:
                raise ValueError("events.immutable_interaction")
            return False
        rows = []
        for step in chunk["steps"]:
            row = db.execute("SELECT ordinal,hash,status,interaction_id FROM interaction_states "
                             "WHERE target=? AND route=? AND step=?", (target, route, step["step_id"])).fetchone()
            if row is None or row[1] != step["math_step_sha256"]:
                raise ValueError("events.interaction_step_mismatch")
            if row[2] != "pending":
                raise ValueError("events.interaction_already_resolved")
            rows.append(row)
        ordinals = [row[0] for row in rows]
        if ordinals != list(range(ordinals[0], ordinals[0] + len(ordinals))):
            raise ValueError("events.interaction_noncontiguous")
        value = {"chunk": chunk, "diagnostics": diagnostics}
        checkpoint = self._checkpoint(db, target, route) if chunk["status"] == "interactive" else None
        if chunk["status"] == "interactive" and (goal_unavailable(self._goal(db, target)) or checkpoint is None
                                                or checkpoint["status"] in {"capability_gap", "math_failed", "execution_error"}):
            # The worker may have started before a route failed or its goal was
            # revoked. Decide availability under the same write lock as the
            # terminal state and event; keep the original request for retries.
            value["request_sha256"] = chunk["interaction_sha256"]
            chunk = deepcopy(chunk)
            chunk.update(status="readonly", parts=[], reason="route_unavailable")
            chunk["interaction_sha256"] = chunk_sha256(chunk)
            value.update(chunk=chunk, diagnostics=[*diagnostics, {"result": "readonly", "reason": "route_unavailable"}])
        db.execute("INSERT INTO interactions VALUES (?,?,?,?,?)", (identifier, target, route, ordinals[0], _dump(value)))
        for step in chunk["steps"]:
            db.execute("UPDATE interaction_states SET status=?,interaction_id=? WHERE target=? AND route=? AND step=?",
                       (chunk["status"], identifier, target, route, step["step_id"]))
        self._append_event(db, commit_id, {"type": "lesson.chunk_ready", "target_ref": target, "route_id": route,
                                           "payload": {"kind": "step_interaction", "interaction_id": identifier,
                                                       "status": chunk["status"], "chunk": chunk}})
        return True

    def _open_interaction(self, db, commit_id, step, seed):
        """A new card starts pending; one without a usable seed is read-only at once."""
        from .interaction import readonly_chunk

        settings = self._interaction_settings(db)
        if settings is None:
            return None
        db.execute("INSERT INTO interaction_states VALUES (?,?,?,?,?,'pending',NULL)",
                   (step["target_ref"], step["route_id"], step["step_id"], step["ordinal"], step["math_step_sha256"]))
        if self._interaction_failure(db, step["target_ref"], step["route_id"])["disabled"]:
            stub = {key: step[key] for key in ("run_id", "lesson_version", "target_ref", "route_id", "step_id",
                                             "math_step_sha256")}
            return readonly_chunk([stub], settings["revision"], "scheduler_error")
        if seed is None:
            reason = "seed_missing"
        elif seed.get("math_step_sha256") != step["math_step_sha256"]:
            reason = "seed_hash_mismatch"
        elif seed.get("status") != "ready":
            reason = seed.get("reason", "seed_missing")
        else:
            return "pending"
        stub = seed or {key: step[key] for key in ("run_id", "lesson_version", "target_ref", "route_id", "step_id")}
        stub = {**stub, "math_step_sha256": step["math_step_sha256"]}
        return readonly_chunk([stub], settings["revision"], reason)

    def commit_interaction(self, chunk, *, diagnostics=(), commit_id=None, before_commit=None, after_commit=None):
        """Resolve pending cards exactly once; an identical retry is idempotent."""
        commit_id = commit_id or f"{chunk['target_ref']}:{chunk['route_id']}:interaction:{chunk['interaction_id']}"
        diagnostics = list(diagnostics)

        def mutate(db):
            return {"interaction_id": chunk["interaction_id"], "committed": self._put_interaction(
                db, commit_id, chunk, diagnostics)}

        return self._transaction(commit_id, {"chunk": chunk, "diagnostics": diagnostics}, mutate,
                                 before_commit=before_commit, after_commit=after_commit)

    @staticmethod
    def _interaction_states(db, target_ref=None, route_id=None):
        query, arguments = "SELECT target,route,step,ordinal,hash,status,interaction_id FROM interaction_states", ()
        if target_ref is not None:
            query, arguments = query + " WHERE target=? AND route=?", (target_ref, route_id)
        return [dict(zip(("target_ref", "route_id", "step_id", "ordinal", "math_step_sha256", "status",
                          "interaction_id"), row, strict=True))
                for row in db.execute(query + " ORDER BY target,route,ordinal", arguments)]

    def interaction_states(self, target_ref=None, route_id=None):
        with closing(self._connect()) as db:
            return self._interaction_states(db, target_ref, route_id)

    def interaction_context(self, target_ref, route_id):
        """Read seeds and their published card states from the same SQLite snapshot."""
        with closing(self._connect()) as db:
            db.execute("BEGIN")
            checkpoint = self._checkpoint(db, target_ref, route_id)
            if checkpoint is not None:
                validate_checkpoint(checkpoint, self.identity)
            return checkpoint, self._interaction_states(db, target_ref, route_id)

    def goal(self, target_ref):
        with closing(self._connect()) as db:
            return self._goal(db, target_ref)

    def interaction(self, interaction_id):
        with closing(self._connect()) as db:
            row = db.execute("SELECT value FROM interactions WHERE interaction_id=?", (interaction_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def commit_route(self, checkpoint, *, commit_id, math_steps=(), events=(), before_commit=None, after_commit=None):
        """Commit exactly one resumable operation and its newly readable fragments."""
        request = {"checkpoint": checkpoint, "math_steps": list(math_steps), "events": list(events)}

        def mutate(db):
            target, route = checkpoint["target_ref"], checkpoint["route_id"]
            if checkpoint["status"] == "verified":
                raise ValueError("events.use_complete_route")
            prior = self._checkpoint(db, target, route)
            if prior and prior["status"] in ("verified", "capability_gap", "math_failed", "execution_error"):
                raise ValueError("events.terminal_route")
            for spec in request["events"]:
                if spec.get("target_ref") != target or spec.get("route_id") != route:
                    raise ValueError("events.route_event_mismatch")
                if spec["type"] == "lesson.chunk_ready" or spec["type"] == "lesson.goal_status":
                    raise ValueError("events.use_typed_commit")
                self._append_event(db, commit_id, spec)
            seeds = {} if self._interaction_failure(db, target, route)["disabled"] else {
                seed["step_id"]: seed for seed in checkpoint.get("driver_state", {}).get("interaction_seeds", [])}
            for step in request["math_steps"]:
                if step["target_ref"] != target or step["route_id"] != route:
                    raise ValueError("events.route_step_mismatch")
                if self._put_step(db, step):
                    opened = self._open_interaction(db, commit_id, step, seeds.get(step["step_id"]))
                    payload = {"kind": "math_step", "step_id": step["step_id"],
                               "math_step_sha256": step["math_step_sha256"], "chunk": step}
                    if opened is not None:
                        payload["interaction_status"] = "pending" if opened == "pending" else "readonly"
                    self._append_event(db, commit_id, {"type": "lesson.chunk_ready", "target_ref": target,
                                                       "route_id": route, "payload": payload})
                    if isinstance(opened, dict):
                        self._put_interaction(db, commit_id, opened, [{"result": "readonly",
                                                                       "reason": opened["reason"]}])
            return {"checkpoint": self._put_checkpoint(db, checkpoint, commit_id)}

        return self._transaction(commit_id, request, mutate, before_commit=before_commit, after_commit=after_commit)

    def commit_events(self, events, *, commit_id, before_commit=None, after_commit=None):
        """Persist selection/status events; typed math and QA use their own gates."""
        events = list(events)

        def mutate(db):
            for spec in events:
                if spec["type"] == "lesson.chunk_ready" and spec["payload"].get("kind") not in {"D1", "D2", "D3", "D4"}:
                    raise ValueError("events.use_typed_commit")
                if spec["type"] == "solver.step_completed":
                    raise ValueError("events.checkpoint_required")
                if spec["type"] == "lesson.goal_status":
                    existing = self._goal(db, spec["target_ref"])
                    if goal_unavailable(existing) and spec["payload"]["status"] == "solved":
                        raise ValueError("events.invalid_goal_reactivation")
                    self._put_goal(db, spec["target_ref"], spec["payload"])
                self._append_event(db, commit_id, spec)

        return self._transaction(commit_id, {"events": events}, mutate,
                                 before_commit=before_commit, after_commit=after_commit)

    def checkpoint(self, target_ref, route_id):
        with closing(self._connect()) as db:
            value = self._checkpoint(db, target_ref, route_id)
            if value is not None:
                validate_checkpoint(value, self.identity)
            return value

    def committed_events(self, commit_id):
        """Read a durable transaction's evidence even after cursor retention prunes events."""
        with closing(self._connect()) as db:
            row = db.execute("SELECT result FROM commits WHERE id=?", (commit_id,)).fetchone()
        return json.loads(row[0])["events"] if row else []

    def events(self, after_seq=0):
        if type(after_seq) is not int or after_seq < 0:
            raise ValueError("events.invalid_cursor")
        with closing(self._connect()) as db:
            db.execute("BEGIN")
            minimum = int(db.execute("SELECT value FROM metadata WHERE key='minimum_seq'").fetchone()[0])
            if after_seq < minimum - 1:
                raise CursorExpired(minimum)
            if after_seq > self._watermark(db):
                raise ValueError("events.future_cursor")
            return [json.loads(row[0]) for row in db.execute("SELECT value FROM events WHERE seq>? ORDER BY seq", (after_seq,))]

    def snapshot(self):
        """Public cards/evidence and their cursor from the same read snapshot."""
        with closing(self._connect()) as db:
            db.execute("BEGIN")
            return self._snapshot(db)

    def _snapshot(self, db):
        from .public_snapshot import project_snapshot

        return project_snapshot(self._internal_snapshot(db))

    def internal_snapshot(self):
        """Full execution evidence for diagnostics, never the browser read model."""
        with closing(self._connect()) as db:
            db.execute("BEGIN")
            return self._internal_snapshot(db)

    def _internal_snapshot(self, db):
        result = {"contract": "graph-stage-three-snapshot/v1", **deepcopy(self.identity),
                  "stream_id": self.identity["run_id"], "last_seq": self._watermark(db)}
        for name, table in (("checkpoints", "checkpoints"), ("math_steps", "steps"), ("handoffs", "handoffs"), ("qa", "qa")):
            order = "target,route,ordinal" if table == "steps" else "target,route"
            result[name] = [json.loads(row[0]) for row in db.execute(f"SELECT value FROM {table} ORDER BY {order}")]
        result["goals"] = {row[0]: json.loads(row[1]) for row in db.execute("SELECT target,value FROM goals ORDER BY target")}
        result["selection_chunks"] = [json.loads(row[0]) for row in db.execute(
            "SELECT value FROM selection_chunks ORDER BY seq",
        )]
        result["minimum_seq"] = int(db.execute("SELECT value FROM metadata WHERE key='minimum_seq'").fetchone()[0])
        settings = self._interaction_settings(db)
        result["interaction_protocol"] = settings["protocol"] if settings else None
        result["interaction_states"] = [
            {key: value for key, value in zip(("target_ref", "route_id", "step_id", "ordinal", "math_step_sha256",
                                               "status", "interaction_id"), row, strict=True) if value is not None}
            for row in db.execute("SELECT target,route,step,ordinal,hash,status,interaction_id "
                                  "FROM interaction_states ORDER BY target,route,ordinal")]
        result["interactions"] = [json.loads(row[0]) for row in db.execute(
            "SELECT value FROM interactions ORDER BY target,route,ordinal")]
        return result

    def prune_events(self, through_seq):
        """Retention never drops materialized steps/checkpoints needed for resync."""
        if type(through_seq) is not int or through_seq < 0:
            raise ValueError("events.invalid_cursor")
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            if through_seq > self._watermark(db):
                raise ValueError("events.future_cursor")
            current = int(db.execute("SELECT value FROM metadata WHERE key='minimum_seq'").fetchone()[0])
            db.execute("DELETE FROM events WHERE seq<=?", (through_seq,))
            db.execute("UPDATE metadata SET value=? WHERE key='minimum_seq'", (str(max(current, through_seq + 1)),))
            db.commit()

    def export(self):
        """Publish a debug view at a route/run boundary, never a recovery journal.

        Export remains O(current evidence), intentionally avoiding a second
        append log that would need its own crash recovery. The cross-process
        lock is acquired *before* taking the SQLite snapshot so concurrent
        exporters cannot replace a newer view with an older one. Retention and
        commits can proceed while this read snapshot is exported.

        The manifest atomically points to an immutable, matched file pair.
        Once its rename is durable, old generations are removed under this
        lock. Readers of the manifest/file pair must hold a shared export lock;
        old manifest paths are not permanent archival references.
        The historical root filenames remain convenience mirrors; if a crash
        interrupts their publication, the manifest still identifies a complete
        pair and the next export repairs both mirrors from SQLite.
        """
        with (self.directory / ".export.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            snapshot, events = self.snapshot_with_events()
            snapshot_text = json.dumps(snapshot, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
            events_text = "".join(_dump(event) + "\n" for event in events)
            checkpoint_hash = sha256(snapshot_text.encode()).hexdigest()
            events_hash = sha256(events_text.encode()).hexdigest()
            generation = f"{snapshot['minimum_seq']}-{snapshot['last_seq']}-{checkpoint_hash}-{events_hash}"
            relative = Path(".event-exports") / generation
            directory = self.directory / relative
            atomic_write(directory / "checkpoint.json", snapshot_text)
            atomic_write(directory / "events.jsonl", events_text)
            # The file pair must be durable before publishing its pointer.
            for parent in (directory, directory.parent):
                _sync_directory(parent)
            export_json(self.directory / "export-manifest.json", {
                "contract": "graph-stage-three-debug-export/v1", "stream_id": self.identity["run_id"],
                "last_seq": snapshot["last_seq"], "minimum_seq": snapshot["minimum_seq"],
                "checkpoint": {"path": str(relative / "checkpoint.json"), "sha256": checkpoint_hash},
                "events": {"path": str(relative / "events.jsonl"), "sha256": events_hash},
            })
            # atomic_write fsyncs the file, not its parent. Make the new pointer
            # durable before deleting any generation the old pointer named.
            _sync_directory(self.directory)
            _prune_export_generations(directory)
            atomic_write(self.directory / "checkpoint.json", snapshot_text)
            atomic_write(self.directory / "events.jsonl", events_text)
            return snapshot

    def snapshot_with_events(self):
        """Read full debug state and retained events at one waterline."""
        with closing(self._connect()) as db:
            db.execute("BEGIN")
            snapshot = self._internal_snapshot(db)
            # Retention and new commits cannot change the events belonging to
            # this snapshot while the read transaction is open.
            events = [json.loads(row[0]) for row in db.execute("SELECT value FROM events ORDER BY seq")]
            return snapshot, events
