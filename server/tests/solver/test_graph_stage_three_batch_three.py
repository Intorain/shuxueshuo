"""Batch-three acceptance uses original recordings and independently derived sets.

GRAPH_STAGE_THREE_BATCH_THREE_RUN_DIR retains every original image, extraction
record, two-route calculation, event stream and human-readable report.
"""

import os
from pathlib import Path

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_three import execution_contracts, runner
from shuxueshuo_server.graph_lesson.stage_three.contracts import ROOT
from shuxueshuo_server.graph_lesson.stage_three.trajectory import decode_value
from shuxueshuo_server.graph_lesson.stage_three.verification import endpoint_check
from tests.solver.test_graph_stage_three_batch_two import ANSWERS as EARLIER_ANSWERS
from tests.solver.test_graph_stage_three_batch_two import Q10_ANSWERS, _gold_set
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

# Q04: max(f(1), f(2))<0 iff m+5<0 and 2m+8<0, giving m<-5.
# Q05: sup(f|(1,2))>0 iff m+5>0 or 2m+8>0, giving m>-5.
# At m=-5, (x-1)(x-4) is negative throughout (1,2); equality is excluded.
ANSWERS = {
    **EARLIER_ANSWERS,
    "q04": sp.Interval.open(-sp.oo, -5),
    "q05": sp.Interval.open(-5, sp.oo),
}
ROUTE_REFS = {
    "interval": {"quadratic-interval-extremum", "method-interval-extremum#conditions"},
    "extremum": {"reciprocal-sum-function", "skill-reciprocal-range",
                 "inequality-properties#multiplication"},
}


def _verified_routes(result):
    goal, = result["goals"]
    assert goal["status"] == "solved", goal
    routes = {route["route_id"]: route for route in goal["routes"] if route["status"] == "verified"}
    assert set(routes) == {"interval", "extremum"}, goal
    return routes


def _trace_math(value):
    return decode_value(value["exact"])


def _calls(trajectory):
    return [call for step in trajectory["steps"] for call in step["calls"]]


def _checked_refs(trajectory):
    refs = set()
    for step in trajectory["steps"]:
        for call in step["calls"]:
            if call["postconditions"] and all(check["passed"] is True for check in call["postconditions"]):
                refs.add(step["method"] + "#" + step["step"])
                if call["public_ref"]:
                    refs.add(call["public_ref"])
                refs.update(call["used_basis"])
    return refs


def _assert_endpoint_policy(case, route_id, trajectory):
    calls = _calls(trajectory)
    policies = [call["outputs"]["policy"] for call in calls if call["capability"] == "select_quantifier_policy"]
    assert policies
    assert all(policy["quantifier"] == ("∀" if case == "q04" else "∃") for policy in policies)
    assert all(policy["strict"] is True for policy in policies)
    if route_id == "extremum":
        ranges = [call["outputs"]["range"] for call in calls if call["capability"] == "reciprocal_range"]
        assert len(ranges) == 1
        extent = ranges[0]
        bounds = {_trace_math(extent["inf"]), _trace_math(extent["sup"])}
        # Either h or -h can be the actual separated function; the trace must
        # retain the exact range and both endpoint-attainment facts.
        assert bounds in ({sp.Integer(4), sp.Integer(5)}, {sp.Integer(-5), sp.Integer(-4)})
        assert extent["inf_attained"] is (case == "q04")
        assert extent["sup_attained"] is (case == "q04")
    else:
        endpoint_ranges = [call["outputs"]["range"] for call in calls
                           if call["capability"] == "endpoint_values_extremum"]
        assert endpoint_ranges
        for extent in endpoint_ranges:
            assert extent["bound"] in ("inf", "sup")
            assert {_trace_math(point["point"]) for point in extent["candidates"]} == {1, 2}
            assert all(point["attained"] is (case == "q04") for point in extent["candidates"])
    boundary, = [record["outputs"] for record in trajectory["finalization"]
                 if record["capability"] == "endpoint_check"]
    assert boundary["status"] == "passed"
    point, = boundary["points"]
    assert point["point"]["expression"] == "-5"
    assert point["included"] is False and point["holds"] is False


