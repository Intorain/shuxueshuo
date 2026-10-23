"""Student-facing discriminant steps retain one normalized function and direction."""

from functools import cache
from itertools import product

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_three import capabilities as cap
from shuxueshuo_server.graph_lesson.stage_three import (
    driver,
    interaction,
    interaction_algebra,
)
from shuxueshuo_server.graph_lesson.stage_three.trajectory import decode_value
from tests.solver.test_graph_stage_three_interaction_algebra import candidates, facts
from tests.solver.test_graph_stage_three_methods import candidate, finish, start
from tests.solver.test_graph_stage_three_opening_direction import (
    assert_excluded,
    direction_parts,
)

x, m = sp.symbols("x m", real=True)
MIRROR = {">": "<", ">=": "<=", "<": ">", "<=": ">="}


@cache
def run(fact, parameter="m"):
    state = finish(start(candidate(fact, parameter)))
    assert state["status"] == "method_complete", state["diagnostics"]
    return state


def seed(state, template):
    return next(row for row in state["interaction_seeds"] if row["template"] == template)


def values(state, template):
    return decode_value(seed(state, template)["values"])


def card(state, unit):
    return next(row for row in state["fragments"] if row["display_unit"] == unit)


def normalized_relation(state):
    original = decode_value(state["input_values"])
    normalized = cap.normalize_to_zero(original["relation"], original["x"])["outputs"]["relation"]
    cards = [row for row in state["fragments"] if row["display_unit"] == "normalized"]
    if original["relation"] == normalized:
        assert not cards
        assert not any(row["template"] == "normalize" for row in state["interaction_seeds"])
    else:
        assert len(cards) == 1
        assert cards[0]["after"][0]["expression"] == str(normalized)
        assert values(state, "normalize")["after"] == [normalized]
    return normalized


def discriminant(expression, variable):
    a, b, c = sp.Poly(expression, variable).all_coeffs()
    return sp.expand(b*b - 4*a*c)


@pytest.mark.parametrize("operator,scale,swapped", product((">", ">=", "<", "<="), (2, -3), (False, True)))
def test_normalization_keeps_zero_rhs_coefficient_scale_and_discriminant(operator, scale, swapped):
    polynomial = x*x - m*x + 1
    common = (m + 1)*x + 5
    original = cap.relation(scale*polynomial + common, operator, common)
    if swapped:
        original = cap.relation(original.rhs, MIRROR[operator], original.lhs)
    normalized = cap.normalize_to_zero(original, x)["outputs"]["relation"]
    assert normalized.rhs == 0
    assert normalized.lhs == sp.expand(abs(scale)*polynomial)
    assert sp.expand(cap.residual(normalized) - cap.residual(original)) == 0
    assert discriminant(normalized.lhs, x) == sp.expand(scale*scale*(m*m - 4))
    assert discriminant(normalized.lhs, x) == discriminant(original.lhs - original.rhs, x)


@pytest.mark.parametrize("operator,swapped", product((">", ">=", "<", "<="), (False, True)))
def test_adjacent_real_route_cards_keep_normalized_function_and_comparison(operator, swapped):
    # All four original operators describe the same upward function being
    # negative somewhere, with equality allowed precisely for weak operators.
    body = "-x^2+m*x-1" if operator in (">", ">=") else "x^2-m*x+1"
    fact = f"∃x∈ℝ:0{MIRROR[operator]}{body}" if swapped else f"∃x∈ℝ:{body}{operator}0"
    state = run(fact)
    normalized = normalized_relation(state)
    strict = operator in (">", "<")
    assert normalized == cap.relation(x*x - m*x + 1, "<" if strict else "<=")
    for template in ("opening", "discriminant"):
        prepared = values(state, template)
        assert prepared["relation"] == normalized
        assert prepared["display_expression"] == normalized.lhs
        assert prepared["display_coefficient"] == 1
        assert prepared["comparison_positive"] is False
        assert prepared["delta_vertex"] == "最低点"
        assert prepared["delta_opening"] == "向上"
        assert prepared["target_sign_text"] == ("严格小于零" if strict else "小于或等于零")
        # Mirroring the displayed coefficient condition preserves exactly the
        # internal residual condition, without displaying the opposite curve.
        assert cap.residual(prepared["display_opening"]) == cap.residual(prepared["opening"])
    opening = values(state, "opening")
    assert opening["after"] == [normalized]
    assert "图像开口向上" in card(state, "opening")["explanation"]
    assert "最低点" in card(state, "opening")["explanation"]
    assert "最高点" not in card(state, "opening")["explanation"]
    delta = values(state, "discriminant")
    assert delta["before"][0] == cap.relation(m*m - 4, ">" if strict else ">=")
    summary = values(state, "opening_branch_solution")
    branch = summary["branch"]
    assert summary["relation"] == normalized
    assert summary["delta"] == discriminant(normalized.lhs, x)
    assert branch["direction"] == "向上" and branch["upward"] is True
    assert branch["condition"] == sp.Gt(1, 0, evaluate=False)
    assert branch["domain"] == sp.S.Reals
    assert branch["delta_condition"] == delta["before"][0]
    # The constant opening remains certified, but is not a parameter constraint.
    assert summary["before"] == [branch["delta_condition"]]
    assert r"\Longleftrightarrow" in card(state, "solution")["explanation"]
    assert "取并集" not in card(state, "solution")["explanation"]
    expected = sp.Union(sp.Interval(-sp.oo, -2, right_open=strict), sp.Interval(2, sp.oo, left_open=strict))
    assert summary["after"][-1] == driver.export_values(state)["feasible_set"] == expected


