"""Batch-four acceptance from retained questions and independent mathematics.

GRAPH_STAGE_THREE_BATCH_FOUR_RUN_DIR retains all 22 original recorded inputs,
route/case evidence, incremental events and reports. Synthetic variants below
are explicitly constructed tests and never represented as model recordings.
"""

import os
from copy import deepcopy
from pathlib import Path

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_three import execution_contracts, runner
from shuxueshuo_server.graph_lesson.stage_three.contracts import ROOT
from shuxueshuo_server.graph_lesson.stage_three.trajectory import decode_value
from shuxueshuo_server.graph_lesson.stage_three.verification import endpoint_check
from tests.solver.test_graph_stage_three_batch_three import ANSWERS as EARLIER_ANSWERS
from tests.solver.test_graph_stage_three_batch_two import Q10_ANSWERS
from tests.solver.test_graph_stage_three_contracts import accepted, upstream
from tests.solver.test_graph_stage_three_execution import (
    Interrupted,
    constructed_upstream,
    events,
    read,
    simple,
    store,
)
from tests.solver.test_graph_stage_three_recorded import (
    SELECTION_GOLD,
    STAGE_ONE_BATCH,
    forbid_live_providers_and_network,  # noqa: F401 — shared autouse fixture
)
from tests.solver.test_graph_stage_three_verification import TARGET, check

# Q06: t=-x>0 gives a≤t+2/t, whose minimum 2√2 occurs at t=√2.
# Q07: x²-x ranges over [2,6], so its positive reciprocal ranges over
# [1/6,1/2]. The universal strict comparison therefore gives m<1/6.
ANSWERS = {
    **EARLIER_ANSWERS,
    "q06": sp.Interval(-sp.oo, 2 * sp.sqrt(2)),
    "q07": sp.Interval.open(-sp.oo, sp.Rational(1, 6)),
}


def _gold_set(case):
    # This reads a trusted test fixture; production inputs use notation_semantics.
    return sp.Union(*(sp.Interval(sp.sympify(part["lower"]), sp.sympify(part["upper"]),
                                 left_open=not part["left_closed"], right_open=not part["right_closed"])
                      for part in case["feasible_set"]["intervals"]))


def _math(value):
    return decode_value(value["exact"])


def _calls(trajectory):
    return [call for step in trajectory["steps"] for call in step["calls"]]


def _checked(record):
    return bool(record.get("postconditions")) and all(item["passed"] is True for item in record["postconditions"])


def _executed_refs(trajectory):
    refs = set()
    for step in trajectory["steps"]:
        for call in step["calls"]:
            if _checked(call):
                refs.update((step["method"], step["method"] + "#" + step["step"]))
                if call["public_ref"]:
                    refs.add(call["public_ref"])
                refs.update(call["used_basis"])
    for record in trajectory["finalization"]:
        if _checked(record):
            refs.update(record.get("used_basis", []))
    return refs


def _both_routes(result):
    goal, = result["goals"]
    assert goal["status"] == "solved", goal
    routes = {route["route_id"]: route for route in goal["routes"] if route["status"] == "verified"}
    assert set(routes) == {"interval", "extremum"}, goal
    return routes


def _assert_case_partition(trajectory, expected):
    records = [record for step in trajectory["steps"] for record in step.get("case_results", [])]
    assert records, "The interval route must retain real case frames and their collected outputs."
    domains = [_math(record["domain"]) for record in records]
    solutions = [_math(record["outputs"]["solution"]) for record in records]
    assert sp.Union(*domains) == sp.S.Reals
    assert all(sp.Intersection(left, right) == sp.S.EmptySet
               for i, left in enumerate(domains) for right in domains[i + 1:])
    assert all(sp.Complement(solution, domain) == sp.S.EmptySet for solution, domain in zip(solutions, domains))
    assert sp.Union(*solutions) == expected
    assert all(record["case_path"] and record["source_refs"] for record in records)
    return records


