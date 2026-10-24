"""Search-only HTTP OCR, filesystem confinement, and bounded local fallback policy."""

import importlib.util
import io
import json
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from PIL import Image

from shuxueshuo_server.search import ocr_client
from shuxueshuo_server.search.ocr_client import OcrClient, OcrWorkerError

RESULT = {"ok": True, "width": 64, "height": 32, "lines": [], "layout": [],
          "orientation": {"status": "upright", "rotation_degrees": 0, "predicted_degrees": 0, "confidence": .99},
          "latency_ms": {"detect": 1}}


@pytest.fixture
def sidecar(tmp_path, monkeypatch):
    path = Path(__file__).resolve().parents[3] / "deploy/ocr/sidecar_server.py"
    spec = importlib.util.spec_from_file_location("ocr_sidecar_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    original_infer = module.infer_search
    root = tmp_path.resolve() / "work/search/private-v1/pages"
    source = root / ("a" * 12) / "source.png"
    source.parent.mkdir(parents=True)
    Image.new("RGB", (64, 32), "white").save(source)
    monkeypatch.setenv("PRODUCT_DATA_DIR", str(tmp_path.resolve()))
    monkeypatch.delenv("PRODUCT_SEARCH_OCR_PAGES_ROOT", raising=False)
    calls = []

    def infer(image_file, *, auto_orient):
        with Image.open(image_file) as image:
            assert image.size == (64, 32)
        calls.append(auto_orient)
        result = deepcopy(RESULT)
        if not auto_orient:
            result["orientation"] = {"status": "manual", "rotation_degrees": 0,
                                     "predicted_degrees": None, "confidence": None}
        return result

    monkeypatch.setattr(module, "READY", True)
    monkeypatch.setattr(module, "infer_search", infer)
    server = ThreadingHTTPServer(("127.0.0.1", 0), module.Handler)
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=.01), daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}"
    monkeypatch.setenv("PRODUCT_OCR_URL", url)
    try:
        yield SimpleNamespace(module=module, root=root, source=source, url=url, calls=calls,
                              original_infer=original_infer)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.parametrize("automatic", [True, False])
def test_real_http_search_contract_preserves_manual_rotation(sidecar, automatic):
    client = OcrClient(interpreter="/nonexistent/local/python")
    result = client.observe(sidecar.source, auto_orient=automatic)
    assert result["width"] == 64 and result["height"] == 32
    assert result["orientation"]["status"] == ("upright" if automatic else "manual")
    assert sidecar.calls == [automatic]
    assert client._process is None
    assert (sidecar.source).is_file()


@pytest.mark.parametrize("invalid", ["outside", "traversal", "doubled", "relative", "wrong_name", "bad_id", "nul", "backslash"])
def test_search_endpoint_rejects_illegal_paths(sidecar, invalid):
    values = {
        "outside": str(sidecar.root.parent / "source.png"),
        "traversal": str(sidecar.source.parent) + "/../" + sidecar.source.parent.name + "/source.png",
        "doubled": str(sidecar.source.parent) + "//source.png",
        "relative": "pages/" + "a" * 12 + "/source.png",
        "wrong_name": str(sidecar.source.with_name("page.png")),
        "bad_id": str(sidecar.root / "bad" / "source.png"),
        "nul": str(sidecar.source) + "\x00",
        "backslash": str(sidecar.source).replace("/source.png", "\\source.png"),
    }
    response = httpx.post(sidecar.url + "/v1/search/observe", json={"image": values[invalid], "auto_orient": True})
    assert response.status_code == 400
    assert response.json() == {"ok": False, "error": "ocr.invalid_request"}
    assert sidecar.calls == []
    assert str(sidecar.root) not in response.text


