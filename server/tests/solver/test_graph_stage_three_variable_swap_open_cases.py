"""Affine sign cases: exact bounds, grouping, provenance and original proof."""

from copy import deepcopy
from itertools import product

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_one.features import extract_features
from shuxueshuo_server.graph_lesson.stage_three import capabilities as cap
from shuxueshuo_server.graph_lesson.stage_three import driver
from shuxueshuo_server.graph_lesson.stage_three.capabilities import (
    variable_swap as swap,
)
from shuxueshuo_server.graph_lesson.stage_three.context import build_context
from shuxueshuo_server.graph_lesson.stage_three.trajectory import (
    decode_value,
    encode_value,
)
from shuxueshuo_server.graph_lesson.stage_three.verification import verify
from shuxueshuo_server.problem_understanding.review_contract import pointer
from tests.solver.test_graph_stage_three_methods import finish

T, A = sp.symbols("t a", real=True)
REVERSE = {">": "<", ">=": "<=", "<": ">", "<=": ">="}
TARGET = "/root/goals/0"
OPERATORS = (">", ">=", "<", "<=")


def checked(result):
    assert result["checks"] and all(row["passed"] is True for row in result["checks"])
    assert decode_value(encode_value(result)) == result
    return result["outputs"]


def solve_cases(expression, domain, quantifier="∀", operator=">", variable=T, parameter=A):
    policy = checked(cap.select_quantifier_policy(quantifier, REVERSE[operator], domain))["policy"]
    plan = swap.variable_case_plan(expression, variable, parameter, domain, policy)
    records, ranges = [], []
    for case in plan["cases"]:
        envelope = checked(swap.parameter_linear_case_range(expression, variable, parameter, domain, policy, case))
        applied = checked(cap.apply_quantifier_policy(policy, envelope["range"], sp.S.Zero))
        conditions = checked(swap.normalize_parameter_conditions(applied["conditions"], parameter))["conditions"]
        solved = checked(swap.solve_variable_conditions(conditions, applied["combiner"], parameter))
        solution = checked(swap.intersect_variable_case_solution(solved["solution"], case))["solution"]
        records.append({"case_id": case["id"], "condition": case["condition"], "domain": case["domain"],
                        "case_path": [case["id"]] if plan["has_cases"] else [],
                        "source_refs": [f"/constructed/{case['id']}"], "outputs": {"solution": solution}})
        ranges.append(envelope)
    result = checked(swap.merge_variable_cases(plan["cases"], records))
    return result["solution"], plan, ranges, records


def notation(expression, domain, quantifier, operator, variable=T, parameter=A):
    left = "(" if domain.left_open else "["
    right = ")" if domain.right_open else "]"
    fact = f"{quantifier}{variable}∈{left}{domain.start},{domain.end}{right}:{sp.sstr(expression).replace('**','^')}{operator}0"
    return {"original_text": fact, "root": {"facts": [fact], "goals": [{"kind": "find_range", "symbol": str(parameter)}]}}


def assert_case_card_sources(cards, trajectory, case_count):
    assert any(card["display_unit"] == "slope" for card in cards)
    case_cards = [card for card in cards if card["display_unit"] == "sign_case"]
    assert len(case_cards) == case_count
    assert len({tuple(card["case_path"]) for card in case_cards}) == case_count
    for card in case_cards:
        assert card["case_path"] and card["local_check"] == "passed"
        sources = [pointer(trajectory, ref) for ref in card["source_refs"]]
        assert {"parameter_linear_case_range", "intersect_variable_case_solution"} <= {
            source.get("capability") for source in sources
        }