def _assert_case_specific_evidence(case, route_id, trajectory):
    calls = _calls(trajectory)
    if route_id == "interval":
        records = _assert_case_partition(trajectory, ANSWERS[case])
        if case == "q07":
            zero_case, = [record for record in records if _math(record["domain"]) == sp.FiniteSet(0)]
            assert _math(zero_case["outputs"]["solution"]) == sp.FiniteSet(0)
            constant_calls = [call for call in calls if call["capability"] == "linear_range"
                              and call["case_path"] == zero_case["case_path"]]
            assert constant_calls and all(_checked(call) for call in constant_calls)
            assert any("skill-linear-range#constant" in {call["public_ref"], *call["used_basis"]}
                       for call in constant_calls)
    elif case == "q06":
        division, = [call for call in calls if call["capability"] == "separation_division"]
        assert _checked(division)
        assert division["outputs"]["divisor_sign"] == "negative"
        assert division["outputs"]["transformation"] == "negative_division"
        original = _math(division["inputs"]["relation"])
        separated = _math(division["outputs"]["separated_relation"])
        assert original.rel_op == ">=" and separated.rel_op == "<="
        assert "multiply_negative" in division["operations"]
        assert any(item["kind"] == "strict_negative_divisor" and item["passed"]
                   for item in division["postconditions"])
    else:
        reciprocal, = [call for call in calls if call["capability"] == "reciprocal_of_range"]
        assert _checked(reciprocal)
        assert "skill-inequality-transform#reciprocal" in {reciprocal["public_ref"], *reciprocal["used_basis"]}
        assert "function-monotonicity" in reciprocal["used_basis"]
        extent = reciprocal["outputs"]["range"]
        assert _math(extent["inf"]) == sp.Rational(1, 6)
        assert _math(extent["sup"]) == sp.Rational(1, 2)
        assert extent["inf_attained"] is True and extent["sup_attained"] is True
    boundary, = [record["outputs"] for record in trajectory["finalization"]
                 if record["capability"] == "endpoint_check"]
    assert boundary["status"] == "passed"
    point, = boundary["points"]
    assert sp.sympify(point["point"]["expression"]) == (2 * sp.sqrt(2) if case == "q06" else sp.Rational(1, 6))
    assert point["included"] is (case == "q06") and point["holds"] is (case == "q06")


def test_all_recordings_preserve_selection_and_q06_q07_complete_both_routes(tmp_path):
    configured = os.getenv("GRAPH_STAGE_THREE_BATCH_FOUR_RUN_DIR")
    output = Path(configured) if configured else tmp_path / "recorded"
    summary = runner.run_recorded_batch(STAGE_ONE_BATCH, output, milestone="4")
    assert summary["completed"], str(output / "index.html")
    assert len(summary["results"]) == 22
    assert sum(row["eligible"] for row in summary["results"]) == 24
    assert sum(row["skipped"] for row in summary["results"]) == 2
    selection_gold = read(SELECTION_GOLD)["cases"]
    answer_gold = read(SELECTION_GOLD.parent / "answers.gold.json")["cases"]
    assert {case: _gold_set(answer_gold[case]) for case in ANSWERS} == ANSWERS
    human = read(ROOT / "site/data/knowledge-next/topics/quadratic-always.json")["problems"]
    nodes = execution_contracts.load_nodes()
    seen = set()
    for row in summary["results"]:
        case, sample = row["case_id"], output / row["sample_dir"]
        result = read(sample / "stage-three-result.json")
        assert result["status"] == "completed", str(sample / "index.html")
        assert result["input_validation"]["ok"] and not any(result["llm"].values())
        source = read(sample / "stage-one-input.json")
        assert source["statuses"]["source_reviewed"] and source["statuses"]["passed"]
        assert source["candidate"] == read(STAGE_ONE_BATCH / row["sample_dir"] / "stage-one-result.json")["candidate"]
        for goal in result["goals"]:
            if goal["status"] == "skipped":
                continue
            expected, = [item for item in selection_gold[case] if item["target_ref"] == goal["target_ref"]]
            assert goal["d3"]["expected_answer"]["cell"] == expected["cell"]
            for branch in goal["selection"]["branches"]:
                for field in ("trigger", "applicability", "recommendation"):
                    assert branch[field] == expected["branches"][branch["branch"]][field]
            assert not any(route["status"] in ("math_failed", "execution_error") for route in goal["routes"])
            if case == "q10":
                assert goal["status"] == "solved"
                assert all(decode_value(route["feasible_set_exact"]) == Q10_ANSWERS[goal["target_ref"]]
                           for route in goal["routes"] if route["status"] == "verified")
            if case == "q11":
                assert all(decode_value(route["feasible_set_exact"]) == sp.Interval.open(-sp.oo, sp.Rational(6, 7))
                           for route in goal["routes"] if route["status"] == "verified")
        if case in ANSWERS:
            goal, = result["goals"]
            assert goal["status"] == "solved", str(sample / "index.html")
            verified = {route["route_id"]: route for route in goal["routes"] if route["status"] == "verified"}
            assert set(verified) == set(answer_gold[case]["routes"])
            assert all(decode_value(route["feasible_set_exact"]) == ANSWERS[case] for route in verified.values())
        if case in ("q06", "q07"):
            for route_id, route in _both_routes(result).items():
                trajectory = read(sample / route["trajectory"])
                authored = human[f"quadratic-always-{case}"]["routes"][route_id]["steps"]
                executed = _executed_refs(trajectory)
                # A root knowledge reference can be represented by its actually
                # executed anchor; different anchors are never interchangeable.
                assert all(ref in executed or ("#" not in ref and any(actual.startswith(ref + "#") for actual in executed))
                           for step in authored.values() for ref in step["refs"])
                cards = [read(sample / item["file"]) for item in trajectory["math_steps"]]
                assert cards and all(card["local_check"] == "passed" for card in cards)
                assert all(execution_contracts.valid_ref(card["method_ref"], nodes) for card in cards)
                _assert_case_specific_evidence(case, route_id, trajectory)
            assert (sample / "events.jsonl").is_file() and (sample / "checkpoint.json").is_file()
            seen.add((case, row["sample_id"]))
        assert (sample / "index.html").is_file() and (sample / "source.png").is_file()
    assert len(seen) == 4 and (output / "index.html").is_file()
    print(f"Batch-four recorded acceptance report: {output / 'index.html'}")


