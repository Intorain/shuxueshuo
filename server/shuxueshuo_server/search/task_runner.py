"""Bounded single-process dispatch over durable search admission tickets."""

import logging
import threading
from collections import deque
from contextvars import copy_context
from dataclasses import dataclass

from ..solver.extraction.request_guard import model_request_scope
from .storage import SearchError

LOGGER = logging.getLogger(__name__)


@dataclass
class _Job:
    ticket: object
    repository: object
    work: object
    cancelled: object
    context: object
    discarded: bool = False


class SearchTaskRunner:
    def __init__(self, executor, workers, queue_size):
        self.executor = executor
        self.workers = workers
        self.capacity = workers + queue_size
        self.pending = deque()
        self.running = set()
        self.finalizations = {}
        self.finalizing = set()
        self.lock = threading.RLock()
        self.closed = False

    def submit(self, ticket, repository, work, cancelled):
        job = _Job(ticket, repository, work, cancelled, copy_context())
        with self.lock:
            if self.closed or len(self.pending) + len(self.running | self.finalizations.keys()) >= self.capacity:
                raise SearchError('search.queue_full', 429)
            self.pending.append(job)
            self._dispatch(propagate=ticket.id)

    def _discard(self, job):
        with self.lock:
            if job.discarded:
                return
            job.discarded = True
            self.finalizations.setdefault(job.ticket.id, (job, 'cancel'))
        try:
            job.cancelled()
        finally:
            self._finalize(job, 'cancel')

    def cancel_unstarted(self, ticket, repository):
        job = _Job(ticket, repository, None, None, None, discarded=True)
        self._finalize(job, 'cancel')

    def _finalize(self, job, action, *, retry=False):
        identifier = job.ticket.id
        with self.lock:
            if retry and identifier not in self.finalizations:
                return
            self.finalizations.setdefault(identifier, (job, action))
            if identifier in self.finalizing:
                return
            job, action = self.finalizations[identifier]
            self.finalizing.add(identifier)
        try:
            if action == 'cancel':
                changed = job.repository.admission.cancel(identifier)
                if not changed:
                    job.repository.admission.finish(identifier)
            else:
                job.repository.admission.finish(identifier)
            interrupt = getattr(job.repository, 'interrupt_admitted', None)
            if interrupt is not None:
                interrupt(job.ticket)
        except Exception:
            LOGGER.exception('Search admission finalization will retry')
        else:
            with self.lock:
                self.finalizations.pop(identifier, None)
        finally:
            with self.lock:
                self.finalizing.discard(identifier)

    def _retry_finalizations(self):
        with self.lock:
            entries = list(self.finalizations.values())
        for job, action in entries:
            self._finalize(job, action, retry=True)

    def _dispatch(self, *, propagate=None):
        while self.pending and len(self.running) < self.workers and not self.finalizations:
            job = self.pending.popleft()
            self.running.add(job.ticket.id)
            try:
                self.executor.submit(job.context.run, self._run, job)
            except BaseException:
                self.running.discard(job.ticket.id)
                if job.ticket.id == propagate:
                    raise
                LOGGER.exception('Search executor rejected an admitted task')
                try:
                    self._discard(job)
                except BaseException:
                    LOGGER.exception('Search task cancellation failed')

    def _run(self, job):
        invoked = False
        try:
            if not job.repository.start_admitted(job.ticket):
                self._discard(job)
                return

            def guard():
                job.repository.require_admitted_model_call(job.ticket)

            with model_request_scope(guard):
                invoked = True
                job.work()
        except BaseException:
            LOGGER.exception('Search admitted task failed before completion')
            if not invoked:
                self._discard(job)
        finally:
            try:
                if not job.discarded:
                    self._finalize(job, 'finish')
            finally:
                with self.lock:
                    self.running.discard(job.ticket.id)
                    self._dispatch()

    def reap(self):
        self._retry_finalizations()
        with self.lock:
            jobs = list(self.pending)
        for job in jobs:
            ticket = job.repository.admission.get_ticket(job.ticket.id)
            inactive = ticket is None or ticket.state != 'reserved'
            if not inactive:
                inactive = not job.repository.admitted_submission_live(job.ticket)
            if inactive:
                with self.lock:
                    if job not in self.pending:
                        continue
                    self.pending.remove(job)
                    self.finalizations.setdefault(job.ticket.id, (job, 'cancel'))
                try:
                    self._discard(job)
                except BaseException:
                    LOGGER.exception('Search queued task cancellation failed')
        with self.lock:
            self._dispatch()

    def shutdown(self):
        with self.lock:
            self.closed = True
            jobs = list(self.pending)
            self.pending.clear()
        try:
            for job in jobs:
                try:
                    self._discard(job)
                except BaseException:
                    LOGGER.exception('Search shutdown task cancellation failed')
        finally:
            self.executor.shutdown(wait=True)
            self._retry_finalizations()
