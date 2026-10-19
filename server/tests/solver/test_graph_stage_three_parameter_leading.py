"""Admitted parameter-leading quadratics reach independent verification."""

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_three import runner
from shuxueshuo_server.graph_lesson.stage_three.trajectory import decode_value
from tests.solver.test_graph_stage_three_execution import (
    constructed_upstream,
    read,
    simple,
)
from tests.solver.test_graph_stage_three_recorded import (
    forbid_live_providers_and_network,  # noqa: F401 — shared autouse fixture
)


@pytest.mark.parametrize("fact,expected", [
    ("∀x∈ℝ:(a^2+1)*x^2+a>=0", sp.Interval(0, sp.oo)),
    ("∀x∈ℝ:(a^2+1)*x^2+a>0", sp.Interval.open(0, sp.oo)),
    ("∀x∈ℝ:-(a^2+1)*x^2-a<=0", sp.Interval(0, sp.oo)),
])
def test_parameter_leading_coefficient_is_preserved_and_verified(tmp_path, fact, expected):
    output = tmp_path / "run"
    result = runner.run_sample(constructed_upstream(tmp_path, simple(fact)), output, milestone="2")
    assert result["status"] == "completed", result
    goal, = result["goals"]
    route, = [route for route in goal["routes"] if route["route_id"] == "discriminant"]
    assert route["status"] == "verified", route
    assert decode_value(route["feasible_set_exact"]) == expected
    option, = [option for option in goal["d4"]["options"] if option["route_id"] == "discriminant"]
    assert option["route_plan"] == "planned"
    trajectory = read(output / route["trajectory"])
    normal, = [step for step in trajectory["steps"] if step["step"] == "normalize"
               and step["method"] == "method-discriminant"]
    expression = decode_value(normal["calls"][0]["outputs"]["expression"]["exact"])
    x, a = sp.symbols("x a", real=True)
    assert sp.Poly(expression, x).LC() == a**2 + 1
    assert all(value == 0 for value in result["llm"].values())
