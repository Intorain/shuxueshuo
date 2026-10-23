"""Discriminant completion cards separate useful conclusions from derivations."""

from functools import cache

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_three import (
    driver,
    execution_contracts,
    interaction,
)
from shuxueshuo_server.graph_lesson.stage_three.math_values import math_value
from shuxueshuo_server.graph_lesson.stage_three.presentation_templates import (
    PREPARED_FIELDS,
    PREPARERS,
    render_highlight,
    render_template,
)
from shuxueshuo_server.graph_lesson.stage_three.trajectory import decode_value
from tests.solver.test_graph_stage_three_methods import candidate, finish, start

t, b = sp.symbols("t b", real=True)


@cache
def route(fact, method="method-discriminant", parameter="b"):
    state = finish(start(candidate(fact, parameter), method))
    assert state["status"] == "method_complete", state["diagnostics"]
    return state


def card(state, unit):
    return next(row for row in state["fragments"] if row["display_unit"] == unit)


def frozen(state, template):
    return decode_value(next(row for row in state["interaction_seeds"] if row["template"] == template)["values"])


@pytest.mark.parametrize("quantifier,operator,expected", [
    ("∃", "<=", sp.Union(sp.Interval(-sp.oo, -2), sp.Interval(2, sp.oo))),
    ("∃", "<", sp.Union(sp.Interval.open(-sp.oo, -2), sp.Interval.open(2, sp.oo))),
    ("∀", ">=", sp.Interval(-2, 2)),
    ("∀", ">", sp.Interval.open(-2, 2)),
])
def test_fixed_opening_shows_the_needed_condition_without_empty_alternative(quantifier, operator, expected):
    state = route(f"{quantifier}t∈ℝ:t^2+b*t+1{operator}0")
    assert driver.export_values(state)["feasible_set"] == expected
    opening = card(state, "opening")
    values = frozen(state, "opening")
    assert values["opening_mode"] == "delta" and values["opening_determined"] is True
    assert values["after"] == [values["relation"]]
    assert opening["highlight"]["replace_with_graph"] is True
    assert opening["highlight"]["items"][0]["math"] == math_value(values["relation"])["latex"]
    assert len(opening["highlight"]["items"]) == 2
    assert "note" not in opening["highlight"]["items"][0]
    assert "最小值" in opening["highlight"]["items"][1]["math"]
    assert "$1 > 0$" not in opening["explanation"] and "$1 < 0$" not in opening["explanation"]
    delta = card(state, "discriminant")
    assert len(delta["highlight"]["items"]) == 2
    assert delta["highlight"]["connector"] == "⇔"
    expected_op = ("<" if operator == ">" else r"\leq") if quantifier == "∀" else (">" if operator == "<" else r"\geq")
    assert delta["highlight"]["items"][0]["math"] == rf"\Delta {expected_op} 0"
    assert "另一种开口" not in delta["explanation"] and "自动有解" not in delta["explanation"]
    assert r"\Delta=" in delta["explanation"]
    delta_values = frozen(state, "discriminant")
    condition = math_value(delta_values["after"][0])["latex"]
    assert delta["highlight"]["items"][-1]["math"] == condition
    assert condition not in delta["explanation"]
    summary = card(state, "solution")
    summary_values = frozen(state, "opening_branch_solution")
    branch = summary_values["branch"]
    assert branch["automatic"] is False and branch["direction"] == "向上"
    assert branch["solution"] == expected and summary_values["after"] == [expected]
    assert summary_values["before"] == [branch["delta_condition"]]
    assert branch in summary_values["opening_certificate"]["branches"]
    assert r"\Longleftrightarrow" in summary["explanation"]
    assert "开口条件" not in summary["explanation"] and "取并集" not in summary["explanation"]
    assert len(summary["highlight"]["items"]) == 1
    assert summary["highlight"]["caption"] == "开口向上"
    assert summary["highlight"]["items"][0]["label"] == "本分支的参数范围"
    assert r"\emptyset" not in str(summary["highlight"])


@pytest.mark.parametrize("quantifier,operator,mode,expected", [
    ("∃", ">=", "automatic", sp.S.Reals),
    ("∃", ">", "automatic", sp.S.Reals),
    ("∀", "<=", "impossible", sp.S.EmptySet),
    ("∀", "<", "impossible", sp.S.EmptySet),
])
def test_fixed_decisive_opening_never_exposes_an_irrelevant_delta_restriction(quantifier, operator, mode, expected):
    state = route(f"{quantifier}t∈ℝ:t^2+b^2+1{operator}0")
    assert driver.export_values(state)["feasible_set"] == expected
    assert frozen(state, "opening")["opening_mode"] == mode
    assert not any(row["template"] == "discriminant" for row in state["interaction_seeds"])
    template = "opening_branch_solution" if mode == "automatic" else "opening_excluded"
    summary = frozen(state, template)
    assert summary["before"] == [] and summary["after"] == [expected]
    if mode == "automatic":
        assert summary["branch"]["automatic"] is True
        assert summary["branch"]["solution"] == expected
        assert summary["branch"] in summary["opening_certificate"]["branches"]
        result = card(state, "automatic_up")
    else:
        assert not any(row["template"] == "opening_branch_solution" for row in state["interaction_seeds"])
        assert all(not branch["viable"] and branch["solution"] == sp.S.EmptySet
                   for branch in summary["branches"])
        result = card(state, "opening_excluded")
    assert "等价参数条件" not in str(result["highlight"])
    assert r"\Delta" not in result["explanation"]


