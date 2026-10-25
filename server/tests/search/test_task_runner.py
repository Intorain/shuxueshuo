"""Offline dispatch capacity, cleanup ownership and context propagation."""

from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from contextvars import ContextVar
from threading import Barrier
from types import SimpleNamespace

import pytest

from shuxueshuo_server.search.storage import SearchError
from shuxueshuo_server.search.task_runner import SearchTaskRunner
from shuxueshuo_server.solver.extraction.request_guard import check_model_request


class HeldExecutor:
    def __init__(self, *, fail_submissions=()):
        self.pending = deque()
        self.submissions = 0
        self.fail_submissions = set(fail_submissions)
        self.closed = False

    def submit(self, function, *arguments):
        self.submissions += 1
        if self.submissions in self.fail_submissions:
            raise RuntimeError('fixture executor rejected submission')
        future = Future()
        self.pending.append((future, function, arguments))
        return future

    def drain(self):
        while self.pending:
            future, function, arguments = self.pending.popleft()
            try:
                future.set_result(function(*arguments))
            except BaseException as exc:
                future.set_exception(exc)
                raise

    def shutdown(self, wait=True):
        assert wait
        self.drain()
        self.closed = True


class FixtureAdmission:
    def __init__(self):
        self.states = {}
        self.cancelled = []
        self.finished = []

    def cancel(self, ticket_id):
        self.cancelled.append(ticket_id)
        if self.states[ticket_id] == 'reserved':
            self.states[ticket_id] = 'cancelled'

    def finish(self, ticket_id):
        self.finished.append(ticket_id)
        if self.states[ticket_id] == 'running':
            self.states[ticket_id] = 'finished'

    def get_ticket(self, ticket_id):
        return SimpleNamespace(state=self.states[ticket_id])


class FixtureRepository:
    def __init__(self):
        self.admission = FixtureAdmission()
        self.dead = set()
        self.started = []
        self.guarded = []

    def ticket(self, name):
        self.admission.states[name] = 'reserved'
        return SimpleNamespace(id=name, search_id=name)

    def start_admitted(self, ticket):
        if ticket.id in self.dead or self.admission.states[ticket.id] != 'reserved':
            return False
        self.admission.states[ticket.id] = 'running'
        self.started.append(ticket.id)
        return True

    def admitted_submission_live(self, ticket):
        return ticket.id not in self.dead

    def require_admitted_model_call(self, ticket):
        self.guarded.append(ticket.id)


def test_two_dispatch_slots_plus_four_fifo_waiters_reject_the_seventh():
    executor, repository = HeldExecutor(), FixtureRepository()
    runner = SearchTaskRunner(executor, workers=2, queue_size=4)
    completed, cancelled = [], []
    for index in range(6):
        name = str(index)
        runner.submit(repository.ticket(name), repository,
                      lambda name=name: completed.append(name), lambda name=name: cancelled.append(name))
    assert runner.running == {'0', '1'}
    assert [job.ticket.id for job in runner.pending] == ['2', '3', '4', '5']
    assert executor.submissions == 2
    with pytest.raises(SearchError, match='search.queue_full') as error:
        runner.submit(repository.ticket('6'), repository,
                      lambda: completed.append('6'), lambda: cancelled.append('6'))
    assert error.value.status == 429
    executor.drain()
    assert completed == ['0', '1', '2', '3', '4', '5']
    assert repository.started == completed
    assert cancelled == []
    assert not runner.pending
    assert not runner.running
    runner.shutdown()


def test_synchronous_executor_failure_leaves_cancellation_to_the_calling_route():
    executor, repository = HeldExecutor(fail_submissions={1}), FixtureRepository()
    runner = SearchTaskRunner(executor, workers=1, queue_size=1)
    cancelled = []
    ticket = repository.ticket('first')
    with pytest.raises(RuntimeError, match='fixture executor'):
        runner.submit(ticket, repository, lambda: pytest.fail('must not execute'), lambda: cancelled.append('first'))
    assert repository.admission.cancelled == []
    assert cancelled == []
    assert not runner.running
    assert not runner.pending
    repository.admission.cancel(ticket.id)
    cancelled.append(ticket.id)
    assert repository.admission.cancelled == ['first']
    assert cancelled == ['first']
    runner.shutdown()


def test_failed_start_and_raising_cancel_callback_are_cleaned_only_once():
    executor, repository = HeldExecutor(), FixtureRepository()
    runner = SearchTaskRunner(executor, workers=1, queue_size=1)
    cancelled = []
    ticket = repository.ticket('deleted')
    repository.dead.add(ticket.id)

    def failing_cleanup():
        cancelled.append(ticket.id)
        raise RuntimeError('fixture cleanup failed after releasing its lease')

    runner.submit(ticket, repository, lambda: pytest.fail('deleted task must not execute'), failing_cleanup)
    executor.drain()
    assert cancelled == ['deleted']
    assert repository.admission.cancelled == ['deleted']
    assert repository.admission.finished == ['deleted']
    assert not runner.running
    runner.shutdown()


