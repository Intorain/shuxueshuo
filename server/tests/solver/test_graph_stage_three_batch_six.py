"""Extremum closure over real Q13 evidence and explicitly constructed variants.

Only Q13 uses student_upload admission and retained model review. Variants run
the actual selection/execution core directly; they never manufacture reviewed
images, source_reviewed flags or gold acceptance. Set
GRAPH_STAGE_THREE_BATCH_SIX_RUN_DIR to retain the reports and original evidence.
"""

import os
import shutil
from copy import deepcopy
from html import escape
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_one.features import extract_features
from shuxueshuo_server.graph_lesson.stage_three import report, runner
from shuxueshuo_server.graph_lesson.stage_three.context import build_context
from shuxueshuo_server.graph_lesson.stage_three.events import EventStore
from shuxueshuo_server.graph_lesson.stage_three.selection import evaluate_goal
from shuxueshuo_server.graph_lesson.stage_three.trajectory import (
    decode_value,
    encode_value,
)
from shuxueshuo_server.graph_lesson.stage_two.contracts import targets
from shuxueshuo_server.problem_understanding.identity import revision
from shuxueshuo_server.problem_understanding.review_contract import pointer
from shuxueshuo_server.problem_understanding.workflow_ledger import save
from shuxueshuo_server.search.lesson import run_stage_two
from tests.search.test_parameter_extremum_recorded import (
    RECORDING,
    revalidate_recording,
)
from tests.solver import test_graph_stage_three_batch_five as batch_five
from tests.solver.graph_stage_three_faults import _offline_worker, offline_dispatch
from tests.solver.test_graph_stage_three_batch_four import _gold_set
from tests.solver.test_graph_stage_three_execution import (
    Interrupted,
    events,
    read,
    store,
)
from tests.solver.test_graph_stage_three_recorded import (
    forbid_live_providers_and_network,  # noqa: F401 — shared autouse fixture
)

GOLD = Path(__file__).parent / "fixtures/graph-guided-stage-three/extrema-answers.gold.json"
TARGET = "/root/goals/0"


def cases():
    return read(GOLD)["cases"]


@pytest.fixture
def output_root(tmp_path):
    configured = os.getenv("GRAPH_STAGE_THREE_BATCH_SIX_RUN_DIR")
    output = Path(configured) if configured else tmp_path
    output.mkdir(parents=True, exist_ok=True)
    return output


def _forbidden(*args, **kwargs):
    raise AssertionError("batch-six integration must never construct a live provider")


def _wrong_closure(payload, fault):
    """Corrupt the proposal inside the worker, before independent closure checks."""
    with _offline_worker():
        from shuxueshuo_server.graph_lesson.stage_three import calculations

        if payload["operation"] != "finish":
            return calculations.dispatch(payload)
        original = calculations.finalize_goal_with_evidence

        def wrong_answer(goal, feasible):
            answer, evidence = original(goal, feasible)
            if fault == "value":
                # Correct-looking display text cannot hide an incorrect exact value.
                answer["value"]["exact"] = encode_value(sp.Rational(5, 2))
            elif fault == "kind":
                answer["kind"] = "find_maximum"
            elif fault == "shape":
                answer["bound"] = deepcopy(answer["value"])
            elif fault == "exact":
                answer["value"]["exact"] = {"$type": "unknown"}
            else:
                answer["status"] = "not_attained"
                answer["bound"] = answer.pop("value")
            return answer, evidence

        with patch.object(calculations, "finalize_goal_with_evidence", wrong_answer):
            return calculations.dispatch(payload)


def wrong_closure_value(payload):
    return _wrong_closure(payload, "value")


def wrong_closure_kind(payload):
    return _wrong_closure(payload, "kind")


def wrong_closure_attainment(payload):
    return _wrong_closure(payload, "attainment")


def wrong_closure_shape(payload):
    return _wrong_closure(payload, "shape")


def wrong_closure_exact(payload):
    return _wrong_closure(payload, "exact")


