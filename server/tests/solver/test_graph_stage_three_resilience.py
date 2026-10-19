"""Failures stay inspectable and retained inputs are portable replay sources."""

import json
import shutil
from pathlib import Path

import pytest

from shuxueshuo_server.graph_lesson.stage_three import runner
from shuxueshuo_server.graph_lesson.stage_three.cli import main
from shuxueshuo_server.graph_lesson.stage_three.contracts import (
    load_input,
    validate_result,
)
from shuxueshuo_server.graph_lesson.stage_two.runner import run_result
from tests.solver.test_graph_stage_three_report import assert_self_contained_report

RECORDED = Path(__file__).parent / "fixtures/graph-guided-stage-one/recorded/live-v2-20261017-02"
MANIFEST_CONTRACT = "graph-stage-three-input-manifest/v1"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def upstream(tmp_path, case="q10", *, admission="acceptance"):
    value = read(RECORDED / case / "sample-01/stage-one-result.json")
    if admission == "student_upload":
        value["statuses"].update(admission=admission)
        value["statuses"].pop("passed", None)
        value["statuses"].pop("evaluation", None)
    output = tmp_path / "stage-two"
    result = run_result(value, output, input_reference="historical/missing.json",
                        unsupported_root=output / "unsupported", admission=admission)
    assert result["status"] == "completed"
    return output / "stage-two-result.json"


@pytest.mark.parametrize("phase", ["build_context", "evaluate_goal"])
@pytest.mark.parametrize("error", [KeyError, TypeError, ValueError])
def test_one_goal_exception_keeps_other_goal_and_debug_artifacts(tmp_path, monkeypatch, phase, error):
    source = upstream(tmp_path)
    original = getattr(runner, phase)
    broken_ref = "/root/children/0/goals/0"

    def fail_one(candidate, ref, *args, **kwargs):
        if ref == broken_ref:
            raise error("injected goal failure")
        return original(candidate, ref, *args, **kwargs)

    monkeypatch.setattr(runner, phase, fail_one)
    output = tmp_path / "stage-three"
    result = runner.run_sample(source, output, milestone="1a")
    validate_result(result)
    assert result["status"] == "partial"
    failed, continued = result["goals"]
    assert failed["status"] == "execution_error"
    assert failed["d3"] is failed["d4"] is failed["selection"] is None
    assert failed["routes"] == []
    assert failed["goal"] == read(source)["goals"][0]["goal"]
    assert failed["features"] == [feature for feature in read(source.parent / "input.json")["features"]
                                   if feature["target_ref"] == broken_ref]
    diagnostic, = [item for item in failed["diagnostics"] if item.get("exception_type") == error.__name__]
    assert diagnostic["phase"] == phase
    assert "injected goal failure" in diagnostic["traceback"]
    assert error.__name__ in diagnostic["traceback"]
    assert continued["status"] == "no_verified_route"
    assert continued["selection"] and continued["d3"] and continued["d4"]
    assert read(output / "stage-three-result.json") == result
    for number, goal in enumerate(result["goals"], 1):
        folder = output / "goals" / f"goal-{number:03}"
        assert read(folder / "goal.json") == goal
        assert read(folder / "features.json") == goal["features"]
    html = assert_self_contained_report(output / "index.html")
    assert "injected goal failure" in html
    assert all(goal["target_ref"] in html for goal in result["goals"])


