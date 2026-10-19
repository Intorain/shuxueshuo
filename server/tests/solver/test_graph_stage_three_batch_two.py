"""Batch-two acceptance from retained evidence and independent mathematical gold.

Set GRAPH_STAGE_THREE_BATCH_TWO_RUN_DIR to keep all 22 recorded runs, their
source evidence, exact route traces, event streams and self-contained reports.
Constructed variants below are explicitly synthetic and never model evidence.
"""

import os
from copy import deepcopy
from pathlib import Path

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_three import runner
from shuxueshuo_server.graph_lesson.stage_three.contracts import ROOT
from shuxueshuo_server.graph_lesson.stage_three.trajectory import decode_value
from shuxueshuo_server.graph_lesson.stage_three.verification import endpoint_check
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

# Derived from the original inequalities, before running the implementation:
# Q02: k=0 gives -2<0; k<0 and 8k(k+1)<0 give -1<k<0.
# Q03: a=1 gives -1<0; a=-1 gives 2x-1<0 and fails; otherwise
#      a²-1<0 and (5a+3)(a-1)<0 give -3/5<a<1.
ANSWERS = {
    "q01": sp.Union(sp.Interval(-sp.oo, -1), sp.Interval(4, sp.oo)),
    "q02": sp.Interval.Lopen(-1, 0),
    "q03": sp.Interval.Lopen(-sp.Rational(3, 5), 1),
}
# Q10(1): x²-2ax+3≥0 for every real x iff a²≤3.
# Q10(2): on [1,2], min((x²+3)/(2x))=√3 is attained at x=√3;
# strict negativity at some x therefore requires a>√3.
Q10_ANSWERS = {
    "/root/children/0/goals/0": sp.Interval(-sp.sqrt(3), sp.sqrt(3)),
    "/root/children/1/goals/0": sp.Interval.open(sp.sqrt(3), sp.oo),
}
REQUIRED_REFS = {
    "method-discriminant#degree",
    "linear-interval-extremum",
    "quadratic-function-properties#definition",
    "method-discriminant#merge",
}
HUMAN_STEPS = {
    "case_basis": "d_degenerate", "degenerate_case": "d_degenerate",
    "opening": "d_position", "discriminant": "d_delta", "solution": "d_range",
    "merge_cases": "d_merge", "boundary": "d_boundary",
}


def _discriminant(result):
    goal, = result["goals"]
    assert goal["status"] == "solved", goal
    route, = [route for route in goal["routes"] if route["route_id"] == "discriminant"]
    assert route["status"] == "verified", route
    return route


def _math_steps(output, route):
    trajectory = read(output / route["trajectory"])
    return trajectory, [read(output / item["file"]) for item in trajectory["math_steps"]]


def _checked_refs(trajectory):
    refs = set()
    for step in trajectory["steps"]:
        for call in step["calls"]:
            if call["postconditions"] and all(item["passed"] for item in call["postconditions"]):
                refs.add(step["method"] + "#" + step["step"])
                if call["public_ref"]:
                    refs.add(call["public_ref"])
                refs.update(call["used_basis"])
    return refs


def _gold_set(case):
    def endpoint(text):
        return {"-oo": -sp.oo, "oo": sp.oo}[text] if text in ("-oo", "oo") else sp.Rational(text)

    return sp.Union(*(sp.Interval(endpoint(part["lower"]), endpoint(part["upper"]),
                                 left_open=not part["left_closed"], right_open=not part["right_closed"])
                      for part in case["feasible_set"]["intervals"]))


