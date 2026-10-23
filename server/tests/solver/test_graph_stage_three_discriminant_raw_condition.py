"""Students keep the computed discriminant while the solver may normalize it."""

from copy import deepcopy
from functools import cache

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_three import (
    driver,
    interaction,
    interaction_opening_branches,
)
from shuxueshuo_server.graph_lesson.stage_three.discriminant_display import (
    displayed_delta_condition,
)
from shuxueshuo_server.graph_lesson.stage_three.math_values import math_value
from shuxueshuo_server.graph_lesson.stage_three.trajectory import decode_value
from tests.solver.test_graph_stage_three_methods import candidate, finish, start

x, k = sp.symbols("x k", real=True)


@pytest.mark.parametrize("quantifier", ["∀", "∃"])
@pytest.mark.parametrize("operator", [">", ">=", "<", "<="])
@pytest.mark.parametrize("variable_coefficient", [False, True])
def test_original_delta_condition_preserves_quantifier_direction_scale_and_strictness(
        quantifier, operator, variable_coefficient):
    base = 2*k*x*x - 4*k*x + 6 if variable_coefficient else 2*x*x - 2*k*x + 2
    polynomial = base if operator in (">", ">=") else -base
    relation = sp.Rel(polynomial, 0, operator, evaluate=False)
    delta = sp.discriminant(polynomial, x)
    strict = operator in (">", "<")
    internal = sp.Rel((-delta if quantifier == "∀" else delta)/4, 0,
                      ">" if strict else ">=", evaluate=False)
    expected_operator = ("<" if strict else "<=") if quantifier == "∀" else (">" if strict else ">=")
    condition = displayed_delta_condition(delta, relation, x, quantifier, internal)
    assert condition == sp.Rel(delta, 0, expected_operator, evaluate=False)
    assert condition.lhs == delta


@pytest.mark.parametrize("change", ["delta", "sign", "strictness", "parameter_scale"])
def test_unverified_delta_or_normalization_is_rejected(change):
    relation = sp.Ge(k*x*x - 6*k*x + k + 8, 0, evaluate=False)
    delta = 32*k*k - 32*k
    internal = sp.Ge(-k*k+k, 0, evaluate=False)
    if change == "delta":
        delta = delta/32
    elif change == "sign":
        internal = sp.Le(-k*k+k, 0, evaluate=False)
    elif change == "strictness":
        internal = sp.Gt(-k*k+k, 0, evaluate=False)
    else:
        internal = sp.Ge(k*(-k*k+k), 0, evaluate=False)
    with pytest.raises(ValueError, match="discriminant_display"):
        displayed_delta_condition(delta, relation, x, "∀", internal)


def test_identically_zero_delta_preserves_an_unevaluated_condition():
    relation = sp.Ge((x-k)**2, 0, evaluate=False)
    displayed = displayed_delta_condition(sp.S.Zero, relation, x, "∀", sp.Ge(0, 0, evaluate=False))
    assert displayed == sp.Le(0, 0, evaluate=False)


@cache
def route():
    state = finish(start(candidate("∀x∈ℝ:k*x^2-6*k*x+k+8>=0", "k")))
    assert state["status"] == "method_complete", state["diagnostics"]
    return state


def seed(template):
    return next(row for row in route()["interaction_seeds"] if row["template"] == template)


def test_parameter_route_uses_original_delta_across_conclusion_derivation_and_question():
    state = route()
    assert driver.export_values(state)["feasible_set"] == sp.Interval(0, 1)
    delta_condition = sp.Le(32*k*k-32*k, 0, evaluate=False)
    raw_tex = math_value(delta_condition)["latex"]
    internal_tex = math_value(sp.Ge(-k*k+k, 0, evaluate=False))["latex"]
    delta_card = next(row for row in state["fragments"] if row["display_unit"] == "discriminant")
    assert delta_card["highlight"]["items"][-1]["math"] == raw_tex
    values = decode_value(seed("opening_branch_solution")["values"])
    assert values["relation"] == sp.Ge(k*x*x-6*k*x+k+8, 0, evaluate=False)
    assert values["delta"] == 32*k*k-32*k
    assert values["branch"]["delta_condition"] == delta_condition
    assert values["before"] == [sp.Gt(k, 0, evaluate=False), delta_condition]
    assert values["branch"]["domain"] == sp.Interval.open(0, sp.oo)
    assert values["branch"]["delta_solution"] == sp.Interval(0, 1)
    assert values["after"] == [sp.Interval.Lopen(0, 1)]
    solution = next(row for row in state["fragments"] if row["display_unit"] == "solution")
    assert raw_tex in solution["explanation"] and internal_tex not in solution["explanation"]
    chunk, diagnostics = interaction.build_chunk([seed("opening_branch_solution")],
                                                 interaction.load_registry(), {"previous": 0})
    assert chunk["status"] == "interactive", diagnostics
    question = chunk["parts"][0]["question"]
    assert raw_tex in question and internal_tex not in question


@pytest.mark.parametrize("change", ["delta", "display", "before"])
def test_interaction_does_not_trust_a_changed_display_condition(change):
    frozen = seed("opening_branch_solution")
    values, context = decode_value(frozen["values"]), decode_value(frozen["context"])
    changed = deepcopy(values)
    if change == "delta":
        changed["delta"] += 1
    elif change == "display":
        changed["branch"]["delta_condition"] = sp.Ge(-k*k+k, 0, evaluate=False)
    else:
        changed["before"][-1] = sp.Ge(-k*k+k, 0, evaluate=False)
    source = interaction_opening_branches.register(interaction.EXTENSION_API)["answers"]["opening_branch_set"]
    with pytest.raises(interaction.NotInteractive, match="opening_branch_display_unverified"):
        source["facts"](changed, context)
