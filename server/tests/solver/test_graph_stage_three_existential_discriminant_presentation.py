"""Existential discriminant cards keep disjunction, strictness and variable roles."""

import json
from copy import deepcopy

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_three import (
    driver,
    interaction,
    interaction_algebra,
)
from shuxueshuo_server.graph_lesson.stage_three.trajectory import (
    decode_value,
    encode_value,
)
from tests.solver.test_graph_stage_three_interaction_algebra import candidates, facts
from tests.solver.test_graph_stage_three_methods import candidate, finish, start
from tests.solver.test_graph_stage_three_selection import branch, evaluate

t, b = sp.symbols("t b", real=True)


def run(fact):
    state = finish(start(candidate(fact, "b")))
    assert state["status"] == "method_complete", state["diagnostics"]
    return state


def card(state, unit):
    return next(item for item in state["fragments"] if item["display_unit"] == unit)


def seed(state, template):
    return next(item for item in state["interaction_seeds"] if item["template"] == template)


@pytest.mark.parametrize("operator,expected", [
    ("<=", sp.Union(sp.Interval(-sp.oo, -2), sp.Interval(2, sp.oo))),
    ("<", sp.Union(sp.Interval.open(-sp.oo, -2), sp.Interval.open(2, sp.oo))),
])
def test_downward_residual_keeps_solvable_delta_branch_and_current_quantifier(operator, expected):
    state = run(f"∃t∈ℝ:t^2+b*t+1{operator}0")
    assert driver.export_values(state)["feasible_set"] == expected
    texts = " ".join(item["explanation"] for item in state["fragments"])
    assert "恒" not in texts and "全称" not in texts and "对所有" not in texts
    assert "图像开口向上" in card(state, "opening")["explanation"]
    assert "最低点须" in card(state, "opening")["explanation"]
    opening_values = decode_value(seed(state, "opening")["values"])
    assert opening_values["after"] == [opening_values["relation"]]
    assert opening_values["opening"] == sp.Gt(-1, 0, evaluate=False)
    summary = card(state, "solution")
    assert r"\Longleftrightarrow" in summary["explanation"] and "取并集" not in summary["explanation"]
    assert len(summary["highlight"]["items"]) == 1
    assert "开口条件" not in summary["highlight"]["items"][0]["label"]
    assert summary["highlight"]["caption"] == "开口向上"
    values = decode_value(seed(state, "opening_branch_solution")["values"])
    assert values["branch"]["automatic"] is False
    assert values["branch"]["delta_solution"] == expected
    assert values["branch"]["solution"] == expected
    assert values["after"] == [expected]


@pytest.mark.parametrize("operator", [">", ">="])
def test_positive_residual_is_solvable_even_when_delta_branch_is_empty(operator):
    state = run(f"∃t∈ℝ:t^2+b^2+1{operator}0")
    assert driver.export_values(state)["feasible_set"] == sp.S.Reals
    assert "因此有实数解" in card(state, "opening")["explanation"]
    opening_values = decode_value(seed(state, "opening")["values"])
    assert opening_values["after"] == [opening_values["relation"]]
    values = decode_value(seed(state, "opening_branch_solution")["values"])
    assert values["branch"]["automatic"] is True
    assert values["branch"]["solution"] == sp.S.Reals
    assert values["branch"]["delta_solution"] == sp.S.EmptySet
    assert not any(row["template"] == "discriminant" for row in state["interaction_seeds"])
    chunk, diagnostics = interaction.build_chunk([seed(state, "opening")], interaction.load_registry(), {"previous": 0})
    assert chunk["status"] == "interactive", diagnostics
    assert len(chunk["parts"]) == 2  # Students discuss both directions, including the excluded one.
    assert "对所有" not in json.dumps(chunk, ensure_ascii=False)


@pytest.mark.parametrize("fact,expected,retained", [
    ("∃t∈ℝ:b*t^2+t-1>=0", sp.Interval(-sp.Rational(1, 4), sp.oo), True),
    ("∃t∈ℝ:b*t^2+b*t>0", sp.Complement(sp.S.Reals, sp.FiniteSet(0)), False),
    ("∃t∈ℝ:b*t^2+b*t>=0", sp.S.Reals, True),
])
def test_parameter_leading_degenerate_cards_and_answers_follow_existence(fact, expected, retained):
    state = run(fact)
    assert driver.export_values(state)["feasible_set"] == expected
    degenerate = card(state, "degenerate_case")
    assert "全称" not in degenerate["explanation"]
    assert ("保留" in degenerate["highlight"]["result"]) == retained
    chunk, diagnostics = interaction.build_chunk([seed(state, "degenerate_case")],
                                                 interaction.load_registry(), {"previous": 0})
    assert chunk["status"] == "interactive", diagnostics
    interaction.validate_chunk(chunk)
    assert "全称" not in json.dumps(chunk, ensure_ascii=False)
    assert "实数解" in json.dumps(chunk, ensure_ascii=False)


