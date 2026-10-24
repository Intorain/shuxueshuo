"""PostgreSQL execution scopes and short lifecycle-checked transactions."""

import os
import re
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache

from sqlalchemy import bindparam, create_engine, text
from sqlalchemy.dialects.postgresql import JSONB

from ...product.config import Settings


class RunNotFound(Exception):
    def __init__(self, code="events.run_not_found"):
        self.code = code
        super().__init__(code)


class RunUnavailable(ValueError):
    def __init__(self, code="events.run_unavailable"):
        self.code = code
        super().__init__(code)


class StorageContextRequired(RuntimeError):
    code = "events.storage_context_required"

    def __init__(self):
        super().__init__(self.code)


def _now():
    return datetime.now(UTC)


@dataclass(frozen=True)
class StorageContext:
    db: object
    submission_id: str | None = None
    clock: object = _now


_current = ContextVar("lesson_execution_storage", default=None)
_required = ContextVar("lesson_execution_storage_required", default=False)


@contextmanager
def require_storage_context():
    token = _required.set(True)
    try:
        yield
    finally:
        _required.reset(token)


@contextmanager
def storage_context(db, submission_id=None, clock=None):
    token = _current.set(StorageContext(db, submission_id, clock or _now))
    try:
        yield _current.get()
    finally:
        _current.reset(token)


@lru_cache(maxsize=16)
def _default_engine(data_dir, instance, schema):
    if schema and (not data_dir or not instance or not re.fullmatch(r"test_[a-z0-9_]+", schema)):
        raise ValueError("events.invalid_test_schema")
    settings = Settings.load("local", data_dir=data_dir, instance=instance)
    options = "-c timezone=UTC" + (f" -c search_path={schema},public" if schema else "")
    db = create_engine(settings.url(), isolation_level="READ COMMITTED", pool_pre_ping=True,
                       hide_parameters=True, connect_args={"options": options})
    if schema:
        with db.connect() as connection:
            if not connection.scalar(text("SELECT to_regclass(:table)"), {"table": schema + ".lesson_runs"}):
                db.dispose()
                raise ValueError("events.test_schema_not_initialized")
    return db


def current_storage():
    context = _current.get()
    required = _required.get() or os.environ.get("PRODUCT_EXECUTION_STORAGE_CONTEXT_REQUIRED") == "1"
    if required and (context is None or context.submission_id is None):
        raise StorageContextRequired()
    if context is not None:
        return context
    return StorageContext(_default_engine(os.environ.get("PRODUCT_TEST_DATA_DIR"),
        os.environ.get("PRODUCT_TEST_INSTANCE"), os.environ.get("PRODUCT_TEST_SCHEMA")))


def _submission(connection, context, *, write):
    if context.submission_id is None:
        return None
    parameters = {"submission": context.submission_id}
    if write:
        page_id = connection.scalar(text("SELECT page_id FROM search_submissions WHERE id=:submission"), parameters)
        if page_id is None:
            raise RunNotFound()
        connection.execute(text("SELECT id FROM search_pages WHERE id=:page FOR SHARE"), {"page": page_id}).first()
    row = connection.execute(text("SELECT artifact_state,expires_at,problem_id FROM search_submissions "
        "WHERE id=:submission" + (" FOR UPDATE" if write else "")), parameters).mappings().first()
    if row is None:
        raise RunNotFound()
    if row["artifact_state"] != "active" or row["expires_at"] <= context.clock():
        raise RunUnavailable("events.submission_expired")
    if row["problem_id"]:
        status = connection.scalar(text("SELECT status FROM search_problems WHERE id=:problem" +
            (" FOR SHARE" if write else "")), {"problem": row["problem_id"]})
        if status != "active":
            raise RunUnavailable("events.problem_disabled")
    return row


@contextmanager
def run_transaction(run_id, *, context=None, write=False, create_identity=None, identity=None, generation=None):
    context = context or current_storage()
    with context.db.connect() as connection:
        if not write:
            connection = connection.execution_options(isolation_level="REPEATABLE READ")
        with connection.begin():
            connection.execute(text("SET LOCAL lock_timeout = '10s'"))
            submission = _submission(connection, context, write=write)
            if create_identity is not None:
                statement = text("INSERT INTO lesson_runs (run_id,submission_id,identity) "
                    "VALUES (:run_id,:submission,:identity) ON CONFLICT (run_id) DO NOTHING RETURNING run_id")
                statement = statement.bindparams(bindparam("identity", type_=JSONB))
                created = connection.scalar(statement, {"run_id": run_id, "submission": context.submission_id,
                                                        "identity": create_identity})
                if created is None:
                    raise FileExistsError("events.run_exists")
            row = connection.execute(text("SELECT * FROM lesson_runs WHERE run_id=:run_id" +
                (" FOR UPDATE" if write else "")), {"run_id": run_id}).mappings().first()
            if row is None or row["submission_id"] != context.submission_id:
                raise RunNotFound()
            if generation is not None and row["created_at"] != generation:
                raise RunNotFound("events.run_replaced")
            if identity is not None and row["identity"] != identity:
                raise ValueError("checkpoint.identity_mismatch")
            if write:
                connection.execute(text("UPDATE lesson_runs SET updated_at=now() WHERE run_id=:run_id"),
                                   {"run_id": run_id})
            yield connection
            if write and submission is not None and submission["expires_at"] <= context.clock():
                raise RunUnavailable("events.submission_expired")


def read_run(run_id):
    with run_transaction(run_id) as connection:
        return dict(connection.execute(text("SELECT * FROM lesson_runs WHERE run_id=:run_id"),
                                       {"run_id": run_id}).mappings().one())