@pytest.mark.parametrize("level", ["file", "page", "root"])
def test_search_endpoint_rejects_symlinks_at_each_level(sidecar, monkeypatch, level):
    if level == "file":
        actual = sidecar.source.with_name("actual.png")
        sidecar.source.rename(actual)
        sidecar.source.symlink_to(actual)
    elif level == "page":
        actual = sidecar.source.parent.with_name("actual-page")
        sidecar.source.parent.rename(actual)
        sidecar.source.parent.symlink_to(actual, target_is_directory=True)
    else:
        actual = sidecar.root.with_name("actual-pages")
        sidecar.root.rename(actual)
        sidecar.root.symlink_to(actual, target_is_directory=True)
    response = httpx.post(sidecar.url + "/v1/search/observe", json={"image": str(sidecar.source), "auto_orient": False})
    assert response.status_code == 400
    assert sidecar.calls == []


@pytest.mark.parametrize("invalid", ["flag", "extra", "missing", "empty", "list", "json"])
def test_search_request_shape_is_not_the_product_protocol(sidecar, invalid):
    bodies = {"flag": {"image": str(sidecar.source), "auto_orient": "false"},
              "extra": {"image": str(sidecar.source), "auto_orient": True, "phase": "source"},
              "missing": {"work_dir": str(sidecar.root), "source_id": "x", "phase": "source"},
              "empty": {}, "list": [], "json": None}
    response = httpx.post(sidecar.url + "/v1/search/observe", content=json.dumps(bodies[invalid]))
    assert response.status_code == 400
    assert sidecar.calls == []


def test_http_request_limit_and_content_length_validation(sidecar):
    response = httpx.post(sidecar.url + "/v1/search/observe", content=b"x" * (sidecar.module.MAX_REQUEST_BYTES + 1))
    assert response.status_code == 413
    for length in ("-1", "invalid"):
        connection = HTTPConnection("127.0.0.1", int(sidecar.url.rsplit(":", 1)[1]))
        try:
            connection.request("POST", "/v1/search/observe", headers={"Content-Length": length})
            response = connection.getresponse()
            assert response.status == 400
            assert json.loads(response.read())["error"] == "ocr.invalid_request"
        finally:
            connection.close()
    assert sidecar.calls == []


@pytest.mark.parametrize("failure", ["bytes", "pixels", "not_png", "directory"])
def test_search_image_limits_are_checked_before_inference(sidecar, monkeypatch, failure):
    if failure == "bytes":
        monkeypatch.setattr(sidecar.module, "MAX_IMAGE_BYTES", 1)
    elif failure == "pixels":
        monkeypatch.setattr(sidecar.module, "MAX_IMAGE_PIXELS", 1)
    elif failure == "not_png":
        Image.new("RGB", (64, 32)).save(sidecar.source, format="JPEG")
    else:
        sidecar.source.unlink()
        sidecar.source.mkdir()
    with pytest.raises(OcrWorkerError, match="^ocr.unavailable$"):
        OcrClient().observe(sidecar.source)
    assert sidecar.calls == []


def test_search_and_product_inference_share_one_lock(sidecar, monkeypatch):
    active = []
    original = sidecar.module.infer_search

    def product(*_args):
        active.append("product")
        assert len(active) == 1
        time.sleep(.05)
        active.pop()
        return {"ok": True, "exit_code": 0, "stdout": "", "stderr": ""}

    def search(*args, **kwargs):
        active.append("search")
        assert len(active) == 1
        time.sleep(.05)
        result = original(*args, **kwargs)
        active.pop()
        return result

    monkeypatch.setattr(sidecar.module, "infer_search", search)
    monkeypatch.setattr(sidecar.module, "run_observe", product)
    with ThreadPoolExecutor(max_workers=2) as pool:
        observation = pool.submit(OcrClient().observe, sidecar.source)
        journal = pool.submit(httpx.post, sidecar.url + "/v1/observe",
                              json={"work_dir": str(sidecar.root), "source_id": "fixture", "phase": "source"})
        assert observation.result(timeout=5)["ok"]
        assert journal.result(timeout=5).status_code == 200


