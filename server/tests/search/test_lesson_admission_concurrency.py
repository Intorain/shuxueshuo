"""Lesson admission never holds the router-wide status lock during slow I/O."""

import threading
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

import pytest

from shuxueshuo_server.problem_understanding.workflow_ledger import save
from shuxueshuo_server.search import dev_api, stage_three
from shuxueshuo_server.search.storage import SearchError
from tests.search.test_stage_three_api import client_for, forbidden, seed
from tests.search.test_stage_three_retry import completed_run


class HeldExecutor:
    def __init__(self):
        self.pending = []
        self.submitted = 0
        self.fail_submission = False

    def submit(self, function, *args, **kwargs):
        if self.fail_submission:
            raise RuntimeError("injected submission failure")
        future = Future()
        self.pending.append((future, function, args, kwargs))
        self.submitted += 1
        return future

    def drain(self):
        while self.pending:
            future, function, args, kwargs = self.pending.pop(0)
            try:
                future.set_result(function(*args, **kwargs))
            except BaseException as exc:
                future.set_exception(exc)
                raise

    def shutdown(self, wait=True):
        self.drain()


class AdmissionPause:
    def __init__(self):
        self.reached = threading.Event()
        self.release = threading.Event()
        self.owner = None
        self.used = False

    def inside(self):
        return threading.get_ident() == self.owner and not self.used

    def pause(self, *, fail=True):
        self.used = True
        self.reached.set()
        assert self.release.wait(10), "test did not release admission I/O"
        if fail:
            raise RuntimeError("injected admission failure")


@pytest.fixture
def held_executor(monkeypatch):
    executor = HeldExecutor()
    monkeypatch.setattr(dev_api, "ThreadPoolExecutor", lambda **_kwargs: executor)
    monkeypatch.setenv("RUN_LLM_INTEGRATION", "0")
    monkeypatch.setattr(dev_api, "run_question_image", forbidden)
    monkeypatch.setattr(dev_api, "run_stage_two", forbidden)
    monkeypatch.setattr(stage_three, "run_stage_three", forbidden)
    monkeypatch.setattr(stage_three, "resume_stage_three", forbidden)
    monkeypatch.setattr("shuxueshuo_server.problem_understanding.batch_smoke.live_provider_factory", forbidden)
    monkeypatch.setattr("shuxueshuo_server.graph_lesson.stage_two.selection.live_provider_factory", forbidden)
    return executor


def admission_url(client, directory, operation):
    base = f"/api/search/problems/{directory.name}/lesson"
    if operation == "retry":
        return base
    if operation == "start":
        return base + "/start"
    completed_run(client, directory)
    output = directory / "stage-two-1/stage-three"
    (output / "stage-three-result.json").unlink()
    save(output / "frozen.json", {"implementation": stage_three.fingerprint()})
    return base + "/" + stage_three.read(output / "run.json")["run_id"] + "/resume"


def track_lifecycle(monkeypatch, repository, directory, pause):
    original = repository.storage.lifecycle_lock

    def acquire(search_id, **kwargs):
        lease = original(search_id, **kwargs)
        if search_id == directory.name:
            pause.owner = threading.get_ident()
        return lease

    monkeypatch.setattr(repository.storage, "lifecycle_lock", acquire)


