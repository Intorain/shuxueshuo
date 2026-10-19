"""Reverify retained model evidence before the entirely offline stage-three run.

Set GRAPH_STAGE_THREE_RUN_DIR to retain the complete 22-sample debug report.
Student-upload evidence is intentionally separate from those acceptance samples.
"""

import json
import os
import shutil
import socket
from pathlib import Path

import pytest

from shuxueshuo_server.graph_lesson.stage_two import selection as stage_two_selection
from shuxueshuo_server.graph_lesson.stage_two.runner import replay_run
from shuxueshuo_server.problem_understanding import batch_smoke
from shuxueshuo_server.problem_understanding.identity import revision
from shuxueshuo_server.problem_understanding.workflow_ledger import save
from shuxueshuo_server.search.lesson import run_stage_two
from shuxueshuo_server.solver.extraction import multimodal_provider
from tests.search.test_parameter_extremum_recorded import (
    RECORDING,
    revalidate_recording,
)

FIXTURES = Path(__file__).parent / "fixtures"
STAGE_ONE_BATCH = FIXTURES / "graph-guided-stage-one/recorded/live-v2-20261017-02"
Q01_SELECTION = FIXTURES / "graph-guided-stage-two/recorded/q01-20261018-02"
SELECTION_GOLD = FIXTURES / "graph-guided-stage-three/selection.gold.json"


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def forbid_live_providers_and_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("stage-three recorded integration must not call a live provider or network")

    monkeypatch.setattr(batch_smoke, "live_provider_factory", forbidden)
    monkeypatch.setattr(stage_two_selection, "live_provider_factory", forbidden)
    monkeypatch.setattr(multimodal_provider, "_default_client_factory", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    return forbidden


def assert_no_new_calls(result):
    assert result["llm"]["new_semantic_calls"] == 0
    assert result["llm"]["new_network_attempts"] == 0


def assert_selection_matches_gold(goal, gold, case):
    expected, = [item for item in gold["cases"][case] if item["target_ref"] == goal["target_ref"]]
    assert goal["d3"]["expected_answer"]["cell"] == expected["cell"]
    actual = {
        branch["branch"]: {key: branch[key] for key in ("trigger", "applicability", "recommendation", "route_plan")}
        for branch in goal["selection"]["branches"]
    }
    assert actual == expected["branches"], (case, goal["target_ref"], actual)


def test_all_22_recordings_reach_selection_with_scoped_gold(tmp_path):
    from shuxueshuo_server.graph_lesson.stage_three.runner import run_recorded_batch

    configured = os.getenv("GRAPH_STAGE_THREE_RUN_DIR")
    output = Path(configured) if configured else tmp_path / "batch"
    summary = run_recorded_batch(STAGE_ONE_BATCH, output)
    assert summary["completed"] and len(summary["results"]) == 22
    assert_no_new_calls(summary)
    assert sum(row["eligible"] for row in summary["results"]) == 24
    assert sum(row["skipped"] for row in summary["results"]) == 2
    gold = read(SELECTION_GOLD)
    seen = set()
    for row in summary["results"]:
        sample = output / row["sample_dir"]
        assert sample.resolve().is_relative_to(output.resolve())
        result = read(sample / "stage-three-result.json")
        assert result["status"] == "completed", str(sample / "index.html")
        assert result["input_validation"]["ok"]
        assert_no_new_calls(result)
        assert_no_new_calls(row)
        for goal in result["goals"]:
            target = goal["target_ref"]
            if row["case_id"] == "q11" and target == "/root/children/0/goals/0":
                assert goal["status"] == "skipped"
                assert goal["d3"] is None and goal["d4"] is None
                continue
            seen.add((row["case_id"], target))
            assert goal["primary"] == "type-quantified-quadratic"
            assert goal["selection"] and goal["d3"] and goal["d4"], str(sample / "index.html")
            assert_selection_matches_gold(goal, gold, row["case_id"])
        assert (sample / "index.html").is_file()
    assert len(seen) == 12
    assert (output / "index.html").is_file()
    print(f"Stage-three recorded integration report: {output / 'index.html'}")


def test_real_q01_selection_provenance_is_admitted_without_new_calls(tmp_path):
    from shuxueshuo_server.graph_lesson.stage_three.runner import run_sample

    configured = os.getenv("GRAPH_STAGE_THREE_RUN_DIR")
    root = Path(configured) if configured else tmp_path
    root.mkdir(parents=True, exist_ok=True)
    replay_directory = root / "selection-replay"
    replay = replay_run(Q01_SELECTION, replay_directory)
    assert replay["replay_comparison"]["ok"]
    assert replay["goals"][0]["primary_source"] == "llm"
    assert replay["historical"]["llm"]["new_semantic_calls"] == 1
    assert_no_new_calls(replay)
    output = replay_directory / "stage-three"
    result = run_sample(replay_directory / "stage-two-result.json", output)
    assert result["status"] == "completed", str(output / "index.html")
    assert result["input_validation"]["ok"]
    assert result["stage_two"]["sha256"] == revision(replay)
    assert_no_new_calls(result)
    goal, = result["goals"]
    assert goal["primary"] == "type-quantified-quadratic"
    assert_selection_matches_gold(goal, read(SELECTION_GOLD), "q01")
    assert (output / "index.html").is_file()


def test_revalidated_student_minimum_recording_preserves_original_goal(tmp_path, forbid_live_providers_and_network):
    from shuxueshuo_server.graph_lesson.stage_three.runner import run_sample

    configured = os.getenv("GRAPH_STAGE_THREE_RUN_DIR")
    root = Path(configured) if configured else tmp_path
    source = root / "student-upload"
    source.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(RECORDING / "fixture/source.png", source / "question.png")
    stage_one, evidence = revalidate_recording()
    assert evidence["historical_semantic_calls"] == evidence["historical_network_attempts"] == 2
    save(source / "revalidated-stage-one.json", stage_one)
    save(source / "revalidation.json", evidence)
    stage_two = run_stage_two(source, stage_one, provider=forbid_live_providers_and_network,
                              unsupported_root=source / "unsupported")
    assert stage_two["status"] == "completed"
    assert stage_two["options"]["admission"] == "student_upload"
    stage_two_directory = source / "stage-two-1"
    admitted_stage_one = read(stage_two_directory / "input.json")
    assert "evaluation" not in admitted_stage_one
    assert "passed" not in admitted_stage_one["statuses"]
    assert admitted_stage_one["candidate"]["root"]["goals"] == [
        {"kind": "find_minimum", "expression": "a"},
    ]
    assert_no_new_calls(stage_two)
    output = source / "stage-three"
    result = run_sample(stage_two_directory / "stage-two-result.json", output)
    assert result["status"] == "completed", str(output / "index.html")
    assert result["input_validation"]["ok"]
    assert result["stage_one"]["sha256"] == revision(admitted_stage_one)
    assert read(output / "input.json")["admission"] == "student_upload"
    assert_no_new_calls(result)
    goal, = result["goals"]
    assert goal["primary"] == "type-quantified-quadratic"
    assert goal["goal"]["kind"] == goal["constraint_context"]["goal"]["kind"] == "find_minimum"
    assert_selection_matches_gold(goal, read(SELECTION_GOLD), "q13")
    assert (output / "index.html").is_file()