@pytest.mark.parametrize("strict,allowed", [(False, {0, 1}), (True, {1})])
def test_existential_opening_uses_maximum_and_downward_option_graphs(strict, allowed):
    source = interaction_algebra.register(interaction.EXTENSION_API)["answers"]["opening_down_positions"]
    polynomial = -t**2+b
    relation = (sp.Gt if strict else sp.Ge)(polynomial, 0, evaluate=False)
    context = {"x": t, "parameter": b, "domain": sp.S.Reals, "quantifier": "∃",
               "relation": relation, "expression": polynomial}
    values = {"strict": strict, "expression": polynomial, "relation": relation}
    data = facts(source, values, context)
    item, = source["answer"](data)
    wrong, _, additional = source["validate"](data, values, context, item, candidates(source, data, item))
    correct = [item["answer"], *additional]
    assert {int(option.value) for option in correct} == allowed
    assert "至少有一个实数解" in data["display"]["opening_question"]
    builder = interaction_algebra.register(interaction.EXTENSION_API)["option_graphs"]["opening_positions"][1]
    graphs, note = builder(data, values, context,
                           [(option, True) for option in correct] + [(option, False) for option in wrong])
    assert "向下" in note
    for graph in graphs:
        interaction.graph_contract.validate_graph(graph)
        assert graph["params"]["coefficient"] == -1


def test_delta_witness_keeps_negative_leading_coefficient_and_equality_boundary():
    source = interaction_algebra.register(interaction.EXTENSION_API)["answers"]["discriminant_condition"]
    polynomial = b*t**2+(b+1)**2
    delta = -4*b*(b+1)**2
    context = {"x": t, "parameter": b, "domain": sp.S.Reals, "quantifier": "∃",
               "relation": sp.Ge(polynomial, 0, evaluate=False), "expression": polynomial}
    values = {"before": [sp.Ge(delta, 0, evaluate=False)], "after": [sp.Le(-delta, 0, evaluate=False)],
              "relation": context["relation"],
              "case": {"domain": sp.Complement(sp.S.Reals, sp.FiniteSet(0))}}
    data = facts(source, values, context)
    item, = source["answer"](data)
    strict = interaction.Candidate("strict", "strict", sp.Gt(delta, 0, evaluate=False))
    kept, records, _ = source["validate"](data, values, context, item, [strict])
    assert kept == [strict] and records[0][2] == "b=-1"
    assert data["opening_condition"].subs(b, -1) is sp.true
    assert "开口向下" in data["display"]["scope_note"]


@pytest.mark.parametrize("template", ["opening", "discriminant", "opening_branch_solution"])
def test_real_negative_leading_seeds_compile_without_universal_prompts(template):
    state = run("∃t∈ℝ:t^2+b*t+1<=0")
    chunk, diagnostics = interaction.build_chunk([seed(state, template)], interaction.load_registry(), {"previous": 0})
    assert chunk["status"] == "interactive", diagnostics
    interaction.validate_chunk(chunk)
    text = json.dumps(chunk, ensure_ascii=False)
    assert "对所有" not in text and "全称" not in text and "恒" not in text
    if template == "opening_branch_solution":
        assert " 或 " not in chunk["parts"][0]["question"]


def test_existential_branch_answer_checks_its_complete_set_and_rejects_changed_evidence():
    state = run("∃t∈ℝ:t^2+b*t+1<=0")
    source = interaction.ANSWERS["opening_branch_set"]
    frozen = seed(state, "opening_branch_solution")
    values, context = decode_value(frozen["values"]), decode_value(frozen["context"])
    data = facts(source, values, context)
    item, = source["answer"](data)
    wrong = interaction._set_candidate("none", sp.S.EmptySet)
    kept, _, _ = source["validate"](data, values, context, item, [wrong])
    assert kept == [wrong]
    # Preserve unevaluated numeric sign evidence (deepcopy would turn 1 > 0 into True).
    broken = decode_value(encode_value(values))
    broken["after"] = [sp.S.EmptySet]
    with pytest.raises(interaction.NotInteractive, match="opening_branch_unverified"):
        source["facts"](broken, context)


def test_existential_union_keeps_negative_opening_and_rejects_omitted_branch():
    state = run("∃t∈ℝ:b*t^2+t-1>=0")
    source = interaction.ANSWERS["opening_union_set"]
    frozen = seed(state, "opening_branch_merge")
    values, context = decode_value(frozen["values"]), decode_value(frozen["context"])
    data = facts(source, values, context)
    item, = source["answer"](data)
    up, down = values["branches"]
    assert up["direction"] == "向上" and down["direction"] == "向下"
    assert down["solution"] == sp.Interval.Ropen(-sp.Rational(1, 4), 0)
    missing_down = interaction._set_candidate("only-up", up["solution"])
    kept, records, _ = source["validate"](data, values, context, item, [missing_down])
    assert kept == [missing_down]
    assert records[0][1] == "witness"
    broken = deepcopy(values)
    broken["branches"] = [up]
    broken["after"] = [up["solution"]]
    with pytest.raises(interaction.NotInteractive, match="opening_union_unverified"):
        source["facts"](broken, context)


def test_existential_interaction_is_independent_of_future_result():
    state = run("∃t∈ℝ:t^2+b*t+1<=0")
    first = seed(state, "discriminant")
    future = deepcopy(seed(state, "opening_branch_solution"))
    registry = interaction.load_registry()
    original, _ = interaction.compile_route([first, future], registry)
    future["values"] = encode_value({"unrelated": sp.FiniteSet(123)})
    changed, _ = interaction.compile_route([first, future], registry)
    assert original[0] == changed[0]


def test_existential_selection_preserves_degenerate_notice_and_variable_names():
    result = evaluate(candidate("∃t∈ℝ:(b^2-1)*t^2+t+2>0", "b"))
    assert branch(result, "discriminant")["recommendation"] == "preferred"
    message = result["d3"]["verdicts"]["discriminant"]["message"]
    assert "存在实数 $t$" in message and "退化" in message
    assert "全称" not in message and "$x$" not in message