def test_all_recordings_preserve_selection_and_q01_q02_q03_publish_exact_routes(tmp_path):
    configured = os.getenv("GRAPH_STAGE_THREE_BATCH_TWO_RUN_DIR")
    output = Path(configured) if configured else tmp_path / "recorded"
    summary = runner.run_recorded_batch(STAGE_ONE_BATCH, output, milestone="2")
    assert summary["completed"], str(output / "index.html")
    assert len(summary["results"]) == 22
    assert sum(row["eligible"] for row in summary["results"]) == 24
    assert sum(row["skipped"] for row in summary["results"]) == 2
    human = read(ROOT / "site/data/knowledge-next/topics/quadratic-always.json")["problems"]
    selection_gold = read(SELECTION_GOLD)["cases"]
    answer_gold = read(SELECTION_GOLD.parent / "answers.gold.json")["cases"]
    assert {case: _gold_set(answer_gold[case]) for case in ANSWERS} == ANSWERS
    seen = set()
    for row in summary["results"]:
        case = row["case_id"]
        sample = output / row["sample_dir"]
        result = read(sample / "stage-three-result.json")
        assert result["status"] == "completed", str(sample / "index.html")
        assert result["input_validation"]["ok"]
        assert all(count == 0 for count in result["llm"].values())
        source = read(sample / "stage-one-input.json")
        assert source["statuses"]["source_reviewed"] and source["statuses"]["passed"]
        assert source["candidate"] == read(STAGE_ONE_BATCH / row["sample_dir"] / "stage-one-result.json")["candidate"]
        for goal in result["goals"]:
            if goal["status"] == "skipped":
                continue
            expected, = [item for item in selection_gold[case] if item["target_ref"] == goal["target_ref"]]
            assert goal["d3"]["expected_answer"]["cell"] == expected["cell"]
            for branch in goal["selection"]["branches"]:
                assert all(branch[key] == expected["branches"][branch["branch"]][key]
                           for key in ("trigger", "applicability", "recommendation"))
            assert not any(route["status"] in ("math_failed", "execution_error") for route in goal["routes"])
            if case not in ANSWERS:
                for route in goal["routes"]:
                    if route["status"] == "verified":
                        # Milestones restrict method families, not historical
                        # capability implementations. Batch 3 extends the
                        # existing separation family to Q04–Q07 and Q10(2).
                        reusable = {"q04": {TARGET: sp.Interval.open(-sp.oo, -5)},
                                    "q05": {TARGET: sp.Interval.open(-5, sp.oo)},
                                    "q06": {TARGET: sp.Interval(-sp.oo, 2 * sp.sqrt(2))},
                                    "q07": {TARGET: sp.Interval.open(-sp.oo, sp.Rational(1, 6))},
                                    "q11": {"/root/children/1/goals/0": sp.Interval.open(-sp.oo, sp.Rational(6, 7))},
                                    "q10": Q10_ANSWERS}
                        assert case in reusable
                        assert goal["target_ref"] in reusable[case]
                        assert decode_value(route["feasible_set_exact"]) == reusable[case][goal["target_ref"]]
        assert (sample / "index.html").is_file()
        assert (sample / "source.png").is_file()
        seen.add((case, row["sample_id"]))
        if case not in ANSWERS:
            continue
        route = _discriminant(result)
        assert decode_value(route["feasible_set_exact"]) == _gold_set(answer_gold[case])
        trajectory, cards = _math_steps(sample, route)
        assert cards and all(card["local_check"] == "passed" for card in cards)
        if case == "q01":
            assert {r["route_id"] for r in result["goals"][0]["routes"] if r["status"] == "verified"} == {
                "discriminant", "extremum",
            }
            assert all(decode_value(r["feasible_set_exact"]) == ANSWERS[case] for r in result["goals"][0]["routes"])
            assert len(cards) == 5 and all(card["case_path"] == [] for card in cards)
        else:
            authored = human[f"quadratic-always-{case}"]["routes"]["discriminant"]["steps"]
            authored_refs = {ref for step in authored.values() for ref in step["refs"]}
            assert REQUIRED_REFS <= authored_refs
            assert REQUIRED_REFS <= _checked_refs(trajectory)
            assert any(card["case_path"] for card in cards)
            order = []
            for card in cards:
                authored_step = HUMAN_STEPS.get(card["display_unit"])
                if authored_step and (not order or order[-1] != authored_step):
                    order.append(authored_step)
            # The method-introduction d_basis is the D3/D4 selection card;
            # every mathematical authored step is then covered in order.
            assert order == [step for step in authored if step != "d_basis"]
            degenerate = [(step, call) for step in trajectory["steps"] for call in step["calls"]
                          if call["capability"] == "degenerate_case_check"]
            expected_points = {0: True} if case == "q02" else {-1: False, 1: True}
            actual_points = {}
            for step, call in degenerate:
                point = decode_value(call["inputs"]["case"]["value"]["exact"])
                actual_points[point] = call["outputs"]["holds"]
                assert step["case_path"] and call["case_path"] == step["case_path"]
                assert decode_value(call["outputs"]["solution"]["exact"]) == (
                    sp.FiniteSet(point) if expected_points[point] else sp.S.EmptySet
                )
            assert actual_points == expected_points
            assert (sample / "events.jsonl").is_file()
            assert (sample / "checkpoint.json").is_file()
    assert len(seen) == 22 and (output / "index.html").is_file()
    print(f"Batch-two recorded acceptance report: {output / 'index.html'}")