def test_inference_failure_and_readiness_never_disclose_paths(sidecar, monkeypatch):
    def fail(*_args, **_kwargs):
        raise RuntimeError(f"private data from {sidecar.source}")

    monkeypatch.setattr(sidecar.module, "infer_search", fail)
    response = httpx.post(sidecar.url + "/v1/search/observe", json={"image": str(sidecar.source), "auto_orient": True})
    assert response.status_code == 500 and response.json() == {"ok": False, "error": "ocr.failed"}
    monkeypatch.setattr(sidecar.module, "READY", False)
    monkeypatch.setattr(sidecar.module, "READY_ERROR", str(sidecar.source))
    response = httpx.get(sidecar.url + "/health")
    assert response.status_code == 503 and str(sidecar.source) not in response.text


@pytest.mark.parametrize("endpoint", ["/v1/observe", "/v1/search/observe"])
def test_model_queue_wait_is_independent_of_request_body_timeout(sidecar, monkeypatch, endpoint):
    mutex = threading.Lock()
    waiting = threading.Event()
    acquired_with = []

    class ObservedLock:
        def acquire(self, **kwargs):
            acquired_with.append(kwargs)
            waiting.set()
            return mutex.acquire(**kwargs)

        def release(self):
            mutex.release()

    monkeypatch.setattr(sidecar.module, "LOCK", ObservedLock())
    monkeypatch.setattr(sidecar.module, "REQUEST_TIMEOUT", .05)
    monkeypatch.setattr(sidecar.module, "SEARCH_LOCK_TIMEOUT", .5)
    monkeypatch.setattr(sidecar.module, "run_observe", lambda *_args: {"ok": True})
    body = ({"image": str(sidecar.source), "auto_orient": True} if endpoint == "/v1/search/observe"
            else {"work_dir": str(sidecar.root), "source_id": "fixture", "phase": "source"})
    with ThreadPoolExecutor(max_workers=1) as pool:
        mutex.acquire()
        try:
            pending = pool.submit(httpx.post, sidecar.url + endpoint, json=body)
            assert waiting.wait(timeout=2)
            time.sleep(.12)
            assert not pending.done()
        finally:
            mutex.release()
        assert pending.result(timeout=3).status_code == 200
    assert acquired_with == ([{"timeout": .5}] if endpoint == "/v1/search/observe" else [{}])


def test_search_queue_timeout_returns_busy_without_inference(sidecar, monkeypatch):
    from shuxueshuo_server.search.ocr_protocol import (
        OBSERVE_TIMEOUT,
        REQUEST_TIMEOUT,
        SEARCH_LOCK_TIMEOUT,
    )

    assert REQUEST_TIMEOUT < SEARCH_LOCK_TIMEOUT == 100 < OBSERVE_TIMEOUT == 120
    monkeypatch.setattr(sidecar.module, "SEARCH_LOCK_TIMEOUT", .04)
    with sidecar.module.LOCK:
        response = httpx.post(sidecar.url + "/v1/search/observe",
                              json={"image": str(sidecar.source), "auto_orient": True})
    assert response.status_code == 503
    assert response.json() == {"ok": False, "error": "ocr.busy"}
    assert sidecar.calls == []


@pytest.mark.parametrize("loaded", [True, False])
def test_search_requests_never_load_models(sidecar, monkeypatch, loaded):
    models = {name: object() for name in ("layout", "det", "rec", "orientation")}
    calls = []

    def observe(current, image_file, *, auto_orient):
        assert current is models
        assert not image_file.closed
        calls.append(auto_orient)
        return deepcopy(RESULT)

    def load_models(**_kwargs):
        pytest.fail("A request must never load OCR models")

    worker = SimpleNamespace(load_models=load_models, observe=observe)
    monkeypatch.setitem(sys.modules, "shuxueshuo_server.search.ocr_worker", worker)
    monkeypatch.setattr(sidecar.module, "infer_search", sidecar.original_infer)
    monkeypatch.setattr(sidecar.module, "SEARCH_MODELS", models if loaded else None)
    for automatic in (True, False):
        response = httpx.post(sidecar.url + "/v1/search/observe",
                              json={"image": str(sidecar.source), "auto_orient": automatic})
        assert response.status_code == (200 if loaded else 500)
        if not loaded:
            assert response.json() == {"ok": False, "error": "ocr.failed"}
    assert calls == ([True, False] if loaded else [])


