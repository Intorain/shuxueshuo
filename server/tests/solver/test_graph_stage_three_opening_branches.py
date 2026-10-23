"""Each viable opening has its own checked parameter work and union."""

from copy import deepcopy
from functools import cache

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_three import (
    driver,
    execution_contracts,
    interaction,
)
from shuxueshuo_server.graph_lesson.stage_three.capabilities import LocalCheckFailed
from shuxueshuo_server.graph_lesson.stage_three.capabilities.openings import (
    quadratic_opening_solutions,
)
from shuxueshuo_server.graph_lesson.stage_three.math_values import math_value
from shuxueshuo_server.graph_lesson.stage_three.presentation import math_step_hash
from shuxueshuo_server.graph_lesson.stage_three.trajectory import decode_value
from tests.solver.test_graph_stage_three_degenerate_conclusions import validator
from tests.solver.test_graph_stage_three_methods import candidate, finish, start


@cache
def checked(fact):
    state = finish(start(candidate(fact, "k")))
    assert state["status"] == "method_complete", state["diagnostics"]
    for fragment in state["fragments"]:
        validator().validate(fragment)
        assert fragment["math_step_sha256"] == math_step_hash(fragment)
    return state


@pytest.mark.parametrize("quantifier,operator,expected", [
    ("∃", ">", sp.Union(sp.Interval.open(-sp.oo, -4), sp.Interval.open(0, sp.oo))),
    ("∃", ">=", sp.Union(sp.Interval(-sp.oo, -4), sp.Interval.open(0, sp.oo))),
    ("∃", "<", sp.S.Reals), ("∃", "<=", sp.S.Reals),
    ("∀", ">", sp.S.EmptySet), ("∀", ">=", sp.S.EmptySet),
    ("∀", "<", sp.Interval.Lopen(-4, 0)), ("∀", "<=", sp.Interval(-4, 0)),
])
def test_all_quantifiers_and_comparisons_keep_distinct_opening_work(quantifier, operator, expected):
    state = checked(f"{quantifier}x∈ℝ:k*x^2-k*x-1{operator}0")
    assert driver.export_values(state)["feasible_set"] == expected
    seeds = state["interaction_seeds"]
    branch_seeds = [seed for seed in seeds if seed["template"] == "opening_branch_solution"]
    assert len(branch_seeds) == (2 if quantifier == "∃" else 1)
    branches = [decode_value(seed["values"])["branch"] for seed in branch_seeds]
    if quantifier == "∃":
        assert [branch["direction"] for branch in branches] == ["向上", "向下"]
        assert sum(branch["automatic"] for branch in branches) == 1
    else:
        shown = decode_value(branch_seeds[0]["values"])["relation"]
        assert branches[0]["direction"] == ("向上" if shown.rel_op in (">", ">=") else "向下")
        assert not branches[0]["automatic"]
    for seed, branch in zip(branch_seeds, branches, strict=True):
        assert seed["case_path"] == ["nondegenerate"]
        assert seed["branch_id"] == branch["id"]
        values = decode_value(seed["values"])
        assert values["case"]["condition"] == branch["condition"]
        assert values["after"] == [branch["solution"]]
        chunk, diagnostics = interaction.build_chunk([seed], interaction.load_registry(), {"previous": 0})
        assert chunk["status"] == "interactive", diagnostics
        assert chunk["parts"][0]["title"] == f"开口{branch['direction']}：求参数范围"
        fragment = next(item for item in state["fragments"] if item["step_id"] == seed["step_id"])
        assert fragment["source_refs"]  # Every card keeps its shared operation's evidence.
        assert fragment["branch_id"] == seed["branch_id"]
        assert fragment["branch_condition"] == seed["branch_condition"] == math_value(branch["condition"])
        for reference in fragment["source_refs"]:
            trace = state["trajectory"]["steps"][int(reference.split("/")[2])]
            assert fragment["case_path"] == trace["case_path"]
    delta_seed, = [seed for seed in seeds if seed["template"] == "discriminant"]
    delta_values = decode_value(delta_seed["values"])
    delta_card = next(card for card in state["fragments"] if card["step_id"] == delta_seed["step_id"])
    assert delta_card["title"] == f"开口{delta_values['branch']['direction']}：建立判别式条件"
    assert delta_values["after"] == [delta_values["branch"]["delta_condition"]]
    assert delta_card["after"][0]["latex"] == math_value(delta_values["branch"]["delta_condition"])["latex"]
    union = [seed for seed in seeds if seed["template"] == "opening_branch_merge"]
    assert len(union) == (1 if quantifier == "∃" else 0)
    if union:
        values = decode_value(union[0]["values"])
        assert values["after"] == [sp.Union(*(branch["solution"] for branch in branches))]
        chunk, diagnostics = interaction.build_chunk(union, interaction.load_registry(), {"previous": 0})
        assert chunk["status"] == "interactive", diagnostics
    assert seeds[-1]["template"] == "merge_cases"


