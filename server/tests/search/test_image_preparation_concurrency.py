"""Keep Pillow preparation serial without holding the lock across OCR waits."""

from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from threading import Event, Lock

import pytest
from PIL import Image

from shuxueshuo_server.search import dev_api
from tests.search.test_upload_limits import repository as repository_fixture
from tests.search.test_upload_limits import upload_client as upload_client_fixture


@pytest.fixture
def repository(tmp_path):
    yield from repository_fixture.__wrapped__(tmp_path)


@pytest.fixture
def upload_client(repository, monkeypatch):
    monkeypatch.setenv("RUN_LLM_INTEGRATION", "0")
    yield from upload_client_fixture.__wrapped__(repository, monkeypatch)


class ObservedLock:
    def __init__(self, lock):
        self.lock = lock
        self.contended = Event()

    def __enter__(self):
        if not self.lock.acquire(blocking=False):
            self.contended.set()
            assert self.lock.acquire(timeout=10), "image preparation lock was not released"
        return self

    def __exit__(self, *_args):
        self.lock.release()

    def locked(self):
        return self.lock.locked()


@pytest.fixture
def preparation_lock(monkeypatch):
    lock = ObservedLock(dev_api.IMAGE_PREPARE_LOCK)
    monkeypatch.setattr(dev_api, "IMAGE_PREPARE_LOCK", lock)
    return lock


def photograph(size):
    buffer = BytesIO()
    with Image.new("RGB", size, "white") as image:
        image.save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.mark.parametrize("phase", ["draft", "thumbnail"])
def test_two_uploads_cannot_decode_at_the_same_time(upload_client, preparation_lock, monkeypatch, phase):
    first_size, second_size = (120, 80), (140, 90)
    first_body, second_body = photograph(first_size), photograph(second_size)
    first_decode, second_decode, release = Event(), Event(), Event()
    original_prepare = getattr(Image.Image, phase)
    counter_lock = Lock()
    active, maximum = 0, 0

    def prepare(image, *args, **kwargs):
        nonlocal active, maximum
        with counter_lock:
            active += 1
            maximum = max(maximum, active)
        try:
            if image.size == first_size and not first_decode.is_set():
                first_decode.set()
                assert release.wait(10), "first upload was not released"
            elif image.size == second_size:
                second_decode.set()
            return original_prepare(image, *args, **kwargs)
        finally:
            with counter_lock:
                active -= 1

    monkeypatch.setattr(Image.Image, phase, prepare)
    with ThreadPoolExecutor(max_workers=2) as requests:
        first = requests.submit(upload_client.client.post, "/api/search/pages", content=first_body)
        try:
            assert first_decode.wait(10)
            second = requests.submit(upload_client.client.post, "/api/search/pages", content=second_body)
            assert preparation_lock.contended.wait(10), "second upload never reached the shared lock"
            assert not second_decode.is_set()
        finally:
            release.set()
        responses = [first.result(timeout=10), second.result(timeout=10)]
    assert [response.status_code for response in responses] == [200, 200]
    assert second_decode.is_set()
    assert maximum == 1
    assert len(upload_client.observations) == 2
    assert not preparation_lock.locked()


def test_blocked_ocr_does_not_block_another_upload_preparation(upload_client, preparation_lock, monkeypatch):
    first_body, second_body = photograph((120, 80)), photograph((140, 90))
    first_ocr, second_ocr, second_decode, release = Event(), Event(), Event(), Event()
    original_observe, original_draft = dev_api.OcrClient.observe, Image.Image.draft
    counter_lock = Lock()
    observations = 0

    def draft(image, *args, **kwargs):
        if image.size == (140, 90):
            second_decode.set()
        return original_draft(image, *args, **kwargs)

    def observe(client, path, *, auto_orient=True):
        nonlocal observations
        result = original_observe(client, path, auto_orient=auto_orient)
        with counter_lock:
            observations += 1
            position = observations
        if position == 1:
            first_ocr.set()
            assert release.wait(10), "first OCR observation was not released"
        else:
            second_ocr.set()
        return result

    monkeypatch.setattr(Image.Image, "draft", draft)
    monkeypatch.setattr(dev_api.OcrClient, "observe", observe)
    with ThreadPoolExecutor(max_workers=2) as requests:
        first = requests.submit(upload_client.client.post, "/api/search/pages", content=first_body)
        try:
            assert first_ocr.wait(10)
            assert not preparation_lock.locked()
            second = requests.submit(upload_client.client.post, "/api/search/pages", content=second_body)
            assert second_decode.wait(10)
            assert second_ocr.wait(10)
            response = second.result(timeout=10)
            assert response.status_code == 200, response.text
            assert not first.done()
        finally:
            release.set()
        response = first.result(timeout=10)
    assert response.status_code == 200, response.text
    assert not preparation_lock.locked()


