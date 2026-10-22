"""Loopback-only student search: crop, understand, classify, then stream verified mathematics.

Not the production API (no login, quota or database); it exists to test
the recorded and live development workflow end to end. Everything a run
produces stays under ``root`` for inspection; stage-three HTTP/WS reads share
the runner's authoritative SQLite stream:

    <root>/<page_id>/page.png, ocr.json, segments.json
    <root>/<page_id>/problems/<search_id>/question.png, crop.json, result.json, workflow/
    <root>/<page_id>/problems/<search_id>/stage-two-<n>/stage-three/
"""

import asyncio
import json
import os
import re
import secrets
import threading
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from shuxueshuo_server.graph_lesson.stage_three.events import CursorExpired
from shuxueshuo_server.problem_understanding.workflow_ledger import save

from . import stage_three
from .lesson import present_lesson, run_stage_two
from .ocr_client import OcrClient, OcrWorkerError
from .question_image import question_png
from .segmentation import segment
from .stage_one import (
    RESULT_FILE,
    ledger_calls,
    reviewing_candidate,
    run_question_image,
)

MAX_UPLOAD = 20 * 1024 * 1024
ID = re.compile(r"^[0-9a-f]{12}$")
FAILURES = {"missing_figure": "figure", "unreadable": "unclear", "ambiguous": "unclear"}


class ProblemRequest(BaseModel):
    page_id: str
    box: list[float] = Field(min_length=4, max_length=4)


