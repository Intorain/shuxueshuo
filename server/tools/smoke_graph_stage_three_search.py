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

import sympy as sp
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
from shuxueshuo_server.graph_lesson.stage_three.trajectory import encode_value
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
    "q06": {"routes": ["interval", "extremum"], "prefix_cards": 7,
            "completed_cards": 13, "qa_cards": 8, "interval_cases": 2,
            "internal_basis": {"ref": "method-interval-extremum#conditions", "read_cards": 4},
            "separation": {"division": "negative", "range_unit": "reciprocal_range",
                           "range_capability": "reciprocal_range", "basis": ["reciprocal-sum-function"]}},
    "q07": {"routes": ["interval", "extremum"], "prefix_cards": 9,
            "completed_cards": 16, "qa_cards": 10, "interval_cases": 3, "constant_case": True,
            "internal_basis": {"ref": "method-interval-extremum#conditions", "read_cards": 4},
            "separation": {"division": "positive", "range_unit": "inverse_range",
                           "range_capability": "reciprocal_of_range",
                           "basis": ["function-monotonicity", "skill-inequality-transform#reciprocal"]}},
    # Variable-route card counts come from committed snapshots and the final
    # handoff, so child-method teaching steps can evolve without hiding gaps.
    "q08": {"routes": ["variable"], "variable_swap": {
        "slope_sign": "positive", "endpoint_mode": "right_endpoint", "endpoint_conditions": 1}},
    "q09": {"routes": ["variable"], "variable_swap": {
        "slope_sign": "unknown", "endpoint_mode": "both_endpoints", "endpoint_conditions": 2}},
    "q13": {"routes": ["interval", "extremum"], "goal_extremum": {
        "kind": "find_minimum", "status": "attained"}},
}


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def answer_gold(case):
    """Read independently authored math gold, never a current execution result."""
    name = "extrema-answers.gold.json" if case == "q13" else "answers.gold.json"
    path = ROOT / "server/tests/solver/fixtures/graph-guided-stage-three" / name
    authored = json.loads(path.read_text())["cases"][case]
    intervals = [sp.Interval(sp.sympify(row["lower"]), sp.sympify(row["upper"]),
                             left_open=not row["left_closed"], right_open=not row["right_closed"])
                 for row in authored["feasible_set"]["intervals"]]
    feasible = sp.Union(*intervals)
    gold = {"source": str(path.relative_to(ROOT)), "feasible_set_exact": encode_value(feasible),
            "boundary_points": [sp.sstr(point) for point in sorted(feasible.boundary)]}
    if "answer" in authored:
        answer = dict(authored["answer"])
        for field in ("value", "bound"):
            if field in answer:
                value = sp.sympify(answer[field])
                answer[field] = {"expression": sp.sstr(value), "latex": sp.latex(value), "exact": encode_value(value)}
        gold.update(goal=authored["goal"], answer=answer)
    return gold


