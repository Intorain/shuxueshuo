from dataclasses import asdict
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa

from shuxueshuo_server.search.admission import TICKETS, SearchAdmission, SearchLimits
from shuxueshuo_server.search.storage import SearchError
from shuxueshuo_server.search.upload_admission import (
    UploadAdmission,
    UploadAdmissionBusy,
)
from tests.search import server_rehearsal as rehearsal
from tests.search.test_repository import repository as repository_fixture
from tests.search.test_repository import student


@pytest.fixture
def repository(tmp_path):
    yield from repository_fixture.__wrapped__(tmp_path)


def test_container_rehearsal_asserts_unmodified_production_limits():
    assert rehearsal.DEFAULT_LIMITS == asdict(SearchLimits.from_env({}))


def test_fixture_gate_and_ledger_require_explicit_offline_opt_in(monkeypatch, tmp_path):
    monkeypatch.delenv('SEARCH_OFFLINE_REHEARSAL', raising=False)
    monkeypatch.setattr(rehearsal, 'DATA', tmp_path)
    with pytest.raises(RuntimeError, match='SEARCH_OFFLINE_REHEARSAL=1'):
        rehearsal.controls()
    with pytest.raises(RuntimeError, match='SEARCH_OFFLINE_REHEARSAL=1'):
        rehearsal.seed_consumed(None, None, 'generation', 1)
    assert not (tmp_path / 'work').exists()


def test_upload_tracking_uses_real_admission_and_always_cleans_markers(monkeypatch, tmp_path):
    monkeypatch.setenv('SEARCH_OFFLINE_REHEARSAL', '1')
    monkeypatch.setattr(rehearsal, 'DATA', tmp_path)
    admission = UploadAdmission()
    with rehearsal.tracked_upload(UploadAdmission.admit, admission, 'owner'):
        with rehearsal.tracked_upload(UploadAdmission.admit, admission, 'owner'):
            assert len(list(rehearsal.controls().glob('upload-owner-*'))) == 2
            with pytest.raises(UploadAdmissionBusy), rehearsal.tracked_upload(UploadAdmission.admit, admission, 'owner'):
                pytest.fail('Third account upload should not acquire a marker')
        assert len(list(rehearsal.controls().glob('upload-owner-*'))) == 1
        with pytest.raises(ValueError), rehearsal.tracked_upload(UploadAdmission.admit, admission, 'other'):
            raise ValueError('offline failure')
    assert not list(rehearsal.controls().glob('upload-*'))
    assert admission._total == 0


@pytest.mark.parametrize(('kind', 'limit'), [('generation', 10), ('rerun', 3)])
def test_account_fixture_stops_one_before_real_default_boundary(repository, monkeypatch, kind, limit):
    monkeypatch.setenv('SEARCH_OFFLINE_REHEARSAL', '1')
    owner = student(repository)
    admission = SearchAdmission(repository.db, clock=repository.clock)
    admission.set_generation_enabled(True)
    with repository.db.begin() as connection:
        assert rehearsal.seed_consumed(connection, owner, kind, limit - 1, now=repository.clock()) == limit - 1
    last = admission.reserve(owner, kind, 'actual-boundary')
    assert admission.start(last.id) and admission.finish(last.id)
    with pytest.raises(SearchError, match='search.daily_' + kind + '_limit'):
        admission.reserve(owner, kind, 'over-boundary')
    with repository.db.connect() as connection:
        rows = connection.execute(sa.select(TICKETS).where(TICKETS.c.error_code == 'offline.fixture.preconsumed')).mappings().all()
    assert len(rows) == limit - 1
    assert all(row['consumed'] and row['state'] == 'finished' and row['request_id'].startswith('offline-fixture-') for row in rows)


@pytest.mark.parametrize(('kind', 'limit'), [('generation', 100), ('rerun', 50)])
def test_global_fixture_stops_one_before_real_default_boundary(repository, monkeypatch, kind, limit):
    monkeypatch.setenv('SEARCH_OFFLINE_REHEARSAL', '1')
    fixture_owner, student_owner = student(repository), student(repository)
    admission = SearchAdmission(repository.db, clock=repository.clock)
    admission.set_generation_enabled(True)
    with repository.db.begin() as connection:
        rehearsal.seed_consumed(connection, fixture_owner, kind, limit - 1, now=repository.clock())
    last = admission.reserve(student_owner, kind, 'actual-boundary')
    assert admission.start(last.id) and admission.finish(last.id)
    with pytest.raises(SearchError, match='search.global_' + kind + '_limit'):
        admission.reserve(student_owner, kind, 'over-boundary')
    admission.set_generation_enabled(False)
    recovered = SearchAdmission(repository.db, clock=repository.clock)
    assert recovered.recover() == {'cancelled': 0, 'interrupted': 0}
    assert recovered.generation_enabled() is False
    with repository.db.connect() as connection:
        assert connection.scalar(sa.select(sa.func.count()).select_from(TICKETS).where(TICKETS.c.consumed)) == limit


def test_fixture_quota_day_uses_shanghai_and_zero_does_not_write(repository, monkeypatch):
    monkeypatch.setenv('SEARCH_OFFLINE_REHEARSAL', '1')
    owner = student(repository)
    now = datetime(2026, 10, 25, 16, 0, tzinfo=UTC)
    with repository.db.begin() as connection:
        assert rehearsal.seed_consumed(connection, owner, 'generation', 0, now=now) == 0
        assert rehearsal.seed_consumed(connection, owner, 'generation', 1, now=now) == 1
    with repository.db.connect() as connection:
        row = connection.execute(sa.select(TICKETS)).mappings().one()
    assert row['quota_day'].isoformat() == '2026-10-26'


@pytest.mark.parametrize(('kind', 'count'), [('continuation', 1), ('generation', -1), ('generation', True)])
def test_invalid_fixture_never_writes(monkeypatch, kind, count):
    monkeypatch.setenv('SEARCH_OFFLINE_REHEARSAL', '1')
    with pytest.raises(ValueError, match='Invalid offline quota fixture'):
        rehearsal.seed_consumed(None, None, kind, count)
