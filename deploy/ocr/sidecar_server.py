"""Persistent OCR HTTP sidecar for product server compose.

Runs inside shuxueshuo-ocr with the repo mounted at /opt/shuxueshuo.
Keeps Paddle models warm; serializes observe requests with a process lock.
"""
from __future__ import annotations

import json
import logging
import os
import re
import stat
import sys
import threading
import traceback
from contextlib import ExitStack, contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import StringIO
from pathlib import Path

from shuxueshuo_server.search.ocr_protocol import (
    MAX_IMAGE_BYTES,
    MAX_IMAGE_PIXELS,
    MAX_REQUEST_BYTES,
    MAX_RESPONSE_BYTES,
    REQUEST_TIMEOUT,
    SEARCH_LOCK_TIMEOUT,
    valid_observation,
)

HOST = os.environ.get("PRODUCT_OCR_BIND", "0.0.0.0")
PORT = int(os.environ.get("PRODUCT_OCR_PORT", "8080"))
READY = False
READY_ERROR = ""
LOCK = threading.Lock()
SEARCH_MODELS = None


def infer_search(image_file, *, auto_orient=True):
    if SEARCH_MODELS is None:
        raise RuntimeError("ocr.not_ready")
    from shuxueshuo_server.search.ocr_worker import observe

    return observe(SEARCH_MODELS, image_file, auto_orient=auto_orient)