@pytest.mark.parametrize("facts,symbol,expected", [
    (("∀t∈(-∞,0):t^2+b*t+2>=0",), "b", ANSWERS["q06"]),
    (("∀z∈[2,3]:n*z^2-n*z-1<0",), "n", ANSWERS["q07"]),
    (("∀x∈(-∞,0):0<=x^2+a*x+2",), "a", ANSWERS["q06"]),
    (("∀x∈(-∞,0):x^2+a*x+8>=0",), "a", sp.Interval(-sp.oo, 4 * sp.sqrt(2))),
    (("∀x∈(-∞,-2]:x^2+a*x+2>=0",), "a", sp.Interval(-sp.oo, 3)),
    (("∀x∈(-∞,0):x^2+a*x+2>0",), "a", sp.Interval.open(-sp.oo, 2 * sp.sqrt(2))),
    (("∃x∈(-∞,0):x^2+a*x+2>=0",), "a", sp.S.Reals),
    (("∀x∈[2,3]:m*x^2-m*x-2<0",), "m", sp.Interval.open(-sp.oo, sp.Rational(1, 3))),
    (("∀x∈[2,4]:m*x^2-m*x-1<0",), "m", sp.Interval.open(-sp.oo, sp.Rational(1, 12))),
    (("∀x∈[2,3]:m*x^2-m*x-1<=0",), "m", sp.Interval(-sp.oo, sp.Rational(1, 6))),
    (("∃x∈[2,3]:m*x^2-m*x-1<0",), "m", sp.Interval.open(-sp.oo, sp.Rational(1, 2))),
    (("∀x∈(2,3):m*x^2-m*x-1<0",), "m", sp.Interval(-sp.oo, sp.Rational(1, 6))),
    (("a∈[0,4]", "∀x∈(-∞,0):x^2+a*x+2>=0"), "a", sp.Interval(0, 2 * sp.sqrt(2))),
    (("m∈[-1,1]", "∀x∈[2,3]:m*x^2-m*x-1<0"), "m", sp.Interval.Ropen(-1, sp.Rational(1, 6))),
])
def test_both_routes_follow_actual_signs_domains_quantifiers_and_constraints(tmp_path, facts, symbol, expected):
    candidate = simple(*facts, symbol=symbol)
    result = runner.run_sample(constructed_upstream(tmp_path, candidate), tmp_path / "run", milestone="4")
    routes = _both_routes(result)
    assert all(decode_value(route["feasible_set_exact"]) == expected for route in routes.values())
    assert check(candidate, expected)["status"] == "verified"
    assert endpoint_check(candidate, TARGET, expected)["status"] == "passed"
    assert not any(result["llm"].values())


@pytest.mark.parametrize("case,bad_set", [
    ("q06", sp.Interval.open(-sp.oo, 2 * sp.sqrt(2))),
    ("q06", sp.Interval(-sp.oo, 0)),
    ("q06", sp.Interval.Lopen(0, 2 * sp.sqrt(2))),
    ("q06", sp.S.Reals),
    ("q07", sp.Interval(-sp.oo, sp.Rational(1, 6))),
    ("q07", sp.Interval.open(0, sp.Rational(1, 6))),
    ("q07", sp.S.EmptySet),
    ("q07", sp.Complement(ANSWERS["q07"], sp.FiniteSet(0))),
])
def test_original_problem_proof_rejects_wrong_bounds_lost_cases_and_wrong_intersection(case, bad_set):
    candidate = accepted(case)["candidate"]
    correct = check(candidate, ANSWERS[case])
    assert correct["status"] == "verified", correct
    rejected = check(candidate, bad_set)
    assert rejected["status"] == "math_failed", rejected
    assert rejected["counterexample"]["original_holds"] != rejected["counterexample"]["candidate_includes"]
    assert rejected["proof"]["critical_points"] == correct["proof"]["critical_points"]
    assert rejected["proof"]["cells"] == correct["proof"]["cells"]


