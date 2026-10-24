"""PostgreSQL migration, run-scoped constraints and committed interaction retention."""

import os
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import IntegrityError

from shuxueshuo_server.graph_lesson.stage_three.events import EventStore
from shuxueshuo_server.product.config import Settings
from shuxueshuo_server.product.db import engine
from tests.solver.test_graph_stage_three_events import IDENTITY

TABLES = {"lesson_runs", "lesson_metadata", "lesson_commits", "lesson_events", "lesson_checkpoints",
          "lesson_steps", "lesson_step_summaries", "lesson_selection_chunks", "lesson_interaction_states",
          "lesson_interactions", "lesson_calculation_budgets", "lesson_calculation_leases", "lesson_calculation_attempts"}
STATE = {"target": "target", "route": "route", "step": "step", "ordinal": 1,
         "hash": "e" * 64, "status": "pending", "interaction_id": None}
CHUNK = {"interaction_id": "f" * 24, "target": "target", "route": "route", "ordinal": 1,
         "value": '{"saved":"interaction"}'}


def tables(connection, schema):
    return set(connection.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema=:schema"),
                                  {"schema": schema}).scalars())


def insert_state(connection, run_id, state=STATE):
    connection.execute(text("""INSERT INTO lesson_interaction_states
        (run_id,target,route,step,ordinal,hash,status,interaction_id)
        VALUES (:run_id,:target,:route,:step,:ordinal,:hash,:status,:interaction_id)"""), {"run_id": run_id, **state})


def test_new_storage_uses_pre_migrated_postgres_tables_without_a_sqlite_file(tmp_path):
    store = EventStore(tmp_path, IDENTITY, create=True)
    with store.transaction() as connection:
        assert connection.dialect.name == "postgresql"
        schema = connection.scalar(text("SELECT current_schema()"))
        assert schema.startswith("test_stage_three_")
        assert TABLES <= tables(connection, schema)
    assert not list(tmp_path.rglob("*.sqlite*"))