@contextmanager
def search_image(path):
    from PIL import Image

    configured = os.environ.get("PRODUCT_SEARCH_OCR_PAGES_ROOT")
    if not configured:
        data = os.environ.get("PRODUCT_DATA_DIR")
        if not data:
            raise ValueError("ocr.image_invalid")
        configured = str(Path(data) / "work/search/private-v1/pages")
    root = Path(configured)
    if not root.is_absolute() or str(root) != configured:
        raise ValueError("ocr.image_invalid")
    if not isinstance(path, str) or len(path) > 4096 or "\\" in path or "\x00" in path:
        raise ValueError("ocr.image_invalid")
    image = Path(path)
    if not image.is_absolute() or str(image) != path or any(part in (".", "..") for part in image.parts):
        raise ValueError("ocr.image_invalid")
    relative = image.relative_to(root)
    if (len(relative.parts) != 2 or re.fullmatch(r"[0-9a-f]{12}", relative.parts[0]) is None
            or relative.parts[1] != "source.png"):
        raise ValueError("ocr.image_invalid")
    with ExitStack() as stack:
        descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
        stack.callback(os.close, descriptor)
        for part in (*root.parts[1:], relative.parts[0]):
            if part in (".", ".."):
                raise ValueError("ocr.image_invalid")
            descriptor = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            stack.callback(os.close, descriptor)
        descriptor = os.open("source.png", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
        source = stack.enter_context(os.fdopen(descriptor, "rb"))
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_IMAGE_BYTES:
            raise ValueError("ocr.image_invalid")
        with Image.open(source) as header:
            if header.format != "PNG" or header.width * header.height > MAX_IMAGE_PIXELS:
                raise ValueError("ocr.image_invalid")
        source.seek(0)
        yield source


def run_search_observe(body):
    if not isinstance(body, dict) or set(body) != {"image", "auto_orient"} or type(body["auto_orient"]) is not bool:
        raise ValueError("ocr.invalid_request")
    with search_image(body["image"]) as image_file:
        result = {"ok": True, **infer_search(image_file, auto_orient=body["auto_orient"])}
    if not valid_observation(result):
        raise ValueError("ocr.invalid_response")
    return result


def warmup() -> None:
    global SEARCH_MODELS
    SEARCH_MODELS = None
    from shuxueshuo_server.product import observation as obs
    from shuxueshuo_server.search.ocr_worker import load_models

    worker = obs.get_paddle_worker()
    worker.manifests()
    for component in ("layout", "text_ocr", "formula_ocr"):
        worker._model(component)
    SEARCH_MODELS = load_models(require_orientation=True)


def run_observe(work_dir: str, source_id: str, phase: str) -> dict:
    from shuxueshuo_server.product.observation import ObservationJournal, run

    directory = Path(work_dir)
    if not directory.is_dir():
        return {
            "ok": False,
            "exit_code": 2,
            "stdout": "",
            "stderr": f"work_dir is not a directory: {work_dir}",
        }
    if phase not in ("source", "observation"):
        return {
            "ok": False,
            "exit_code": 2,
            "stdout": "",
            "stderr": f"invalid phase: {phase}",
        }
    stdout, stderr = StringIO(), StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    try:
        sys.stdout, sys.stderr = stdout, stderr
        journal = ObservationJournal(directory, source_id, phase)
        run(journal, directory.name, phase)
        return {"ok": True, "exit_code": 0, "stdout": stdout.getvalue(), "stderr": stderr.getvalue()}
    except Exception:
        logging.getLogger(__name__).exception("Product OCR request failed")
        stderr.write(traceback.format_exc())
        return {"ok": False, "exit_code": 1, "stdout": stdout.getvalue(), "stderr": stderr.getvalue()}
    finally:
        sys.stdout, sys.stderr = old_out, old_err


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def setup(self):
        super().setup()
        self.connection.settimeout(REQUEST_TIMEOUT)

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write(f"{self.address_string()} - {fmt % args}\n")

    def _send(self, code: int, payload: dict) -> None:
        try:
            body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode()
            if self.path == "/v1/search/observe" and len(body) > MAX_RESPONSE_BYTES:
                raise ValueError("ocr.invalid_response")
        except (TypeError, ValueError):
            code, body = 502, b'{"ok":false,"error":"ocr.invalid_response"}'
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        try:
            self.wfile.write(body)
        except (OSError, TimeoutError):
            pass

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/health":
            if not READY:
                self._send(503, {"ok": False, "ready": False, "error": "ocr.not_ready"})
                return
            self._send(200, {"ok": True, "ready": True})
            return
        if path == "/v1/manifests":
            if not READY:
                self._send(503, {"ok": False, "ready": False, "error": "ocr.not_ready"})
                return
            from shuxueshuo_server.product.observation import get_paddle_worker

            payloads = [item.to_payload() for item in get_paddle_worker().manifests()]
            self._send(200, {"ok": True, "providers": payloads})
            return
        self._send(404, {"ok": False, "error": "not_found"})

    def do_POST(self) -> None:
        path = self.path
        if path not in {"/v1/observe", "/v1/search/observe"}:
            self._send(404, {"ok": False, "error": "not_found"})
            return
        if not READY:
            self._send(503, {"ok": False, "ready": False, "error": "ocr.not_ready"})
            return
        try:
            lengths = self.headers.get_all("Content-Length", [])
            if len(lengths) != 1 or not lengths[0].isdigit() or self.headers.get("Transfer-Encoding"):
                raise ValueError("ocr.invalid_request")
            length = int(lengths[0])
            if length > MAX_REQUEST_BYTES:
                self._send(413, {"ok": False, "error": "ocr.request_too_large"})
                return
            self.connection.settimeout(REQUEST_TIMEOUT)
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ValueError("ocr.invalid_request")
            body = json.loads(raw)
            if not isinstance(body, dict):
                raise TypeError("ocr.invalid_request")
            if path == "/v1/observe":
                work_dir, source_id, phase = (body[key] for key in ("work_dir", "source_id", "phase"))
                if not all(isinstance(item, str) for item in (work_dir, source_id, phase)):
                    raise ValueError("ocr.invalid_request")
        except (UnicodeDecodeError, ValueError, KeyError, TypeError, OSError):
            self._send(400, {"ok": False, "error": "ocr.invalid_request"})
            return
        acquired = LOCK.acquire(timeout=SEARCH_LOCK_TIMEOUT) if path == "/v1/search/observe" else LOCK.acquire()
        if not acquired:
            self._send(503, {"ok": False, "error": "ocr.busy"})
            return
        try:
            if path == "/v1/search/observe":
                result = run_search_observe(body)
            else:
                result = run_observe(work_dir, source_id, phase)
        except (ValueError, OSError):
            self._send(400, {"ok": False, "error": "ocr.invalid_request"})
            return
        except Exception:
            logging.getLogger(__name__).exception("Search OCR request failed")
            self._send(500, {"ok": False, "error": "ocr.failed"})
            return
        finally:
            LOCK.release()
        self._send(200 if result.get("ok") else 500, result)


def main() -> int:
    global READY, READY_ERROR
    READY = False
    READY_ERROR = ""
    try:
        warmup()
        READY = True
    except Exception as exc:
        READY_ERROR = f"{type(exc).__name__}: {exc}"
        logging.getLogger(__name__).exception("OCR warmup failed")
        # Fail closed: compose healthcheck should restart until models load.
        print(f"ocr sidecar warmup failed: {READY_ERROR}", flush=True)
        return 1
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"ocr sidecar listening on {HOST}:{PORT}", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