def test_asynchronous_dispatch_failure_and_cleanup_error_do_not_strand_later_waiters():
    executor, repository = HeldExecutor(fail_submissions={2}), FixtureRepository()
    runner = SearchTaskRunner(executor, workers=1, queue_size=3)
    completed, cancelled = [], []

    def cleanup(name):
        cancelled.append(name)
        if name == '1':
            raise RuntimeError('fixture cleanup failure')

    for index in range(4):
        name = str(index)
        runner.submit(repository.ticket(name), repository,
                      lambda name=name: completed.append(name), lambda name=name: cleanup(name))
    executor.drain()
    assert completed == ['0', '2', '3']
    assert cancelled == ['1']
    assert repository.admission.cancelled == ['1']
    assert not runner.pending
    assert not runner.running
    runner.shutdown()


@pytest.mark.parametrize('reason', ['stopped', 'deleted'])
def test_reaper_cancels_unstarted_work_without_executing_it_twice(reason):
    executor, repository = HeldExecutor(), FixtureRepository()
    runner = SearchTaskRunner(executor, workers=1, queue_size=2)
    completed, cancelled = [], []
    for name in ('running', 'cancelled', 'next'):
        runner.submit(repository.ticket(name), repository,
                      lambda name=name: completed.append(name), lambda name=name: cancelled.append(name))
    if reason == 'stopped':
        repository.admission.states['cancelled'] = 'cancelled'
    else:
        repository.dead.add('cancelled')
    runner.reap()
    runner.reap()
    executor.drain()
    assert completed == ['running', 'next']
    assert cancelled == ['cancelled']
    assert repository.admission.cancelled == ['cancelled']
    assert repository.admission.states['cancelled'] == 'cancelled'
    runner.shutdown()


def test_shutdown_cancels_queued_work_and_waits_for_dispatched_work():
    executor, repository = HeldExecutor(), FixtureRepository()
    runner = SearchTaskRunner(executor, workers=1, queue_size=2)
    completed, cancelled = [], []
    for name in ('running', 'queued-one', 'queued-two'):
        runner.submit(repository.ticket(name), repository,
                      lambda name=name: completed.append(name), lambda name=name: cancelled.append(name))
    runner.shutdown()
    assert completed == ['running']
    assert cancelled == ['queued-one', 'queued-two']
    assert executor.closed
    with pytest.raises(SearchError, match='search.queue_full'):
        runner.submit(repository.ticket('late'), repository, lambda: None, lambda: None)


def test_shutdown_cleanup_failure_does_not_skip_other_leases_or_executor_join():
    executor, repository = HeldExecutor(), FixtureRepository()
    runner = SearchTaskRunner(executor, workers=1, queue_size=2)
    completed, cancelled = [], []

    def cleanup(name):
        cancelled.append(name)
        if name == 'queued-one':
            raise RuntimeError('fixture shutdown cleanup failure')

    for name in ('running', 'queued-one', 'queued-two'):
        runner.submit(repository.ticket(name), repository,
                      lambda name=name: completed.append(name), lambda name=name: cleanup(name))
    runner.shutdown()
    assert cancelled == ['queued-one', 'queued-two']
    assert repository.admission.cancelled == ['queued-one', 'queued-two']
    assert completed == ['running']
    assert not runner.pending
    assert not runner.running
    assert executor.closed


def test_reaper_cleanup_failure_does_not_delay_other_cancelled_jobs():
    executor, repository = HeldExecutor(), FixtureRepository()
    runner = SearchTaskRunner(executor, workers=1, queue_size=2)
    completed, cancelled = [], []

    def cleanup(name):
        cancelled.append(name)
        if name == 'cancelled-one':
            raise RuntimeError('fixture reaper cleanup failure')

    for name in ('running', 'cancelled-one', 'cancelled-two'):
        runner.submit(repository.ticket(name), repository,
                      lambda name=name: completed.append(name), lambda name=name: cleanup(name))
    repository.admission.states['cancelled-one'] = 'cancelled'
    repository.admission.states['cancelled-two'] = 'cancelled'
    runner.reap()
    runner.reap()
    assert cancelled == ['cancelled-one', 'cancelled-two']
    assert repository.admission.cancelled == ['cancelled-one', 'cancelled-two']
    assert not runner.pending
    executor.drain()
    assert completed == ['running']
    runner.shutdown()


def test_real_workers_receive_their_own_request_context_and_guard():
    owner = ContextVar('offline_request_owner', default=None)
    repository = FixtureRepository()
    barrier = Barrier(2)
    observed = []
    repository.require_admitted_model_call = lambda ticket: observed.append((ticket.id, owner.get()))
    executor = ThreadPoolExecutor(max_workers=2)
    runner = SearchTaskRunner(executor, workers=2, queue_size=0)

    def work():
        barrier.wait(timeout=5)
        check_model_request()

    try:
        for name in ('alice', 'bob'):
            token = owner.set(name)
            try:
                runner.submit(repository.ticket(name), repository, work,
                              lambda: pytest.fail('real worker unexpectedly cancelled'))
            finally:
                owner.reset(token)
        runner.shutdown()
        assert sorted(observed) == [('alice', 'alice'), ('bob', 'bob')]
        assert owner.get() is None
        check_model_request()
        assert len(observed) == 2
    finally:
        executor.shutdown(wait=True)
