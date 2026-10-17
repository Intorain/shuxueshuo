"""Independent acceptance checks inspect transcription, semantics and features."""

import json
import shutil
from copy import deepcopy
from pathlib import Path

import pytest

from shuxueshuo_server.graph_lesson.stage_one.evaluation import (
    evaluate,
    math_equal,
    read_json,
    validate_fixture,
)
from shuxueshuo_server.graph_lesson.stage_one.extraction import validate_candidate
from shuxueshuo_server.graph_lesson.stage_one.features import extract_features
from shuxueshuo_server.graph_lesson.stage_one.runner import CASES

FIXTURES = Path(__file__).parent / "fixtures/graph-guided-stage-one/quadratic-always"


def _evaluate(case, candidate):
    return evaluate(
        FIXTURES / case, candidate, extract_features(candidate), source_reviewed=True
    )


@pytest.mark.parametrize("case_id", CASES)
def test_independently_authored_golds_validate_their_own_policy(case_id):
    fixture = FIXTURES / case_id
    preflight = validate_fixture(fixture)
    assert preflight["ok"], preflight
    result = _evaluate(case_id, read_json(fixture / "notation.gold.json"))
    assert result["ok"], result
    assert result["acceptance"]["ok"]


@pytest.mark.parametrize("case_id", ["q01", "q02"])
def test_reordered_facts_are_semantically_equal(case_id):
    candidate = read_json(FIXTURES / case_id / "notation.gold.json")
    candidate["root"]["facts"].reverse()
    assert _evaluate(case_id, candidate)["ok"]


@pytest.mark.parametrize("case_id", ["q01", "q02", "q06"])
def test_explicit_or_default_real_target_fact_is_optional(case_id):
    candidate = read_json(FIXTURES / case_id / "notation.gold.json")
    candidate["root"]["facts"] = [
        fact for fact in candidate["root"]["facts"] if not fact.endswith("∈ℝ")
    ]
    assert _evaluate(case_id, candidate)["ok"]


def test_rearranged_relation_uses_semantics():
    candidate = read_json(FIXTURES / "q01/notation.gold.json")
    candidate["root"]["facts"][1] = "∀x∈ℝ: a^2-3*a+x^2-2*x-3 >= 0"
    assert _evaluate("q01", candidate)["ok"]


def test_changed_strictness_fails_semantics():
    candidate = read_json(FIXTURES / "q01/notation.gold.json")
    candidate["root"]["facts"][1] = candidate["root"]["facts"][1].replace("≤", "<")
    result = _evaluate("q01", candidate)
    assert not result["semantics"]["ok"]
    assert not result["ok"]


def test_required_feature_cannot_be_missing_or_unknown():
    candidate = read_json(FIXTURES / "q01/notation.gold.json")
    features = extract_features(candidate)
    next(row for row in features["features"] if row["feature_id"] == "degree_in_bound")[
        "status"
    ] = "unknown"
    result = evaluate(FIXTURES / "q01", candidate, features, source_reviewed=True)
    assert not result["ok"]
    assert {item.get("feature_id") for item in result["acceptance"]["diagnostics"]} == {
        "degree_in_bound"
    }


def test_flattened_or_leaked_sub_question_conditions_fail_semantics():
    gold = read_json(FIXTURES / "q11/notation.gold.json")
    leaked = read_json(FIXTURES / "q11/notation.gold.json")
    leaked["root"]["facts"].append(leaked["root"]["children"][0]["facts"].pop(0))
    assert validate_candidate(leaked)["contract_valid"]
    assert not _evaluate("q11", leaked)["semantics"]["ok"]
    flattened = {
        "original_text": gold["original_text"],
        "root": {
            "definitions": gold["root"]["definitions"],
            "facts": [
                fact for child in gold["root"]["children"] for fact in child["facts"]
            ],
            "goals": [goal for child in gold["root"]["children"] for goal in child["goals"]],
        },
    }
    result = _evaluate("q11", flattened)
    assert not result["ok"]
    assert {item["code"] for item in result["acceptance"]["diagnostics"]} >= {
        "acceptance.missing_goal"
    }


def test_swapped_sub_questions_fail_per_goal_acceptance():
    candidate = read_json(FIXTURES / "q10/notation.gold.json")
    candidate["root"]["children"].reverse()
    result = _evaluate("q10", candidate)
    assert not result["ok"]
    failed = {
        (item["target_ref"], item["code"]) for item in result["acceptance"]["diagnostics"]
    }
    assert ("/root/children/0/goals/0", "acceptance.quantifier_identity") in failed
    assert ("/root/children/1/goals/0", "acceptance.required_domain") in failed