@pytest.mark.parametrize("quantifier,operator", product(("∀", "∃"), OPERATORS))
def test_linear_zero_is_constant_and_never_borrowed_as_an_open_endpoint(quantifier, operator):
    expression = (A-1)*(T+1)
    domain = sp.Interval.open(0, 1)
    expected = {">": sp.Interval.open(1, sp.oo), ">=": sp.Interval(1, sp.oo),
                "<": sp.Interval.open(-sp.oo, 1), "<=": sp.Interval(-sp.oo, 1)}[operator]
    actual, plan, ranges, _ = solve_cases(expression, domain, quantifier, operator)
    assert actual == expected
    assert plan["has_cases"] and len(plan["cases"]) == 3
    zero_index = next(i for i,c in enumerate(plan["cases"]) if c["slope_sign"] == "zero")
    assert plan["cases"][zero_index]["domain"] == sp.FiniteSet(1)
    assert ranges[zero_index]["range"]["candidates"][0]["attained"] is True
    assert all(envelope["range"]["candidates"][0]["attained"] is False
               for i,envelope in enumerate(ranges) if i != zero_index)
    candidate = notation(expression, domain, quantifier, operator)
    result = verify(candidate, TARGET, build_context(candidate, TARGET), actual)
    assert result["status"] == "verified", result


@pytest.mark.parametrize("quantifier,operator,domain", product(
    ("∀", "∃"), OPERATORS,
    (sp.Interval(0, 1), sp.Interval.open(0, 1), sp.Interval.Lopen(0, 1), sp.Interval.Ropen(0, 1)),
))
@pytest.mark.parametrize("slope,zero_set,positive,negative", [
    (A, sp.FiniteSet(0), sp.Interval.open(0, sp.oo), sp.Interval.open(-sp.oo, 0)),
    ((A-1)**2, sp.FiniteSet(1), sp.S.Reals-sp.FiniteSet(1), sp.S.EmptySet),
    (A*A-2, sp.FiniteSet(-sp.sqrt(2), sp.sqrt(2)),
     sp.Union(sp.Interval.open(-sp.oo, -sp.sqrt(2)), sp.Interval.open(sp.sqrt(2), sp.oo)),
     sp.Interval.open(-sp.sqrt(2), sp.sqrt(2))),
])
def test_all_quantifiers_relations_and_half_open_endpoints_with_authored_sign_sets(
    quantifier, operator, domain, slope, zero_set, positive, negative,
):
    # t is positive except possibly the included t=0. Thus its sign can only
    # add universal-strict failure or an existential-weak zero witness.
    expected = positive if operator in (">", ">=") else negative
    if operator in (">=", "<="):
        expected |= zero_set
    if not domain.left_open and quantifier == "∀" and operator in (">", "<"):
        expected = sp.S.EmptySet
    if not domain.left_open and quantifier == "∃" and operator in (">=", "<="):
        expected = sp.S.Reals
    expression = slope*T
    actual, plan, _, _ = solve_cases(expression, domain, quantifier, operator)
    assert actual == expected
    assert plan["has_cases"] is True
    candidate = notation(expression, domain, quantifier, operator)
    result = verify(candidate, TARGET, build_context(candidate, TARGET), actual)
    assert result["status"] == "verified", result


def test_closed_interval_keeps_all_three_successful_sign_cases_before_union():
    actual, plan, ranges, records = solve_cases(A*T-1, sp.Interval(-1, 1), operator="<")
    assert actual == sp.Interval.open(-1, 1)
    assert plan["has_cases"] is True
    assert [case["slope_sign"] for case in plan["cases"]] == ["positive", "zero", "negative"]
    assert [case["domain"] for case in plan["cases"]] == [
        sp.Interval.open(0, sp.oo), sp.FiniteSet(0), sp.Interval.open(-sp.oo, 0),
    ]
    assert [row["outputs"]["solution"] for row in records] == [
        sp.Interval.open(0, 1), sp.FiniteSet(0), sp.Interval.open(-1, 0),
    ]
    assert [row["endpoint_mode"] for row in ranges] == ["right_endpoint", "constant", "left_endpoint"]
    assert all(row["range"]["candidates"][0]["attained"] for row in ranges)


