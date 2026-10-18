"""Offline replay stays within its directory and exposes decision regressions."""

import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from shuxueshuo_server.graph_lesson.stage_two import cli, recognition, verification
from shuxueshuo_server.graph_lesson.stage_two.runner import (
    record_run,
    replay_run,
    run_result,
)

FIXTURES = Path(__file__).parent / "fixtures"
Q01 = FIXTURES / "graph-guided-stage-two/recorded/q01-20261018-01"


def recorded_input(case):
    return json.loads((FIXTURES / "graph-guided-stage-one/recorded/live-v2-20261017-02"
                       / case / "sample-01/stage-one-result.json").read_text())


def recording(tmp_path, case):
    source, target = tmp_path / "source", tmp_path / "recording"
    run_result(recorded_input(case), source, unsupported_root=source / "pending")
    return record_run(source, target)


def test_unsupported_replay_writes_only_within_output(tmp_path):
    source = recording(tmp_path, "q11")
    before = {p.name for p in tmp_path.iterdir()}
    output = tmp_path / "replay"
    result = replay_run(source, output)
    assert {p.name for p in tmp_path.iterdir()} == before | {"replay"}
    assert Path(result["unsupported_directory"]).is_relative_to(output)
    unsupported = next(g for g in result["goals"] if g["status"] == "unsupported")
    assert (output / unsupported["unsupported_record"]).is_file()
    assert result["replay_comparison"]["ok"]


def test_multimatch_becoming_unique_is_reported_and_survives_rerecording(tmp_path, monkeypatch):
    monkeypatch.setattr(verification, "verify_amgm", lambda *args, **kwargs: {
        "status": "unknown", "reason": "test.changed_verifier", "steps": [], "input_refs": [],
    })
    result = replay_run(Q01, tmp_path / "replay")
    assert result["status"] == "completed"  # Calculation succeeded; comparison did not.
    assert result["goals"][0]["primary_source"] == "program"
    assert result["goals"][0]["primary"] == "type-quantified-quadratic"
    assert result["llm"]["new_network_attempts"] == 0
    comparison = result["replay_comparison"]
    assert not comparison["ok"]
    assert {d["field"] for d in comparison["differences"]} == {"primary_source", "supported"}
    assert "与历史结论不一致，回放验收未通过" in (tmp_path / "replay/index.html").read_text()
    record_run(tmp_path / "replay", tmp_path / "recorded-replay")
    again = replay_run(tmp_path / "recorded-replay", tmp_path / "second-replay")
    assert again["replay_comparison"] == comparison


@pytest.mark.parametrize("change", ["unsupported", "new_primary"])
def test_program_only_replay_compares_goal_status_and_primary(tmp_path, monkeypatch, change):
    source = recording(tmp_path, "q02")
    catalog = []
    if change == "new_primary":
        alternate = deepcopy(next(c for c in recognition.load_contracts()
                                  if c["type_id"] == "type-quantified-quadratic"))
        alternate["type_id"] = "test-changed-primary"
        catalog = [alternate]
    monkeypatch.setattr(recognition, "load_contracts", lambda: catalog)
    result = replay_run(source, tmp_path / "replay")
    assert result["status"] == "completed"
    differences = result["replay_comparison"]["differences"]
    assert not result["replay_comparison"]["ok"]
    assert any(d["target_ref"] == "/root/goals/0" and d["field"] == "primary" for d in differences)
    if change == "unsupported":
        assert any(d["field"] == "status" and d["actual"] == "unsupported" for d in differences)
    else:
        assert any(d["field"] == "primary" and d["actual"] == "test-changed-primary" for d in differences)


@pytest.mark.parametrize("changed", [False, True])
def test_cli_replay_exit_status_includes_decision_comparison(tmp_path, monkeypatch, capsys, changed):
    source = recording(tmp_path, "q02")
    if changed:
        monkeypatch.setattr(recognition, "load_contracts", list)
    monkeypatch.setattr(sys, "argv", ["stage-two", "replay", "--recording", str(source),
                                     "--output", str(tmp_path / "replay")])
    with pytest.raises(SystemExit) as exited:
        cli.main()
    assert exited.value.code == int(changed)
    printed = json.loads(capsys.readouterr().out)
    assert printed["status"] == "completed"
    assert printed["replay_comparison"]["ok"] is not changed
