"""Affine case conclusions retain endpoint meaning and grouped set operations."""

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_three import driver
from shuxueshuo_server.graph_lesson.stage_three.math_values import latex
from tests.solver.test_graph_stage_three_batch_five import _finish_swap
from tests.solver.test_graph_stage_three_execution import simple


def test_disconnected_slope_case_is_grouped_before_intersecting_its_solution():
    state = _finish_swap(simple("∀m∈(-1,1):(x^2-1)*m+x^2-2<0", symbol="x"))
    assert state["status"] == "method_complete"
    card = next(card for card in state["fragments"] if card["display_unit"] == "sign_case"
                and card["title"].startswith("一次项系数为正"))
    region = sp.Union(sp.Interval.open(-sp.oo, -1), sp.Interval.open(1, sp.oo))
    assert rf"\cap \left({latex(region)}\right)=" in card["explanation"]
    assert r"\lim_{m\to 1^-}" in card["highlight"]["items"][0]["math"]
    assert card["highlight"]["items"][0]["label"] == "值域上端"
    assert r"\leq 0" in card["explanation"]


@pytest.mark.parametrize("domain,expected", [
    ("[-1,1]", sp.Interval.open(-1, 1)),
    ("(-1,1)", sp.Interval(-1, 1)),
])
def test_case_summary_presents_all_three_checked_sets_and_their_union(domain, expected):
    state = _finish_swap(simple(f"∀m∈{domain}:x*m-1<0", symbol="x"))
    assert driver.export_values(state)["feasible_set"] == expected
    card, = [card for card in state["fragments"] if card["display_unit"] == "case_union"]
    assert card["highlight"]["layout"] == "merge"
    assert len(card["highlight"]["items"]) == 3
    assert card["highlight"]["items"][1]["math"] == latex(sp.FiniteSet(0))
    assert card["highlight"]["result"] == rf"$x\in {latex(expected)}$"
    assert card["explanation"].count(r"\cup") == 2


@pytest.mark.parametrize("quantifier,endpoint_name", [
    ("∀", "值域上端"),
    ("∃", "值域下端"),
])
def test_open_affine_conclusion_names_the_range_endpoint_and_distinguishes_constant_case(
        quantifier, endpoint_name):
    state = _finish_swap(simple(f"{quantifier}m∈(-1,1):x*m-1<0", symbol="x"))
    assert state["status"] == "method_complete"
    cards = [card for card in state["fragments"] if card["display_unit"] == "sign_case"]
    assert len(cards) == 3
    for card in cards:
        label = card["highlight"]["items"][0]["label"]
        assert label == ("常数函数" if card["title"].startswith("一次项系数为零") else endpoint_name)
        assert "确界" not in card["explanation"]
