"""Quantified discriminant results retain the original parameter restrictions."""

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_three import driver
from shuxueshuo_server.graph_lesson.stage_three.context import build_context
from shuxueshuo_server.graph_lesson.stage_three.route_constraints import (
    apply_visible_constraints,
)
from shuxueshuo_server.graph_lesson.stage_three.verification import (
    endpoint_check,
    verify,
)
from tests.solver.test_graph_stage_three_methods import TARGET, candidate, finish, start


@pytest.mark.parametrize("fact,restrictions,raw_expected,expected", [
    (
        "∃x∈ℝ:-x^2+a*x-1>=0", ["a∈[-3,3]", "a!=2"],
        sp.Union(sp.Interval(-sp.oo, -2), sp.Interval(2, sp.oo)),
        sp.Union(sp.Interval(-3, -2), sp.Interval.Lopen(2, 3)),
    ),
    (
        "∀x∈ℝ:-x^2+a*x-1<=0", ["a>0"],
        sp.Interval(-2, 2), sp.Interval.Lopen(0, 2),
    ),
    (
        "∃x∈ℝ:a*x^2+x-1>=0", ["a<=-1"],
        sp.Interval(-sp.Rational(1, 4), sp.oo), sp.S.EmptySet,
    ),
    (
        "∃x∈ℝ:a*x^2+a>=0", ["a!=0"],
        sp.Interval(0, sp.oo), sp.Interval.open(0, sp.oo),
    ),
    (
        "∃x∈ℝ:a*x^2+a*x>=0", ["a∈[-1,1]"],
        sp.S.Reals, sp.Interval(-1, 1),
    ),
], ids=["existential-punctured-interval", "universal-reversed-relation", "empty-intersection",
        "exclude-degenerate-point", "retain-degenerate-point"])
def test_discriminant_restrictions_match_independent_original_problem_verification(
    fact, restrictions, raw_expected, expected,
):
    original = candidate(fact, extra=restrictions)
    completed = finish(start(original, method="method-discriminant"))
    assert completed["status"] == "method_complete", completed.get("diagnostics")
    raw = driver.export_values(completed)["feasible_set"]
    assert raw == raw_expected

    context = build_context(original, TARGET)
    feasible, processing = apply_visible_constraints(context, raw)
    assert feasible == expected
    assert len([item for item in processing if item["status"] == "intersected"]) == len(restrictions)
    checked = verify(original, TARGET, context, feasible)
    assert checked["status"] == "verified", checked
    endpoints = endpoint_check(original, TARGET, feasible)
    assert endpoints["status"] == "passed", endpoints
