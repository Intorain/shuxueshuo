"""Transient database failures release capacity without rerunning work or leases."""

import pytest

from shuxueshuo_server.search.storage import SearchError
from shuxueshuo_server.search.task_runner import SearchTaskRunner
from tests.search.test_task_runner import FixtureRepository, HeldExecutor


def test_failed_queued_cancellation_is_retried_without_repeating_cleanup():
    executor, repository = HeldExecutor(), FixtureRepository()
    runner = SearchTaskRunner(executor, workers=1, queue_size=1)
    completed, cancelled = [], []
    for name in ('first', 'deleted'):
        runner.submit(repository.ticket(name), repository,
            lambda name=name: completed.append(name), lambda name=name: cancelled.append(name))
    repository.dead.add('deleted')
    original = repository.admission.cancel
    attempts = []

    def transient_cancel(identifier):
        attempts.append(identifier)
        if len(attempts) == 1:
            raise RuntimeError('fixture database temporarily unavailable')
        return original(identifier)

    repository.admission.cancel = transient_cancel
    runner.reap()
    assert set(runner.finalizations) == {'deleted'}
    assert cancelled == ['deleted']
    assert repository.admission.states['deleted'] == 'reserved'
    with pytest.raises(SearchError, match='search.queue_full'):
        runner.submit(repository.ticket('extra'), repository, lambda: None, lambda: None)
    runner.reap()
    assert not runner.finalizations
    assert repository.admission.states['deleted'] == 'cancelled'
    assert cancelled == ['deleted']
    executor.drain()
    runner.shutdown()
    assert completed == ['first']
    assert attempts == ['deleted', 'deleted']


def test_failed_finish_releases_stale_running_slot_before_dispatching_next_job():
    executor, repository = HeldExecutor(), FixtureRepository()
    runner = SearchTaskRunner(executor, workers=1, queue_size=1)
    completed = []
    original = repository.admission.finish
    attempts = []

    def transient_finish(identifier):
        attempts.append(identifier)
        if len(attempts) == 1:
            raise RuntimeError('fixture finish lost its database connection')
        return original(identifier)

    repository.admission.finish = transient_finish
    for name in ('first', 'next'):
        runner.submit(repository.ticket(name), repository,
            lambda name=name: completed.append(name), lambda: pytest.fail('accepted work was cancelled'))
    executor.drain()
    assert completed == ['first']
    assert repository.admission.states['first'] == 'running'
    assert [job.ticket.id for job in runner.pending] == ['next']
    assert set(runner.finalizations) == {'first'}
    assert not runner.running
    runner.reap()
    executor.drain()
    runner.shutdown()
    assert completed == ['first', 'next']
    assert attempts == ['first', 'first', 'next']
    assert not runner.finalizations
    assert repository.admission.states == {'first': 'finished', 'next': 'finished'}


def test_start_commit_uncertainty_finalizes_consumed_ticket_without_running_work():
    executor, repository = HeldExecutor(), FixtureRepository()
    runner = SearchTaskRunner(executor, workers=1, queue_size=0)
    ticket = repository.ticket('uncertain')
    cancelled = []

    def uncertain_start(ticket):
        repository.admission.states[ticket.id] = 'running'
        raise RuntimeError('fixture connection lost after start committed')

    repository.start_admitted = uncertain_start
    runner.submit(ticket, repository, lambda: pytest.fail('uncertain task must not run'),
        lambda: cancelled.append(ticket.id))
    executor.drain()
    runner.shutdown()
    assert cancelled == ['uncertain']
    assert repository.admission.states['uncertain'] == 'finished'
    assert not runner.running
    assert not runner.finalizations


def test_failed_cleanup_callback_is_not_repeated_and_status_repair_retries():
    executor, repository = HeldExecutor(), FixtureRepository()
    runner = SearchTaskRunner(executor, workers=1, queue_size=0)
    ticket = repository.ticket('cancelled')
    repository.dead.add(ticket.id)
    cleanup, repaired = [], []
    repair_available = False

    def interrupt(ticket):
        if not repair_available:
            raise RuntimeError('fixture status repair unavailable')
        repaired.append(ticket.id)

    def release_once():
        cleanup.append(ticket.id)
        raise RuntimeError('fixture callback database update failed but lease was released')

    repository.interrupt_admitted = interrupt
    runner.submit(ticket, repository, lambda: pytest.fail('cancelled task must not run'), release_once)
    executor.drain()
    assert cleanup == ['cancelled']
    assert set(runner.finalizations) == {'cancelled'}
    repair_available = True
    runner.reap()
    runner.shutdown()
    assert cleanup == ['cancelled']
    assert repaired == ['cancelled']
    assert not runner.finalizations


def test_shutdown_attempts_pending_finalization_again_and_remains_bounded_on_failure():
    executor, repository = HeldExecutor(), FixtureRepository()
    runner = SearchTaskRunner(executor, workers=1, queue_size=0)
    ticket = repository.ticket('completed')
    attempts, completed = [], []

    def unavailable(identifier):
        attempts.append(identifier)
        raise RuntimeError('fixture database remains offline')

    repository.admission.finish = unavailable
    runner.submit(ticket, repository, lambda: completed.append(ticket.id), lambda: None)
    runner.shutdown()
    assert completed == ['completed']
    assert attempts == ['completed', 'completed']
    assert set(runner.finalizations) == {'completed'}
    assert executor.closed


@pytest.mark.parametrize('executor_rejected', [False, True])
def test_route_owned_cleanup_retains_failed_unstarted_cancellation_for_reaper(executor_rejected):
    executor = HeldExecutor(fail_submissions={1} if executor_rejected else ())
    repository = FixtureRepository()
    runner = SearchTaskRunner(executor, workers=1, queue_size=0)
    ticket = repository.ticket('not-enqueued')
    callbacks, attempts, repaired = [], [], []
    original = repository.admission.cancel

    def cancel(identifier):
        attempts.append(identifier)
        if len(attempts) == 1:
            raise RuntimeError('fixture database unavailable after enqueue failed')
        return original(identifier)

    repository.admission.cancel = cancel
    repository.interrupt_admitted = lambda ticket: repaired.append(ticket.id)
    if executor_rejected:
        with pytest.raises(RuntimeError, match='fixture executor'):
            runner.submit(ticket, repository, lambda: pytest.fail('unstarted work must not run'),
                          lambda: callbacks.append('runner'))
    runner.cancel_unstarted(ticket, repository)
    callbacks.append('route')
    assert set(runner.finalizations) == {ticket.id}
    assert repository.admission.states[ticket.id] == 'reserved'
    with pytest.raises(SearchError, match='search.queue_full'):
        runner.submit(repository.ticket('extra'), repository, lambda: None, lambda: None)
    runner.reap()
    runner.shutdown()
    assert callbacks == ['route']
    assert attempts == [ticket.id, ticket.id]
    assert repaired == [ticket.id]
    assert repository.admission.states[ticket.id] == 'cancelled'
    assert not runner.finalizations
    assert not executor.pending
