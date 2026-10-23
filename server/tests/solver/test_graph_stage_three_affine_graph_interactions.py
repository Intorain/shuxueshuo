"""Affine teaching decisions use frozen sign cases and visible interval graphs."""

import json
from copy import deepcopy

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_three import interaction
from shuxueshuo_server.graph_lesson.stage_three.capabilities import (
    apply_quantifier_policy,
    select_quantifier_policy,
)
from shuxueshuo_server.graph_lesson.stage_three.capabilities.variable_swap import (
    parameter_linear_case_range,
    variable_case_plan,
)
from tests.solver.test_graph_stage_three_interactions import _seed

m, x = sp.symbols("m x", real=True)


def affine_seed(slope, intercept, domain, *, sign=None, quantifier="∀", relation=">"):
    function = slope * m + intercept
    policy = select_quantifier_policy(quantifier, relation, domain)["outputs"]["policy"]
    cases = variable_case_plan(function, m, x, domain, policy)["cases"]
    case = next(item for item in cases if sign is None or item["slope_sign"] == sign)
    outputs = parameter_linear_case_range(function, m, x, domain, policy, case)["outputs"]
    conditions = apply_quantifier_policy(policy, outputs["range"], sp.S.Zero)["outputs"]["conditions"]
    return _seed("variable_sign_case", {
        "before": [function], "after": [], "x": m, "parameter": x, "domain": domain,
        "slope": slope, "intercept": intercept, "case": case, "policy": policy,
        "conditions": conditions, "function_name": "f", **outputs,
    }, {"x": m, "parameter": x, "domain": domain, "interval_function": function})


def part(source, generator, *, component="choice", graph=False):
    result = {"component": component, "title": "判断", "question": "${domain}$", "min_options": 2}
    spec = {"answer": {"from": source}, "distractors": [{"generator": generator}]}
    if component == "checklist":
        result["rows"] = [{"seed": 0, **spec}]
    else:
        result.update(spec)
    if graph:
        result["graphs"] = {"stem": "affine_function"}
    return result


def compile_parts(seed, parts):
    original = deepcopy(seed)
    result = interaction.compile_interaction([seed], {"repeat": "always", "parts": parts},
                                              {"previous": 0}, interaction_id="affine-test")
    assert original == seed
    interaction.graph_contract.validate_part_graphs(result["parts"])
    return result["parts"]


def selected(part):
    if part["interaction"]["type"] == "checklist":
        return [next(option["label"] for option in row["options"] if option["value"] == answer)
                for row, answer in zip(part["interaction"]["slots"], part["expected_answer"]["terms"], strict=True)]
    return [option["label"] for option in part["interaction"]["options"]
            if option["value"] in part["expected_answer"]["one_of"]]


@pytest.mark.parametrize("slope,answer", [(x*x-x+1, "恒大于 0"), (-x*x-1, "恒小于 0"),
                                          (sp.S.Zero, "恒等于 0"), (x, "随参数变化，需要分类讨论")])
def test_slope_question_classifies_all_possible_cases_without_assuming_a_letter(slope, answer):
    policy = select_quantifier_policy("∀", ">", sp.Interval(1, 3))["outputs"]["policy"]
    cases = variable_case_plan(slope*m-6, m, x, sp.Interval(1, 3), policy)["cases"]
    seed = _seed("variable_slope", {"slope": slope, "cases": cases, "parameter": x}, {"parameter": x})
    question = part("affine_slope_sign", "other_slope_signs")
    question["question"] = "${slope}$ 的符号？"
    result, = compile_parts(seed, [question])
    assert selected(result) == [answer]
    assert "graph" not in result


@pytest.mark.parametrize("sign,endpoint", [("positive", "右端点 $m=3$"), ("negative", "左端点 $m=1$")])
def test_location_question_draws_both_endpoints_without_marking_the_answer(sign, endpoint):
    seed = affine_seed(x, -6, sp.Interval(1, 3), sign=sign)
    question, = compile_parts(seed, [part("affine_bound_location", "other_affine_locations", graph=True)])
    assert selected(question) == [endpoint]
    graph = question["graph"]
    assert graph["kind"] == "linear"
    assert graph["params"]["variable"] == "m"
    assert graph["params"]["interval"] == [1.0, 3.0]
    assert graph["params"]["points"] == [{"x": 1.0}, {"x": 3.0}]
    assert (graph["params"]["slope"] > 0) is (sign == "positive")
    assert "最大值" not in graph["params"]["description"]