@pytest.mark.parametrize("domain", ["(-∞,+∞)", "(-∞,∞)"])
def test_unbounded_interval_is_the_real_domain(domain):
    candidate = read_json(FIXTURES / "q01/notation.gold.json")
    candidate["root"]["facts"] = [
        f"a∈{domain}",
        candidate["root"]["facts"][1].replace("∀x∈ℝ", f"∀x∈{domain}"),
    ]
    result = _evaluate("q01", candidate)
    assert result["semantics"]["ok"] and result["features"]["ok"], result
    assert result["ok"]
    half = deepcopy(candidate)
    half["root"]["facts"][1] = half["root"]["facts"][1].replace(domain, "(-∞,0)")
    assert not _evaluate("q01", half)["semantics"]["ok"]


@pytest.mark.parametrize("domain", ["(-∞,+∞)", "ℝ"])
@pytest.mark.parametrize("member", ["sqrt(a-2)", "1/0"])
def test_real_membership_of_an_expression_is_a_condition(domain, member):
    candidate = read_json(FIXTURES / "q01/notation.gold.json")
    candidate["root"]["facts"].append(f"{member}∈{domain}")
    result = _evaluate("q01", candidate)
    assert not result["ok"]
    assert not result.get("semantics", {}).get("ok")


def test_quantifier_inside_a_conjunction_satisfies_acceptance():
    candidate = read_json(FIXTURES / "q10/notation.gold.json")
    part = candidate["root"]["children"][0]
    part["facts"] = [f"a∈ℝ ∧ ({part['facts'][0]})"]
    result = _evaluate("q10", candidate)
    assert result["acceptance"]["ok"], result["acceptance"]
    assert result["ok"]


def test_acceptance_must_cover_every_gold_goal(tmp_path):
    fixture = tmp_path / "q10"
    shutil.copytree(FIXTURES / "q10", fixture)
    acceptance = read_json(fixture / "acceptance.json")
    acceptance["goals"].pop()
    (fixture / "acceptance.json").write_text(json.dumps(acceptance), encoding="utf-8")
    codes = {item["code"] for item in validate_fixture(fixture)["diagnostics"]}
    assert "fixture.acceptance_goal_coverage" in codes


def test_frozen_problem_or_image_corruption_fails_preflight(tmp_path):
    fixture = tmp_path / "q01"
    shutil.copytree(FIXTURES / "q01", fixture)
    (fixture / "problem.md").write_text("改过的题文\n", encoding="utf-8")
    result = validate_fixture(fixture)
    assert not result["ok"]
    codes = {item["code"] for item in result["diagnostics"]}
    assert {"fixture.hash_mismatch", "fixture.transcription_mismatch"} <= codes


def test_unparseable_candidate_still_has_inspectable_failure():
    candidate = {"original_text": 12, "root": "not a scope"}
    result = evaluate(FIXTURES / "q01", candidate, {"ok": False, "features": []})
    assert not result["ok"]
    assert not result["contract_valid"]
    assert result["validation"]["reports"]["ir"]["issues"]


def test_feature_expression_equivalence_preserves_domain_obligations():
    assert math_equal("a^2-1", "(a-1)*(a+1)")
    assert math_equal("2", "a-a+2")
    assert not math_equal("1", "a/a")
    assert not math_equal("1", "__import__('os').system('true')")


def test_first_pass_statistics_do_not_claim_source_review():
    candidate = read_json(FIXTURES / "q01/notation.gold.json")
    features = extract_features(candidate)
    first_pass = evaluate(
        FIXTURES / "q01", candidate, features, require_source_review=False
    )
    assert first_pass["ok"]
    assert not first_pass["source_reviewed"]
    assert not first_pass["source_review_required"]
    final = evaluate(FIXTURES / "q01", candidate, features)
    assert not final["ok"]
    assert final["source_review_required"]


def test_transcription_ignores_layout_tex_and_prose_punctuation():
    candidate = read_json(FIXTURES / "q08/notation.gold.json")
    candidate["original_text"] = (
        "\n"
        + candidate["original_text"]
        .replace("$", "")
        .replace(r"\le", "≤")
        .replace("^2", "²")
        .replace("恒成立，求", "恒成立\n求")
        + "\n"
    )
    result = _evaluate("q08", candidate)
    assert result["transcription"]["ok"], result["transcription"]
    assert result["ok"]


def test_transcription_without_formula_delimiters_matches():
    candidate = read_json(FIXTURES / "q06/notation.gold.json")
    candidate["original_text"] = "“∀x<0，x^2+ax+2≥0”为真命题，求实数a的取值范围。"
    assert _evaluate("q06", candidate)["transcription"]["ok"]


@pytest.mark.parametrize(
    "before,after",
    [
        ("恒成立", "成立"),
        ("y<0", "y>0"),
        ("取值范围", "最小值"),
        ("-6+m", "-.6+m"),
        ("1\\le m\\le3", "1.\\le m\\le3"),
    ],
)
def test_transcription_still_rejects_changed_words_and_formulae(before, after):
    candidate = read_json(FIXTURES / "q08/notation.gold.json")
    candidate["original_text"] = candidate["original_text"].replace(before, after, 1)
    result = _evaluate("q08", candidate)
    assert result["semantics"]["ok"]
    assert not result["transcription"]["ok"]
    assert not result["ok"]