@pytest.mark.parametrize("phase", ["build_context", "evaluate_goal"])
def test_all_admitted_goals_failing_reports_failed_and_cli_returns_one(tmp_path, monkeypatch, capsys, phase):
    source = upstream(tmp_path)

    def fail(*args, **kwargs):
        raise ValueError("all goals failed")

    monkeypatch.setattr(runner, phase, fail)
    output = tmp_path / "stage-three"
    assert main(["run", "--input", str(source), "--output", str(output)]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "failed"
    result = read(output / "stage-three-result.json")
    validate_result(result)
    assert result["status"] == "failed"
    assert len(result["goals"]) == 2
    assert all(goal["status"] == "execution_error" for goal in result["goals"])
    assert_self_contained_report(output / "index.html")


def test_unconfirmed_goal_stays_skipped_without_running_its_context_or_selection(tmp_path, monkeypatch):
    source = upstream(tmp_path, "q11")
    skipped_ref = "/root/children/0/goals/0"
    for phase in ("build_context", "evaluate_goal"):
        original = getattr(runner, phase)

        def fail_unconfirmed(candidate, ref, *args, _original=original, **kwargs):
            if ref == skipped_ref:
                raise AssertionError("unconfirmed target must not enter stage-three evaluation")
            return _original(candidate, ref, *args, **kwargs)

        monkeypatch.setattr(runner, phase, fail_unconfirmed)
    result = runner.run_sample(source, tmp_path / "stage-three", milestone="1a")
    assert result["status"] == "completed"
    skipped, continued = result["goals"]
    assert skipped["status"] == "skipped"
    assert not skipped["routes"] and skipped["d3"] is skipped["d4"] is None
    assert continued["status"] == "no_verified_route"


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("admission", ["acceptance", "student_upload"])
def test_retained_snapshot_replays_after_original_source_is_removed(tmp_path, legacy, admission):
    source = upstream(tmp_path, admission=admission)
    first_directory = tmp_path / "first"
    first = runner.run_sample(source, first_directory, milestone="1a")
    manifest = read(first_directory / "input.json")
    assert manifest["contract"] == MANIFEST_CONTRACT
    if legacy:
        manifest.pop("contract")
        write(first_directory / "input.json", manifest)
    shutil.rmtree(source.parent)
    replay_source = first_directory / "stage-two-input.json"
    admitted = load_input(replay_source)
    assert admitted["ok"], admitted["diagnostics"]
    assert admitted["admission"] == admission
    assert Path(admitted["stage_one_source"]) == first_directory / "stage-one-input.json"
    replay = runner.run_sample(replay_source, tmp_path / "replay", milestone="1a")
    assert replay["status"] == first["status"] == "completed"
    assert replay["goals"] == first["goals"]
    assert replay["stage_one"]["sha256"] == first["stage_one"]["sha256"]
    assert replay["llm"]["new_network_attempts"] == 0


@pytest.mark.parametrize("corruption", [
    "bad_manifest_json", "bad_snapshot_json", "missing_snapshot", "stage_one_hash",
    "stage_two_hash", "stage_one_snapshot_hash", "wrong_contract", "incomplete_legacy",
])
def test_corrupt_retained_input_never_falls_back_to_valid_original(tmp_path, corruption):
    source = upstream(tmp_path)
    stage_two = read(source)
    stage_two["stage_one"]["reference"] = str(source.parent / "input.json")
    write(source, stage_two)
    retained = tmp_path / "retained"
    runner.run_sample(source, retained, milestone="1a")
    manifest_path = retained / "input.json"
    manifest = read(manifest_path)
    snapshot = retained / "stage-one-input.json"
    if corruption == "bad_manifest_json":
        manifest_path.write_text("{", encoding="utf-8")
    elif corruption == "bad_snapshot_json":
        snapshot.write_text("{", encoding="utf-8")
    elif corruption == "missing_snapshot":
        snapshot.unlink()
    elif corruption == "stage_one_hash":
        value = read(snapshot)
        value["run_id"] = "tampered-stage-one"
        write(snapshot, value)
    else:
        if corruption == "stage_two_hash":
            manifest["stage_two"]["sha256"] = "0" * 64
        elif corruption == "stage_one_snapshot_hash":
            manifest["stage_one"]["sha256"] = "0" * 64
        elif corruption == "wrong_contract":
            manifest["contract"] = "graph-stage-three-input-manifest/v999"
        elif corruption == "incomplete_legacy":
            manifest.pop("contract", None)
            manifest["stage_two"].pop("snapshot")
        write(manifest_path, manifest)
    assert load_input(source)["ok"]
    result = runner.run_sample(retained / "stage-two-input.json", tmp_path / "rejected", milestone="1a")
    assert result["status"] == "input_error"
    assert result["input_diagnostics"]
    assert not result["goals"]
    assert_self_contained_report(tmp_path / "rejected/index.html")


@pytest.mark.parametrize("escape", ["relative", "absolute", "symlink"])
@pytest.mark.parametrize("snapshot_kind", ["stage_one", "stage_two"])
def test_manifest_snapshot_cannot_escape_retained_directory(tmp_path, escape, snapshot_kind):
    source = upstream(tmp_path)
    retained = tmp_path / "retained"
    runner.run_sample(source, retained, milestone="1a")
    manifest = read(retained / "input.json")
    snapshot = retained / manifest[snapshot_kind]["snapshot"]
    outside = tmp_path / "outside.json"
    shutil.copyfile(snapshot, outside)
    if escape == "relative":
        manifest[snapshot_kind]["snapshot"] = "../outside.json"
    elif escape == "absolute":
        manifest[snapshot_kind]["snapshot"] = str(outside)
    else:
        alias = retained / "alias.json"
        alias.symlink_to(outside)
        manifest[snapshot_kind]["snapshot"] = "alias.json"
    write(retained / "input.json", manifest)
    result = load_input(retained / "stage-two-input.json")
    assert not result["ok"] and result["diagnostics"]