def _source(directory):
    """Revalidate the real source; no stored passed or reviewed flag is copied."""
    directory.mkdir(parents=True, exist_ok=False)
    shutil.copytree(RECORDING, directory / "recorded-source")
    shutil.copyfile(RECORDING / "fixture/source.png", directory / "question.png")
    stage_one, evidence = revalidate_recording()
    save(directory / "revalidated-stage-one.json", stage_one)
    save(directory / "revalidation.json", evidence)
    assert evidence["historical_semantic_calls"] == evidence["historical_network_attempts"] == 2
    assert evidence["new_semantic_calls"] == evidence["new_network_attempts"] == 0
    assert stage_one["candidate"]["root"]["goals"] == [{"kind": "find_minimum", "expression": "a"}]
    stage_two = run_stage_two(directory, stage_one, provider=_forbidden, unsupported_root=directory / "unsupported")
    assert stage_two["status"] == "completed" and not any(stage_two["llm"].values())
    upstream = directory / "stage-two-1/stage-two-result.json"
    stage_one_input = read(upstream.parent / "input.json")
    assert stage_one_input["statuses"]["admission"] == "student_upload"
    assert "passed" not in stage_one_input["statuses"] and "evaluation" not in stage_one_input["statuses"]
    return upstream, stage_one, evidence


def _index(root):
    links = []
    for path in sorted(root.rglob("index.html")):
        if path == root / "index.html" or "recorded-source" in path.parts:
            continue
        relative = str(path.relative_to(root))
        links.append('<li><a href="' + escape(relative, quote=True) + '">' + escape(relative) + '</a></li>')
    body = ('<h1>批次 6：参数最值与目标收束</h1>'
            '<p>Q13 使用原始真实识图和复核录制；变式明确标记 constructed_non_llm，直接运行数学核心。'
            '本轮新增 LLM 与网络调用均为 0。</p><ul>' + ''.join(links) + '</ul>')
    evidence = root / "q13-student-upload"
    if (evidence / "revalidation.json").is_file():
        body += ('<h2>Q13 原始录制与本轮重验证</h2>'
                 '<p>以下为同一份真实题图的历史两次模型调用（提取、复核）。本轮仅离线重验，不新增调用。</p><ul>')
        for label, name in (
            ("原始题图", "question.png"), ("重验证收据", "revalidation.json"),
            ("重算题意与特征", "revalidated-stage-one.json"),
            ("原始录制清单", "recorded-source/recording.json"),
            ("原始提取响应", "recorded-source/workflow/calls/01-extract/response.json"),
            ("原始复核响应", "recorded-source/workflow/calls/02-review/response.json"),
            ("原始调用账本", "recorded-source/workflow/ledger.json"),
        ):
            relative = (evidence / name).relative_to(root)
            body += f'<li><a href="{escape(str(relative), quote=True)}">{label}</a></li>'
        body += '</ul>' + report._details("Q13 本轮重验证证据", read(evidence / "revalidation.json"))
    (root / "index.html").write_text(report._page("阶段③批次6验收", body), encoding="utf-8")


def _assert_answer(answer, expected):
    assert answer["kind"] == expected["kind"] and answer["status"] == expected["status"], answer
    for key in ("value", "bound"):
        if key not in expected:
            assert key not in answer
            continue
        assert {"expression", "latex", "exact"} <= answer[key].keys()
        assert decode_value(answer[key]["exact"]) == sp.sympify(expected[key])
        assert sp.sympify(answer[key]["expression"]) == sp.sympify(expected[key])
        assert isinstance(answer[key]["latex"], str) and answer[key]["latex"]
    assert "set" not in answer, "An extremum target must not be rewritten into a range target."