@pytest.mark.parametrize("domain", [sp.Interval(-1, 1), sp.Interval.open(-1, 1)])
def test_quadratic_slope_groups_disconnected_cells_and_all_zero_roots(domain):
    actual, plan, _, records = solve_cases((A*A-1)*T-1, domain, operator="<")
    expected = (sp.Union(sp.Interval.open(-sp.sqrt(2), 0), sp.Interval.open(0, sp.sqrt(2)))
                if not domain.left_open else sp.Interval(-sp.sqrt(2), sp.sqrt(2)))
    assert actual == expected
    positive, zero, negative = plan["cases"]
    assert [case["slope_sign"] for case in plan["cases"]] == ["positive", "zero", "negative"]
    assert positive["domain"] == sp.Union(sp.Interval.open(-sp.oo, -1), sp.Interval.open(1, sp.oo))
    assert zero["domain"] == sp.FiniteSet(-1, 1)
    assert negative["domain"] == sp.Interval.open(-1, 1)
    assert zero["value"] is None
    assert len(positive["certificate"]["cells"]) == len(zero["certificate"]["cells"]) == 2
    assert sp.Union(*(case["domain"] for case in plan["cases"])) == sp.S.Reals
    assert all(first["domain"].intersect(second["domain"]) == sp.S.EmptySet
               for i, first in enumerate(plan["cases"]) for second in plan["cases"][i+1:])
    assert records[1]["outputs"]["solution"] == sp.FiniteSet(-1, 1)
    for case in plan["cases"]:
        assert sp.Union(*(cell["domain"] for cell in case["certificate"]["cells"])) == case["domain"]
        assert all({1: "positive", 0: "zero", -1: "negative"}[cell["signs"]["slope"]] == case["slope_sign"]
                   for cell in case["certificate"]["cells"])


@pytest.mark.parametrize("slope,sign", [(A*A+1, "positive"), (-A*A-1, "negative"), (sp.S.Zero, "zero")])
@pytest.mark.parametrize("domain", [sp.Interval(-1, 1), sp.Interval.open(-1, 1)])
def test_globally_fixed_sign_uses_one_direct_case(slope, sign, domain):
    _, plan, _, _ = solve_cases(slope*T+A, domain, operator="<")
    assert plan["has_cases"] is False
    case, = plan["cases"]
    assert case["mode"] == "direct" and case["slope_sign"] == sign
    assert case["domain"] == sp.S.Reals


def test_grouped_sign_certificate_rejects_tampered_member_cells():
    expression, domain = (A*A-1)*T, sp.Interval(-1, 1)
    policy = checked(cap.select_quantifier_policy("∀", "<", domain))["policy"]
    case = deepcopy(swap.variable_case_plan(expression, T, A, domain, policy)["cases"][0])
    case["certificate"]["cells"].pop()
    with pytest.raises(cap.LocalCheckFailed, match="variable_case_certificate_mismatch"):
        swap.parameter_linear_case_range(expression, T, A, domain, policy, case)


@pytest.mark.parametrize("quantifier,operator", product(("∀", "∃"), OPERATORS))
def test_isolated_parameter_points_are_retained_for_zero_slope_and_attained_constants(quantifier, operator):
    expression = (A-1)**2*T - 1
    domain = sp.Interval.open(0, 1)
    expected = ({">": sp.S.EmptySet, ">=": sp.S.EmptySet,
                 "<": sp.Interval(0, 2), "<=": sp.Interval(0, 2)} if quantifier == "∀" else
                {">": sp.Union(sp.Interval.open(-sp.oo, 0), sp.Interval.open(2, sp.oo)),
                 ">=": sp.Union(sp.Interval.open(-sp.oo, 0), sp.Interval.open(2, sp.oo)),
                 "<": sp.S.Reals, "<=": sp.S.Reals})[operator]
    actual, _, _, _ = solve_cases(expression, domain, quantifier, operator)
    assert actual == expected
    candidate = notation(expression, domain, quantifier, operator)
    assert verify(candidate, TARGET, build_context(candidate, TARGET), actual)["status"] == "verified"


