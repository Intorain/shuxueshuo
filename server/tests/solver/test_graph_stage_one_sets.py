"""Finite sets and the set-count goal in the graph stage-one notation."""

import pytest

from shuxueshuo_server.graph_lesson.stage_one import contracts
from shuxueshuo_server.graph_lesson.stage_one.extraction import validate_candidate
from shuxueshuo_server.problem_understanding.notation_compile import NotationValidator
from shuxueshuo_server.problem_understanding.workflow_diagnostics import diagnose


def compile_root(facts, goal="M"):
    root = {"facts": facts, "goals": [{"kind": "find_count", "symbol": goal}]}
    return validate_candidate({"original_text": "题", "root": root}), root


def test_chained_inclusion_counts_sets():
    result, _ = compile_root(["{a} ⊆ M ⊊ {a,b,c,d}"])
    assert result["contract_valid"]
    root = result["compiled"]["root"]
    m = ["ref", "r:set:M", "set"]
    fact = root["facts"][0]
    assert fact[0] == "and"
    assert fact[1][0] == "⊆" and fact[1][2] == m
    assert fact[2][0] == "⊊" and fact[2][1] == m and len(fact[2][2]) == 5
    assert root["goals"] == [{"kind": "find_count", "target": m}]


@pytest.mark.parametrize(
    "facts",
    [
        ["a ∈ M", "M ⊆ {a,b,c,d}", "M ≠ {a,b,c,d}"],
        ["A = {1,2,3}", "∅ ⊊ M", "M ⫋ A"],
        ["M ∪ {1,2} = {1,2,3}"],
        ["M ⊆ {1,2,3,4}", "1 ∉ M", "2 ∈ M"],
        ["M ∩ {1,2} = {1}", "M ⊆ {1,2,3}"],
    ],
)
def test_set_relations_compile(facts):
    result, _ = compile_root(facts)
    assert result["contract_valid"], result["reports"]["ir"]["issues"]


@pytest.mark.parametrize(
    "facts",
    [
        ["A ∪ B = {1,2,3}"],
        ["(A ∩ B) ∪ C = ∅"],
        ["A = B", "B = C", "C = {1,2}"],
        ["C = {1,2}", "B = C", "A = B"],
    ],
)
def test_set_type_reaches_nested_and_chained_names(facts):
    result, _ = compile_root(facts, goal="A")
    assert result["contract_valid"], result["reports"]["ir"]["issues"]


@pytest.mark.parametrize(
    "facts,goal",
    [
        (
            ["a > 0", "{x∈ℝ | x^2-4*a*x+3*a^2 < 0} ⊊ {x∈ℝ | x^2-x-6 ≤ 0}"],
            {"kind": "find_range", "symbol": "a"},
        ),
        (["A = {x∈ℝ: x^2-3*x+2 = 0}", "M ⊆ A"], {"kind": "find_count", "symbol": "M"}),
        (["{x∈[0,2] | x > a} = ∅"], {"kind": "find_range", "symbol": "a"}),
    ],
)
def test_set_builder_binds_its_variable(facts, goal):
    root = {"facts": facts, "goals": [goal]}
    result = validate_candidate({"original_text": "题", "root": root})
    assert result["contract_valid"], result["reports"]["ir"]["issues"]
    names = {o["name"] for o in result["compiled"]["objects"]}
    assert "x" not in names


def test_set_builder_needs_a_domain():
    result, root = compile_root(["{x | x > 1} ⊆ M"])
    routed = {(d["code"], d["action"]) for d in diagnose(result, root)}
    assert ("notation.set_builder", "repair") in routed


def test_element_sum_and_remainder():
    result, _ = compile_root(["M = {1,2,3,4,5,6}", "S ⊆ M", "S ≠ ∅", "mod(sum(S),3) = 0"], "S")
    assert result["contract_valid"], result["reports"]["ir"]["issues"]
    fact = result["compiled"]["root"]["facts"][-1]
    assert fact[1] == ["call", "mod", ["call", "sum", ["ref", "r:set:S", "set"]], ["number", "3"]]


def test_sum_alone_declares_its_set():
    result, _ = compile_root(["mod(sum(T),3) = 0", "T ⊆ {1,2,3}"], "T")
    assert result["contract_valid"], result["reports"]["ir"]["issues"]


@pytest.mark.parametrize("fact", ["B = {x∈ℝ | |x-1| <= 1}", "B = {x∈ℝ | abs(x-1) <= 1}"])
def test_absolute_value_bars_and_call_are_the_same(fact):
    root = {"facts": [fact], "goals": [{"kind": "find_range", "symbol": "a"}]}
    result = validate_candidate({"original_text": "题", "root": root})
    assert result["contract_valid"], result["reports"]["ir"]["issues"]
    builder = result["compiled"]["root"]["facts"][0][2]
    assert builder[0] == "set_builder" and builder[3][1][:2] == ["call", "abs"]


@pytest.mark.parametrize("fact", ["M = {1, |a|}", "M = {|a|, 1}", "M = {||a|-1|, 2}", "M = {1, abs(a)}"])
def test_absolute_value_elements_are_not_set_builders(fact):
    result, _ = compile_root([fact])
    assert result["contract_valid"], result["reports"]["ir"]["issues"]
    literal = result["compiled"]["root"]["facts"][0][2]
    assert literal[0] == "set" and len(literal) == 3


def test_sum_needs_a_set():
    result, root = compile_root(["M ⊆ {1,2}", "sum(t) = 3"])
    routed = {(d["code"], d["action"]) for d in diagnose(result, root)}
    assert ("type.call_arguments", "repair") in routed


def test_capitalized_literals_remain_point_sets():
    root = {
        "definitions": ["Γ: y = x^2-1"],
        "facts": ["Γ ∩ x_axis = {A,B}"],
        "goals": [{"kind": "find_value", "expression": "AB"}],
    }
    assert validate_candidate({"original_text": "题", "root": root})["contract_valid"]


@pytest.mark.parametrize(
    "facts,goal,code,action",
    [
        (["{a} ⊆ M", "M ∈ {1}"], "M", "binding.type_conflict", "repair"),
        (["M ⊆ {1}", "M < {1,2}"], "M", "type.relation", "repair"),
        (["t > 0"], "t", "type.goal_target", "repair"),
        (["|{M: M ⊆ {1}}| = 2"], "M", "notation.set_builder", "repair"),
        (["M = {x | x > 0}"], "M", "notation.set_builder", "repair"),
        (["M ⊂ {1,2}"], "M", "notation.unrecognized_token", "code_gap"),
        (["$\\{a\\} \\subseteq M$"], "M", "notation.latex_markup", "repair"),
    ],
)
def test_malformed_set_notation_is_routed(facts, goal, code, action):
    result, root = compile_root(facts, goal)
    routed = {(d["code"], d["action"]) for d in diagnose(result, root)}
    assert (code, action) in routed


def test_count_goal_is_stage_one_only():
    root = {"facts": ["M ⊆ {1}"], "goals": [{"kind": "find_count", "symbol": "M"}]}
    assert not NotationValidator().validate_root(root).ok
    assert NotationValidator().validate_root(root, contracts.schema()["$defs"]).ok


def test_catalog_describes_sets_and_count_goal():
    entries = {e["id"]: e for e in contracts.expression_catalog()["expressions"]}
    assert "find_count" in entries["finite_set"]["meaning"]
    assert "{a} ⊆ M ⊊ {a,b,c,d}" in entries["finite_set"]["examples"]