def create_search_router(root, *, stage_three_hooks=None):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    ocr = OcrClient()
    runs = ThreadPoolExecutor(max_workers=2, thread_name_prefix="search-stage-one")
    errors, lesson_errors, judging = {}, {}, set()
    errors_lock = threading.Lock()
    router = APIRouter(prefix="/api/search")

    def page_dir(page_id):
        if not ID.match(page_id) or not (root / page_id / "page.png").is_file():
            raise HTTPException(404, "page.not_found")
        return root / page_id

    def problem_dir(search_id):
        if ID.match(search_id):
            for match in root.glob(f"*/problems/{search_id}"):
                return match
        raise HTTPException(404, "search.not_found")

    @router.post("/pages")
    async def upload_page(request: Request):
        body = await request.body()
        if not body or len(body) > MAX_UPLOAD:
            raise HTTPException(413 if body else 400, "page.size")
        try:
            with Image.open(BytesIO(body)) as image:
                page = ImageOps.exif_transpose(image).convert("RGB")
        except (UnidentifiedImageError, OSError) as exc:
            raise HTTPException(400, "page.not_an_image") from exc
        page_id = secrets.token_hex(6)
        directory = root / page_id
        directory.mkdir()
        page.save(directory / "page.png")
        try:
            observed = await run_in_threadpool(ocr.observe, directory / "page.png")
        except OcrWorkerError as exc:
            raise HTTPException(503, f"ocr.unavailable: {exc}") from exc
        save(directory / "ocr.json", observed)
        result = segment(observed)
        payload = {"page_id": page_id, "width": page.width, "height": page.height, "mode": result.mode,
                   "regions": result.regions, "diagnostics": result.diagnostics,
                   "latency_ms": observed["latency_ms"]}
        save(directory / "segments.json", payload)
        return payload

    @router.get("/pages/{page_id}/image")
    def page_image(page_id: str):
        return FileResponse(page_dir(page_id) / "page.png", media_type="image/png")

    @router.post("/problems")
    def start_problem(body: ProblemRequest):
        directory = page_dir(body.page_id)
        x0, y0, x1, y1 = (min(1.0, max(0.0, v)) for v in body.box)
        if x1 - x0 < 0.02 or y1 - y0 < 0.01:
            raise HTTPException(400, "box.too_small")
        if os.getenv("RUN_LLM_INTEGRATION") != "1":
            raise HTTPException(503, "stage_one.disabled: start run_site.py with RUN_LLM_INTEGRATION=1")
        with Image.open(directory / "page.png") as page:
            w, h = page.size
            crop = page.crop((round(x0 * w), round(y0 * h), round(x1 * w), round(y1 * h)))
        png = question_png(crop)
        with Image.open(BytesIO(png)) as sent:
            size = list(sent.size)
        search_id = secrets.token_hex(6)
        output = directory / "problems" / search_id
        output.mkdir(parents=True)
        save(output / "crop.json", {"page_id": body.page_id, "box": [x0, y0, x1, y1], "page_size": [w, h],
                                    "crop_size": size, "bytes": len(png)})
        (output / "question.png").write_bytes(png)

        def work():
            from shuxueshuo_server.problem_understanding.batch_smoke import (
                live_provider_factory,
            )

            try:
                result = run_question_image(png, output, live_provider_factory("deepseek")(), problem_id=search_id)
            except Exception as exc:  # noqa: BLE001 - surfaced to the page as a system failure
                with errors_lock:
                    errors[search_id] = _message(exc)
                    judging.discard(search_id)
                return
            if result["status"] == "reviewed_candidate":
                judge(search_id, output, result)
            else:
                with errors_lock:
                    judging.discard(search_id)

        # Marked before result.json can appear, so a poll never sees "done" without stage two.
        with errors_lock:
            judging.add(search_id)
        runs.submit(work)
        return {"search_id": search_id, "crop_size": size}

    def judge(search_id, directory, result, lease=None):
        """Stage two: usually program-only; one LLM call only when several types hold."""
        from shuxueshuo_server.graph_lesson.stage_two.selection import (
            live_provider_factory,
        )

        with errors_lock:
            judging.add(search_id)
            lesson_errors.pop(search_id, None)
        try:
            lease = lease or stage_three.acquire_problem(directory)
            run_stage_two(directory, result, provider=live_provider_factory(),
                          unsupported_root=root / "unsupported")
            stage_three.run_stage_three(stage_three.latest_attempt(directory), hooks=stage_three_hooks)
        except Exception as exc:  # noqa: BLE001 - surfaced to the page as a judging failure
            with errors_lock:
                lesson_errors[search_id] = _message(exc)
        finally:
            if lease is not None:
                stage_three.release_problem(lease)
            with errors_lock:
                judging.discard(search_id)

    def lesson(search_id, directory, result):
        if stage_three.pending_retry(directory) is not None:
            return {"status": "running", "execution_status": "starting", "stream": None}
        attempt = stage_three.latest_attempt(directory)
        stage_two = (stage_three.read(attempt / stage_three.RESULT)
                     if attempt is not None and (attempt / stage_three.RESULT).is_file() else None)
        with errors_lock:
            running, error = search_id in judging, lesson_errors.get(search_id)
        if stage_two is None:
            if running:
                return {"status": "running", "execution_status": "not_started", "stream": None}
            return {"status": "error", "message": error or "stage_two.missing"}
        presented = present_lesson(stage_two, result.get("features", []),
                                   (result.get("candidate") or {}).get("original_text", ""), search_id,
                                   candidate=result.get("candidate"))
        presented.update(stage_three.presentation(directory, search_id, running=running, attempt=attempt))
        if error:
            presented["execution_error"] = error
        return presented

    @router.post("/problems/{search_id}/lesson")
    def retry_lesson(search_id: str):
        """Rerun stage two only (no image reading) after a judging failure."""
        directory = problem_dir(search_id)
        if not (directory / RESULT_FILE).exists():
            raise HTTPException(409, "stage_one.not_done")
        result = json.loads((directory / RESULT_FILE).read_text(encoding="utf-8"))
        if result["status"] != "reviewed_candidate":
            raise HTTPException(409, "stage_one.not_reviewed")
        with errors_lock:
            if search_id in judging:
                return {"status": "running"}
            try:
                lease = stage_three.acquire_problem(directory)
            except stage_three.LessonBusy as exc:
                raise HTTPException(409, str(exc)) from exc
            try:
                stage_three.reserve_retry(directory)
            except BaseException:
                stage_three.release_problem(lease)
                raise
            judging.add(search_id)
            lesson_errors.pop(search_id, None)
        try:
            runs.submit(judge, search_id, directory, result, lease)
        except BaseException:
            with errors_lock:
                judging.discard(search_id)
            stage_three.release_problem(lease)
            raise
        return {"status": "running"}

    def queue_execution(search_id, directory, operation, *, validate=None):
        with errors_lock:
            if search_id in judging:
                raise HTTPException(409, "lesson.running")
            try:
                lease = stage_three.acquire_problem(directory)
            except stage_three.LessonBusy as exc:
                raise HTTPException(409, str(exc)) from exc
            # The request may have read the previous attempt just before a
            # retry acquired this lease. Validate its identity while reserved,
            # before queueing work or changing the in-memory running marker.
            try:
                if validate is not None:
                    validate()
            except stage_three.LessonConflict as exc:
                stage_three.release_problem(lease)
                raise HTTPException(409, str(exc)) from exc
            except BaseException:
                stage_three.release_problem(lease)
                raise
            judging.add(search_id)
            lesson_errors.pop(search_id, None)

        def work():
            try:
                operation()
            except Exception as exc:  # noqa: BLE001 - persist the failure without replacing committed mathematics.
                with errors_lock:
                    lesson_errors[search_id] = _message(exc)
            finally:
                stage_three.release_problem(lease)
                with errors_lock:
                    judging.discard(search_id)

        runs.submit(work)

    def locate_run(search_id, run_id):
        directory = problem_dir(search_id)
        try:
            return directory, stage_three.find_run(directory, run_id)
        except FileNotFoundError as exc:
            raise HTTPException(404, "lesson.run_not_found") from exc

    @router.post("/problems/{search_id}/lesson/start")
    def start_existing_lesson(search_id: str):
        """Explicitly start stage three for an already saved stage-two attempt."""
        directory = problem_dir(search_id)
        attempt = stage_three.latest_attempt(directory)
        if attempt is None or not (attempt / stage_three.RESULT).is_file():
            raise HTTPException(409, "stage_two.not_done")
        if (attempt / "stage-three").exists():
            return stage_three.presentation(directory, search_id)
        queue_execution(search_id, directory, lambda: stage_three.run_stage_three(attempt, hooks=stage_three_hooks),
                        validate=lambda: stage_three.assert_current_attempt(directory, attempt))
        return {"status": "running", **stage_three.presentation(directory, search_id, running=True)}

    @router.post("/problems/{search_id}/lesson/{run_id}/resume")
    def resume_lesson(search_id: str, run_id: str):
        directory, output = locate_run(search_id, run_id)
        try:
            stage_three.assert_resumable(directory, output)
        except stage_three.LessonConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        if (output / "stage-three-result.json").is_file() and not stage_three.has_pending_interactions(output):
            return {"status": "completed", **stage_three.presentation(directory, search_id)}
        queue_execution(search_id, directory,
                        lambda: stage_three.resume_stage_three(directory, run_id, hooks=stage_three_hooks),
                        validate=lambda: stage_three.assert_resumable(directory, output))
        return {"status": "running", "stream": stage_three.stream_descriptor(search_id, output)}

    @router.get("/problems/{search_id}/lesson/{run_id}/snapshot")
    def lesson_snapshot(search_id: str, run_id: str):
        _directory, output = locate_run(search_id, run_id)
        if stage_three.stream_descriptor(search_id, output) is None:
            raise HTTPException(409, "lesson.stream_not_ready")
        return JSONResponse(stage_three.open_store(output).snapshot(), headers={"Cache-Control": "no-store"})

    def expired_payload(exc):
        return {"error": "events.cursor_expired", "cursor_expired": True, "minimum_seq": exc.minimum_seq}

    @router.get("/problems/{search_id}/lesson/{run_id}/events")
    def lesson_events(search_id: str, run_id: str, after_seq: int = 0):
        _directory, output = locate_run(search_id, run_id)
        if stage_three.stream_descriptor(search_id, output) is None:
            raise HTTPException(409, "lesson.stream_not_ready")
        try:
            payload = stage_three.event_page(output, after_seq)
        except CursorExpired as exc:
            return JSONResponse(expired_payload(exc), status_code=409, headers={"Cache-Control": "no-store"})
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return JSONResponse(payload, headers={"Cache-Control": "no-store"})

    @router.websocket("/problems/{search_id}/lesson/{run_id}/ws")
    async def lesson_websocket(websocket: WebSocket, search_id: str, run_id: str, after: int = 0):
        await websocket.accept()
        try:
            _directory, output = locate_run(search_id, run_id)
            if stage_three.stream_descriptor(search_id, output) is None:
                raise HTTPException(409, "lesson.stream_not_ready")
            first = True
            while True:
                payload = await run_in_threadpool(stage_three.event_page, output, after)
                if first or payload["events"]:
                    await websocket.send_json(payload)
                    after = payload["last_seq"]
                    first = False
                try:
                    await asyncio.wait_for(websocket.receive_text(), timeout=0.15)
                except TimeoutError:
                    pass
        except CursorExpired as exc:
            await websocket.send_json(expired_payload(exc))
            await websocket.close(code=4009)
        except (HTTPException, ValueError) as exc:
            await websocket.send_json({"error": exc.detail if isinstance(exc, HTTPException) else str(exc)})
            await websocket.close(code=4404 if isinstance(exc, HTTPException) and exc.status_code == 404 else 4400)
        except WebSocketDisconnect:
            pass

    @router.get("/problems/{search_id}")
    def problem_status(search_id: str):
        directory = problem_dir(search_id)
        calls = ledger_calls(directory / "workflow")
        state = {"search_id": search_id, "calls": [{"stage": s, "status": st} for s, st in calls],
                 "crop": json.loads((directory / "crop.json").read_text(encoding="utf-8"))}
        with errors_lock:
            error = errors.get(search_id)
        if (directory / RESULT_FILE).exists():
            result = json.loads((directory / RESULT_FILE).read_text(encoding="utf-8"))
            presented = _present(result)
            if presented["outcome"] == "ok":
                presented["lesson"] = lesson(search_id, directory, result)
            return {**state, "state": "done", **presented}
        if error:
            return {**state, "state": "done", "status": str(error), "outcome": "error"}
        candidate = reviewing_candidate(directory / "workflow")
        preview = {"original_text": candidate.get("original_text"), "parts": _parts(candidate),
                   "root": candidate.get("root")} if candidate else None
        return {**state, "state": "running", "preview": preview}

    @router.get("/problems/{search_id}/image")
    def problem_image(search_id: str):
        return FileResponse(problem_dir(search_id) / "question.png", media_type="image/png")

    return router