def test_all_recordings_preserve_selection_and_q04_q05_complete_both_routes(tmp_path):
    configured = os.getenv("GRAPH_STAGE_THREE_BATCH_THREE_RUN_DIR")
    output = Path(configured) if configured else tmp_path / "recorded"
    summary = runner.run_recorded_batch(STAGE_ONE_BATCH, output, milestone="3")
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
        assert result["input_validation"]["ok"] and all(count == 0 for count in result["llm"].values())
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
        if case in ANSWERS:
            goal, = result["goals"]
            assert goal["status"] == "solved", str(sample / "index.html")
            verified = {route["route_id"]: route for route in goal["routes"] if route["status"] == "verified"}
            assert set(verified) == set(answer_gold[case]["routes"])
            assert all(decode_value(route["feasible_set_exact"]) == ANSWERS[case] for route in verified.values())
        if case == "q10":
            assert {goal["target_ref"] for goal in result["goals"]} == set(Q10_ANSWERS)
            expected_routes = {"/root/children/0/goals/0": {"discriminant"},
                               "/root/children/1/goals/0": {"extremum", "interval"}}
            for goal in result["goals"]:
                assert goal["status"] == "solved", str(sample / "index.html")
                verified = {route["route_id"]: route for route in goal["routes"] if route["status"] == "verified"}
                assert set(verified) == expected_routes[goal["target_ref"]]
                assert all(decode_value(route["feasible_set_exact"]) == Q10_ANSWERS[goal["target_ref"]]
                           for route in verified.values())
        if case in ("q04", "q05"):
            routes = _verified_routes(result)
            for route_id, route in routes.items():
                trajectory = read(sample / route["trajectory"])
                authored = human[f"quadratic-always-{case}"]["routes"][route_id]["steps"]
                authored_refs = {ref for step in authored.values() for ref in step["refs"]}
                assert ROUTE_REFS[route_id] <= authored_refs
                assert ROUTE_REFS[route_id] <= _checked_refs(trajectory)
                cards = [read(sample / item["file"]) for item in trajectory["math_steps"]]
                assert cards and all(card["local_check"] == "passed" for card in cards)
                assert all(execution_contracts.valid_ref(card["method_ref"], nodes) for card in cards)
                _assert_endpoint_policy(case, route_id, trajectory)
            assert (sample / "events.jsonl").is_file() and (sample / "checkpoint.json").is_file()
            seen.add((case, row["sample_id"]))
        assert (sample / "index.html").is_file() and (sample / "source.png").is_file()
    assert len(seen) == 4 and (output / "index.html").is_file()
    print(f"Batch-three recorded acceptance report: {output / 'index.html'}")