def test_user_example_orders_automatic_up_before_downward_delta_and_unions():
    state = checked("∃x∈ℝ:k*x^2-k*x-1>0")
    assert [card["display_unit"] for card in state["fragments"]] == [
        "case_basis", "degenerate_case", "opening", "automatic_up", "discriminant",
        "solution", "opening_merge", "merge_cases",
    ]
    values = [decode_value(seed["values"]) for seed in state["interaction_seeds"]
              if seed["template"] == "opening_branch_solution"]
    assert values[0]["after"] == [sp.Interval.open(0, sp.oo)]
    assert values[1]["after"] == [sp.Interval.open(-sp.oo, -4)]
    assert values[0]["case"]["condition"] != values[1]["case"]["condition"]


@pytest.mark.parametrize("fact,automatic,viable", [
    ("∃x∈ℝ:x^2+k>0", True, True),
    ("∃x∈ℝ:x^2+k<0", False, True),
    ("∀x∈ℝ:x^2+k>=0", False, True),
    ("∀x∈ℝ:x^2+k<0", False, False),
])
def test_fixed_coefficient_has_no_fictitious_opposite_follow_up(fact, automatic, viable):
    state = checked(fact)
    seeds = state["interaction_seeds"]
    branches = [decode_value(seed["values"])["branch"] for seed in seeds
                if seed["template"] == "opening_branch_solution"]
    assert len(branches) == int(viable)
    assert all(branch["direction"] == "向上" and branch["automatic"] is automatic for branch in branches)
    assert sum(seed["template"] == "discriminant" for seed in seeds) == int(viable and not automatic)
    assert not any(seed["template"] == "opening_branch_merge" for seed in seeds)
    if not viable:
        assert driver.export_values(state)["feasible_set"] == sp.S.EmptySet


def test_constant_opening_is_not_presented_as_a_parameter_restriction():
    state = checked("∀x∈ℝ:x^2+(k+1)*x+1>=0")
    assert driver.export_values(state)["feasible_set"] == sp.Interval(-3, 1)
    seed, = [row for row in state["interaction_seeds"] if row["template"] == "opening_branch_solution"]
    values = decode_value(seed["values"])
    constant_sign = sp.Gt(1, 0, evaluate=False)
    sign_tex = math_value(constant_sign)["latex"]
    delta = values["branch"]["delta_condition"]
    assert values["before"] == [delta]
    # Hiding a trivial display condition must not remove its checked evidence.
    assert values["case"]["condition"] == constant_sign
    assert values["branch"]["condition"] == constant_sign
    assert values["opening_certificate"]["branches"][0]["condition"] == constant_sign
    card = next(row for row in state["fragments"] if row["step_id"] == seed["step_id"])
    assert card["before"] == [math_value(delta)]
    assert "case_condition" not in card
    assert "branch_condition" not in card
    assert sign_tex not in card["explanation"]
    assert r"\cap" not in card["explanation"]
    chunk, diagnostics = interaction.build_chunk([seed], interaction.load_registry(), {"previous": 0})
    assert chunk["status"] == "interactive", diagnostics
    question = chunk["parts"][0]["question"]
    assert math_value(delta)["latex"] in question and sign_tex not in question
    opening, = [row for row in state["interaction_seeds"] if row["template"] == "opening"]
    graph_chunk, diagnostics = interaction.build_chunk([opening], interaction.load_registry(), {"previous": 0})
    assert graph_chunk["status"] == "interactive", diagnostics
    assert len(graph_chunk["parts"]) == 2
    for part in graph_chunk["parts"]:
        assert sign_tex not in part["question"]
        assert sign_tex not in part["feedback"]["answer"]
        assert math_value(sp.Lt(1, 0, evaluate=False))["latex"] not in part["feedback"]["answer"]


def test_constant_automatic_opening_has_a_complete_question_without_empty_conditions():
    state = checked("∃x∈ℝ:x^2+k>0")
    assert driver.export_values(state)["feasible_set"] == sp.S.Reals
    seed, = [row for row in state["interaction_seeds"] if row["template"] == "opening_branch_solution"]
    values = decode_value(seed["values"])
    assert values["before"] == []
    assert values["branch"]["condition"] == sp.Gt(1, 0, evaluate=False)
    assert values["after"] == [sp.S.Reals]
    card = next(row for row in state["fragments"] if row["step_id"] == seed["step_id"])
    assert card["before"] == []
    assert "case_condition" not in card
    assert "branch_condition" not in card
    assert "1 > 0" not in card["explanation"]
    assert r"\Longleftrightarrow" not in card["explanation"]
    chunk, diagnostics = interaction.build_chunk([seed], interaction.load_registry(), {"previous": 0})
    assert chunk["status"] == "interactive", diagnostics
    question = chunk["parts"][0]["question"]
    assert question == "此时必有实数解，无需限制判别式。$k$ 的取值范围是？"