def seed(output, source, case):
    directory = output / "search" / PAGE_ID / "problems" / SEARCH_ID
    directory.mkdir(parents=True)
    shutil.copytree(source, directory / "stage-two-1", ignore=shutil.ignore_patterns("stage-three"))
    shutil.copyfile(source / "source.png", directory / "question.png")
    stage_one = json.loads((source / "input.json").read_text())
    digest = sha256((directory / "question.png").read_bytes()).hexdigest()
    result = {
        "status": "reviewed_candidate", "candidate": stage_one["candidate"], "features": stage_one["features"],
        "features_ok": True, "source_reviewed": True, "review_findings": [],
    }
    provenance = None
    if case == "q13":
        # Consume the integration run's actual revalidation result; do not
        # manufacture an upload admission or reviewed flag for browser setup.
        parent = source.parent
        result = json.loads((parent / "revalidated-stage-one.json").read_text())
        evidence = json.loads((parent / "revalidation.json").read_text())
        assert stage_one["statuses"]["admission"] == "student_upload"
        assert "passed" not in stage_one["statuses"] and "evaluation" not in stage_one["statuses"]
        assert result["candidate"] == stage_one["candidate"] and result["features"] == stage_one["features"]
        assert result["status"] == "reviewed_candidate" and result["source_reviewed"] is True
        assert evidence["review"]["status"] == "confirmed" and evidence["source_sha256"] == digest
        assert evidence["new_semantic_calls"] == evidence["new_network_attempts"] == 0
        retained = output / "source-evidence"
        retained.mkdir()
        shutil.copytree(parent / "recorded-source", retained / "recorded-source")
        for name in ("revalidated-stage-one.json", "revalidation.json"):
            shutil.copyfile(parent / name, retained / name)
        provenance = {"kind": "real_recorded_image_and_review", "source_sha256": digest,
                      "revalidation": "source-evidence/revalidation.json",
                      "revalidated_stage_one": "source-evidence/revalidated-stage-one.json",
                      "recorded_source": "source-evidence/recorded-source",
                      "retained_files_sha256": {
                          str(path.relative_to(output)): sha256(path.read_bytes()).hexdigest()
                          for path in sorted(retained.rglob("*")) if path.is_file()},
                      **{key: evidence[key] for key in ("historical_semantic_calls", "historical_network_attempts",
                                                        "new_semantic_calls", "new_network_attempts")}}
    save(directory / "result.json", {**result, "question_sha256": digest, "sent_image_sha256": [digest]})
    with Image.open(directory / "question.png") as image:
        size = list(image.size)
    save(directory / "crop.json", {"page_id": PAGE_ID, "box": [0, 0, 1, 1], "page_size": size,
                                   "crop_size": size, "bytes": (directory / "question.png").stat().st_size})
    source_label = str(source.relative_to(ROOT)) if source.is_relative_to(ROOT) else str(source)
    save(output / "recording.json", {"source": source_label, "case": case,
                                    "evidence": "historical_recording", "new_llm_calls": 0,
                                    "qa": "constructed_interface_fixture",
                                    **({"provenance": provenance} if provenance else {})})
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
    if expectations.get("variable_swap") or expectations.get("goal_extremum"):
        expectations["gold"] = answer_gold(args.case)
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    directory = seed(output, source, args.case)
    if expectations.get("goal_extremum"):
        expectations["provenance"] = json.loads((output / "recording.json").read_text())["provenance"]
    save(output / "browser-case.json", expectations)
    releases = {route: threading.Event() for route in expectations["routes"]}
    paused = set()
    llm_provider_attempts = 0

    def barrier(state, _store):
        route = state["route_id"]
        paused.add(route)
        if not releases[route].wait(180):
            raise TimeoutError("search_browser.release_timeout")

    def forbidden(*args, **kwargs):
        nonlocal llm_provider_attempts
        llm_provider_attempts += 1
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
                "llm_provider_attempts": llm_provider_attempts,
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
                   ("02-first-route-with-qa.png", "已验证路线交付后，问答通过游标恢复单独附加"),
                   ("03-student-reading.png", "自己做：作答与逐步阅读进度独立保存"),
                   ("04-refreshed.png", "刷新恢复同一运行与阅读位置")]
    if expectations.get("internal_basis"):
        screenshots.append(("05-internal-basis.png", "阅读条件求解卡后，内部调用的真实依据进入图谱"))
    if expectations.get("interval_cases"):
        screenshots.append(("06-interval-cases.png", "逐个阅读真实分类卡，常数与二次分支按实际调用点亮图谱"))
    if expectations.get("separation"):
        screenshots.append(("07-separation-range.png", "分离路线的除法方向与范围计算均来自实际执行证据"))
    if expectations.get("variable_swap"):
        screenshots.append(("08-variable-sources.png", "逐卡阅读主元法；公开调用与独立边界检查按真实来源点亮图谱"))
    if expectations.get("goal_extremum"):
        screenshots.extend((f"09-goal-closure-{route}.png", "独立边界检查后，读取完整可行集并确定最小值")
                           for route in expectations["routes"])
    figures = "".join(f'<figure><figcaption>{escape(title)}</figcaption><a href="{name}"><img src="{name}"></a></figure>'
                      for name, title in screenshots)
    provenance_link = (
        '<p>Q13 保留真实题图的历史识图与复核两次调用；本次离线复验和浏览器新增调用均为 0。'
        '<a href="source-evidence/revalidation.json">本次复验证据</a> · '
        '<a href="source-evidence/recorded-source/recording.json">历史录制文件校验清单</a></p>'
        if expectations.get("goal_extremum") else ""
    )
    (output / "index.html").write_text(
        '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>阶段③ 浏览器验收</title>'
        '<style>body{max-width:1100px;margin:32px auto;padding:20px;font:17px/1.7 system-ui;background:#f5f7f5;color:#203633}'
        'img{max-width:100%}figure{margin:30px 0}pre{white-space:pre-wrap;background:white;padding:20px}</style>'
        f'<h1>阶段③ {escape(args.case.upper())}：拍题页逐步展示</h1><p>输入来自既有 {escape(args.case.upper())} 录制。数学步骤为本次实际执行；问答为接口测试夹具；新增 LLM 调用为 0。</p>'
        '<p>中断探针仅构造执行状态响应和继续计算回执，实际求解仍停在验证屏障；用于验证页面在没有新事件时发现中断，进程恢复另由后端回归覆盖。</p>'
        '<p><a href="search/000000000000/problems/111111111111/stage-two-1/stage-three/index.html">求解轨迹与预算报告</a> · '
        '<a href="browser-evidence.json">浏览器验收数据</a> · <a href="recording.json">输入出处</a></p>'
        '<p>验收最后注入了构造的冲突事件，检查已交付答案和问答的撤销；这不是对原题数学结论的更正。</p>'
        f'{provenance_link}<pre>{escape(json.dumps(evidence, ensure_ascii=False, indent=2))}</pre>{figures}</html>', encoding="utf-8")
    print(output / "browser-evidence.json")


if __name__ == "__main__":
    main()
