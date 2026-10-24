"""Process cleanup waits for concurrent multiprocessing status publication."""

import multiprocessing as mp
import os
import pickle
import threading
from types import SimpleNamespace

import pytest

from shuxueshuo_server.graph_lesson.stage_three import bounded


def _exit_immediately():
    return None


class PendingProcess:
    pid = 54321
    exitcode = None

    def __init__(self, clock, publish_at=None):
        self.clock = clock
        self.publish_at = publish_at
        self.join_timeouts = []
        self.signals = []
        self.close_calls = 0

    def start(self):
        return None

    def is_alive(self):
        return self.exitcode is None

    def terminate(self):
        self.signals.append("terminate")

    def kill(self):
        self.signals.append("kill")

    def join(self, timeout=None):
        assert timeout is not None, "reaping must not perform an unbounded join"
        self.join_timeouts.append(timeout)
        self.clock[0] += min(timeout, 0.001)
        if self.publish_at is not None and self.clock[0] >= self.publish_at:
            self.exitcode = 0

    def close(self):
        self.close_calls += 1
        if self.exitcode is None:
            raise ValueError("Cannot close a process while it is still running")


class PipeHandle:
    closed = False

    def close(self):
        self.closed = True


@pytest.fixture
def pending_worker(monkeypatch):
    clock = [0.0]

    def sleep(seconds):
        clock[0] += seconds

    monkeypatch.setattr(bounded, "time", SimpleNamespace(monotonic=lambda: clock[0], sleep=sleep))
    monkeypatch.setattr(bounded, "_REAP_SECONDS", 0.01, raising=False)
    process = PendingProcess(clock)
    handles = []

    def pipe(**_kwargs):
        pair = PipeHandle(), PipeHandle()
        handles.extend(pair)
        return pair

    context = SimpleNamespace(Pipe=pipe, Process=lambda **_kwargs: process)
    monkeypatch.setattr(bounded.mp, "get_context", lambda _method: context)
    return SimpleNamespace(process=process, clock=clock, handles=handles)


def test_reap_stops_waiting_and_logs_when_exit_status_is_never_published(pending_worker, caplog):
    process = pending_worker.process
    assert bounded._reap(process) is False
    assert process.exitcode is None
    assert 0 < pending_worker.clock[0] <= bounded._REAP_SECONDS
    assert process.signals == ["terminate", "kill"]
    assert all(0 <= timeout <= bounded._REAP_SECONDS for timeout in process.join_timeouts)
    assert str(process.pid) in caplog.text and "unconfirmed" in caplog.text


def test_reap_accepts_exit_status_published_before_the_cleanup_deadline(pending_worker, caplog):
    process = pending_worker.process
    process.publish_at = 0.005
    assert bounded._reap(process) is True
    assert process.exitcode == 0
    assert pending_worker.clock[0] < bounded._REAP_SECONDS
    assert not caplog.records


@pytest.mark.parametrize("outcome", ["returned", "timeout", "interrupted"])
def test_bounded_cleanup_does_not_close_unconfirmed_worker_or_replace_outcome(
    pending_worker, monkeypatch, caplog, outcome,
):
    error = bounded.CalculationTimeout(elapsed_seconds=0, phase="original") if outcome == "timeout" else KeyboardInterrupt("original")

    def receive(*_args):
        if outcome != "returned":
            raise error
        return pickle.dumps({"ok": True, "result": {"exact": 42}})

    monkeypatch.setattr(bounded, "_receive", receive)
    if outcome == "returned":
        result, elapsed = bounded.run_bounded(_exit_immediately, timeout_seconds=5)
        assert result == {"exact": 42} and elapsed <= bounded._REAP_SECONDS
    else:
        with pytest.raises(type(error)) as caught:
            bounded.run_bounded(_exit_immediately, timeout_seconds=5)
        assert caught.value is error
    assert pending_worker.process.close_calls == 0
    assert all(handle.closed for handle in pending_worker.handles)
    assert "unconfirmed" in caplog.text


@pytest.mark.parametrize("outcome", ["returned", "timeout", "interrupted"])
def test_json_session_cleanup_preserves_outcome_and_closes_pipes_without_false_reaping(
    pending_worker, monkeypatch, caplog, outcome,
):
    from shuxueshuo_server.graph_lesson.stage_three import json_bounded

    error = bounded.CalculationTimeout(elapsed_seconds=0, phase="original") if outcome == "timeout" else KeyboardInterrupt("original")
    session = json_bounded.JsonCalculationSession(_exit_immediately)
    session._process = pending_worker.process
    session._requests, session._responses = PipeHandle(), PipeHandle()

    def receive(*_args):
        if outcome != "returned":
            raise error
        return json_bounded._encode({"phase": "settled", "status": "returned", "result": {"exact": 42}, "elapsed_seconds": 0.1})

    monkeypatch.setattr(json_bounded, "_send", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(json_bounded, "_receive", receive)
    if outcome == "returned":
        with session:
            assert session.run({}, timeout_seconds=5) == ({"exact": 42}, 0.1)
    else:
        with pytest.raises(type(error)) as caught, session:
            session.run({}, timeout_seconds=5)
        assert caught.value is error
    assert session._closed and session._requests.closed and session._responses.closed
    assert pending_worker.process.close_calls == 0
    assert "unconfirmed" in caplog.text


def test_json_supervisor_cleanup_does_not_close_an_unconfirmed_worker(pending_worker, monkeypatch, caplog):
    from shuxueshuo_server.graph_lesson.stage_three import json_bounded

    requests, responses = PipeHandle(), PipeHandle()

    def receive(*_args):
        raise EOFError("parent closed")

    def exit_process(status):
        raise SystemExit(status)

    monkeypatch.setattr(json_bounded, "_receive", receive)
    monkeypatch.setattr(json_bounded.os, "_exit", exit_process)
    with pytest.raises(SystemExit) as exit_status:
        json_bounded._supervisor(requests, responses, __name__, "_exit_immediately")
    assert exit_status.value.code == 0
    assert requests.closed and responses.closed
    assert all(handle.closed for handle in pending_worker.handles)
    assert pending_worker.process.close_calls == 0
    assert "unconfirmed" in caplog.text


@pytest.mark.skipif(os.name != "posix", reason="POSIX waitpid race")
def test_reap_waits_when_another_thread_has_reaped_but_not_published_exitcode(monkeypatch):
    process = mp.get_context("spawn").Process(target=_exit_immediately)
    process.start()
    reaped, publish = threading.Event(), threading.Event()
    original_waitpid = os.waitpid
    failures = []

    def delayed_waitpid(pid, flags):
        result = original_waitpid(pid, flags)
        if pid == process.pid and threading.current_thread().name == "multiprocessing-cleanup":
            reaped.set()
            assert publish.wait(5)
        return result

    def cleanup():
        try:
            mp.active_children()
        except (AssertionError, AttributeError, OSError, ValueError) as exc:
            failures.append(exc)

    cleaner = threading.Thread(target=cleanup, name="multiprocessing-cleanup")
    timer = threading.Timer(0.1, publish.set)
    try:
        assert bounded.wait([process.sentinel], timeout=5)
        monkeypatch.setattr(os, "waitpid", delayed_waitpid)
        cleaner.start()
        assert reaped.wait(5)
        timer.start()
        assert bounded._reap(process) is True
        assert process.exitcode == 0
        process.close()
    finally:
        publish.set()
        timer.cancel()
        if cleaner.ident is not None:
            cleaner.join(5)
        if not process._closed:
            process.join()
            process.close()
    assert not failures
