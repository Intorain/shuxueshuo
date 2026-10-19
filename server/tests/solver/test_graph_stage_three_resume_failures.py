"""Target failures during resume revoke every previously published answer."""

import json

import pytest

from shuxueshuo_server.graph_lesson.stage_three import runner
from shuxueshuo_server.graph_lesson.stage_three.events import EventStore
from tests.solver.test_graph_stage_three_contracts import upstream

TARGET = "/root/goals/0"


def read(path):
    return json.loads(path.read_text())


def events(output):
    return [json.loads(line) for line in (output / "events.jsonl").read_text().splitlines()]


@pytest.mark.parametrize("phase", ["build_context", "evaluate_goal"])
def test_resume_preexecution_failure_revokes_completions_and_is_idempotent(tmp_path, monkeypatch, phase):
    output = tmp_path / "out"
    initial = runner.run_sample(upstream(tmp_path), output)
    assert initial["goals"][0]["status"] == "solved"
    before = read(output / "checkpoint.json")
    assert {task["route_id"] for task in before["handoffs"]} == {"discriminant", "extremum"}
    assert all(task["available"] for task in before["handoffs"])
    completion_ids = [event["event_id"] for event in events(output)
                      if event["payload"].get("kind") == "route_completion"]

    def broken(*args, **kwargs):
        raise KeyError("injected resumed target failure")

    monkeypatch.setattr(runner, phase, broken)
    result = runner.resume_sample(output)
    assert result["status"] == "failed"
    goal = result["goals"][0]
    assert goal["status"] == "execution_error" and goal["answer"] is None
    assert goal["d3"] == initial["goals"][0]["d3"]
    assert goal["d4"] == initial["goals"][0]["d4"]
    assert goal["diagnostics"][0]["phase"] == phase
    assert goal["diagnostics"][0]["exception_type"] == "KeyError"
    assert "injected resumed target failure" in goal["diagnostics"][0]["traceback"]
    snapshot = read(output / "checkpoint.json")
    assert snapshot["goals"][TARGET] == {
        "status": "no_verified_route", "reason": "execution.target_error", "available": False,
    }
    assert snapshot["math_steps"] == before["math_steps"]
    assert snapshot["checkpoints"] == before["checkpoints"]
    for task in snapshot["handoffs"]:
        assert task["available"] is False and task["status"] == "cancelled"
        exported = read(output / "goals/goal-001/handoff" / (task["route_id"] + ".json"))
        assert exported == task
    committed = events(output)
    assert committed[-1]["type"] == "lesson.goal_status"
    assert committed[-1]["payload"]["available"] is False
    assert [event["event_id"] for event in committed if event["payload"].get("kind") == "route_completion"] == completion_ids
    assert (output / "stage-three-result.json").is_file() and (output / "index.html").is_file()

    repeated = runner.resume_sample(output)
    assert repeated["status"] == "failed"
    assert events(output) == committed
    assert read(output / "checkpoint.json") == snapshot


@pytest.mark.parametrize("phase", ["build_context", "evaluate_goal"])
def test_initial_target_failure_publishes_unavailable_state_with_report(tmp_path, monkeypatch, phase):
    def broken(*args, **kwargs):
        raise ValueError("injected target failure")

    monkeypatch.setattr(runner, phase, broken)
    output = tmp_path / "out"
    result = runner.run_sample(upstream(tmp_path), output)
    assert result["status"] == "failed"
    assert result["goals"][0]["status"] == "execution_error"
    snapshot = read(output / "checkpoint.json")
    assert snapshot["goals"][TARGET]["available"] is False
    assert snapshot["handoffs"] == [] and snapshot["math_steps"] == []
    assert len(events(output)) == 1
    assert (output / "index.html").is_file()


def test_resume_failure_preserves_published_selection_after_event_retention(tmp_path, monkeypatch):
    output = tmp_path / "out"
    initial = runner.run_sample(upstream(tmp_path), output, milestone="1b-1")
    snapshot = read(output / "checkpoint.json")
    store = EventStore(output, snapshot)
    store.prune_events(snapshot["last_seq"])

    def broken(*args, **kwargs):
        raise KeyError("context unavailable")

    monkeypatch.setattr(runner, "build_context", broken)
    resumed = runner.resume_sample(output)
    goal = resumed["goals"][0]
    assert goal["status"] == "execution_error" and goal["answer"] is None
    assert goal["d3"] == initial["goals"][0]["d3"]
    assert goal["d4"] == initial["goals"][0]["d4"]
    assert read(output / "goals/goal-001/d3.json") == goal["d3"]
    assert read(output / "goals/goal-001/d4.json") == goal["d4"]
    assert store.snapshot()["goals"][TARGET]["available"] is False
