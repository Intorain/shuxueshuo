"""Replay the student's real extraction/review through current recognition and UI data.

No provider is constructed: review status is rederived from the original
hash-checked response and its candidate revision, never copied from a fixture flag.
Set GRAPH_PARAMETER_EXTREMUM_RUN_DIR to retain a self-contained debug report.
"""

import json
import os
import shutil
import socket
from hashlib import sha256
from html import escape
from pathlib import Path

from shuxueshuo_server.graph_lesson.stage_one.extraction import (
    GraphStageOneContract,
    validate_candidate,
)
from shuxueshuo_server.graph_lesson.stage_one.runner import (
    candidate_features,
    verify_recorded_sample,
)
from shuxueshuo_server.graph_lesson.stage_two.runner import record_run, replay_run
from shuxueshuo_server.problem_understanding import batch_smoke
from shuxueshuo_server.problem_understanding.identity import revision
from shuxueshuo_server.problem_understanding.workflow_ledger import save
from shuxueshuo_server.search.lesson import present_lesson, run_stage_two
from shuxueshuo_server.solver.extraction import multimodal_provider

RECORDING = Path(__file__).parent / "fixtures/parameter-extremum/recorded-20261018"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def revalidate_recording():
    manifest = read(RECORDING / "recording.json")
    assert manifest["contract"] == "student-search-recording/v1"
    for name, expected in manifest["files"].items():
        path = (RECORDING / name).resolve()
        assert path.is_relative_to(RECORDING.resolve())
        assert sha256(path.read_bytes()).hexdigest() == expected
    frozen, responses = verify_recorded_sample(RECORDING)
    assert [row["stage"] for row in responses] == ["extract", "review"]
    ledger = read(RECORDING / "workflow/ledger.json")
    image_hash = frozen["fixture_hashes"]["source.png"]
    assert ledger["identity"]["binding"]["images"] == [image_hash]
    for row, call in zip(responses, ledger["calls"], strict=True):
        response = row["response"]
        # Keep evidence of actual provider calls, separately from this offline replay.
        assert response["metadata"]["provider"] == "deepseek"
        assert response["network_attempts"] == call["network_attempts"] == 1
        assert response["raw_payload"]["id"]
        assert response["raw_payload"]["usage"]["total_tokens"] > 0
        message = response["raw_payload"]["choices"][0]["message"]
        assert message["content"] == response["text"]
        request = read(RECORDING / "workflow" / call["directory"] / "request.json")
        images = [part["image"] for message in request["messages"]
                  if isinstance(message["content"], list)
                  for part in message["content"] if "image" in part]
        assert [image["sha256"] for image in images] == [image_hash]

    extraction, review = responses
    candidate = json.loads(extraction["response"]["text"])
    validation = validate_candidate(candidate)
    assert validation["contract_valid"], validation
    assert extraction["response"]["finish_reason"] == "stop"
    checked_review = GraphStageOneContract().validate_review(review["response"]["text"], candidate)
    source_reviewed = (
        checked_review["status"] == "confirmed"
        and review["response"]["finish_reason"] == "stop"
        and review["base_revision"] == revision(candidate)
    )
    assert source_reviewed
    features = candidate_features(candidate)
    assert features["ok"], features
    return {
        "status": "reviewed_candidate" if source_reviewed else "unreviewed",
        "source_reviewed": source_reviewed,
        "candidate": candidate,
        "features": features["features"],
        "features_ok": features["ok"],
    }, {"validation": validation, "review": checked_review,
        "review_base_revision": review["base_revision"], "source_sha256": image_hash,
        "mode": "offline_replay", "new_semantic_calls": 0, "new_network_attempts": 0,
        "historical_semantic_calls": len(responses),
        "historical_network_attempts": sum(row["response"]["network_attempts"] for row in responses)}