def test_decode_failure_releases_the_preparation_lock(upload_client, preparation_lock, monkeypatch):
    body = photograph((120, 80))
    original_draft = Image.Image.draft
    failed = False

    def draft(image, *args, **kwargs):
        nonlocal failed
        if not failed:
            failed = True
            raise OSError("synthetic decode failure")
        return original_draft(image, *args, **kwargs)

    monkeypatch.setattr(Image.Image, "draft", draft)
    response = upload_client.client.post("/api/search/pages", content=body)
    assert response.status_code == 400
    assert response.json() == {"detail": "page.not_an_image"}
    assert not preparation_lock.locked()
    assert upload_client.observations == []
    response = upload_client.client.post("/api/search/pages", content=body)
    assert response.status_code == 200, response.text
    assert len(upload_client.observations) == 1
    assert not preparation_lock.locked()


@pytest.mark.parametrize("first_operation", ["upload", "rotate"])
def test_upload_and_manual_rotation_share_one_preparation_lock(
    upload_client, repository, preparation_lock, monkeypatch, first_operation,
):
    response = upload_client.client.post("/api/search/pages", content=photograph((180, 100)))
    assert response.status_code == 200, response.text
    parent_id = response.json()["page_id"]
    parent_path = repository.page(upload_client.user, parent_id)["path"] / "page.png"
    upload_body = photograph((140, 90))
    entered = {"upload": Event(), "rotate": Event()}
    release = Event()
    original_draft, original_open = Image.Image.draft, Image.open

    def draft(image, *args, **kwargs):
        if image.size == (140, 90) and not entered["upload"].is_set():
            entered["upload"].set()
            if first_operation == "upload":
                assert release.wait(10), "upload preparation was not released"
        return original_draft(image, *args, **kwargs)

    def open_image(source, *args, **kwargs):
        if isinstance(source, (str, Path)) and Path(source) == parent_path:
            entered["rotate"].set()
            if first_operation == "rotate":
                assert release.wait(10), "rotation preparation was not released"
        return original_open(source, *args, **kwargs)

    monkeypatch.setattr(Image.Image, "draft", draft)
    monkeypatch.setattr(Image, "open", open_image)
    operations = {
        "upload": lambda: upload_client.client.post("/api/search/pages", content=upload_body),
        "rotate": lambda: upload_client.client.post(f"/api/search/pages/{parent_id}/rotate", json={"degrees": 90}),
    }
    second_operation = "rotate" if first_operation == "upload" else "upload"
    with ThreadPoolExecutor(max_workers=2) as requests:
        first = requests.submit(operations[first_operation])
        try:
            assert entered[first_operation].wait(10)
            second = requests.submit(operations[second_operation])
            assert preparation_lock.contended.wait(10), "other operation never reached the shared lock"
            assert not entered[second_operation].is_set()
        finally:
            release.set()
        responses = {first_operation: first.result(timeout=10), second_operation: second.result(timeout=10)}
    assert all(response.status_code == 200 for response in responses.values())
    assert entered[second_operation].is_set()
    assert (responses["rotate"].json()["width"], responses["rotate"].json()["height"]) == (100, 180)
    assert len(upload_client.observations) == 3
    assert not preparation_lock.locked()
