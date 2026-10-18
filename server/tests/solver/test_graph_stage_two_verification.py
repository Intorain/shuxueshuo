"""Exact, bounded certificates; neither case IDs nor raw eval determine support."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from shuxueshuo_server.graph_lesson.stage_one.features import extract_features
from shuxueshuo_server.graph_lesson.stage_two.recognition import evaluate_types
from shuxueshuo_server.graph_lesson.stage_two.verification import verify_amgm

CORPUS = Path(__file__).parent / "fixtures/graph-guided-stage-one/quadratic-always"


def candidate(case="q01"):
    return json.loads((CORPUS / case / "notation.gold.json").read_text())


def verify(value, enabled=True, target="/root/goals/0"):
    rows = [f for f in extract_features(value)["features"] if f["target_ref"] == target]
    return verify_amgm(value, target, rows, enabled=enabled)


def test_q01_proof_covers_identities_positive_region_outside_and_attainment():
    value = candidate()
    result = verify(value)
    assert result["status"] == "supported"
    steps = {s["step_id"]: s for s in result["steps"]}
    assert set(steps) == {"separate-bound", "sum-product-identity", "positive-factors", "fixed-sum", "amgm-bound", "outside-sign", "attainment", "full-real-bound"}
    assert all(s["checked"] for s in steps.values())
    assert steps["amgm-bound"]["certificate"] == "1-u*(2-u)=(u-1)^2"
    assert steps["attainment"]["point"] == "u=1"
    assert steps["attainment"]["value"] == "4"
    assert steps["full-real-bound"]["cover"] == ["u<=0", "0<u<2", "u>=2"]
    assert steps["full-real-bound"]["attained"] is True
    assert steps["separate-bound"]["expression"] == "p^2-3*p >= -u^2+2*u+3"
    assert result["symbol_mapping"] == {"u": "x", "p": "a"}
    assert set(result["input_refs"]) == {"/root/facts/1", "/root/goals/0"}
    assert "parameter_range" not in result
    reports = evaluate_types(extract_features(value)["features"], result)
    assert {r["type_id"] for r in reports if r["status"] == "supported"} == {"type-quantified-quadratic", "type-amgm-quantified"}


def test_disabled_verification_has_no_proof():
    assert verify(candidate(), enabled=False) == {"status": "unknown", "reason": "verification.disabled", "steps": [], "input_refs": ["/root/goals/0"]}


@pytest.mark.parametrize("fact", [
    "∀t∈ℝ: -t^2+2*t+3 <= b^2-3*b",
    "∀t∈ℝ: b^2-3*b >= -t^2+2*t+3",
    "∀t∈ℝ: t^2-2*t+b^2-3*b-3 >= 0",
    "∀t∈(-∞,∞): 3+t*(2-t) <= b*(b-3)",
])
def test_mathematical_shape_supports_renaming_rearrangement_and_factoring(fact):
    value = {"original_text": "A new problem, no Q01 identifier", "root": {"facts": [fact], "goals": [{"kind": "find_range", "symbol": "b"}]}}
    assert verify(value)["status"] == "supported"


@pytest.mark.parametrize("fact,expected", [
    ("∀t∈ℝ: -t^2+2*t+3 <= b", "p"),
    ("∀t∈ℝ: -t^2+2*t+3 <= 2*b+1", "2*p+1"),
    ("∀t∈ℝ: -t^2+2*t+3 <= b^2-4*b", "p^2-4*p"),
    ("∀t∈ℝ: b^3-4*b+7 >= -t^2+2*t+3", "p^3-4*p+7"),
    ("∀t∈ℝ: t^2-2*t+2*b-2 >= 0", "2*p+1"),
    ("∀t∈ℝ: 3+t*(2-t) <= b*(b+1)", "p^2+p"),
])
def test_parameter_expression_is_separated_from_the_bound_and_rendered(fact, expected):
    value = {"original_text": "A parameter-side variation", "root": {
        "facts": [fact], "goals": [{"kind": "find_range", "symbol": "b"}]}}
    result = verify(value)
    assert result["status"] == "supported"
    assert result["steps"][0]["expression"] == f"{expected} >= -u^2+2*u+3"
    assert result["symbol_mapping"] == {"u": "t", "p": "b"}
    assert "parameter_range" not in result
    reports = evaluate_types(extract_features(value)["features"], result)
    assert {r["type_id"] for r in reports if r["status"] == "supported"} == {
        "type-quantified-quadratic", "type-amgm-quantified"}


@pytest.mark.parametrize("fact", [
    "∀x∈ℝ:-x^2+2*x+3 >= a^2-3*a",
    "∀x∈ℝ:-x^2+2*x+3 < a^2-3*a",
    "∀x∈ℝ:-x^2+2*x+3 = a^2-3*a",
    "∃x∈ℝ:-x^2+2*x+3 <= a^2-3*a",
    "∀x∈(0,1):-x^2+2*x+3 <= a^2-3*a",
    "∀x∈[2,3]:-x^2+2*x+3 <= a^2-3*a",
    "∀x∈ℝ:-x^2+3*x+3 <= a^2-3*a",
    "∀x∈ℝ:-x^2+2*x+3 <= a*x+1",
    "∀x∈ℝ:-x^2+2*x+3 <= a*x^2+1",
    "∀x∈ℝ:-x^2+2*x+3 <= a+x^3",
    "∀x∈ℝ:(-x^2+2*x+3)/x <= a^2-3*a",
])
def test_unproved_domain_direction_equality_or_algebra_never_supports(fact):
    value = candidate()
    value["root"]["facts"][1] = fact
    result = verify(value)
    assert result["status"] == "unknown"
    assert result["reason"] != "verification.disabled"
    assert result["steps"] == []


@pytest.mark.parametrize("case", [f"q{i:02}" for i in range(2, 10)])
def test_other_corpus_problems_remain_unknown(case):
    assert verify(candidate(case))["status"] == "unknown"


def test_verification_does_not_borrow_sibling_conditions_or_target():
    value = candidate()
    local = deepcopy(value["root"])
    value["root"] = {"children": [local, {"facts": ["∀x∈ℝ:x^2+a>=0"], "goals": [{"kind": "find_range", "symbol": "a"}]}]}
    assert verify(value, target="/root/children/0/goals/0")["status"] == "supported"
    assert verify(value, target="/root/children/1/goals/0")["status"] == "unknown"


@pytest.mark.parametrize("domain", ["ℝ", "(-∞,+∞)", "(-∞,∞)"])
def test_target_full_real_domain_forms_produce_the_same_supported_types(domain):
    value = candidate()
    value["root"]["facts"][0] = f"a∈{domain}"
    result = verify(value)
    assert result["status"] == "supported"
    reports = evaluate_types(extract_features(value)["features"], result)
    assert {r["type_id"] for r in reports if r["status"] == "supported"} == {
        "type-quantified-quadratic", "type-amgm-quantified"}


@pytest.mark.parametrize("fact", ["a∈(0,+∞)", "a∈[-1,1]", "b∈(-∞,+∞)"])
def test_real_domain_equivalence_does_not_discard_other_conditions(fact):
    value = candidate()
    value["root"]["facts"][0] = fact
    assert verify(value)["reason"] == "verification.additional_conditions"


def test_ancestor_full_real_domain_is_used_without_borrowing_sibling_constraints():
    value = candidate()
    quantified = value["root"]["facts"][1]
    local = {"facts": [quantified], "goals": [{"kind": "find_range", "symbol": "a"}]}
    value["root"] = {"facts": ["a∈(-∞,+∞)"], "children": [
        local, {**deepcopy(local), "facts": ["a∈(0,+∞)", quantified]}]}
    assert verify(value, target="/root/children/0/goals/0")["status"] == "supported"
    assert verify(value, target="/root/children/1/goals/0")["reason"] == "verification.additional_conditions"


def test_additional_domain_assumptions_and_unknown_features_are_not_ignored():
    value = candidate()
    value["root"]["facts"].append("a>0")
    assert verify(value)["reason"] == "verification.additional_conditions"
    value = candidate()
    rows = extract_features(value)["features"]
    next(f for f in rows if f["feature_id"] == "domain")["status"] = "unknown"
    assert verify_amgm(value, "/root/goals/0", rows, enabled=True)["reason"] == "verification.unknown_input"


def test_raw_expression_text_cannot_execute(tmp_path):
    marker = tmp_path / "executed"
    value = candidate()
    rows = extract_features(value)["features"]
    value["root"]["facts"][1] = f"∀x∈ℝ: __import__('pathlib').Path('{marker}').touch() <= a"
    assert verify_amgm(value, "/root/goals/0", rows, enabled=True)["status"] == "unknown"
    assert not marker.exists()