@pytest.mark.parametrize("quantifier,operator", product(("∀", "∃"), OPERATORS))
def test_identically_zero_slope_stays_one_direct_attained_case(quantifier, operator):
    actual, plan, ranges, _ = solve_cases(A-1, sp.Interval.open(0, 1), quantifier, operator)
    expected = {">": sp.Interval.open(1, sp.oo), ">=": sp.Interval(1, sp.oo),
                "<": sp.Interval.open(-sp.oo, 1), "<=": sp.Interval(-sp.oo, 1)}[operator]
    assert actual == expected and not plan["has_cases"]
    assert ranges[0]["range"]["candidates"][0]["attained"] is True


def test_parameter_roles_can_be_renamed_without_changing_partition():
    u, z = sp.symbols("u z", real=True)
    actual, plan, _, _ = solve_cases((z-1)*(u+1), sp.Interval.open(0, 1), variable=u, parameter=z)
    assert actual == sp.Interval.open(1, sp.oo)
    assert all(case["condition"].free_symbols <= {z} for case in plan["cases"])


@pytest.mark.parametrize("field,value", [("slope_sign", "positive"), ("domain", sp.S.Reals), ("condition", sp.true)])
def test_changed_case_certificate_is_rejected_before_range_evaluation(field, value):
    domain = sp.Interval.open(0, 1)
    policy = checked(cap.select_quantifier_policy("∀", "<", domain))["policy"]
    case = deepcopy(swap.variable_case_plan(A*T, T, A, domain, policy)["cases"][1])
    case[field] = value
    with pytest.raises(cap.LocalCheckFailed, match="variable_case_certificate_mismatch"):
        swap.parameter_linear_case_range(A*T, T, A, domain, policy, case)


@pytest.mark.parametrize("fault", ["missing", "duplicate", "outside", "provenance"])
def test_case_union_rejects_missing_duplicate_unrestricted_or_untraced_results(fault):
    _, plan, _, records = solve_cases((A-1)*(T+1), sp.Interval.open(0, 1))
    records = deepcopy(records)
    if fault == "missing":
        records.pop()
    elif fault == "duplicate":
        records[1]["case_id"] = records[0]["case_id"]
    elif fault == "outside":
        records[0]["outputs"]["solution"] = sp.S.Reals
    else:
        records[0]["source_refs"] = []
    with pytest.raises(cap.LocalCheckFailed):
        swap.merge_variable_cases(plan["cases"], records)


@pytest.mark.parametrize("expression,domain,reason", [
    (A*T, sp.Interval(0, sp.oo), "bounded_interval_required"),
    (A*T, sp.Interval.open(0, sp.sqrt(2)), "rational_interval_endpoints_required"),
    ((A+sp.Symbol("b", real=True))*T, sp.Interval.open(0, 1), "single_parameter_affine_required"),
])
def test_classification_does_not_expand_other_unsupported_boundaries(expression, domain, reason):
    policy = checked(cap.select_quantifier_policy("∀", "<", domain))["policy"]
    with pytest.raises(cap.CapabilityGap, match=reason):
        swap.variable_case_plan(expression, T, A, domain, policy)