def pause_admission(monkeypatch, repository, directory, operation, phase, pause):
    track_lifecycle(monkeypatch, repository, directory, pause)
    if phase == "database":
        original = repository.submission

        def submission(user, search_id, **kwargs):
            row = original(user, search_id, **kwargs)
            if search_id == directory.name and pause.inside():
                pause.pause()
            return row

        monkeypatch.setattr(repository, "submission", submission)
    elif phase == "state":
        original = repository.set_state

        def set_state(search_id, **kwargs):
            if search_id == directory.name and kwargs.get("lesson_state") == "running" and pause.inside():
                pause.pause()
            return original(search_id, **kwargs)

        monkeypatch.setattr(repository, "set_state", set_state)
    elif operation == "retry":
        original = Path.read_text

        def read_text(path, *args, **kwargs):
            if path == directory / dev_api.RESULT_FILE and pause.inside():
                pause.pause()
            return original(path, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", read_text)
    else:
        name = "assert_current_attempt" if operation == "start" else "assert_resumable"
        original = getattr(stage_three, name)

        def validate(problem, attempt):
            original(problem, attempt)
            if problem == directory and pause.inside():
                pause.pause()

        monkeypatch.setattr(stage_three, name, validate)


def assert_unrelated_status_is_available(requests, client, other):
    response = requests.submit(client.get, f"/api/search/problems/{other.name}").result(timeout=3)
    assert response.status_code == 200, response.text
    assert response.json()["search_id"] == other.name
    assert response.json()["lesson"]["execution_status"] == "not_started"


def assert_admission_recovers(client, directory, url, executor):
    repository = client.app.state.search_repository
    with repository.storage.lifecycle_lock(directory.name):
        stage_three.release_problem(stage_three.acquire_problem(directory))
    current = client.get(f"/api/search/problems/{directory.name}")
    assert current.status_code == 200, current.text
    assert current.json()["lesson"]["execution_status"] not in {"running", "starting"}
    accepted = client.post(url)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "running"
    assert executor.submitted == 1
    duplicate = client.post(url)
    assert duplicate.status_code in {200, 409}, duplicate.text
    if duplicate.status_code == 200:
        assert duplicate.json()["status"] == "running"
    assert executor.submitted == 1
    executor.drain()
    current = client.get(f"/api/search/problems/{directory.name}")
    assert current.status_code == 200, current.text
    assert current.json()["lesson"]["execution_status"] not in {"running", "starting"}


@pytest.mark.parametrize("operation", ["retry", "start", "resume"])
@pytest.mark.parametrize("phase", ["database", "state", "files_or_validation"])
def test_blocked_admission_does_not_block_other_status_and_failure_releases_reservation(
    tmp_path, monkeypatch, held_executor, operation, phase,
):
    root, directory = seed(tmp_path)
    _, other = seed(tmp_path)
    pause = AdmissionPause()
    with client_for(root) as client:
        url = admission_url(client, directory, operation)
        pause_admission(monkeypatch, client.app.state.search_repository, directory, operation, phase, pause)
        with ThreadPoolExecutor(max_workers=3) as requests:
            admission = requests.submit(client.post, url)
            try:
                assert pause.reached.wait(5), "request did not reach lifecycle-protected I/O"
                assert_unrelated_status_is_available(requests, client, other)
                duplicate = requests.submit(client.post, url).result(timeout=3)
                assert duplicate.status_code in {200, 409}, duplicate.text
                if duplicate.status_code == 200:
                    assert duplicate.json()["status"] == "running"
                assert held_executor.submitted == 0
            finally:
                pause.release.set()
            with pytest.raises(RuntimeError, match="injected admission failure"):
                admission.result(timeout=5)
        assert_admission_recovers(client, directory, url, held_executor)


@pytest.mark.parametrize("operation", ["retry", "start", "resume"])
def test_failed_submission_keeps_lifecycle_until_interrupted_state_is_saved(
    tmp_path, monkeypatch, held_executor, operation,
):
    root, directory = seed(tmp_path)
    _, other = seed(tmp_path)
    pause = AdmissionPause()
    held_executor.fail_submission = True
    with client_for(root) as client:
        url = admission_url(client, directory, operation)
        repository = client.app.state.search_repository
        original = repository.set_state

        def interrupted(search_id, **kwargs):
            if search_id == directory.name and kwargs.get("lesson_state") == "interrupted" and not pause.used:
                with pytest.raises(SearchError, match="search.running"):
                    repository.storage.lifecycle_lock(search_id)
                pause.pause(fail=False)
            return original(search_id, **kwargs)

        monkeypatch.setattr(repository, "set_state", interrupted)
        with ThreadPoolExecutor(max_workers=2) as requests:
            admission = requests.submit(client.post, url)
            try:
                assert pause.reached.wait(5), "failed submission did not retain its lifecycle lease"
                assert_unrelated_status_is_available(requests, client, other)
                assert held_executor.submitted == 0
            finally:
                pause.release.set()
            with pytest.raises(RuntimeError, match="injected submission failure"):
                admission.result(timeout=5)
        held_executor.fail_submission = False
        assert_admission_recovers(client, directory, url, held_executor)


def test_old_worker_cleanup_cannot_clear_a_new_admission_marker(tmp_path, monkeypatch, held_executor):
    root, directory = seed(tmp_path)
    released, finish_cleanup = threading.Event(), threading.Event()
    with client_for(root) as client:
        repository = client.app.state.search_repository
        original_lock = repository.storage.lifecycle_lock
        first_lease = True

        def lifecycle_lock(search_id, **kwargs):
            nonlocal first_lease
            lease = original_lock(search_id, **kwargs)
            if search_id == directory.name and first_lease:
                first_lease = False
                original_close = lease.close

                def close():
                    original_close()
                    released.set()
                    assert finish_cleanup.wait(10), "test did not release old worker cleanup"

                monkeypatch.setattr(lease, "close", close)
            return lease

        monkeypatch.setattr(repository.storage, "lifecycle_lock", lifecycle_lock)
        url = f"/api/search/problems/{directory.name}/lesson/start"
        assert client.post(url).status_code == 200
        future, function, args, kwargs = held_executor.pending.pop(0)

        def complete_first():
            future.set_result(function(*args, **kwargs))

        with ThreadPoolExecutor(max_workers=1) as workers:
            previous = workers.submit(complete_first)
            try:
                assert released.wait(5), "old worker did not release its lifecycle lease"
                admitted = client.post(url)
                assert admitted.status_code == 200, admitted.text
                assert held_executor.submitted == 2
            finally:
                finish_cleanup.set()
            previous.result(timeout=5)
        retry = client.post(f"/api/search/problems/{directory.name}/lesson")
        assert retry.status_code == 200, retry.text
        assert retry.json() == {"status": "running"}
        assert held_executor.submitted == 2
        held_executor.drain()