@pytest.mark.parametrize("existing", [(), ("state",), ("state", "chunk")])
def test_reopen_preserves_committed_interactions_without_replaying_receipts(tmp_path, stage_three_storage, existing):
    store = EventStore(tmp_path, IDENTITY, create=True)
    parameters = {"run_id": IDENTITY["run_id"]}
    with store.transaction(write=True) as connection:
        if "state" in existing:
            insert_state(connection, IDENTITY["run_id"])
        if "chunk" in existing:
            connection.execute(text("""INSERT INTO lesson_interactions (run_id,interaction_id,target,route,ordinal,value)
                VALUES (:run_id,:interaction_id,:target,:route,:ordinal,:value)"""), {**parameters, **CHUNK})
        connection.execute(text("INSERT INTO lesson_metadata (run_id,key,value) VALUES (:run_id,'interactions','{\"saved\":\"settings\"}')"), parameters)
        connection.execute(text("INSERT INTO lesson_commits (run_id,id,digest,result) VALUES (:run_id,'untouched','digest','{\"events\":[]}')"), parameters)
    statements = []

    def trace(_connection, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    event.listen(stage_three_storage, "before_cursor_execute", trace)
    try:
        EventStore(tmp_path, IDENTITY)
        EventStore(tmp_path, IDENTITY)
    finally:
        event.remove(stage_three_storage, "before_cursor_execute", trace)
    assert not any("FROM lesson_commits" in statement or "FROM lesson_steps" in statement for statement in statements)
    assert not any(statement.lstrip().upper().startswith(("CREATE", "INSERT", "UPDATE", "DELETE")) for statement in statements)
    with store.transaction() as connection:
        states = connection.execute(text("SELECT target,route,step,ordinal,hash,status,interaction_id FROM lesson_interaction_states WHERE run_id=:run_id"), parameters).mappings().all()
        chunks = connection.execute(text("SELECT interaction_id,target,route,ordinal,value FROM lesson_interactions WHERE run_id=:run_id"), parameters).mappings().all()
        assert [dict(row) for row in states] == ([STATE] if "state" in existing else [])
        assert [dict(row) for row in chunks] == ([CHUNK] if "chunk" in existing else [])
        assert connection.scalar(text("SELECT value FROM lesson_metadata WHERE run_id=:run_id AND key='interactions'"), parameters) == '{"saved":"settings"}'


def test_interaction_keys_are_run_scoped_and_duplicate_inserts_roll_back(tmp_path):
    first = EventStore(tmp_path / "first", IDENTITY, create=True)
    second = EventStore(tmp_path / "second", {**IDENTITY, "run_id": "run-02"}, create=True)
    for store in (first, second):
        with store.transaction(write=True) as connection:
            insert_state(connection, store.identity["run_id"])
    with pytest.raises(IntegrityError), first.transaction(write=True) as connection:
        connection.execute(text("INSERT INTO lesson_metadata (run_id,key,value) VALUES (:run_id,'must-roll-back','value')"), {"run_id": IDENTITY["run_id"]})
        insert_state(connection, IDENTITY["run_id"])
    with first.transaction() as connection:
        assert connection.scalar(text("SELECT count(*) FROM lesson_interaction_states")) == 2
        assert connection.scalar(text("SELECT count(*) FROM lesson_metadata WHERE key='must-roll-back'")) == 0
    with pytest.raises(FileExistsError):
        EventStore(tmp_path / "duplicate", IDENTITY, create=True)


@pytest.mark.parametrize("table", ["lesson_events", "lesson_interaction_states", "lesson_interactions"])
def test_executor_rows_require_an_existing_run(stage_three_storage, table):
    with pytest.raises(IntegrityError), stage_three_storage.begin() as connection:
        if table == "lesson_events":
            connection.execute(text("INSERT INTO lesson_events (run_id,seq,value) VALUES ('missing',1,'{}')"))
        elif table == "lesson_interaction_states":
            insert_state(connection, "missing")
        else:
            connection.execute(text("""INSERT INTO lesson_interactions (run_id,interaction_id,target,route,ordinal,value)
                VALUES (:run_id,:interaction_id,:target,:route,:ordinal,:value)"""), {"run_id": "missing", **CHUNK})
    with stage_three_storage.connect() as connection:
        assert connection.scalar(text(f"SELECT count(*) FROM {table} WHERE run_id='missing'")) == 0


def test_executor_migration_ddl_is_atomic_and_retries_after_rollback(stage_three_storage):
    settings = Settings.load("local", os.environ["PRODUCT_TEST_DATA_DIR"], os.environ["PRODUCT_TEST_INSTANCE"])
    admin = engine(settings.url("migration"))
    schema = "test_stage_three_migration_" + uuid4().hex
    migration = (Path(__file__).parents[2] / "alembic/versions/0014_lesson_execution.sql").read_text()
    try:
        with pytest.raises(RuntimeError, match="migration interrupted"), admin.begin() as connection:
            connection.exec_driver_sql(f"CREATE SCHEMA {schema}")
            connection.exec_driver_sql(f"SET LOCAL search_path TO {schema}, public")
            connection.exec_driver_sql(migration)
            assert TABLES <= tables(connection, schema)
            raise RuntimeError("migration interrupted")
        with admin.connect() as connection:
            assert connection.scalar(text("SELECT to_regnamespace(:schema)"), {"schema": schema}) is None
        with admin.begin() as connection:
            connection.exec_driver_sql(f"CREATE SCHEMA {schema}")
            connection.exec_driver_sql(f"SET LOCAL search_path TO {schema}, public")
            connection.exec_driver_sql(migration)
        with admin.connect() as connection:
            assert TABLES <= tables(connection, schema)
    finally:
        with admin.begin() as connection:
            connection.exec_driver_sql(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
        admin.dispose()
