"""Case merging shows its certified input sets and their actual mathematical union."""

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_three import driver, interaction
from shuxueshuo_server.graph_lesson.stage_three.math_values import math_value
from shuxueshuo_server.graph_lesson.stage_three.trajectory import decode_value
from tests.solver.test_graph_stage_three_degenerate_conclusions import validator
from tests.solver.test_graph_stage_three_methods import candidate, finish, start


@pytest.mark.parametrize(
    "fact,expected",
    [
        ("∀t∈ℝ:b*t^2-6*b*t+b+8>=0", sp.Interval(0, 1)),
        ("∀t∈ℝ:(b^2-1)*t^2+t+2>0", None),
        ("∃t∈ℝ:(b^2-1)*t^2+t+2>0", sp.S.Reals),
    ],
)
def test_merge_conclusion_uses_each_verified_case_solution(fact, expected):
    state = finish(start(candidate(fact, "b")))
    assert state["status"] == "method_complete", state["diagnostics"]
    total = driver.export_values(state)["feasible_set"]
    if expected is not None:
        assert total == expected
    card, = [item for item in state["fragments"] if item["display_unit"] == "merge_cases"]
    validator().validate(card)
    seed, = [item for item in state["interaction_seeds"] if item["template"] == "merge_cases"]
    values = decode_value(seed["values"])
    rows = values["case_results"]
    highlight = card["highlight"]
    assert highlight["layout"] == "merge"
    assert highlight["caption"] == "取并集"
    assert highlight["items"] == [
        {"label": "$" + math_value(row["condition"])["latex"] + "$",
         "math": math_value(row["outputs"]["solution"])["latex"]}
        for row in rows
    ]
    assert highlight["result"] == rf"$b \in {math_value(total)['latex']}$"
    union = r" \cup ".join(math_value(row["outputs"]["solution"])["latex"] for row in rows)
    assert card["explanation"] == f"${union} = {math_value(total)['latex']}$。"
    assert "每种情况" not in card["explanation"]
    assert "检查分类" not in card["explanation"]

    if "6*b" in fact:
        assert highlight["items"] == [
            {"label": "$b = 0$", "math": r"\left\{0\right\}"},
            {"label": r"$b \neq 0$", "math": r"\left(0, 1\right]"},
        ]
        chunk, diagnostics = interaction.build_chunk([seed], interaction.load_registry(), {"previous": 0})
        assert chunk["status"] == "interactive", diagnostics
        assert card["title"] == "合并二次项系数为 0 和不为 0 的情况"
        assert chunk["parts"][0]["title"] == card["title"]
    else:
        assert len(highlight["items"]) == 3  # Both zeroes and the nonzero coefficient case survive.
