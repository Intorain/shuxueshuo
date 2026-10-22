"""Student extrema notation must say when a limiting value is not attained."""

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_three import driver, interaction
from shuxueshuo_server.graph_lesson.stage_three.trajectory import decode_value
from tests.solver.test_graph_stage_three_interactions import _policy_seed, a, x
from tests.solver.test_graph_stage_three_methods import candidate, finish, start


@pytest.mark.parametrize("quantifier,operator,truth", [
    ("∀", "<", [False, False, False, True, True]),
    ("∀", "<=", [False, False, False, True, True]),
    ("∀", ">", [True, True, False, False, False]),
    ("∀", ">=", [True, True, False, False, False]),
    ("∃", "<", [False, False, True, True, True]),
    ("∃", "<=", [False, False, True, True, True]),
    ("∃", ">", [True, True, True, False, False]),
    ("∃", ">=", [True, True, True, False, False]),
])
def test_policy_names_range_ends_without_claiming_extrema_exist(quantifier, operator, truth):
    # x+a has range (a,a+1). The relevant end may be zero but never attained.
    seed = _policy_seed(x + a, sp.Interval.open(0, 1), quantifier, operator)
    facts = interaction._policy_facts(decode_value(seed["values"]), decode_value(seed["context"]))
    answer = interaction._policy_answer(facts)[0]["answer"]
    assert [answer.value(point) for point in map(sp.sympify, (-2, -1, sp.Rational(-1, 2), 0, 1))] == truth
    assert r"\min" not in answer.label and r"\max" not in answer.label
    assert r"\text{下端}" in answer.label or r"\text{上端}" in answer.label
    assert "最小值/最大值" in facts["display"]["bound_explanation"]
    assert "无限接近" in facts["display"]["bound_explanation"]
    assert "确界" not in facts["display"]["bound_explanation"]
    if quantifier == "∀" and operator in ("<", ">"):
        assert "取到时不能相等" in answer.label
    if quantifier == "∃" and operator in ("<=", ">="):
        assert "等号成立时" in answer.label and "必须能取到" in answer.label


def test_q13_minimum_existence_is_visibly_different_from_the_correct_condition():
    seed = _policy_seed(x**2 + a*x + 1, sp.Interval.Lopen(0, sp.Rational(1, 2)), "∀", "<=")
    facts = interaction._policy_facts(decode_value(seed["values"]), decode_value(seed["context"]))
    answer = interaction._policy_answer(facts)[0]["answer"]
    attained = interaction._require_attained(facts, {})[0]
    assert answer.value(sp.S.One) is True
    assert attained.value(sp.S.One) is False
    assert r"\text{下端}" in answer.label and r"\min" not in answer.label
    assert r"\min" in attained.label and "存在" in attained.label


@pytest.mark.parametrize("fact,method,expected,bound", [
    ("∀x∈(0,1):x^2+a>=0", "method-separation", sp.Interval(0, sp.oo), "上端"),
    ("∀x∈(0,1):x^2+a>=0", "method-interval-extremum", sp.Interval(0, sp.oo), "下端"),
])
def test_real_open_interval_route_does_not_assert_a_nonexistent_extremum(fact, method, expected, bound):
    state = finish(start(candidate(fact), method))
    assert state["status"] == "method_complete", state["diagnostics"]
    assert driver.export_values(state)["feasible_set"] == expected
    policy = next(card for card in state["fragments"] if card["display_unit"] == "policy")
    assert f"\\text{{{bound}}}" in policy["highlight"]["result"]
    assert r"\min" not in policy["explanation"] and r"\max" not in policy["explanation"]
    assert "无限接近" in policy["explanation"]
    assert any("不存在" in card["explanation"] for card in state["fragments"])


@pytest.mark.parametrize("fact,caveat", [
    ("∀x∈[0,1]:x^2+a>0", "值域下端取到时不能相等"),
    ("∃x∈(0,1):x^2+a>=0", "相等时值域上端必须能取到"),
])
def test_carried_policy_summary_keeps_the_equality_and_attainment_caveat(fact, caveat):
    state = finish(start(candidate(fact), "method-interval-extremum"))
    assert state["status"] == "method_complete", state["diagnostics"]
    policy = next(card for card in state["fragments"] if card["display_unit"] == "policy")
    assert caveat in policy["highlight"]["result"]
    assert caveat in policy["explanation"]


def test_unnamed_product_bound_groups_the_whole_function():
    state = finish(start(candidate("∀a∈[1,2]:a*x>=0", "x"), "method-variable-swap"))
    assert state["status"] == "method_complete", state["diagnostics"]
    assert driver.export_values(state)["feasible_set"] == sp.Interval(0, sp.oo)
    policy = next(card for card in state["fragments"] if card["display_unit"] == "policy")
    assert r"\left(a x\right)_{\text{下端}}" in policy["highlight"]["result"]
    seed = _policy_seed(a*x, sp.Interval(1, 2), "∀", "<=")
    facts = interaction._policy_facts(decode_value(seed["values"]), decode_value(seed["context"]))
    assert r"\left(a x\right)_{\text{下端}}" in interaction._policy_answer(facts)[0]["answer"].label