def test_unknown_opening_keeps_both_existential_branches_and_their_verified_union():
    state = route("∃t∈ℝ:b*t^2+t-1>=0")
    opening = frozen(state, "opening")
    assert opening["opening_mode"] == "parameter" and opening["opening_determined"] is False
    highlight = card(state, "opening")["highlight"]
    assert "replace_with_graph" not in highlight
    assert "开口向上：有解" in highlight["items"][1]["math"]
    assert "开口向下：" in highlight["items"][1]["math"] and "最大值" in highlight["items"][1]["math"]
    summaries = [decode_value(row["values"]) for row in state["interaction_seeds"]
                 if row["template"] == "opening_branch_solution"]
    assert [row["branch"]["direction"] for row in summaries] == ["向上", "向下"]
    up, down = summaries
    assert up["branch"]["automatic"] is True and up["after"] == [sp.Interval.open(0, sp.oo)]
    assert up["before"] == [sp.Gt(b, 0, evaluate=False)]
    assert down["branch"]["automatic"] is False and down["after"] == [sp.Interval.Ropen(-sp.Rational(1, 4), 0)]
    assert down["before"] == [sp.Lt(b, 0, evaluate=False), down["branch"]["delta_condition"]]
    assert r"\cap" in card(state, "solution")["explanation"]
    merged = frozen(state, "opening_branch_merge")
    assert merged["branches"] == [row["branch"] for row in summaries]
    assert merged["after"] == [sp.Union(*(row["branch"]["solution"] for row in summaries))]
    assert card(state, "opening_merge")["highlight"]["layout"] == "merge"
    assert card(state, "opening_merge")["highlight"]["caption"] == "取并集"
    assert driver.export_values(state)["feasible_set"] == sp.Interval(-sp.Rational(1, 4), sp.oo)


def test_unrestricted_parameter_solution_is_a_set_not_a_boolean():
    state = route("∀t∈ℝ:t^2+b^2+1>=0")
    values = frozen(state, "opening_branch_solution")
    assert values["branch"]["automatic"] is False
    assert values["branch"]["delta_solution"] == sp.S.Reals
    assert values["after"] == [sp.S.Reals]
    assert "b" + r"\in " + math_value(sp.S.Reals)["latex"] in card(state, "solution")["explanation"]
    assert r"\text{True}" not in card(state, "solution")["explanation"]


def test_actual_scaled_delta_is_kept_in_derivation_and_conclusion():
    state = route("∃t∈ℝ:-3*t^2+3*b*t>=3")
    values = frozen(state, "discriminant")
    step = card(state, "discriminant")
    assert values["delta"] == 9*b*b-36
    assert math_value(values["delta"])["latex"] in step["explanation"]
    assert values["delta_formula"].count(r"\Delta=") == 1
    assert step["highlight"]["items"][-1]["math"] == r"9 b^{2} - 36 \geq 0"
    assert "b^{2} - 4" not in step["explanation"]


@pytest.mark.parametrize("before,after", [
    (sp.Le(-t*t+b*t, 1, evaluate=False), sp.Ge(t*t-b*t+1, 0, evaluate=False)),
    (sp.Gt(2*t+b, 3, evaluate=False), sp.Gt(2*t+b-3, 0, evaluate=False)),
    (sp.Le(t*t+b, 0, evaluate=False), sp.Le(t*t+b, 0, evaluate=False)),
])
def test_generic_normalization_has_one_result_board_and_an_equivalent_derivation(before, after):
    specification = execution_contracts.read("presentation-registry")["templates"]["normalize"]
    bindings = {"before": [before], "after": [after]}
    original, result, explanation = render_template(specification, bindings)
    highlight = render_highlight(specification, bindings)
    assert original == [before] and result == [after]
    assert len(highlight["items"]) == (1 if before == after else 2)
    assert highlight["connector"] == "⇔"
    assert highlight["items"][0]["math"] == math_value(before)["latex"]
    assert highlight["items"][-1]["math"] == math_value(after)["latex"]
    assert "将各项" not in explanation
    assert math_value(before)["latex"] in explanation and math_value(after)["latex"] in explanation
    assert explanation.count(r"\Longleftrightarrow") == (0 if before == after else 1)


@pytest.mark.parametrize("method", ["method-separation", "method-interval-extremum"])
def test_other_methods_keep_their_verified_parameter_sets(method):
    state = route("∀t∈[1,2]:t^2+b>=0", method)
    assert driver.export_values(state)["feasible_set"] == sp.Interval(-1, sp.oo)


def test_retired_combined_discriminant_card_is_not_registered():
    assert "discriminant_solution" not in execution_contracts.read("presentation-registry")["templates"]
    assert "discriminant_solution" not in PREPARERS
    assert "discriminant_solution" not in PREPARED_FIELDS
    assert "discriminant_solution" not in interaction.load_registry()["templates"]
    # The generic solution card remains part of the separation method.
    separation = execution_contracts.read("method-separation")
    assert any(unit["template"] == "solution" for step in separation["steps"]
               for unit in step.get("display_units", []))
