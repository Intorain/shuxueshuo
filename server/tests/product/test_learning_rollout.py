"""Stage 4 rehearsals use fresh native clusters, never the shared manual instance."""
import json
import os
import socket
from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from shuxueshuo_server.learning import content
from shuxueshuo_server.product.admin import database, learning, native
from shuxueshuo_server.product.admin.backup import backup, restore_data
from shuxueshuo_server.product.config import REPO, Settings
from shuxueshuo_server.product.db import engine
from shuxueshuo_server.product.errors import Conflict
from sqlalchemy import text

pytestmark = pytest.mark.skipif(os.getenv('RUN_LEARNING_ROLLOUT_TEST') != '1',
                               reason='Explicit temporary PostgreSQL rollout rehearsal')


@pytest.fixture
def cluster(tmp_path):
    active = []

    def create(name):
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            port = probe.getsockname()[1]
        settings = Settings.load('local', tmp_path / name, name, port, initialize=True)
        native.start(settings)
        active.append(settings)
        database.bootstrap(settings)
        return settings
    try:
        yield create
    finally:
        for settings in reversed(active):
            native.stop(settings)


def legacy(settings):
    db = engine(settings.url('migration'))
    config = Config(str(REPO / 'server/alembic.ini'))
    with db.begin() as c:
        config.attributes['connection'] = c
        command.upgrade(config, '0010_learning_record_integrity')
    user = database.seed(db).user_id
    with db.begin() as c:
        c.execute(text("INSERT INTO knowledge_nodes(id,label,kind,summary,explanation_md) VALUES('legacy-node','旧知识','knowledge','','')"))
    return db, user


def site_version(tmp_path, meta):
    """The repository site's teaching version file, as updated by git pull."""
    version = tmp_path / 'site/knowledge/teaching/version.json'
    version.parent.mkdir(parents=True, exist_ok=True)
    version.write_text(json.dumps({k: meta[k] for k in learning.CONTENT_KEYS}))
    return version


def test_readonly_four_states_and_refuse_any_legacy_personal_record(cluster):
    settings = cluster('inventory')
    assert learning.preflight(settings)['state'] == 'empty'
    db, user = legacy(settings)
    try:
        before = {str(p.relative_to(settings.root / 'config')): p.read_bytes()
                  for p in (settings.root / 'config').iterdir()}
        assert learning.preflight(settings)['state'] == 'legacy_public_only'
        assert not (settings.root / 'locks/admin.lock').exists()
        assert before == {str(p.relative_to(settings.root / 'config')): p.read_bytes()
                          for p in (settings.root / 'config').iterdir()}
        with db.begin() as c:
            c.execute(text("INSERT INTO student_learning_marks(user_id,problem_id,practiced) VALUES(:u,'unrelated-lesson',true)"), {'u': user})
        state = learning.preflight(settings)
        assert state['state'] == 'blocked' and state['reason'].endswith('personal_records_present')
        with pytest.raises(Conflict, match='personal_records_present'), db.begin() as c:
            learning.replace_legacy_public(c, settings, content.load_content())
        with db.connect() as c:
            assert c.scalar(text('SELECT count(*) FROM student_learning_marks')) == 1
            assert c.scalar(text('SELECT count(*) FROM knowledge_nodes')) == 1
            assert c.scalar(text('SELECT version_num FROM alembic_version')) == '0010_learning_record_integrity'
    finally:
        db.dispose()


def test_atomic_public_replacement_repeat_and_backup_restore(cluster, tmp_path):
    settings = cluster('rollout')
    db, user = legacy(settings)
    rows = content.load_content()
    site = site_version(tmp_path, rows['_meta'])
    try:
        # Ordinary deployment cannot bypass the migration's explicit first-replacement gate.
        with pytest.raises(Conflict, match='explicit_public_replacement_required'):
            learning.deploy(settings)
        result = learning.deploy(settings, replace_public=True)
        assert result['ok'] and result['replaced_public']['knowledge_nodes'] == 1
        assert learning.preflight(settings)['state'] == 'current'
        assert learning.verify_release(settings, site)['site'] == 'match'
        with db.connect() as c:
            assert c.scalar(text('SELECT count(*) FROM users WHERE id=:u'), {'u': user}) == 1
        assert learning.deploy(settings)['ok']
        with pytest.raises(Conflict, match='not_applicable'):
            learning.deploy(settings, replace_public=True)
        saved = backup(settings)
        assert (Path(saved['backup']) / 'manifest.json').is_file()
        restored = cluster('restored')
        assert restore_data(restored, saved['backup'])['ok']
        assert learning.preflight(restored)['content_version'] == rows['_meta']['content_version']
    finally:
        db.dispose()


def test_failure_rolls_back_ddl_and_public_data_and_keeps_fence(cluster, tmp_path, monkeypatch):
    settings = cluster('rollback')
    db, _ = legacy(settings)
    real = content.publish

    def fail_after_import(connection, rows):
        real(connection, rows)
        raise RuntimeError('injected import failure')
    monkeypatch.setattr(content, 'publish', fail_after_import)
    try:
        with pytest.raises(RuntimeError, match='injected import failure'):
            learning.deploy(settings, replace_public=True)
        with db.connect() as c:
            assert c.scalar(text('SELECT version_num FROM alembic_version')) == '0010_learning_record_integrity'
            assert c.scalar(text('SELECT count(*) FROM knowledge_nodes')) == 1
            assert c.scalar(text("SELECT to_regclass('learning_content_current')")) is None
        with psycopg.connect(database.dsn(settings.url('bootstrap'))) as c:
            assert c.execute("SELECT rolcanlogin FROM pg_roles WHERE rolname='product_app'").fetchone() == (False,)
        saved = list((settings.root / 'backups').glob('*/manifest.json'))
        assert len(saved) == 1 and json.loads(saved[0].read_text())['revision'] == '0010_learning_record_integrity'
    finally:
        db.dispose()


def test_verify_release_checks_database_and_repository_site(cluster, tmp_path):
    settings = cluster('verify')
    db, _ = legacy(settings)
    meta = content.load_content()['_meta']
    try:
        with pytest.raises(Conflict, match='content_version_mismatch'):
            learning.verify_release(settings, site_version(tmp_path, meta))
        learning.deploy(settings, replace_public=True)
        assert learning.verify_release(settings, site_version(tmp_path, meta))['site'] == 'match'
        with pytest.raises(Conflict, match='site_content_missing'):
            learning.verify_release(settings, tmp_path / 'absent.json')
        stale = site_version(tmp_path, {**meta, 'content_version': '0' * 64})
        with pytest.raises(Conflict, match='site_content_mismatch'):
            learning.verify_release(settings, stale)
        # Unattended service starts report a stale site without refusing to run.
        assert learning.verify_release(settings, stale, require_site=False)['site'] == 'mismatch'
    finally:
        db.dispose()


def test_preflight_never_treats_unknown_existing_database_as_empty(cluster):
    settings = cluster('unknown')
    db = engine(settings.url('migration'))
    try:
        with db.begin() as c:
            c.execute(text('CREATE TABLE foreign_data(id int)'))
        state = learning.preflight(settings)
        assert state['state'] == 'blocked' and state['reason'].endswith('unknown_database_revision')
    finally:
        db.dispose()