@pytest.mark.parametrize("fact,symbol,expected", [
    ("∀t∈ℝ:b*t^2+2*b*t-(b+2)<0", "b", ANSWERS["q02"]),
    ("∀z∈ℝ:(m^2-1)*z^2-(m-1)*z-1<0", "m", ANSWERS["q03"]),
    ("∀x∈ℝ:0>k*x^2+2*k*x-(k+2)", "k", ANSWERS["q02"]),
    ("∀x∈ℝ:-k*x^2-2*k*x+(k+2)>0", "k", ANSWERS["q02"]),
    ("∀x∈ℝ:0>(a^2-1)*x^2-(a-1)*x-1", "a", ANSWERS["q03"]),
    ("∀x∈ℝ:(1-a^2)*x^2+(a-1)*x+1>0", "a", ANSWERS["q03"]),
    ("∀x∈ℝ:k*x^2+2*k*x-(k+2)<=0", "k", sp.Interval(-1, 0)),
    ("∀x∈ℝ:(a^2-1)*x^2-(a-1)*x-1<=0", "a", sp.Interval(-sp.Rational(3, 5), 1)),
    ("∀t∈ℝ:(b^2-1)*t^2-(b-1)*t-1>=0", "b", sp.S.EmptySet),
    ("∀x∈ℝ:k*x^2+2*k*x-(k+4)<0", "k", sp.Interval.Lopen(-2, 0)),
    ("∀x∈ℝ:(a^2-4)*x^2-(a-2)*x-1<0", "a", sp.Interval.Lopen(-sp.Rational(6, 5), 2)),
])
def test_equivalent_relations_names_and_strict_boundaries_use_original_input(tmp_path, fact, symbol, expected):
    candidate = simple(fact, symbol=symbol)
    source = constructed_upstream(tmp_path, candidate)
    output = tmp_path / "out"
    result = runner.run_sample(source, output, milestone="2")
    route = _discriminant(result)
    assert decode_value(route["feasible_set_exact"]) == expected, str(output / "index.html")
    assert check(candidate, expected)["status"] == "verified"
    assert endpoint_check(candidate, TARGET, expected)["status"] == "passed"
    assert all(count == 0 for count in result["llm"].values())


@pytest.mark.parametrize("case,bad_set,reason", [
    ("q02", sp.Interval.open(-1, 0), "missing_feasible_point"),
    ("q02", sp.S.EmptySet, "missing_feasible_point"),
    ("q02", sp.Interval(-1, 0), "extraneous_point"),
    ("q03", sp.Interval.open(-sp.Rational(3, 5), 1), "missing_feasible_point"),
    ("q03", sp.S.EmptySet, "missing_feasible_point"),
    ("q03", sp.Union(ANSWERS["q03"], sp.FiniteSet(-1)), "extraneous_point"),
    ("q03", sp.Interval(-sp.Rational(3, 5), 1), "extraneous_point"),
])
def test_independent_proof_rejects_lost_cases_wrong_intersection_and_endpoints(case, bad_set, reason):
    candidate = accepted(case)["candidate"]
    correct = check(candidate, ANSWERS[case])
    assert correct["status"] == "verified", correct
    rejected = check(candidate, bad_set)
    assert rejected["status"] == "math_failed", rejected
    assert rejected["counterexample"]["reason"] == reason
    assert rejected["counterexample"]["original_holds"] != rejected["counterexample"]["candidate_includes"]
    assert rejected["proof"]["critical_points"] == correct["proof"]["critical_points"]
    assert rejected["proof"]["cells"] == correct["proof"]["cells"]


@pytest.mark.parametrize("position", ["before_commit", "after_commit"])
def test_interrupt_inside_degenerate_case_resumes_with_stable_paths_and_prefix(tmp_path, position):
    source = upstream(tmp_path, "q03")
    output = tmp_path / "resumed"
    stopped = []

    def stop_after_first_case(state, durable):
        paths = [fragment["case_path"] for fragment in state["fragments"]]
        if not stopped and any(path and path[-1].startswith("degenerate-") for path in paths):
            stopped.append(deepcopy(state))
            raise Interrupted()

    with pytest.raises(Interrupted):
        runner.run_sample(source, output, milestone="2", hooks={position: stop_after_first_case})
    committed_prefix = store(output).snapshot()["math_steps"]
    interrupted_events = store(output).events()
    resumed = runner.resume_sample(output)
    route = _discriminant(resumed)
    assert decode_value(route["feasible_set_exact"]) == ANSWERS["q03"]
    trajectory, cards = _math_steps(output, route)
    assert cards[:len(committed_prefix)] == committed_prefix
    assert cards[:len(stopped[0]["fragments"])] == stopped[0]["fragments"]
    assert events(output)[:len(interrupted_events)] == interrupted_events
    identifiers = [card["step_id"] for card in cards]
    assert len(identifiers) == len(set(identifiers))
    assert {tuple(card["case_path"]) for card in cards if card["case_path"]} >= {
        ("degenerate-0",), ("degenerate-1",), ("nondegenerate",),
    }
    assert all(step["case_path"] in ([], ["degenerate-0"], ["degenerate-1"], ["nondegenerate"])
               for step in trajectory["steps"])
    sequence = events(output)
    assert [event["seq"] for event in sequence] == list(range(1, len(sequence) + 1))
    runner.resume_sample(output)
    assert events(output) == sequence