def test_parameter_opening_condition_remains_visible_and_certified():
    state = checked("∃x∈ℝ:k*x^2-k*x-1>0")
    seed = next(row for row in state["interaction_seeds"] if row["template"] == "opening_branch_solution")
    values = decode_value(seed["values"])
    condition = sp.Gt(sp.Symbol("k", real=True), 0, evaluate=False)
    assert values["before"] == [condition]
    card = next(row for row in state["fragments"] if row["step_id"] == seed["step_id"])
    assert card["before"] == [math_value(condition)]
    assert card["branch_condition"] == math_value(condition)
    assert card["case_condition"] == math_value(sp.Ne(sp.Symbol("k", real=True), 0, evaluate=False))
    assert math_value(condition)["latex"] in card["explanation"]
    chunk, diagnostics = interaction.build_chunk([seed], interaction.load_registry(), {"previous": 0})
    assert chunk["status"] == "interactive", diagnostics
    assert math_value(condition)["latex"] in chunk["parts"][0]["question"]


def test_presentation_branches_cannot_be_merged_across_the_same_execution_case():
    registry = {"merges": [{"display_units": ["first", "second"]}]}
    first = {"route_id": "route", "target_ref": "/root/goals/0", "case_path": ["nondegenerate"],
             "branch_id": "opening-up", "ordinal": 1, "display_unit": "first"}
    second = {**first, "ordinal": 2, "display_unit": "second"}
    assert interaction.merge_match(registry, first, second) == registry["merges"][0]
    assert interaction.merge_match(registry, first, {**second, "branch_id": "opening-down"}) is None
    assert interaction.merge_match(registry, first, {key: value for key, value in second.items()
                                                     if key != "branch_id"}) is None


def test_nonlinear_coefficient_keeps_all_sign_intervals_and_empty_restrictive_solution():
    state = checked("∃x∈ℝ:(k^2-1)*x^2+1>0")
    branches = [decode_value(seed["values"])["branch"] for seed in state["interaction_seeds"]
                if seed["template"] == "opening_branch_solution"]
    assert branches[0]["domain"] == sp.Union(sp.Interval.open(-sp.oo, -1), sp.Interval.open(1, sp.oo))
    assert branches[1]["domain"] == sp.Interval.open(-1, 1)
    assert driver.export_values(state)["feasible_set"] == sp.S.Reals
    empty = checked("∀x∈ℝ:k*x^2+1<0")
    restricted, = [decode_value(seed["values"])["branch"] for seed in empty["interaction_seeds"]
                   if seed["template"] == "opening_branch_solution"]
    assert restricted["solution"] == sp.S.EmptySet  # Still discuss this viable direction.


@pytest.mark.parametrize("field", ["solution", "delta_solution"])
def test_branch_capability_rejects_uncertified_input_sets(field):
    x, k = sp.symbols("x k", real=True)
    inputs = {"relation": sp.Gt(k*x*x-k*x-1, 0, evaluate=False), "variable": x, "parameter": k,
              "quantifier": "∃", "case_domain": sp.Complement(sp.S.Reals, sp.FiniteSet(0)),
              "delta": k*k+4*k, "parameter_condition": sp.Gt(k*k+4*k, 0, evaluate=False),
              "delta_solution": sp.Union(sp.Interval.open(-sp.oo, -4), sp.Interval.open(0, sp.oo)),
              "solution": sp.Union(sp.Interval.open(-sp.oo, -4), sp.Interval.open(0, sp.oo))}
    bad = deepcopy(inputs)
    bad[field] = sp.S.Reals
    with pytest.raises(LocalCheckFailed):
        quadratic_opening_solutions(**bad)


