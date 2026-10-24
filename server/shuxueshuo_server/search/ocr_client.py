"""Talk to the long-lived OCR worker in the isolated Paddle interpreter."""

import json
import os
import subprocess
import threading
from pathlib import Path
from queue import Empty, Queue

import httpx

from .ocr_protocol import (
    MAX_REQUEST_BYTES,
    MAX_RESPONSE_BYTES,
    OBSERVE_TIMEOUT,
    STARTUP_TIMEOUT,
    valid_observation,
)

REPO = Path(__file__).resolve().parents[3]


class OcrWorkerError(RuntimeError):
    pass


class OcrClient:
    """Starts the worker lazily and serialises requests; Paddle models are not thread-safe."""

    def __init__(self, interpreter=None):
        self.interpreter = interpreter or os.environ.get(
            "REVIEW_OCR_PYTHON", str(REPO / "server/.venv-ocr/bin/python"))
        self._process = None
        self._lock = threading.Lock()
        self.url = os.environ.get("PRODUCT_OCR_URL", "").strip()

    def _start(self):
        if not Path(self.interpreter).is_file():
            raise OcrWorkerError("configuration.ocr_missing")
        self._process = subprocess.Popen(
            [self.interpreter, "-m", "shuxueshuo_server.search.ocr_worker"],
            cwd=REPO / "server", env={**os.environ, "PYTHONPATH": str(REPO / "server")},
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        ready = json.loads(self._read(timeout=STARTUP_TIMEOUT))
        if not isinstance(ready, dict) or ready.get("ready") is not True:
            self._stop()
            raise OcrWorkerError("ocr.worker_not_ready")

    def _read(self, *, timeout=OBSERVE_TIMEOUT):
        replies = Queue(maxsize=1)
        stream = self._process.stdout

        def read():
            try:
                replies.put(stream.readline(MAX_RESPONSE_BYTES + 1))
            except (OSError, ValueError):
                replies.put("")

        threading.Thread(target=read, daemon=True).start()
        try:
            line = replies.get(timeout=timeout)
        except Empty as exc:
            self._stop()
            raise OcrWorkerError("ocr.timeout") from exc
        if not line:
            self._stop()
            raise OcrWorkerError("ocr.worker_exited")
        if len(line.encode()) > MAX_RESPONSE_BYTES or not line.endswith("\n"):
            self._stop()
            raise OcrWorkerError("ocr.invalid_response")
        return line

    def _remote(self, request):
        try:
            url = httpx.URL(self.url)
            if url.scheme not in {"http", "https"} or not url.host or url.userinfo or url.query or url.fragment:
                raise OcrWorkerError("configuration.ocr_url")
            content = bytearray()
            with (
                httpx.Client(timeout=httpx.Timeout(OBSERVE_TIMEOUT, connect=5), trust_env=False,
                             follow_redirects=False) as client,
                client.stream("POST", self.url.rstrip("/") + "/v1/search/observe", content=request,
                              headers={"Content-Type": "application/json"}) as response,
            ):
                if response.status_code != 200:
                    raise OcrWorkerError("ocr.unavailable")
                for chunk in response.iter_bytes(chunk_size=65536):
                    content.extend(chunk)
                    if len(content) > MAX_RESPONSE_BYTES:
                        raise OcrWorkerError("ocr.invalid_response")
            reply = json.loads(content)
            if not valid_observation(reply):
                raise OcrWorkerError("ocr.invalid_response")
            return reply
        except httpx.TimeoutException as exc:
            raise OcrWorkerError("ocr.timeout") from exc
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise OcrWorkerError("ocr.unavailable") from exc

    def observe(self, image_path, *, auto_orient=True):
        if type(auto_orient) is not bool:
            raise ValueError("orientation.invalid_auto_orient")
        request = json.dumps({"image": str(image_path), "auto_orient": auto_orient}).encode()
        if len(request) > MAX_REQUEST_BYTES:
            raise OcrWorkerError("ocr.invalid_request")
        with self._lock:
            if self.url:
                return self._remote(request)
            try:
                if self._process is None or self._process.poll() is not None:
                    self._start()
                self._process.stdin.write(request.decode() + "\n")
                self._process.stdin.flush()
                reply = json.loads(self._read())
            except (OSError, ValueError, TypeError) as exc:
                self._stop()
                raise OcrWorkerError("ocr.unavailable") from exc
        if not isinstance(reply, dict) or reply.get("ok") is not True:
            raise OcrWorkerError("ocr.failed")
        return reply

    def _stop(self):
        process, self._process = self._process, None
        if process is not None:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=10)
            process.stdin.close()
            process.stdout.close()

    def close(self):
        with self._lock:
            self._stop()