@pytest.mark.parametrize("expression,operator,expected,case_count", [
    ((A-1)*(T+1), ">", sp.Interval.open(1, sp.oo), 3),
    ((A-1)**2*T, ">", sp.S.Reals-sp.FiniteSet(1), 2),
    ((A*A-2)*T, ">=", sp.Union(sp.Interval(-sp.oo, -sp.sqrt(2)), sp.Interval(sp.sqrt(2), sp.oo)), 3),
])
def test_full_contract_exposes_each_case_range_solution_and_checked_union(expression, operator, expected, case_count):
    candidate = notation(expression, sp.Interval.open(0, 1), "∀", operator)
    context = build_context(candidate, TARGET)
    state = finish(driver.create_state(features=extract_features(candidate)["features"], context=context,
                                      method="method-variable-swap", route_id="variable", branch="swap",
                                      target_ref=TARGET, run_id="constructed-open-slope", lesson_version="v1"))
    assert state["status"] == "method_complete", state
    result = driver.export_values(state)["feasible_set"]
    assert result == expected
    assert verify(candidate, TARGET, context, result)["status"] == "verified"
    cards = state["fragments"]
    assert_case_card_sources(cards, state["trajectory"], case_count)
    assert any(card["display_unit"] == "case_union" for card in cards)
    assert all(card["source_refs"] and card["local_check"] == "passed" for card in cards)
    for step in state["trajectory"]["steps"]:
        for call in step["calls"]:
            if call["capability"] in ("parameter_linear_case_range", "intersect_variable_case_solution"):
                assert step["case_path"]
                assert call["postconditions"] and all(row["passed"] for row in call["postconditions"])



def test_child_scope_keeps_own_roles_and_excludes_sibling_constraints():
    from shuxueshuo_server.graph_lesson.stage_three.route_constraints import (
        apply_visible_constraints,
    )

    candidate = {"original_text": "constructed two-goal case", "root": {
        "facts": ["a<3"], "children": [
            {"facts": ["∀t∈(0,1):(a-1)*(t+1)>0"], "goals": [{"kind": "find_range", "symbol": "a"}]},
            {"facts": ["a<0", "∀u∈(0,1):(a+1)*(u+1)>0"], "goals": [{"kind": "find_range", "symbol": "a"}]},
        ],
    }}
    target = "/root/children/0/goals/0"
    context = build_context(candidate, target)
    state = finish(driver.create_state(features=extract_features(candidate)["features"], context=context,
                                      method="method-variable-swap", route_id="variable", branch="swap",
                                      target_ref=target, run_id="constructed-scoped-slope", lesson_version="v1"))
    assert state["status"] == "method_complete", state
    actual, processing = apply_visible_constraints(context, driver.export_values(state)["feasible_set"])
    assert actual == sp.Interval.open(1, 3)
    assert all("/children/1/" not in row["source_ref"] for row in processing)
    assert verify(candidate, target, context, actual)["status"] == "verified"



@pytest.mark.parametrize("quantifier,interval,expected", [
    ("∀", "(-1,1)", sp.Interval.Ropen(-1, 1)),
    ("∀", "[-1,1)", sp.Interval.open(-1, 1)),
    ("∀", "(-1,1]", sp.Interval.Ropen(-1, 1)),
    ("∃", "(-1,1)", sp.S.Reals-sp.FiniteSet(1)),
])
def test_open_q09_runs_through_admission_worker_verification_and_delivery(tmp_path, quantifier, interval, expected):
    from shuxueshuo_server.graph_lesson.stage_three import runner
    from tests.solver.test_graph_stage_three_execution import (
        constructed_upstream,
        read,
        simple,
    )

    candidate = simple(f"{quantifier}a∈{interval}:a*x^2-(a+1)*x+1>0", symbol="x")
    output = tmp_path / "run"
    result = runner.run_sample(constructed_upstream(tmp_path, candidate), output, milestone="6")
    goal, = result["goals"]
    route, = [route for route in goal["routes"] if route["route_id"] == "variable"]
    assert goal["status"] == "solved" and route["status"] == "verified", result
    assert decode_value(route["feasible_set_exact"]) == expected
    snapshot = read(output / "checkpoint.json")
    assert snapshot["handoffs"] and not any(result["llm"].values())
    trajectory = read(output / route["trajectory"])
    cards = [read(output / row["file"]) for row in trajectory["math_steps"]]
    assert_case_card_sources(cards, trajectory, 3)
