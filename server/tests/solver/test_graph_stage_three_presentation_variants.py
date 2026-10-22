"""Presentation must preserve supported mathematical routes under role/shape changes."""

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_three import driver
from tests.solver.test_graph_stage_three_methods import candidate, finish, start


@pytest.mark.parametrize("fact,parameter,expected", [
    ("∀x∈[0,1]:a*x^2-2*x+1>=0", "a", sp.Interval(1, sp.oo)),
    ("∀t∈[0,1]:b*t^2-2*t+1>=0", "b", sp.Interval(1, sp.oo)),
    ("∀x∈[0,1]:(a^2+1)*x^2-2*x+1>=0", "a", sp.S.Reals),
])
def test_rational_parameter_axis_keeps_certified_interval_route(fact, parameter, expected):
    state = finish(start(candidate(fact, parameter), "method-interval-extremum"))
    assert state["status"] == "method_complete", state["diagnostics"]
    assert driver.export_values(state)["feasible_set"] == expected
    # A failed optional axis-position presentation must not erase case evidence.
    assert any(card["display_unit"] == "interval_cases" for card in state["fragments"])
    assert any(card["case_path"] for card in state["fragments"])


@pytest.mark.parametrize("fact,parameter", [
    ("∀a∈(-1,1):a*x^2-(a+1)*x+1>0", "x"),
    ("∀t∈(-1,1):t*b^2-(t+1)*b+1>0", "b"),
])
def test_variable_case_presentation_uses_only_its_linear_case_bindings(fact, parameter):
    state = finish(start(candidate(fact, parameter), "method-variable-swap"))
    assert state["status"] == "method_complete", state["diagnostics"]
    assert driver.export_values(state)["feasible_set"] == sp.Interval.Ropen(-1, 1)
    units = {card["display_unit"] for card in state["fragments"]}
    assert {"variable_cases", "case_union"} <= units


@pytest.mark.parametrize("fact,axis", [
    ("∀t∈[0,1]:t^2-2*a*t+1>=0", "a"),
    ("∀t∈[0,1]:t^2+a>=0", "0"),
])
def test_interval_axis_formulas_use_actual_quantified_variable(fact, axis):
    state = finish(start(candidate(fact), "method-interval-extremum"))
    assert state["status"] == "method_complete", state["diagnostics"]
    explanations = "\n".join(card["explanation"] for card in state["fragments"])
    assert f"对称轴为 $t={axis}$" in explanations
    assert "对称轴 $x=" not in explanations
    assert "对称轴为 $x=" not in explanations
    if axis == "0":
        assert "对称轴 $t=0$" in explanations
