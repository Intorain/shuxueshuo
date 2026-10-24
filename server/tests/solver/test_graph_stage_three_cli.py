"""Public CLI admission, report regeneration, and immutable output directories."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import text

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


def test_cli_child_inherits_the_isolated_postgres_schema(tmp_path, stage_three_storage):
    output = tmp_path / "child-run"
    environment = os.environ.copy()
    assert environment["PRODUCT_TEST_DATA_DIR"] and environment["PRODUCT_TEST_INSTANCE"]
    assert environment["PRODUCT_TEST_SCHEMA"].startswith("test_stage_three_")
    completed = subprocess.run(
        [sys.executable, "-m", "shuxueshuo_server.graph_lesson.stage_three.cli", "run", "--input", str(SOURCE),
         "--output", str(output), "--milestone", "1a"],
        cwd=Path(__file__).parents[2], env=environment, capture_output=True, text=True, timeout=60, check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert json.loads(completed.stdout)["status"] == "completed"
    run = json.loads((output / "run.json").read_text())
    with stage_three_storage.connect() as connection:
        assert connection.scalar(text("SELECT current_schema()")) == environment["PRODUCT_TEST_SCHEMA"]
        assert connection.scalar(text("SELECT run_id FROM lesson_runs WHERE run_id=:run_id"), {"run_id": run["run_id"]}) == run["run_id"]
    assert not list(output.rglob("*.sqlite*"))
