"""Talk to the long-lived OCR worker in the isolated Paddle interpreter."""

import json
import os
import subprocess
import threading
from pathlib import Path

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

    def _start(self):
        if not Path(self.interpreter).is_file():
            raise OcrWorkerError("configuration.ocr_missing")
        self._process = subprocess.Popen(
            [self.interpreter, "-m", "shuxueshuo_server.search.ocr_worker"],
            cwd=REPO / "server", env={**os.environ, "PYTHONPATH": str(REPO / "server")},
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        if json.loads(self._read()).get("ready") is not True:
            raise OcrWorkerError("ocr.worker_not_ready")

    def _read(self):
        line = self._process.stdout.readline()
        if not line:
            self._process = None
            raise OcrWorkerError("ocr.worker_exited")
        return line

    def observe(self, image_path, *, auto_orient=True):
        if type(auto_orient) is not bool:
            raise ValueError("orientation.invalid_auto_orient")
        with self._lock:
            if self._process is None or self._process.poll() is not None:
                self._start()
            self._process.stdin.write(json.dumps({"image": str(image_path), "auto_orient": auto_orient}) + "\n")
            self._process.stdin.flush()
            reply = json.loads(self._read())
        if not reply.get("ok"):
            raise OcrWorkerError(reply.get("error", "ocr.failed"))
        return reply

    def close(self):
        if self._process is not None:
            self._process.stdin.close()
            self._process.wait(timeout=10)
            self._process = None