def _assert_routes(goal, output, expected):
    assert goal["status"] == "solved", goal
    assert goal["goal"] == expected["goal"]
    _assert_answer(goal["answer"], expected["answer"])
    routes = {route["route_id"]: route for route in goal["routes"]}
    assert set(routes) == set(expected["routes"])
    mathematical_set = _gold_set(expected)
    for route in routes.values():
        assert route["status"] == "verified", route
        assert decode_value(route["feasible_set_exact"]) == mathematical_set
        _assert_answer(route["answer"], expected["answer"])
        trajectory = read(output / route["trajectory"])
        finalization = trajectory["finalization"]
        closure, = [record for record in finalization if record["capability"] == "finalize_goal"]
        _assert_answer(closure["answer"], expected["answer"])
        assert closure.get("postconditions") and all(check["passed"] is True for check in closure["postconditions"])
        cards = [read(output / reference["file"]) for reference in trajectory["math_steps"]]
        assert all(card["local_check"] == "passed" for card in cards)
        assert all(card["source_refs"] and all(pointer(trajectory, ref) for ref in card["source_refs"])
                   for card in cards)
        boundary, = [card for card in cards if card["display_unit"] == "boundary"]
        goal_cards = [card for card in cards if any(
            pointer(trajectory, ref).get("capability") == "finalize_goal" for ref in card["source_refs"])]
        assert len(goal_cards) == 1 and goal_cards[0]["ordinal"] == boundary["ordinal"] + 1
        assert goal_cards[0]["display_unit"] == "goal_finalization"
        assert goal_cards[0] == cards[-1]
        assert decode_value(goal_cards[0]["before"][0]["exact"]) == mathematical_set
        assert "function-range-extrema#attainability" in goal_cards[0]["used_basis"]
        assert any(check["kind"] == "goal_answer_matches_feasible_set" for check in closure["postconditions"])
        assert "*" not in goal_cards[0]["explanation"] and "sqrt(" not in goal_cards[0]["explanation"]
    return routes


def _constructed(case, output):
    """Run real mathematics without constructing image-admission evidence."""
    output.mkdir(parents=True, exist_ok=False)
    candidate = {"original_text": "构造变式：" + "；".join(case["facts"]),
                 "root": {"facts": deepcopy(case["facts"]), "goals": [deepcopy(case["goal"])]}}
    feature_result = extract_features(candidate)
    assert feature_result["ok"], feature_result
    features = feature_result["features"]
    save(output / "candidate.json", candidate)
    save(output / "features.json", feature_result)
    save(output / "provenance.json", {"mode": "constructed_non_llm", "image_admission": "not_run",
                                     "source_review": "not_run", "new_semantic_calls": 0, "new_network_attempts": 0})
    target, = targets(candidate)
    goal = {**target, "primary": "type-quantified-quadratic", "routes": [], "route_status": [],
            "answer": None, "feasible_set": None, "diagnostics": [], "features": features,
            "constraint_context": build_context(candidate, TARGET)}
    goal.update(evaluate_goal(candidate, TARGET, features, "type-quantified-quadratic"))
    revisions = runner.fingerprint()
    identity = {"run_id": uuid4().hex, "lesson_version": revision({"candidate": candidate, "implementation": revisions}),
                "input_sha256": revision(candidate), "revisions": revisions}
    durable = EventStore(output, identity, create=True)
    runner._execute_goal(candidate, goal, output / "goals/goal-001", durable, milestone="6",
                         hooks={"calculation_dispatch": offline_dispatch},
                         solve_budget_seconds=10, verification_budget_seconds=20)
    snapshot = durable.export()
    value = {"mode": "constructed_non_llm", "candidate": candidate, "goal": goal,
             "events": {"last_seq": snapshot["last_seq"]}, "llm": runner.zero_calls()}
    save(output / "constructed-result.json", value)
    body = ('<h1>构造变式：直接数学核心验收</h1><p>未运行图片提取或来源复核；没有 source_reviewed、passed 等准入声明。'
            '该用例仅检验特征、方法选择、实际求解、独立验证与目标收束。本次 LLM 调用为 0。</p>')
    body += report._details("构造题意", candidate) + report._details("结果", value)
    body += report._route_details(output, goal, durable.events())
    (output / "index.html").write_text(report._page("参数最值构造变式", body), encoding="utf-8")
    return goal