def _present(result):
    """What the problem page needs, plus the image identity check."""
    status = result["status"]
    findings = [{"kind": f["kind"], "source_excerpt": f["source_excerpt"], "message": f["message"]}
                for f in result.get("review_findings", [])]
    # Uncertainties the model declared while extracting (before any review).
    findings += [{"kind": d["code"], "source_excerpt": "", "message": d.get("message", "")}
                 for d in result.get("confirmation_diagnostics", [])]
    if status == "reviewed_candidate":
        outcome = "ok"
    elif status == "needs_confirmation":
        kinds = [FAILURES.get(f["kind"]) for f in findings]
        outcome = "figure" if "figure" in kinds else "unclear"
    elif status == "code_gap" or (status != "workflow.internal_error" and result.get("unsupported_diagnostics")):
        # A run stopped by budget or oscillation while the last candidate still
        # used unsupported mathematics is unsupported, not a system failure.
        outcome = "unsupported"
    else:
        outcome = "error"
    candidate = result.get("candidate") or {}
    return {
        "status": status,
        "outcome": outcome,
        "original_text": candidate.get("original_text"),
        "parts": _parts(candidate),
        "root": candidate.get("root"),
        "findings": findings,
        "features": [{"feature_id": f["feature_id"], "scope": f["scope"], "status": f["status"]}
                     for f in result.get("features", [])],
        "image_check": {
            "question_sha256": result["question_sha256"],
            "sent_image_sha256": result["sent_image_sha256"],
            "verified": result["sent_image_sha256"] == [result["question_sha256"]],
        },
        "elapsed_seconds": result.get("elapsed_seconds"),
    }


def _message(exc):
    return getattr(exc, "args", [type(exc).__name__])[0] or type(exc).__name__


def _parts(candidate):
    labels = [child.get("label") for child in (candidate.get("root") or {}).get("children", [])]
    return [label for label in labels if label]