def debug_report(output, result, evidence, lesson):
    save(output / "revalidated-stage-one.json", result)
    save(output / "revalidation.json", evidence)
    save(output / "lesson.json", lesson)
    sections = "".join(
        "<section><h2>" + escape(title) + "</h2><pre>"
        + escape(json.dumps(value, ensure_ascii=False, indent=2)) + "</pre></section>"
        for title, value in (("提取与复核证据", evidence), ("当前学生页面数据", lesson))
    )
    (output / "index.html").write_text(
        '<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
        '<title>参数最小值 · 真实 LLM 录制回归</title>'
        '<style>body{font:16px/1.65 system-ui;max-width:1120px;margin:40px auto;padding:0 24px}'
        'img{max-width:100%}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f4f7fa;padding:16px}'
        '</style><h1>参数最小值 · 真实 LLM 录制回归</h1>'
        '<p>历史识图与复核各调用一次真实 LLM；本次为离线重放，新增模型调用与网络请求均为 0。</p>'
        '<img alt="历史 LLM 实际读取的题图" src="question.png">'
        '<p><a href="stage-two-1/index.html">当前题型、D1/D2 与特征报告</a> · '
        '<a href="replay/index.html">阶段二录制重放比对</a> · '
        '<a href="lesson.json">学生页面 JSON</a></p>'
        '<p><a href="recorded-source/workflow/calls/01-extract/response.json">原始识图响应</a> · '
        '<a href="recorded-source/workflow/calls/02-review/response.json">原始复核响应</a> · '
        '<a href="recorded-source/historical-result.json">修改前的特征结果</a></p>'
        + sections + '</html>', encoding="utf-8",
    )


def test_real_parameter_minimum_recording_reaches_the_student_lesson(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("recorded parameter-extremum integration must never use a live provider")

    monkeypatch.setattr(batch_smoke, "live_provider_factory", forbidden)
    monkeypatch.setattr(multimodal_provider, "_default_client_factory", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    configured = os.getenv("GRAPH_PARAMETER_EXTREMUM_RUN_DIR")
    output = Path(configured) if configured else tmp_path / "integration"
    output.mkdir(parents=True, exist_ok=False)
    shutil.copytree(RECORDING, output / "recorded-source")
    shutil.copyfile(RECORDING / "fixture/source.png", output / "question.png")
    result, evidence = revalidate_recording()
    historical = read(RECORDING / "historical-result.json")
    assert result["candidate"] == historical["candidate"]
    assert result["candidate"]["root"]["goals"] == [{"kind": "find_minimum", "expression": "a"}]
    assert all(row["status"] == "unknown" for row in historical["features"])
    features = {row["feature_id"]: row for row in result["features"]}
    assert features["goal"]["value"] == {"kind": "find_minimum", "symbol": "a"}
    assert features["quantifier"]["value"] == "∀"
    assert features["domain"]["value"]["expression"] == "(0,1/2]"
    assert features["degree_in_bound"]["value"]["degree"] == 2
    stage_two = run_stage_two(output, result, provider=forbidden, unsupported_root=output / "unsupported")
    record_run(output / "stage-two-1", output / "recording")
    replay = replay_run(output / "recording", output / "replay")
    lesson = present_lesson(stage_two, result["features"], result["candidate"]["original_text"],
                            candidate=result["candidate"])
    debug_report(output, result, evidence, lesson)
    report = str(output / "index.html")
    assert stage_two["status"] == lesson["status"] == "completed", report
    assert replay["replay_comparison"]["ok"], report
    assert stage_two["llm"]["new_semantic_calls"] == stage_two["llm"]["new_network_attempts"] == 0
    (goal,) = stage_two["goals"]
    assert goal["status"] == "resolved" and goal["primary"] == "type-quantified-quadratic", report
    assert goal["primary_source"] == "program"
    (presented,) = lesson["goals"]
    rows = {row["kind"]: row for row in presented["d1"]["rows"]}
    assert set(rows) == {"quantifier", "relation", "goal"}, report
    (correct_goal,) = [option["text"] for option in rows["goal"]["options"] if option["correct"]]
    assert "最小值" in correct_goal and "$a$" in correct_goal, report
    assert "最小值" in presented["d1"]["summary"], report
    assert any(option["role"] == "primary" for option in presented["d2"]), report
    print(f"Parameter-extremum recorded integration report: {report}")