def test_product_response_keeps_large_journal_output(sidecar, monkeypatch):
    output = "fixture journal\n" * (sidecar.module.MAX_RESPONSE_BYTES // 15 + 1)
    assert len(output.encode()) > sidecar.module.MAX_RESPONSE_BYTES
    monkeypatch.setattr(sidecar.module, "run_observe",
                        lambda *_args: {"ok": True, "exit_code": 0, "stdout": output, "stderr": ""})
    response = httpx.post(sidecar.url + "/v1/observe",
                          json={"work_dir": str(sidecar.root), "source_id": "fixture", "phase": "source"})
    assert response.status_code == 200
    assert response.json()["stdout"] == output


def test_sidecar_response_limit_is_enforced(sidecar, monkeypatch):
    monkeypatch.setattr(sidecar.module, "MAX_RESPONSE_BYTES", 10)
    response = httpx.post(sidecar.url + "/v1/search/observe", json={"image": str(sidecar.source), "auto_orient": True})
    assert response.status_code == 502
    assert response.json()["error"] == "ocr.invalid_response"


@pytest.mark.parametrize("failure", ["http", "redirect", "timeout", "product", "json", "huge"])
def test_remote_failure_never_starts_local_ocr(monkeypatch, failure):
    monkeypatch.setenv("PRODUCT_OCR_URL", "http://ocr:8080")
    original = httpx.Client

    def transport(request):
        assert request.url.path == "/v1/search/observe"
        assert json.loads(request.content)["auto_orient"] is False
        if failure == "timeout":
            raise httpx.ReadTimeout("private backend/path", request=request)
        if failure == "http":
            return httpx.Response(500, text="private backend/path")
        if failure == "redirect":
            return httpx.Response(302, headers={"Location": "http://outside.invalid/private"})
        if failure == "product":
            return httpx.Response(200, json={"ok": True, "exit_code": 0, "stdout": "private/path", "stderr": ""})
        if failure == "json":
            return httpx.Response(200, text="not json private/path")
        return httpx.Response(200, content=b"x" * (ocr_client.MAX_RESPONSE_BYTES + 1))

    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        assert kwargs["timeout"].read == 120 and kwargs["timeout"].connect == 5
        return original(transport=httpx.MockTransport(transport), **kwargs)

    monkeypatch.setattr(ocr_client.httpx, "Client", client)
    instance = OcrClient()
    monkeypatch.setattr(instance, "_start", lambda: pytest.fail("remote failure cannot fall back to local OCR"))
    with pytest.raises(OcrWorkerError) as failed:
        instance.observe("/private/page.png", auto_orient=False)
    assert str(failed.value) in {"ocr.unavailable", "ocr.timeout", "ocr.invalid_response"}


def test_local_error_payload_is_sanitized(monkeypatch):
    monkeypatch.delenv("PRODUCT_OCR_URL", raising=False)
    client = OcrClient()
    client._process = SimpleNamespace(stdin=io.StringIO(), stdout=io.StringIO(
        '{"ok":false,"error":"private source /home/student/page.png"}\n'), poll=lambda: None)
    with pytest.raises(OcrWorkerError, match="^ocr.failed$"):
        client.observe("/private/page.png")


def test_local_worker_timeout_kills_the_process(monkeypatch):
    monkeypatch.delenv("PRODUCT_OCR_URL", raising=False)
    client = OcrClient()
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    client._process = process
    with pytest.raises(OcrWorkerError, match="^ocr.timeout$"):
        client._read(timeout=.02)
    assert process.poll() is not None and client._process is None