def test_real_q13_recording_keeps_minimum_goal_and_completes_both_routes(output_root):
    directory = output_root / "q13-student-upload"
    source, stage_one, evidence = _source(directory)
    output = directory / "stage-three"
    result = runner.run_sample(source, output, hooks={"calculation_dispatch": offline_dispatch})
    assert result["milestone"] == "6" and result["status"] == "completed"
    assert result["input_validation"]["ok"] and not any(result["llm"].values())
    assert read(output / "input.json")["admission"] == "student_upload"
    input_one = read(output / "stage-one-input.json")
    assert input_one["candidate"] == stage_one["candidate"]
    assert "passed" not in input_one["statuses"] and "evaluation" not in input_one["statuses"]
    goal, = result["goals"]
    routes = _assert_routes(goal, output, cases()["q13"])
    assert set(routes) == {"interval", "extremum"}
    handoffs = store(output).snapshot()["handoffs"]
    assert {task["route_id"] for task in handoffs} == set(routes)
    assert (output / "source.png").read_bytes() == (RECORDING / "fixture/source.png").read_bytes()
    assert evidence["mode"] == "offline_replay"
    _index(output_root)
    print(f"Q13 real-recording extremum report: {output / 'index.html'}")


@pytest.mark.parametrize("name", ["maximum", "strict_minimum", "unbounded_maximum", "empty_minimum"])
def test_constructed_extremum_variants_preserve_full_sets_and_distinct_answer_statuses(output_root, name):
    output = output_root / "constructed" / name
    expected = cases()[name]
    goal = _constructed(expected, output)
    _assert_routes(goal, output, expected)
    provenance = read(output / "provenance.json")
    assert provenance["mode"] == "constructed_non_llm" and provenance["source_review"] == "not_run"
    assert not (output / "stage-one-input.json").exists()
    _index(output_root)


@pytest.mark.parametrize("route_id", ["interval", "extremum"])
@pytest.mark.parametrize("position", ["before_commit", "after_commit"])
def test_goal_finalization_commit_resumes_without_duplicate_closure_or_early_handoff(output_root, route_id, position):
    directory = output_root / "recovery" / f"{route_id}-{position}"
    source, _, _ = _source(directory)
    output = directory / "stage-three"
    stopped = []

    def stop_on_goal_finalization(state, durable):
        if stopped or state["route_id"] != route_id or not state.get("goal_finalized"):
            return
        assert state["status"] == "method_complete"
        assert not any(task["route_id"] == route_id for task in durable.snapshot()["handoffs"])
        stopped.append(deepcopy(state))
        raise Interrupted()

    with pytest.raises(Interrupted):
        runner.run_sample(source, output, hooks={position: stop_on_goal_finalization,
                                                 "calculation_dispatch": offline_dispatch})
    assert stopped
    original_finish, = [operation for operation in stopped[0]["verification_timing"]
                        if operation["operation"] == "goal_finalize_and_consistency"]
    prefix_events = events(output)
    prefix_cards = store(output).snapshot()["math_steps"]
    result = runner.resume_sample(output, hooks={"calculation_dispatch": offline_dispatch})
    goal, = result["goals"]
    _assert_routes(goal, output, cases()["q13"])
    snapshot = store(output).snapshot()
    current = {card["step_id"]: card for card in snapshot["math_steps"]}
    assert len(current) == len(snapshot["math_steps"])
    assert all(current[card["step_id"]] == card for card in prefix_cards)
    assert all(current[card["step_id"]] == card for card in stopped[0]["fragments"])
    assert events(output)[:len(prefix_events)] == prefix_events
    assert {task["route_id"] for task in snapshot["handoffs"]} == {"interval", "extremum"}
    sequence = events(output)
    assert [event["seq"] for event in sequence] == list(range(1, len(sequence) + 1))
    resumed_state = store(output).checkpoint(TARGET, route_id)["driver_state"]
    resumed_finish, = [operation for operation in resumed_state["verification_timing"]
                       if operation["operation"] == "goal_finalize_and_consistency"]
    assert resumed_finish["attempt_id"] == original_finish["attempt_id"]
    for identifier in ("interval", "extremum"):
        closure, = [event for event in sequence if event["route_id"] == identifier
                    and event["type"] == "solver.step_completed"
                    and event["payload"]["operation"] == "finalize_goal"]
        handoff, = [event for event in sequence if event["route_id"] == identifier
                    and event["payload"].get("kind") == "route_completion"]
        assert closure["payload"]["status"] == "method_complete" and closure["seq"] < handoff["seq"]
    runner.resume_sample(output, hooks={"calculation_dispatch": offline_dispatch})
    assert events(output) == sequence
    _index(output_root)


