"""Public CLI admission, report regeneration, and immutable output directories."""

import json
from pathlib import Path

import pytest

from shuxueshuo_server.graph_lesson.stage_three.cli import main
from shuxueshuo_server.graph_lesson.stage_three.runner import run_sample

FIXTURES = Path(__file__).parent / "fixtures"
SOURCE = FIXTURES / "graph-guided-stage-two/recorded/q01-20261018-02/stage-two-result.json"


def test_cli_accepts_recorded_input_and_regenerates_report(tmp_path, capsys):
    output = tmp_path / "output"
    assert main(["run", "--input", str(SOURCE), "--output", str(output), "--milestone", "1a"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["status"] == "completed" and printed["milestone"] == "1a"
    assert printed["llm"]["new_network_attempts"] == 0
    assert Path(printed["report"]).is_file()
    report = (output / "index.html").read_text()
    (output / "index.html").unlink()
    assert main(["report", "--run", str(output)]) == 0
    assert (output / "index.html").read_text() == report


def test_cli_rejected_input_exits_one_with_debug_result(tmp_path, capsys):
    source = tmp_path / "invalid.json"
    source.write_text('{"broken":')
    output = tmp_path / "output"
    assert main(["run", "--input", str(source), "--output", str(output)]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "input_error"
    result = json.loads((output / "stage-three-result.json").read_text())
    assert not result["goals"] and result["input_diagnostics"]
    assert (output / "index.html").is_file()


def test_existing_output_is_preserved(tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    original = output / "keep.json"
    original.write_text('{"user":"content"}')
    with pytest.raises(FileExistsError):
        main(["run", "--input", str(SOURCE), "--output", str(output)])
    assert original.read_text() == '{"user":"content"}'
    assert list(output.iterdir()) == [original]


def test_identical_inputs_have_identical_decisions_but_distinct_runs(tmp_path):
    first = run_sample(SOURCE, tmp_path / "first", milestone="1a")
    second = run_sample(SOURCE, tmp_path / "second", milestone="1a")
    assert first["run_id"] != second["run_id"]
    assert first["lesson_version"] == second["lesson_version"]
    assert first["goals"] == second["goals"]
    assert first["events"]["last_seq"] == second["events"]["last_seq"] == 0
    assert first["events"]["snapshot"] is second["events"]["snapshot"] is None