@pytest.mark.parametrize("fact,branch_count", [
    ("∀x∈ℝ:k*x^2-k*x-1>0", 1),
    ("∃x∈ℝ:k*x^2-k*x-1>0", 2),
    ("∃x∈ℝ:x^2+k>0", 1),
    ("∀x∈ℝ:x^2+k<0", 0),
])
def test_opening_union_basis_requires_multiple_branches_but_always_checks_the_result(fact, branch_count):
    state = checked(fact)
    call, = [call for step in state["trajectory"]["steps"] for call in step["calls"]
             if call["capability"] == "quadratic_opening_solutions"]
    inputs = {name: decode_value(value["exact"]) if isinstance(value, dict) else value
              for name, value in call["inputs"].items()}
    computed = quadratic_opening_solutions(**inputs)
    assert len(computed["outputs"]["branches"]) == branch_count
    assert ("union_case_conditions" in call["operations"]) is (branch_count > 1)
    assert call["operations"] == computed["operations"]
    checks = {check["kind"]: check["passed"] for check in computed["checks"]}
    assert checks == {"displayed_discriminant_solution": True,
                      "opening_direction_partition": True, "opening_branch_union": True}
    incorrect = sp.S.EmptySet if inputs["solution"] == sp.S.Reals else sp.S.Reals
    with pytest.raises(LocalCheckFailed, match="opening_branch_union"):
        quadratic_opening_solutions(**{**inputs, "solution": incorrect})


@pytest.mark.parametrize("field", ["relation", "delta", "condition", "before", "direction", "automatic"])
def test_branch_interaction_rejects_changed_display_evidence(field):
    state = checked("∀x∈ℝ:k*x^2-6*k*x+k+8>=0")
    seed = next(seed for seed in state["interaction_seeds"] if seed["template"] == "opening_branch_solution")
    values, context = decode_value(seed["values"]), decode_value(seed["context"])
    if field == "relation":
        values["relation"] = sp.Ge(values["relation"].lhs + 1, 0, evaluate=False)
    elif field == "delta":
        values["delta"] += 1
    elif field == "condition":
        values["branch"]["condition"] = sp.Lt(values["branch"]["condition"].lhs, 0, evaluate=False)
    elif field == "before":
        values["before"][-1] = sp.Ge(-values["delta"]/32, 0, evaluate=False)
    elif field == "direction":
        values["branch"]["direction"] = "向下"
    else:
        values["branch"]["automatic"] = True
    source = interaction.ANSWERS["opening_branch_set"]
    with pytest.raises(interaction.NotInteractive, match="opening_branch_display_unverified"):
        source["facts"](values, context)


@pytest.mark.parametrize("change", ["trim_delta_set", "merge_direction", "missing_branch"])
def test_frozen_certificate_prevents_locally_consistent_but_incomplete_branch_evidence(change):
    state = checked("∃x∈ℝ:k*x^2-k*x-1>0")
    template = "opening_branch_solution" if change == "trim_delta_set" else "opening_branch_merge"
    seeds = [seed for seed in state["interaction_seeds"] if seed["template"] == template]
    seed = seeds[-1]
    values, context = decode_value(seed["values"]), decode_value(seed["context"])
    if change == "trim_delta_set":
        values["branch"]["delta_solution"] = sp.Interval.open(-sp.oo, -4)
    elif change == "merge_direction":
        values["branches"][0]["direction"] = "向下"
    else:
        values["branches"] = values["branches"][1:]
        values["after"] = [values["branches"][0]["solution"]]
    source = interaction.ANSWERS["opening_branch_set" if change == "trim_delta_set" else "opening_union_set"]
    with pytest.raises(interaction.NotInteractive, match="opening_(branch_display|union)_unverified"):
        source["facts"](values, context)


def test_each_card_attributes_only_its_mathematical_operations():
    state = checked("∃x∈ℝ:k*x^2-k*x-1>0")
    for fragment in state["fragments"]:
        unit = fragment["display_unit"]
        if unit not in ("automatic_up", "discriminant", "solution", "opening_merge"):
            continue
        rows = []
        for reference in fragment["source_refs"]:
            _, _, index, category, item = reference.split("/")
            trace = state["trajectory"]["steps"][int(index)]
            rows.append((trace, trace[category][int(item)]))
        assert rows
        if unit == "discriminant":
            assert {trace["step"] for trace, _ in rows} == {"conditions"}
            assert {row["action_id"] for _, row in rows} == {"delta", "simplify", "transform"}
            assert fragment["method_ref"] == "method-discriminant#conditions"
        elif unit == "solution":
            assert {trace["step"] for trace, _ in rows} == {"solve"}
            assert any(row.get("capability") == "submethod" for _, row in rows)
        else:
            assert len(rows) == 1
            assert rows[0][1]["capability"] == "quadratic_opening_solutions"


@pytest.mark.parametrize("scope", [{"step": "merge"}, {"step": "conditions", "actions": ["missing"]}])
def test_display_sources_cannot_claim_future_or_nonexistent_operations(scope):
    contract = execution_contracts.read("method-discriminant")
    step = next(step for step in contract["steps"] if step["id"] == "solve")
    step["display_units"][0]["source_scope"] = scope
    with pytest.raises(ValueError, match="execution.invalid_display_source_scope"):
        execution_contracts.validate_contract(contract)
