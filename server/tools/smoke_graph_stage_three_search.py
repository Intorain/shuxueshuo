"""Offline browser acceptance through the real development photo-search API.

Seeds an existing recorded extraction/type result (no fresh-image claim),
then starts stage three through POST /lesson/start. Real method execution is
paused before each route's verification while Chrome reads committed steps.
Only this test app exposes release, constructed-QA and retention controls.
"""

import argparse
import json
import shutil
import socket
import subprocess
import threading
import time
from hashlib import sha256
from html import escape
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from PIL import Image

from shuxueshuo_server.graph_lesson.stage_three.contracts import ROOT
from shuxueshuo_server.graph_lesson.stage_three.handoff import (
    attach_qa,
    enrichment_status,
    invalidate_goal,
)
from shuxueshuo_server.graph_lesson.stage_three.preview import open_store
from shuxueshuo_server.search.dev_api import create_search_router

PAGE_ID = "0" * 12
SEARCH_ID = "1" * 12
SOURCE = ROOT / "server/tests/solver/fixtures/graph-guided-stage-two/recorded/q01-20261018-02"
# Browser acceptance expectations only. Production route selection and mathematics
# are still computed by the server from the supplied recorded stage-two input.
CASE_EXPECTATIONS = {
    "q01": {"routes": ["discriminant", "extremum"], "prefix_cards": 4,
            "completed_cards": 10, "qa_cards": 5},
    "q04": {"routes": ["interval", "extremum"], "prefix_cards": 3,
            "completed_cards": 9, "qa_cards": 4,
            "internal_basis": {"ref": "method-interval-extremum#conditions", "read_cards": 3}},
    "q05": {"routes": ["interval", "extremum"], "prefix_cards": 3,
            "completed_cards": 9, "qa_cards": 4,
            "internal_basis": {"ref": "method-interval-extremum#conditions", "read_cards": 3}},
}


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def seed(output, source, case):
    directory = output / "search" / PAGE_ID / "problems" / SEARCH_ID
    directory.mkdir(parents=True)
    shutil.copytree(source, directory / "stage-two-1")
    shutil.copyfile(source / "source.png", directory / "question.png")
    stage_one = json.loads((source / "input.json").read_text())
    digest = sha256((directory / "question.png").read_bytes()).hexdigest()
    save(directory / "result.json", {
        "status": "reviewed_candidate", "candidate": stage_one["candidate"], "features": stage_one["features"],
        "features_ok": True, "source_reviewed": True, "review_findings": [],
        "question_sha256": digest, "sent_image_sha256": [digest],
    })
    with Image.open(directory / "question.png") as image:
        size = list(image.size)
    save(directory / "crop.json", {"page_id": PAGE_ID, "box": [0, 0, 1, 1], "page_size": size,
                                   "crop_size": size, "bytes": (directory / "question.png").stat().st_size})
    source_label = str(source.relative_to(ROOT)) if source.is_relative_to(ROOT) else str(source)
    save(output / "recording.json", {"source": source_label, "case": case,
                                    "evidence": "historical_recording", "new_llm_calls": 0,
                                    "qa": "constructed_interface_fixture"})
    return directory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--source", type=Path, help="Recorded stage-two directory containing input.json and source.png")
    parser.add_argument("--case", choices=CASE_EXPECTATIONS, default="q01")
    args = parser.parse_args()
    if args.case != "q01" and args.source is None:
        parser.error("--source is required for cases other than the default Q01 recording")
    source = (args.source or SOURCE).resolve()
    for name in ("input.json", "source.png", "stage-two-result.json"):
        if not (source / name).is_file():
            parser.error(f"recording is missing {name}: {source}")
    expectations = {"case": args.case, **CASE_EXPECTATIONS[args.case]}
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    save(output / "browser-case.json", expectations)
    directory = seed(output, source, args.case)
    releases = {route: threading.Event() for route in expectations["routes"]}
    paused = set()

    def barrier(state, _store):
        route = state["route_id"]
        paused.add(route)
        if not releases[route].wait(180):
            raise TimeoutError("search_browser.release_timeout")

    def forbidden(*args, **kwargs):
        raise AssertionError("browser acceptance must not construct an LLM provider")

    from shuxueshuo_server.graph_lesson.stage_two import selection
    from shuxueshuo_server.problem_understanding import batch_smoke

    selection.live_provider_factory = forbidden
    batch_smoke.live_provider_factory = forbidden
    app = FastAPI()
    app.include_router(create_search_router(output / "search", stage_three_hooks={"before_verification": barrier}))

    def store():
        return open_store(directory / "stage-two-1/stage-three")

    @app.get("/test/state")
    def state():
        snapshot = store().snapshot()
        return {"paused": sorted(paused), "snapshot": snapshot,
                "stage_two_attempts": len(list(directory.glob("stage-two-*")))}

    @app.post("/test/release/{route}")
    def release(route: str):
        releases[route].set()
        return {"released": route}

    @app.post("/test/qa/{phase}")
    def qa(phase: str):
        durable = store()
        task = next(t for t in durable.snapshot()["handoffs"] if t["route_id"] == expectations["routes"][0])
        steps = task["math_steps"] if phase == "completed" else task["math_steps"][:1]
        enrichment_status(durable, task["target_ref"], task["route_id"], status="running", commit_id=f"fixture-qa-{phase}-start")
        for step in steps:
            chunk = {key: task[key] for key in ("run_id", "lesson_version", "target_ref", "route_id", "verified_route_sha256")}
            chunk.update({key: step[key] for key in ("step_id", "math_step_sha256")})
            chunk["qa"] = {"questions": ["这一步为什么成立？"], "feedback": "对照本步列出的条件与数学依据。"}
            attach_qa(durable, chunk, commit_id="fixture-qa-" + step["step_id"])
        enrichment_status(durable, task["target_ref"], task["route_id"], status=phase, commit_id=f"fixture-qa-{phase}")
        return {"status": phase, "steps": len(steps)}

    @app.post("/test/prune")
    def prune():
        durable = store()
        through = durable.snapshot()["last_seq"]
        durable.prune_events(through)
        return {"through": through}

    @app.post("/test/invalidate")
    def invalidate():
        durable = store()
        target = durable.snapshot()["handoffs"][0]["target_ref"]
        invalidate_goal(durable, target, status="conflict", reason="constructed_browser_probe", commit_id="fixture-conflict")
        return {"status": "conflict"}

    app.mount("/", StaticFiles(directory=ROOT / "site", html=True), name="site")
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", ws="websockets"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        until = time.monotonic() + 10
        while not server.started:
            if not thread.is_alive() or time.monotonic() > until:
                raise RuntimeError("search_browser.server_start_failed")
            time.sleep(0.05)
        subprocess.run(["node", str(ROOT / "tools/verify-stage-three-search.mjs"),
                        f"http://127.0.0.1:{sock.getsockname()[1]}", str(output), SEARCH_ID,
                        str(output / "browser-case.json")], check=True, timeout=170)
    finally:
        for event in releases.values():
            event.set()
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()
    evidence = json.loads((output / "browser-evidence.json").read_text())
    screenshots = [("01-running-prefix.png", "完整验证之前，数学步骤已可阅读"),
                   ("01a-interrupted-prefix.png", "构造中断状态：无新增事件、无需刷新即可继续计算，已提交步骤保留"),
                   ("02-first-route-with-qa.png", "第一条路线已交付，第二条仍在计算；问答单独附加"),
                   ("03-student-reading.png", "自己做：作答与逐步阅读进度独立保存"),
                   ("04-refreshed.png", "刷新恢复同一运行与阅读位置")]
    if expectations.get("internal_basis"):
        screenshots.append(("05-internal-basis.png", "阅读条件求解卡后，内部调用的真实依据进入图谱"))
    figures = "".join(f'<figure><figcaption>{escape(title)}</figcaption><a href="{name}"><img src="{name}"></a></figure>'
                      for name, title in screenshots)
    (output / "index.html").write_text(
        '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>阶段③ 浏览器验收</title>'
        '<style>body{max-width:1100px;margin:32px auto;padding:20px;font:17px/1.7 system-ui;background:#f5f7f5;color:#203633}'
        'img{max-width:100%}figure{margin:30px 0}pre{white-space:pre-wrap;background:white;padding:20px}</style>'
        f'<h1>阶段③ {escape(args.case.upper())}：拍题页逐步展示</h1><p>输入来自既有 {escape(args.case.upper())} 录制。数学步骤为本次实际执行；问答为接口测试夹具；新增 LLM 调用为 0。</p>'
        '<p>中断探针仅构造执行状态响应和继续计算回执，实际求解仍停在验证屏障；用于验证页面在没有新事件时发现中断，进程恢复另由后端回归覆盖。</p>'
        '<p><a href="search/000000000000/problems/111111111111/stage-two-1/stage-three/index.html">求解轨迹与预算报告</a> · '
        '<a href="browser-evidence.json">浏览器验收数据</a> · <a href="recording.json">输入出处</a></p>'
        '<p>验收最后注入了构造的冲突事件，检查已交付答案和问答的撤销；这不是对原题数学结论的更正。</p>'
        f'<pre>{escape(json.dumps(evidence, ensure_ascii=False, indent=2))}</pre>{figures}</html>', encoding="utf-8")
    print(output / "browser-evidence.json")


if __name__ == "__main__":
    main()
