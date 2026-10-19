"""Both 1b milestones run all retained evidence with no live model calls."""

import json
import os
from pathlib import Path

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_three.runner import run_recorded_batch
from shuxueshuo_server.graph_lesson.stage_three.trajectory import decode_value
from tests.solver.test_graph_stage_three_recorded import (
    SELECTION_GOLD,
    STAGE_ONE_BATCH,
    forbid_live_providers_and_network,  # noqa: F401 — shared autouse fixture
)


@pytest.mark.parametrize("milestone", ["1b-1", "1b"])
def test_all_recordings_keep_selection_and_execute_supported_routes(tmp_path, milestone):
    configured = os.getenv("GRAPH_STAGE_THREE_1B_RUN_DIR")
    output = (Path(configured) if configured else tmp_path) / milestone
    summary = run_recorded_batch(STAGE_ONE_BATCH, output, milestone=milestone)
    assert summary["completed"] and len(summary["results"]) == 22
    assert sum(row["eligible"] for row in summary["results"]) == 24
    assert sum(row["skipped"] for row in summary["results"]) == 2
    gold = json.loads(SELECTION_GOLD.read_text())
    answer_gold = json.loads((SELECTION_GOLD.parent / "answers.gold.json").read_text())["cases"]["q01"]
    def endpoint(text):
        return {"-oo": -sp.oo, "oo": sp.oo}.get(text) if text in ("-oo", "oo") else sp.Rational(text)
    expected_answer = sp.Union(*[sp.Interval(endpoint(part["lower"]), endpoint(part["upper"]),
        left_open=not part["left_closed"], right_open=not part["right_closed"])
        for part in answer_gold["feasible_set"]["intervals"]])
    for row in summary["results"]:
        result = json.loads((output / row["sample_dir"] / "stage-three-result.json").read_text())
        assert all(value == 0 for value in result["llm"].values())
        for goal in result["goals"]:
            if goal["status"] == "skipped":
                continue
            expected, = [g for g in gold["cases"][row["case_id"]] if g["target_ref"] == goal["target_ref"]]
            assert goal["d3"]["expected_answer"]["cell"] == expected["cell"]
            for branch in goal["selection"]["branches"]:
                for key in ("trigger", "applicability", "recommendation"):
                    assert branch[key] == expected["branches"][branch["branch"]][key]
            if row["case_id"] == "q01":
                assert goal["status"] == "solved"
                assert all(decode_value(route["feasible_set_exact"]) == expected_answer for route in goal["routes"])
                assert {r["route_id"] for r in goal["routes"] if r["status"] == "verified"} == (
                    {"discriminant"} if milestone == "1b-1" else {"discriminant", "extremum"}
                )
                assert result["events"]["last_seq"] > 0
    assert (output / "index.html").is_file()