@pytest.mark.parametrize("strict", [False, True])
def test_real_opening_seed_draws_upward_graphs_and_tests_the_minimum(strict):
    state = run("∃x∈ℝ:-x^2+m*x-1" + (">0" if strict else ">=0"))
    frozen = seed(state, "opening")
    prepared, context = decode_value(frozen["values"]), decode_value(frozen["context"])
    extension = interaction_algebra.register(interaction.EXTENSION_API)
    source = extension["answers"]["opening_up_positions"]
    data = facts(source, prepared, context)
    item, = source["answer"](data)
    wrong, _, additional = source["validate"](data, prepared, context, item, candidates(source, data, item))
    correct = [item["answer"], *additional]
    assert {int(option.value) for option in correct} == ({-1} if strict else {-1, 0})
    assert data["display"]["relation"] == values(state, "normalize")["after"][0]
    graphs, note = extension["option_graphs"]["opening_positions"][1](
        data, prepared, context, [(option, True) for option in correct] + [(option, False) for option in wrong],
    )
    assert "向上" in note
    for graph in graphs:
        interaction.graph_contract.validate_graph(graph)
        assert graph["params"]["coefficient"] == 1
    chunk, diagnostics = interaction.build_chunk([frozen], interaction.load_registry(), {"previous": 0})
    assert chunk["status"] == "interactive", diagnostics
    assert "最高点" not in chunk["parts"][0]["question"]


@pytest.mark.parametrize("scale", [2, 3])
def test_nonzero_original_rhs_and_nonunit_scale_keep_actual_delta_in_all_cards(scale):
    z, b = sp.symbols("z b", real=True)
    state = run(f"∃z∈ℝ:-{scale}*z^2+{scale}*b*z>={scale}", "b")
    normalized = values(state, "normalize")["after"][0]
    assert normalized.rhs == 0
    assert normalized.lhs == sp.expand(scale*(z*z - b*z + 1))
    delta = values(state, "discriminant")
    actual_delta = discriminant(normalized.lhs, z)
    assert delta["before"][0].lhs == actual_delta == scale*scale*b*b - 4*scale*scale
    assert delta["after"][0] == cap.relation(actual_delta, ">=")
    assert delta["before"] == delta["after"]
    summary = values(state, "opening_branch_solution")
    branch = summary["branch"]
    assert summary["relation"] == normalized
    assert summary["delta"] == actual_delta
    assert branch["condition"] == sp.Gt(scale, 0, evaluate=False)
    assert branch["domain"] == sp.S.Reals
    assert branch["delta_condition"] == cap.relation(actual_delta, ">=")
    assert summary["before"] == [cap.relation(actual_delta, ">=")]
    assert branch["delta_solution"] == sp.Union(sp.Interval(-sp.oo, -2), sp.Interval(2, sp.oo))
    assert delta["display_expression"] == normalized.lhs
    assert driver.export_values(state)["feasible_set"] == sp.Union(sp.Interval(-sp.oo, -2), sp.Interval(2, sp.oo))


def test_unknown_parameter_leading_coefficient_keeps_conditional_opening_and_unmodified_relation():
    state = run("∃x∈ℝ:m*x^2+x-1>=0")
    normalized = normalized_relation(state)
    opening = values(state, "opening")
    assert opening["relation"] == normalized
    assert opening["display_coefficient"] == m
    assert opening["after"] == [normalized]
    explanation = card(state, "opening")["explanation"]
    assert "开口向上时自动有解" in explanation and "开口向下时" in explanation and "最高点" in explanation
    assert "图像开口向下。" not in explanation
    assert driver.export_values(state)["feasible_set"] == sp.Interval(-sp.Rational(1, 4), sp.oo)


@pytest.mark.parametrize("fact,expected,viable", [
    ("∀x∈ℝ:x^2-m*x+1>=0", sp.Interval(-2, 2), True),
    ("∀x∈ℝ:x^2-m*x+1<=0", sp.S.EmptySet, False),
])
def test_universal_route_preserves_actual_normalized_opening_and_rejects_impossible_branch(fact, expected, viable):
    state = run(fact)
    normalized = normalized_relation(state)
    opening = values(state, "opening")
    assert opening["relation"] == normalized
    assert opening["display_expression"] == x*x - m*x + 1
    assert opening["after"] == [normalized]
    assert "图像开口向上" in card(state, "opening")["explanation"]
    assert driver.export_values(state)["feasible_set"] == expected
    chunk, diagnostics = interaction.build_chunk([seed(state, "opening")],
                                                 interaction.load_registry(), {"previous": 0})
    assert chunk["status"] == "interactive", diagnostics
    parts = direction_parts(chunk)
    assert_excluded(parts[-1], "本题不存在这种开口")
    if viable:
        assert parts[1]["interaction"]["type"] == "multi"
        assert values(state, "opening_branch_solution")["after"] == [expected]
        assert values(state, "discriminant")["branch"]["direction"] == "向上"
    else:
        assert_excluded(parts[1], "此开口不适合")
        assert not any(row["template"] in ("discriminant", "opening_branch_solution")
                       for row in state["interaction_seeds"])
        assert values(state, "opening_excluded")["after"] == [sp.S.EmptySet]
