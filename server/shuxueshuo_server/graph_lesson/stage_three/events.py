"""A durable event stream and execution state committed in one SQLite transaction.

There is no browser callback in the write path. Readers observe only committed
state, and a retry of the same logical commit cannot repeat a business event.
"""

import json
import sqlite3
from contextlib import closing
from copy import deepcopy
from pathlib import Path

from jsonschema import Draft202012Validator

from shuxueshuo_server.problem_understanding.identity import revision

from .checkpoint import atomic_write, export_json, identity_value, validate_checkpoint
from .contracts import ROOT


def goal_unavailable(value):
    return bool(value) and (value["status"] == "conflict" or value.get("available") is False
                           or value.get("reason") == "route_consistency_undecidable")


class CursorExpired(ValueError):
    def __init__(self, minimum_seq):
        self.minimum_seq = minimum_seq
        super().__init__("events.cursor_expired")


def _dump(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def math_step_hash(fragment, revisions):
    return revision({"content": {key: value for key, value in fragment.items() if key != "math_step_sha256"},
                     "revisions": revisions})


def _validate(name, value):
    schema = json.loads((ROOT / "internal/schemas" / name).read_text())
    Draft202012Validator(schema).validate(value)


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

    def _connect(self):
        db = sqlite3.connect(self.path, isolation_level=None, timeout=10)
        db.execute("PRAGMA synchronous=FULL")
        db.execute("PRAGMA journal_mode=WAL")
        return db

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
                    return json.loads(previous[1])
                first = self._watermark(db)
                result = mutate(db) or {}
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
        value["math_steps"] = [{key: step[key] for key in ("step_id", "ordinal", "math_step_sha256")}
                               for step in self._steps(db, value["target_ref"], value["route_id"])]
        validate_checkpoint(value, self.identity)
        db.execute("INSERT INTO checkpoints VALUES (?,?,?) ON CONFLICT(target,route) DO UPDATE SET value=excluded.value",
                   (value["target_ref"], value["route_id"], _dump(value)))
        return value

    def _put_step(self, db, step):
        _validate("graph-math-step-v1.schema.json", step)
        for key in ("run_id", "lesson_version", "revisions"):
            if step[key] != self.identity[key]:
                raise ValueError("events.step_identity_mismatch")
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
            for step in request["math_steps"]:
                if step["target_ref"] != target or step["route_id"] != route:
                    raise ValueError("events.route_step_mismatch")
                if self._put_step(db, step):
                    self._append_event(db, commit_id, {"type": "lesson.chunk_ready", "target_ref": target,
                        "route_id": route, "payload": {"kind": "math_step", "step_id": step["step_id"],
                            "math_step_sha256": step["math_step_sha256"], "chunk": step}})
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
        """Materialized content and its cursor come from the same read snapshot."""
        with closing(self._connect()) as db:
            db.execute("BEGIN")
            return self._snapshot(db)

    def _snapshot(self, db):
        result = {"contract": "graph-stage-three-snapshot/v1", **deepcopy(self.identity),
                  "stream_id": self.identity["run_id"], "last_seq": self._watermark(db)}
        for name, table in (("checkpoints", "checkpoints"), ("math_steps", "steps"), ("handoffs", "handoffs"), ("qa", "qa")):
            order = "target,route,ordinal" if table == "steps" else "target,route"
            result[name] = [json.loads(row[0]) for row in db.execute(f"SELECT value FROM {table} ORDER BY {order}")]
        result["goals"] = {row[0]: json.loads(row[1]) for row in db.execute("SELECT target,value FROM goals ORDER BY target")}
        # Selection is immutable commit evidence, too. Cursor retention can
        # remove its delivery events; recover it inside this same read
        # transaction so a fresh browser never loses D1–D4 at resync.
        selections = {}
        for row in db.execute("SELECT result FROM commits"):
            for event in json.loads(row[0])["events"]:
                payload = event["payload"]
                if event["type"] == "lesson.chunk_ready" and payload.get("kind") in {"D1", "D2", "D3", "D4"}:
                    key = (event["target_ref"], payload["kind"])
                    if key not in selections or event["seq"] > selections[key]["seq"]:
                        selections[key] = event
        result["selection_chunks"] = [
            {"target_ref": event["target_ref"], "kind": event["payload"]["kind"], "chunk": event["payload"]["chunk"]}
            for event in sorted(selections.values(), key=lambda event: event["seq"])
        ]
        result["minimum_seq"] = int(db.execute("SELECT value FROM metadata WHERE key='minimum_seq'").fetchone()[0])
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
        """Export committed evidence, never read these files to resume execution."""
        snapshot, events = self.snapshot_with_events()
        export_json(self.directory / "checkpoint.json", snapshot)
        atomic_write(self.directory / "events.jsonl", "".join(_dump(event) + "\n" for event in events))
        return snapshot

    def snapshot_with_events(self):
        """Read materialized state and retained delivery events at one waterline."""
        with closing(self._connect()) as db:
            db.execute("BEGIN")
            snapshot = self._snapshot(db)
            # Retention and new commits cannot change the events belonging to
            # this snapshot while the read transaction is open.
            events = [json.loads(row[0]) for row in db.execute("SELECT value FROM events ORDER BY seq")]
            return snapshot, events