@pytest.mark.parametrize("case", ["q06", "q07"])
@pytest.mark.parametrize("position", ["before_commit", "after_commit"])
def test_actual_interval_case_frame_resumes_with_stable_calls_cards_and_events(tmp_path, case, position):
    output = tmp_path / "resumed"
    stopped = []

    def stop_inside_case(state, _durable):
        if stopped or state["method"] != "method-interval-extremum":
            return
        actual_calls = [call for step in state["trajectory"]["steps"] if step["case_path"]
                        for call in step["calls"] if call["capability"] in ("linear_range", "parametric_interval_extremum")]
        if actual_calls and any(frame.get("case_path") for frame in state["frames"]):
            stopped.append(deepcopy(state))
            raise Interrupted()

    with pytest.raises(Interrupted):
        runner.run_sample(upstream(tmp_path, case), output, milestone="4", hooks={position: stop_inside_case})
    assert stopped
    prefix_events = events(output)
    prefix_cards = store(output).snapshot()["math_steps"]
    assert any(card["route_id"] == "interval" for card in prefix_cards)
    resumed = runner.resume_sample(output)
    routes = _both_routes(resumed)
    assert all(decode_value(route["feasible_set_exact"]) == ANSWERS[case] for route in routes.values())
    trajectory = read(output / routes["interval"]["trajectory"])
    _assert_case_partition(trajectory, ANSWERS[case])
    assert events(output)[:len(prefix_events)] == prefix_events
    cards = store(output).snapshot()["math_steps"]
    current = {card["step_id"]: card for card in cards}
    assert len(current) == len(cards)
    assert all(current[card["step_id"]] == card for card in prefix_cards)
    assert all(current[card["step_id"]] == card for card in stopped[0]["fragments"])
    for old_step in stopped[0]["trajectory"]["steps"]:
        matching, = [step for step in trajectory["steps"] if step["seq"] == old_step["seq"]]
        assert matching["case_path"] == old_step["case_path"]
        assert matching["calls"][:len(old_step["calls"])] == old_step["calls"]
    sequence = events(output)
    assert [event["seq"] for event in sequence] == list(range(1, len(sequence) + 1))
    runner.resume_sample(output)
    assert events(output) == sequence


@pytest.mark.parametrize("case", ["q06", "q07"])
@pytest.mark.parametrize("method", ["method-interval-extremum", "method-separation"])
def test_student_cards_show_real_case_conditions_and_signed_range_evidence(case, method):
    from tests.solver.test_graph_stage_three_methods import finish, start

    state = finish(start(accepted(case)["candidate"], method))
    assert state["status"] == "method_complete", state["diagnostics"]
    cards = state["fragments"]
    assert all("*" not in card["explanation"] and "sqrt(" not in card["explanation"] for card in cards)
    if method == "method-interval-extremum":
        conditional = [card for card in cards if card["case_path"]]
        assert conditional and all(card["highlight"]["items"][0]["label"].startswith("当 $") for card in conditional)
        conditions = [card for card in conditional if card["display_unit"] == "conditions"]
        assert conditions and all(card["explanation"].startswith(r"由 $\begin{cases}") for card in conditions)
        bounds = [card for card in conditional if card["display_unit"] == "classified_range"]
        assert bounds and all(card["explanation"].startswith(r"$\because\ ") for card in bounds)
        if case == "q07":
            constant, = [card for card in cards if card["display_unit"] == "linear_range"]
            assert constant["explanation"] == r"$\because\ m=0$，$\therefore\ g(x)=-1$，为常数。"
            rising, = [card for card in bounds if "m > 0" in card["explanation"]]
            assert "开口向上" in rising["explanation"] and "右端点离对称轴更远" in rising["explanation"]
            assert r"g(x)_{\max}=g\left(3\right)=6 m - 1" in rising["explanation"]
    elif case == "q06":
        negative, = [card for card in cards if card["display_unit"] == "negative_divided"]
        assert r"$\therefore\ x<0$" in negative["explanation"] and "不等号变向" in negative["explanation"]
        extent, = [card for card in cards if card["display_unit"] == "reciprocal_range"]
        assert "由对勾函数的性质" in extent["explanation"]
        assert r"h(x)_{\min}=h\left(- \sqrt{2}\right)=2 \sqrt{2}" in extent["explanation"]
        assert extent["highlight"]["result"] == r"$h(x) \in \left[2 \sqrt{2}, \infty\right)$"
    else:
        inverse, = [card for card in cards if card["display_unit"] == "inverse_range"]
        assert "始终为正" in inverse["explanation"] and "端点是否取得" in inverse["explanation"]