@pytest.mark.parametrize("facts,symbol,expected", [
    (("∀t∈[1,2]:t^2+b*t+4<0",), "b", ANSWERS["q04"]),
    (("∃z∈(1,2):z^2+n*z+4>0",), "n", ANSWERS["q05"]),
    (("∀x∈[1,2]:0>x^2+m*x+4",), "m", ANSWERS["q04"]),
    (("∀x∈[1,2]:x^2+m*x+9<0",), "m", sp.Interval.open(-sp.oo, -10)),
    (("∃x∈(1,2):x^2+m*x+9>0",), "m", sp.Interval.open(-10, sp.oo)),
    (("∀x∈[2,4]:x^2+m*x+4<0",), "m", ANSWERS["q04"]),
    (("∃x∈(2,4):x^2+m*x+4>0",), "m", ANSWERS["q05"]),
    (("∀x∈(1,2]:x^2+m*x+4<0",), "m", sp.Interval(-sp.oo, -5)),
    (("∃x∈(1,2):x^2+m*x+4>=0",), "m", ANSWERS["q05"]),
    (("∃x∈[1,2]:x^2+m*x+4>=0",), "m", sp.Interval(-5, sp.oo)),
    (("∀x∈[1,2]:x^2+m*x+4<=0",), "m", sp.Interval(-sp.oo, -5)),
    (("m∈[-8,-4]", "∀x∈[1,2]:x^2+m*x+4<0"), "m", sp.Interval.Ropen(-8, -5)),
])
def test_both_routes_use_actual_parameters_intervals_quantifiers_and_endpoint_policy(tmp_path, facts, symbol, expected):
    candidate = simple(*facts, symbol=symbol)
    result = runner.run_sample(constructed_upstream(tmp_path, candidate), tmp_path / "run", milestone="3")
    routes = _verified_routes(result)
    assert all(decode_value(route["feasible_set_exact"]) == expected for route in routes.values())
    assert check(candidate, expected)["status"] == "verified"
    assert endpoint_check(candidate, TARGET, expected)["status"] == "passed"
    assert all(count == 0 for count in result["llm"].values())


@pytest.mark.parametrize("case,bad_set", [
    ("q04", sp.Interval(-sp.oo, -5)),
    ("q04", sp.Interval.open(-sp.oo, -6)),
    ("q05", sp.Interval(-5, sp.oo)),
    ("q05", sp.Interval.open(-4, sp.oo)),
])
def test_independent_verification_rejects_wrong_endpoint_and_missing_interval(case, bad_set):
    candidate = accepted(case)["candidate"]
    correct = check(candidate, ANSWERS[case])
    assert correct["status"] == "verified", correct
    rejected = check(candidate, bad_set)
    assert rejected["status"] == "math_failed", rejected
    assert rejected["counterexample"]["original_holds"] != rejected["counterexample"]["candidate_includes"]
    assert rejected["proof"]["cells"] == correct["proof"]["cells"]


@pytest.mark.parametrize("case", ["q06", "q07"])
def test_batch_four_capabilities_reuse_the_existing_batch_three_method_families(tmp_path, case):
    result = runner.run_sample(upstream(tmp_path, case), tmp_path / "run", milestone="3")
    routes = _verified_routes(result)
    expected = sp.Interval(-sp.oo, 2 * sp.sqrt(2)) if case == "q06" else sp.Interval.open(-sp.oo, sp.Rational(1, 6))
    assert all(decode_value(route["feasible_set_exact"]) == expected for route in routes.values())
    assert len(store(tmp_path / "run").snapshot()["handoffs"]) == 2


@pytest.mark.parametrize("position", ["before_commit", "after_commit"])
def test_interval_route_stream_prefix_and_sources_survive_resume(tmp_path, position):
    output = tmp_path / "run"
    interrupted = []

    def stop_after_interval_prefix(state, _durable):
        if state["method"] == "method-interval-extremum" and len(state["fragments"]) >= 2 and not interrupted:
            interrupted.append(True)
            raise Interrupted()

    with pytest.raises(Interrupted):
        runner.run_sample(upstream(tmp_path, "q05"), output, milestone="3", hooks={position: stop_after_interval_prefix})
    prefix = events(output)
    cards = store(output).snapshot()["math_steps"]
    assert any(card["route_id"] == "interval" for card in cards)
    resumed = runner.resume_sample(output)
    routes = _verified_routes(resumed)
    assert all(decode_value(route["feasible_set_exact"]) == ANSWERS["q05"] for route in routes.values())
    assert events(output)[:len(prefix)] == prefix
    current = {card["step_id"]: card for card in store(output).snapshot()["math_steps"]}
    assert all(current[card["step_id"]] == card for card in cards)
    sequence = events(output)
    assert [event["seq"] for event in sequence] == list(range(1, len(sequence) + 1))
    runner.resume_sample(output)
    assert events(output) == sequence