def test_current_problem_shows_graph_then_value_then_required_condition():
    seed = affine_seed(x*x-x+1, -6, sp.Interval(1, 3))
    result = compile_parts(seed, [
        part("affine_bound_location", "other_affine_locations", graph=True),
        part("affine_endpoint_values", "endpoint_substitution_errors", component="checklist"),
        part("affine_open_attainment", "flip_candidate_attainment", component="checklist"),
        part("affine_bound_condition", "affine_condition_errors", component="checklist"),
    ])
    assert len(result) == 3  # Closed-endpoint attainment is not another question.
    assert selected(result[0]) == ["右端点 $m=3$"]
    assert selected(result[1]) == ["$3 x^{2} - 3 x - 3$"]
    assert selected(result[2]) == ["$3 x^{2} - 3 x - 3 < 0$"]


@pytest.mark.parametrize("quantifier,endpoint_name,extremum_name", [
    ("∀", "值域上端", "最大值"),
    ("∃", "值域下端", "最小值"),
])
@pytest.mark.parametrize("is_open", [False, True])
def test_affine_questions_and_feedback_distinguish_range_endpoints_from_attained_extrema(
        quantifier, endpoint_name, extremum_name, is_open):
    domain = sp.Interval(-1, 1, left_open=is_open, right_open=is_open)
    seed = affine_seed(x, -1, domain, sign="positive", quantifier=quantifier)
    # Use the real card wording, including feedback and its bound-condition
    # question, rather than constructing an abbreviated test-only question.
    parts = interaction.load_registry()["templates"]["variable_sign_case"]["parts"][:4]
    result = compile_parts(seed, parts)
    assert f"哪个位置决定{endpoint_name}？" in result[0]["question"]
    expected_name = endpoint_name if is_open else extremum_name
    assert f"已经求出的{expected_name}" in result[-1]["question"]
    visible = json.dumps(result, ensure_ascii=False)
    assert "确界" not in visible and "上界" not in visible and "下界" not in visible
    if is_open:
        assert "最大值" not in visible and "最小值" not in visible


@pytest.mark.parametrize("quantifier,relation,expected", [
    ("∀", ">", "$x - 1 \\leq 0$"),
    ("∃", ">=", "$- x - 1 < 0$"),
])
def test_open_endpoint_keeps_attainment_and_correct_strictness(quantifier, relation, expected):
    seed = affine_seed(x, -1, sp.Interval.open(-1, 1), sign="positive", quantifier=quantifier, relation=relation)
    result = compile_parts(seed, [
        part("affine_open_attainment", "flip_candidate_attainment", component="checklist", graph=True),
        part("affine_bound_condition", "affine_condition_errors", component="checklist"),
    ])
    assert selected(result[0]) == ["只能趋近，不能取得"]
    assert selected(result[1]) == [expected]
    assert all(point["open"] for point in result[0]["graph"]["params"]["points"])


def test_zero_case_has_horizontal_graph_and_no_endpoint_or_attainment_question():
    seed = affine_seed(x, -1, sp.Interval.open(-1, 1), sign="zero")
    result = compile_parts(seed, [
        part("affine_bound_location", "other_affine_locations", graph=True),
        part("affine_endpoint_values", "endpoint_substitution_errors", component="checklist", graph=True),
        part("affine_open_attainment", "flip_candidate_attainment", component="checklist"),
        part("affine_bound_condition", "affine_condition_errors", component="checklist"),
    ])
    assert len(result) == 2
    assert selected(result[0]) == ["$-1$"]
    assert result[0]["interaction"]["slots"][0]["label"] == "区间内处处相同的函数值"
    assert result[0]["graph"]["params"]["slope"] == 0
    assert selected(result[1]) == ["$-1 < 0$"]


def test_zero_case_with_multiple_parameter_roots_has_a_valid_representative_graph():
    seed = affine_seed(x*x-1, x, sp.Interval(-1, 1), sign="zero")
    result, = compile_parts(seed, [
        part("affine_bound_condition", "affine_condition_errors", component="checklist", graph=True),
    ])
    assert selected(result) == ["$x < 0$"]
    assert result["graph"]["params"]["slope"] == 0
    assert "固定 $x=-1$" in result["graph"]["caption"]


def test_identically_zero_value_still_has_a_graph_for_its_constant_condition():
    seed = affine_seed(sp.S.Zero, sp.S.Zero, sp.Interval.open(-1, 1))
    result = compile_parts(seed, [
        part("affine_endpoint_values", "endpoint_substitution_errors", component="checklist", graph=True),
        part("affine_bound_condition", "affine_condition_errors", component="checklist", graph=True),
    ])
    assert len(result) == 1
    assert selected(result[0]) == ["$0 < 0$"]
    assert result[0]["graph"]["params"]["slope"] == result[0]["graph"]["params"]["intercept"] == 0
