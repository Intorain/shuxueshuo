"""Checked child results and actual decision/public-call provenance for swap."""

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_three import execution_contracts, judgments
from shuxueshuo_server.graph_lesson.stage_three.capabilities import (
    CapabilityGap,
    LocalCheckFailed,
)
from shuxueshuo_server.graph_lesson.stage_three.capabilities.variable_swap import (
    combine_variable_solutions,
    solve_affine_condition,
)

x = sp.Symbol("x", real=True)


def test_public_quadratic_calls_are_guarded_real_submethods():
    contract = execution_contracts.load_contracts()["method-variable-swap"]
    solve = contract["steps"][-1]
    calls = [call for call in solve["calls"] if call["public_ref"] == "quadratic-inequality-solve"]
    assert len(calls) == 2
    for call in calls:
        assert call["capability"] == "submethod"
        assert call["guard"]["equals"] == "quadratic"
        assert call["guard"]["ref"] in ("first_kind", "second_kind")
    extent = contract["steps"][3]
    decision, = extent["judgments"]
    assert {option["id"] for option in decision["options"]} == {"positive", "negative", "zero", "unknown"}
    assert extent["display_units"][0]["after"] == decision["id"]


@pytest.mark.parametrize("expression,kind", [(x*x-1, "quadratic"), (x-1, "affine"),
                                             (sp.S.One, "affine"), (sp.S.Zero, "affine")])
def test_condition_degree_selects_the_actual_method(expression, kind):
    condition = sp.Ge(expression, 0, evaluate=False)
    plan = judgments.endpoint_condition_plan([condition], x)
    assert plan["first_kind"] == kind
    assert plan["second_kind"] == "absent" and plan["second"] is None
    if kind == "quadratic":
        with pytest.raises(CapabilityGap, match="polynomial_degree"):
            solve_affine_condition(condition, x)
    else:
        assert solve_affine_condition(condition, x)["checks"]


@pytest.mark.parametrize("combiner,expected", [("all", sp.Interval.open(-1, 1)),
                                             ("any", sp.S.Reals-sp.FiniteSet(1))])
def test_combination_checks_each_child_before_intersection_or_union(combiner, expected):
    conditions = [sp.Gt(1-x*x, 0, evaluate=False), sp.Gt((x-1)**2, 0, evaluate=False)]
    first, second = sp.Interval.open(-1, 1), sp.S.Reals-sp.FiniteSet(1)
    result = combine_variable_solutions(conditions, first, second, combiner, x)
    assert result["outputs"]["solution"] == expected
    with pytest.raises(LocalCheckFailed, match="incorrect_endpoint_solution"):
        combine_variable_solutions(conditions, sp.S.Reals, second, combiner, x)
    with pytest.raises(LocalCheckFailed, match="incomplete_endpoint_solutions"):
        combine_variable_solutions(conditions, first, None, combiner, x)


def test_single_endpoint_rejects_a_fabricated_second_result():
    condition = sp.Gt(x, 0, evaluate=False)
    actual = sp.Interval.open(0, sp.oo)
    result = combine_variable_solutions([condition], actual, None, "all", x)
    assert result["outputs"]["solutions"] == [actual]
    with pytest.raises(LocalCheckFailed, match="incomplete_endpoint_solutions"):
        combine_variable_solutions([condition], actual, actual, "all", x)


@pytest.mark.parametrize("certificate", [{}, {"passed": False, "sign": "positive"},
                                       {"passed": True, "sign": "maybe"}])
def test_slope_judgment_rejects_missing_or_failed_evidence(certificate):
    with pytest.raises(CapabilityGap, match="missing_affine_slope_certificate"):
        judgments.affine_slope_decision(certificate)