@pytest.mark.parametrize("name,dispatch", [
    ("value", wrong_closure_value), ("kind", wrong_closure_kind), ("attainment", wrong_closure_attainment),
    ("shape", wrong_closure_shape), ("exact", wrong_closure_exact),
])
def test_wrong_goal_closure_is_rejected_before_any_goal_card_or_handoff(output_root, name, dispatch):
    directory = output_root / "rejected-closures" / name
    source, _, _ = _source(directory)
    output = directory / "stage-three"
    result = runner.run_sample(source, output, hooks={"calculation_dispatch": dispatch})
    assert not any(result["llm"].values())
    goal, = result["goals"]
    assert goal["goal"] == cases()["q13"]["goal"]
    assert goal["status"] == "no_verified_route" and goal["answer"] is None
    assert {route["route_id"] for route in goal["routes"]} == {"interval", "extremum"}
    snapshot = store(output).snapshot()
    assert not snapshot["handoffs"]
    assert not any(event["payload"].get("kind") == "route_completion" for event in events(output))
    for route in goal["routes"]:
        assert route["status"] == "math_failed" and route["answer"] is None
        assert any(row["code"] == "goal_finalize.answer_mismatch" for row in route["diagnostics"])
        trajectory = read(output / route["trajectory"])
        assert not any(record["capability"] == "finalize_goal" for record in trajectory["finalization"])
        cards = [read(output / ref["file"]) for ref in trajectory["math_steps"]]
        assert cards and cards[-1]["display_unit"] == "boundary"
        assert all(card["local_check"] == "passed" for card in cards)
        assert not any(card["display_unit"] == "goal_finalization" for card in cards)
        state = store(output).checkpoint(TARGET, route["route_id"])["driver_state"]
        assert not state.get("goal_finalized") and not state.get("verified_result")
    _index(output_root)


def test_all_22_original_recordings_keep_batch_five_math_and_source_assertions(output_root, tmp_path, monkeypatch):
    """Reuse the preceding acceptance contract; only the execution milestone changes."""
    output = output_root / "original-recordings"
    monkeypatch.setenv("GRAPH_STAGE_THREE_BATCH_FIVE_RUN_DIR", str(output))
    run_batch = runner.run_recorded_batch
    run_sample = runner.run_sample

    def current_milestone(*args, **kwargs):
        kwargs["milestone"] = "6"
        return run_batch(*args, **kwargs)

    def offline_sample(*args, **kwargs):
        kwargs["hooks"] = {**(kwargs.get("hooks") or {}), "calculation_dispatch": offline_dispatch}
        return run_sample(*args, **kwargs)

    monkeypatch.setattr(runner, "run_recorded_batch", current_milestone)
    monkeypatch.setattr(runner, "run_sample", offline_sample)
    batch_five.test_all_recordings_complete_all_authored_routes_and_keep_extended_answers(tmp_path)
    assert read(output / "batch-summary.json")["milestone"] == "6"
    _index(output_root)
