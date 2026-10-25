"""Real database ownership and Cookie sessions for private search API tests."""

import os
import atexit
import secrets
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shuxueshuo_server.auth.api import cookie_name
from shuxueshuo_server.auth.config import AuthConfig
from shuxueshuo_server.auth.service import AuthService
from shuxueshuo_server.auth.sms import MockSms
from shuxueshuo_server.graph_lesson.stage_three.storage import storage_context
from shuxueshuo_server.product.config import Settings
from shuxueshuo_server.product.db import engine
from shuxueshuo_server.product.admin.database import DELETABLE, MUTABLE
from shuxueshuo_server.product.models import metadata
from shuxueshuo_server.search import dev_api
from shuxueshuo_server.search.repository import SearchRepository


@lru_cache(maxsize=256)
def session_for(root):
    data_dir = os.getenv("PRODUCT_TEST_DATA_DIR")
    if not data_dir:
        pytest.fail("Requires independently migrated PRODUCT_TEST_DATA_DIR")
    settings = Settings.load("local", data_dir, os.getenv("PRODUCT_TEST_INSTANCE", "search-stage1"))
    administrator = engine(settings.url('migration'))
    schema = 'search_api_test_' + secrets.token_hex(8)
    with administrator.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        connection.exec_driver_sql(f'SET LOCAL search_path TO "{schema}", public')
        connection.exec_driver_sql(f'GRANT USAGE ON SCHEMA "{schema}" TO product_app')
        migrations = Path(__file__).parents[2] / 'alembic/versions'
        for name in ('0013_student_search.sql', '0014_lesson_execution.sql', '0015_search_recovery.sql', '0016_search_admission.sql'):
            connection.execute(sa.text((migrations / name).read_text()))
        for name, table in metadata.tables.items():
            if not name.startswith(('search_', 'student_search_', 'lesson_')):
                continue
            connection.exec_driver_sql(f'GRANT SELECT, INSERT ON "{table.name}" TO product_app')
            if name in MUTABLE:
                columns = ','.join('"' + column + '"' for column in MUTABLE[name].split())
                connection.exec_driver_sql(f'GRANT UPDATE ({columns}) ON "{name}" TO product_app')
            if name in DELETABLE:
                connection.exec_driver_sql(f'GRANT DELETE ON "{name}" TO product_app')
    administrator.dispose()
    database = sa.create_engine(settings.url(), isolation_level='READ COMMITTED', pool_pre_ping=True, poolclass=sa.pool.NullPool,
        hide_parameters=True, connect_args={'options': f'-c timezone=UTC -c search_path={schema},public'})

    def cleanup():
        database.dispose()
        with administrator.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        administrator.dispose()

    atexit.register(cleanup)
    config = AuthConfig(mode="mock", environment="test", origin="https://testserver", secret=secrets.token_urlsafe(48))
    auth = AuthService(database, config, MockSms())
    phone = "139" + "".join(str(secrets.randbelow(10)) for _ in range(8))
    challenge = auth.send(phone, "fixture-" + secrets.token_hex(6))
    code = auth.sms.messages[challenge["challenge_id"]][1]
    user, token = auth.verify(phone, UUID(challenge["challenge_id"]), code, "fixture-" + secrets.token_hex(6))
    repository = SearchRepository(database, Path(root))
    repository.admission.set_generation_enabled(True)
    return SimpleNamespace(auth=auth, user=user, token=token, repository=repository)


def authenticated_client(root, *, hooks=None, raise_server_exceptions=True):
    session = session_for(Path(root))
    app = FastAPI()
    app.state.student_auth = session.auth
    app.state.search_repository = session.repository
    app.include_router(dev_api.create_search_router(root, stage_three_hooks=hooks))
    client = TestClient(app, base_url=session.auth.config.origin, headers={"Origin": session.auth.config.origin},
                        raise_server_exceptions=raise_server_exceptions)
    client.cookies.set(cookie_name(session.auth.config), session.token)
    return client


def execution_scope(root):
    session = session_for(Path(root))
    return storage_context(session.repository.db, session.search_id, clock=session.repository.clock)


def execution_store(root, output):
    from shuxueshuo_server.graph_lesson.stage_three.preview import open_store
    with execution_scope(root):
        return open_store(output)
