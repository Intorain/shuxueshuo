"""Variable-swap acceptance from original recordings and independent math gold.

GRAPH_STAGE_THREE_BATCH_FIVE_RUN_DIR retains the complete 22-sample batch and
Q08/Q09 human-step/source comparison. Automatic checks never approve teaching
granularity: the generated comparison stays pending_human_review.
"""

import json
import os
from copy import deepcopy
from pathlib import Path

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_one.features import extract_features
from shuxueshuo_server.graph_lesson.stage_three import (
    driver,
    execution_contracts,
    runner,
)
from shuxueshuo_server.graph_lesson.stage_three.context import build_context
from shuxueshuo_server.graph_lesson.stage_three.contracts import ROOT
from shuxueshuo_server.graph_lesson.stage_three.trajectory import decode_value
from shuxueshuo_server.graph_lesson.stage_three.verification import endpoint_check
from shuxueshuo_server.problem_understanding.review_contract import pointer
from tests.solver.test_graph_stage_three_batch_four import (
    ANSWERS as EARLIER_ANSWERS,
)
from tests.solver.test_graph_stage_three_batch_four import (
    _calls,
    _checked,
    _executed_refs,
    _gold_set,
    _math,
)
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
from tests.solver.test_graph_stage_three_methods import finish
from tests.solver.test_graph_stage_three_recorded import (
    SELECTION_GOLD,
    STAGE_ONE_BATCH,
    forbid_live_providers_and_network,  # noqa: F401 — shared autouse fixture
)
from tests.solver.test_graph_stage_three_verification import TARGET, check

# Independently: Q08 has positive m-slope and requires f(3)<0. Q09 has
# x-dependent a-slope, requiring BOTH f(-1)=1-x²>0 and f(1)=(x-1)²>0.
ANSWERS = {
    **EARLIER_ANSWERS,
    "q08": sp.Interval.open((1 - sp.sqrt(5)) / 2, (1 + sp.sqrt(5)) / 2),
    "q09": sp.Interval.open(-1, 1),
}
Q09_EXISTS = sp.S.Reals - sp.FiniteSet(1)
METHOD = "method-variable-swap"
HUMAN_METHOD_STEPS = {
    "v_basis": "roles", "v_rewrite": "reorder", "v_condition": "quantifier",
    "v_extremum": "range", "v_range": "solve",
}


def _variable_route(result):
    goal, = result["goals"]
    assert goal["status"] == "solved", goal
    route, = goal["routes"]
    assert route["route_id"] == "variable" and route["status"] == "verified", route
    return route


def _finish_swap(candidate):
    return finish(driver.create_state(features=extract_features(candidate)["features"],
                                      context=build_context(candidate, TARGET), method=METHOD,
                                      route_id="variable", branch="swap", target_ref=TARGET,
                                      run_id="constructed-method-case", lesson_version="v1"))


def _has_ref(ref, refs):
    return ref in refs or ("#" not in ref and any(actual.startswith(ref + "#") for actual in refs))


def _card_refs(card, trajectory):
    # Derive coverage from the referenced executed records. A presentation
    # field alone must not invent a skill or borrow one from another step.
    refs = set()
    for source in card["source_refs"]:
        record = pointer(trajectory, source)
        if _checked(record) or (record.get("selected") and record.get("decided_by") == "program"):
            if record.get("public_ref"):
                refs.add(record["public_ref"])
            refs.update(record.get("used_basis", []))
            if source.startswith("/steps/"):
                step = trajectory["steps"][int(source.split("/")[2])]
                refs.update((step["method"], step["method"] + "#" + step["step"]))
    return refs


def _human_alignment(case, sample_id, sample, trajectory, authored):
    cards = [read(sample / item["file"]) for item in trajectory["math_steps"]]
    nodes = execution_contracts.load_nodes()
    assert cards and all(card["local_check"] == "passed" for card in cards)
    assert all(execution_contracts.valid_ref(card["method_ref"], nodes) for card in cards)
    assert all(card["source_refs"] and all(pointer(trajectory, ref) for ref in card["source_refs"])
               for card in cards)
    assert all("*" not in card["explanation"] and "sqrt(" not in card["explanation"] for card in cards)
    executed = _executed_refs(trajectory)
    assert all(_has_ref(ref, executed) for step in authored.values() for ref in step["refs"])
    rows = []
    for name, step in authored.items():
        expected_method = METHOD + "#" + HUMAN_METHOD_STEPS.get(name, "")
        matching = [card for card in cards if (card["display_unit"] == "boundary" if name == "v_boundary"
                                               else card["method_ref"] == expected_method
                                               and card["display_unit"] != "boundary")]
        assert matching, (case, name, [card["method_ref"] for card in cards])
        card_refs = set().union(*(_card_refs(card, trajectory) for card in matching))
        assert all(_has_ref(ref, card_refs) for ref in step["refs"]), (case, name, step["refs"], card_refs)
        # Even source coverage and monotone card boundaries do not confirm
        # identical teaching granularity or the original drag interactions.
        rows.append({"human_step": name, "authored_refs": step["refs"],
                     "math_step_ids": [card["step_id"] for card in matching],
                     "math_step_ordinals": [card["ordinal"] for card in matching],
                     "math_step_sources": [card["source_refs"] for card in matching],
                     "route_refs_covered": all(_has_ref(ref, executed) for ref in step["refs"]),
                     "matched_card_refs": sorted(card_refs),
                     "card_refs_covered": True,
                     "status": "pending_human_review"})
    ordinals = [ordinal for row in rows for ordinal in row["math_step_ordinals"]]
    assert ordinals == sorted(set(ordinals))
    return {"case_id": case, "sample_id": sample_id, "route_id": "variable",
            "status": "pending_human_review", "fully_aligned": False,
            "route_refs_covered": True, "steps": rows,
            "all_math_steps": [{"id": card["step_id"], "ordinal": card["ordinal"],
                                "method_ref": card["method_ref"], "display_unit": card["display_unit"],
                                "source_refs": card["source_refs"]} for card in cards]}


def _save_alignment(output, rows):
    value = {"status": "pending_human_review", "fully_aligned": False,
             "note": "数学金标与真实引用自动核对通过；教学粒度、交互和额外卡片仍须人工审阅。", "routes": rows}
    (output / "human-alignment.json").write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    lines = ["# Q08/Q09 更换主元：人工步骤与实际来源对照", "", "状态：pending_human_review；fully_aligned=false。",
             "", "数学结果与引用检查不等同于教学粒度已获人工确认。", ""]
    for row in rows:
        lines.extend([f"## {row['case_id'].upper()} / sample-{row['sample_id']:02d} / variable", "",
                      "| 人工步骤 | 人工引用 | 实际数学卡 | 来源指针 |", "| --- | --- | --- | --- |"])
        for step in row["steps"]:
            lines.append("| " + " | ".join((step["human_step"], ", ".join(step["authored_refs"]),
                                             ", ".join(step["math_step_ids"]) or "尚无独立卡片，待人工审阅",
                                             "; ".join(", ".join(refs) for refs in step["math_step_sources"]))) + " |")
        lines.append("")
    (output / "human-alignment.md").write_text("\n".join(lines), encoding="utf-8")


def _assert_swap_evidence(case, trajectory):
    calls = _calls(trajectory)
    reordered, = [call for call in calls if call["capability"] == "reorder_by_variable"]
    assert _checked(reordered)
    extent, = [call for call in calls if call["capability"] == "parameter_linear_range"]
    assert _checked(extent)
    assert "skill-linear-range" in {extent["public_ref"], *extent["used_basis"]}
    assert "linear-interval-extremum#interval" in extent["used_basis"]
    assert extent["outputs"]["slope_sign"] == ("positive" if case == "q08" else "unknown")
    assert extent["outputs"]["endpoint_mode"] == ("right_endpoint" if case == "q08" else "both_endpoints")
    applied, = [call for call in calls if call["capability"] == "apply_quantifier_policy"]
    assert _checked(applied) and applied["outputs"]["combiner"] == "all"
    assert len(applied["outputs"]["conditions"]) == (1 if case == "q08" else 2)
    solved, = [call for call in calls if call["capability"] == "combine_variable_solutions"]
    assert _checked(solved) and _math(solved["outputs"]["solution"]) == ANSWERS[case]
    assert solved["inputs"]["combiner"] == "all"
    assert sp.Intersection(*(_math(value) for value in solved["outputs"]["solutions"])) == ANSWERS[case]
    sign, = [judgment for step in trajectory["steps"] if step["method"] == METHOD and step["step"] == "range"
             for judgment in step["judgments"] if judgment["id"] == "sign"]
    assert sign["selected"] == extent["outputs"]["slope_sign"] and sign["decided_by"] == "program"
    assert sign["inputs"]["certificate"] == extent["outputs"]["slope_certificate"]
    child_steps = [step for step in trajectory["steps"] if step["method"] == "quadratic-inequality-solve"]
    assert child_steps and all(step["depth"] == 1 and step["parent_call"] for step in child_steps)
    assert len({step["parent_call"] for step in child_steps}) == (1 if case == "q08" else 2)
    assert {step["step"] for step in child_steps} == {"normalize", "roots", "signs", "solution"}
    children = [call for call in calls if call["capability"] == "submethod"
                and call["public_ref"] == "quadratic-inequality-solve"]
    assert len(children) == (1 if case == "q08" else 2) and all(_checked(call) for call in children)
    policies = [call["outputs"]["policy"] for call in calls if call["capability"] == "select_quantifier_policy"]
    assert policies and all(policy["quantifier"] == "∀" and policy["strict"] for policy in policies)
    assert all(judgment["decided_by"] == "program" for step in trajectory["steps"] for judgment in step["judgments"])
    boundary, = [record["outputs"] for record in trajectory["finalization"] if record["capability"] == "endpoint_check"]
    assert boundary["status"] == "passed"
    assert {sp.sympify(point["point"]["expression"]) for point in boundary["points"]} == {
        ANSWERS[case].start, ANSWERS[case].end,
    }
    assert all(point["included"] is False and point["holds"] is False for point in boundary["points"])


def test_all_recordings_complete_all_authored_routes_and_keep_extended_answers(tmp_path):
    configured = os.getenv("GRAPH_STAGE_THREE_BATCH_FIVE_RUN_DIR")
    output = Path(configured) if configured else tmp_path / "recorded"
    summary = runner.run_recorded_batch(STAGE_ONE_BATCH, output, milestone="5")
    assert summary["completed"], str(output / "index.html")
    assert len(summary["results"]) == 22
    assert sum(row["eligible"] for row in summary["results"]) == 24
    assert sum(row["skipped"] for row in summary["results"]) == 2
    assert sum(row["solved"] for row in summary["results"]) == 24
    assert sum(row["verified_routes"] for row in summary["results"]) == 38
    assert not any(summary["llm"].values())
    selection_gold = read(SELECTION_GOLD)["cases"]
    answer_gold = read(SELECTION_GOLD.parent / "answers.gold.json")["cases"]
    assert {case: _gold_set(answer_gold[case]) for case in ANSWERS} == ANSWERS
    human = read(ROOT / "site/data/knowledge-next/topics/quadratic-always.json")["problems"]
    alignment = []
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
                assert case == "q11" and goal["target_ref"] == "/root/children/0/goals/0"
                continue
            expected, = [item for item in selection_gold[case] if item["target_ref"] == goal["target_ref"]]
            assert goal["d3"]["expected_answer"]["cell"] == expected["cell"]
            for branch in goal["selection"]["branches"]:
                for field in ("trigger", "applicability", "recommendation"):
                    assert branch[field] == expected["branches"][branch["branch"]][field]
            assert goal["status"] == "solved", str(sample / "index.html")
            assert all(route["status"] == "verified" for route in goal["routes"])
            if case == "q10":
                assert all(decode_value(route["feasible_set_exact"]) == Q10_ANSWERS[goal["target_ref"]]
                           for route in goal["routes"])
            if case == "q11":
                assert all(decode_value(route["feasible_set_exact"]) == sp.Interval.open(-sp.oo, sp.Rational(6, 7))
                           for route in goal["routes"])
        if case in ANSWERS:
            goal, = result["goals"]
            verified = {route["route_id"]: route for route in goal["routes"]}
            assert set(verified) == set(answer_gold[case]["routes"])
            assert all(decode_value(route["feasible_set_exact"]) == ANSWERS[case] for route in verified.values())
        if case in ("q08", "q09"):
            route = _variable_route(result)
            swap, = [branch for branch in result["goals"][0]["selection"]["branches"] if branch["branch"] == "swap"]
            assert swap["route_plan"] == "planned"
            trajectory = read(sample / route["trajectory"])
            _assert_swap_evidence(case, trajectory)
            alignment.append(_human_alignment(case, row["sample_id"], sample, trajectory,
                                               human[f"quadratic-always-{case}"]["routes"]["variable"]["steps"]))
            assert (sample / "events.jsonl").is_file() and (sample / "checkpoint.json").is_file()
        assert (sample / "index.html").is_file() and (sample / "source.png").is_file()
    assert len(alignment) == 4 and (output / "index.html").is_file()
    _save_alignment(output, alignment)
    print(f"Batch-five recorded acceptance report: {output / 'index.html'}")


@pytest.mark.parametrize("facts,symbol,expected", [
    (("∀t∈[1,3]:t*z^2-t*z-6+t<0",), "z", ANSWERS["q08"]),
    (("∀m∈[1,3]:0>m*x^2-m*x-6+m",), "x", ANSWERS["q08"]),
    (("∀m∈[1,3]:-m*x^2+m*x+6-m>0",), "x", ANSWERS["q08"]),
    (("∀m∈[1,3]:m*x^2-m*x-9+m<0",), "x", sp.Interval.open(-1, 2)),
    (("∀m∈[1,2]:m*x^2-m*x-6+m<0",), "x", sp.Interval.open(-1, 2)),
    (("∀m∈[1,3]:m*x^2-m*x-6+m<=0",), "x", sp.Interval((1-sp.sqrt(5))/2, (1+sp.sqrt(5))/2)),
    (("∃m∈[1,3]:m*x^2-m*x-6+m<0",), "x", sp.Interval.open((1-sp.sqrt(21))/2, (1+sp.sqrt(21))/2)),
    (("∀t∈[-1,1]:t*z^2-(t+1)*z+1>0",), "z", ANSWERS["q09"]),
    (("∀a∈[-1,1]:0<a*x^2-(a+1)*x+1",), "x", ANSWERS["q09"]),
    (("∀a∈[-1,1]:a*x^2-(a+1)*x+1>=0",), "x", sp.Interval(-1, 1)),
    (("∀a∈[-1,1]:a*x^2-(a+1)*x+1<0",), "x", sp.S.EmptySet),
    (("∃a∈[-1,1]:a*x^2-(a+1)*x+1>0",), "x", Q09_EXISTS),
    (("∃a∈[-1,1]:a*x^2-(a+1)*x+1<0",), "x", sp.Union(sp.Interval.open(-sp.oo, -1), sp.Interval.open(1, sp.oo))),
    (("x∈[0,2]", "∀a∈[-1,1]:a*x^2-(a+1)*x+1>0"), "x", sp.Interval.Ropen(0, 1)),
])
def test_swap_uses_actual_roles_quantifiers_endpoints_and_constraints(tmp_path, facts, symbol, expected):
    candidate = simple(*facts, symbol=symbol)
    result = runner.run_sample(constructed_upstream(tmp_path, candidate), tmp_path / "run", milestone="5")
    route = _variable_route(result)
    assert decode_value(route["feasible_set_exact"]) == expected
    assert check(candidate, expected)["status"] == "verified"
    assert endpoint_check(candidate, TARGET, expected)["status"] == "passed"
    assert not any(result["llm"].values())


@pytest.mark.parametrize("case", ["q08", "q09"])
def test_original_swap_has_real_child_traces_sign_judgment_and_ordered_card_sources(tmp_path, case):
    output = tmp_path / "run"
    result = runner.run_sample(upstream(tmp_path, case), output, milestone="5")
    route = _variable_route(result)
    trajectory = read(output / route["trajectory"])
    _assert_swap_evidence(case, trajectory)
    authored = read(ROOT / "site/data/knowledge-next/topics/quadratic-always.json")["problems"][
        f"quadratic-always-{case}"]["routes"]["variable"]["steps"]
    alignment = _human_alignment(case, 1, output, trajectory, authored)
    assert alignment["status"] == "pending_human_review" and not alignment["fully_aligned"]


@pytest.mark.parametrize("fact,expected", [
    ("∀m∈[1,3]:m+x-4<0", sp.Interval.open(-sp.oo, 1)),
    ("∀m∈[1,3]:m-4<0", sp.S.Reals),
    ("∀m∈[1,3]:m-2<0", sp.S.EmptySet),
])
def test_affine_and_constant_endpoint_conditions_never_claim_quadratic_calls(fact, expected):
    # Lower-degree goals exercise the method boundary; stage two has a
    # deliberately narrower quadratic family admission contract.
    state = _finish_swap(simple(fact, symbol="x"))
    assert state["status"] == "method_complete", state["diagnostics"]
    assert driver.export_values(state)["feasible_set"] == expected
    calls = _calls(state["trajectory"])
    affine = [call for call in calls if call["capability"] == "solve_affine_condition"]
    assert affine and all(_checked(call) for call in affine)
    assert not any(call["public_ref"] == "quadratic-inequality-solve" for call in calls)
    assert not any(step["method"] == "quadratic-inequality-solve" for step in state["trajectory"]["steps"])


def test_existential_q09_keeps_x_two_witness_and_unions_endpoint_sets(tmp_path):
    candidate = simple("∃a∈[-1,1]:a*x^2-(a+1)*x+1>0", symbol="x")
    result = runner.run_sample(constructed_upstream(tmp_path, candidate), tmp_path / "run", milestone="5")
    route = _variable_route(result)
    actual = decode_value(route["feasible_set_exact"])
    assert actual == Q09_EXISTS and actual.contains(2) is sp.S.true
    assert sp.Integer(1) * 2**2 - (1 + 1) * 2 + 1 == 1
    original_intersection = check(candidate, ANSWERS["q09"])
    assert original_intersection["status"] == "math_failed"
    assert original_intersection["counterexample"]["reason"] == "missing_feasible_point"
    trajectory = read(tmp_path / "run" / route["trajectory"])
    policies = [call["outputs"]["policy"] for call in _calls(trajectory)
                if call["capability"] == "select_quantifier_policy"]
    assert policies and all(policy["quantifier"] == "∃" for policy in policies)
    applied, = [call for call in _calls(trajectory) if call["capability"] == "apply_quantifier_policy"]
    solved, = [call for call in _calls(trajectory) if call["capability"] == "combine_variable_solutions"]
    assert applied["outputs"]["combiner"] == solved["inputs"]["combiner"] == "any"
    assert len(applied["outputs"]["conditions"]) == 2
    assert {_math(value) for value in solved["outputs"]["solutions"]} == {ANSWERS["q09"], Q09_EXISTS}
    assert sp.Union(*(_math(value) for value in solved["outputs"]["solutions"])) == Q09_EXISTS


@pytest.mark.parametrize("case,bad_set", [
    ("q08", sp.Interval((1-sp.sqrt(5))/2, (1+sp.sqrt(5))/2)),
    ("q08", sp.Interval.open((1-sp.sqrt(21))/2, (1+sp.sqrt(21))/2)),
    ("q08", sp.Interval.open(0, 1)), ("q08", sp.S.Reals),
    ("q09", sp.Interval(-1, 1)), ("q09", Q09_EXISTS),
    ("q09", sp.Interval.open(0, 1)), ("q09", sp.S.EmptySet),
])
def test_original_problem_proof_rejects_wrong_endpoints_one_end_and_lost_cells(case, bad_set):
    candidate = accepted(case)["candidate"]
    correct = check(candidate, ANSWERS[case])
    assert correct["status"] == "verified", correct
    rejected = check(candidate, bad_set)
    assert rejected["status"] == "math_failed", rejected
    assert rejected["counterexample"]["original_holds"] != rejected["counterexample"]["candidate_includes"]
    assert rejected["proof"]["critical_points"] == correct["proof"]["critical_points"]
    assert rejected["proof"]["cells"] == correct["proof"]["cells"]


@pytest.mark.parametrize("fact", ["∀a∈(-1,1):a*x^2-(a+1)*x+1>0", "∃a∈ℝ:a*x^2-(a+1)*x+1>0"])
def test_uncovered_open_or_unbounded_domains_never_use_closed_endpoint_rule(tmp_path, fact):
    result = runner.run_sample(constructed_upstream(tmp_path, simple(fact, symbol="x")), tmp_path / "run", milestone="5")
    goal, = result["goals"]
    discriminant, = [branch for branch in goal["selection"]["branches"] if branch["branch"] == "discriminant"]
    assert discriminant["trigger"] == "not_triggered"
    assert goal["status"] != "solved"
    assert not any(route["status"] == "verified" for route in goal["routes"])
    assert not store(tmp_path / "run").snapshot()["handoffs"]
    assert not any(result["llm"].values())


@pytest.mark.parametrize("case", ["q08", "q09"])
@pytest.mark.parametrize("position", ["before_commit", "after_commit"])
def test_swap_resumes_without_repeating_calls_cards_or_events(tmp_path, case, position):
    output = tmp_path / "resumed"
    stopped = []

    def stop_after_actual_range(state, _durable):
        if stopped or state["method"] != METHOD:
            return
        if any(call["capability"] == "parameter_linear_range" for call in _calls(state["trajectory"])):
            stopped.append(deepcopy(state))
            raise Interrupted()

    with pytest.raises(Interrupted):
        runner.run_sample(upstream(tmp_path, case), output, milestone="5", hooks={position: stop_after_actual_range})
    assert stopped
    prefix_events = events(output)
    prefix_cards = store(output).snapshot()["math_steps"]
    assert prefix_cards and all(card["route_id"] == "variable" for card in prefix_cards)
    resumed = runner.resume_sample(output)
    route = _variable_route(resumed)
    assert decode_value(route["feasible_set_exact"]) == ANSWERS[case]
    trajectory = read(output / route["trajectory"])
    assert events(output)[:len(prefix_events)] == prefix_events
    cards = store(output).snapshot()["math_steps"]
    current = {card["step_id"]: card for card in cards}
    assert len(current) == len(cards)
    assert all(current[card["step_id"]] == card for card in prefix_cards)
    assert all(current[card["step_id"]] == card for card in stopped[0]["fragments"])
    for old_step in stopped[0]["trajectory"]["steps"]:
        matching, = [step for step in trajectory["steps"] if step["seq"] == old_step["seq"]]
        assert matching["calls"][:len(old_step["calls"])] == old_step["calls"]
    sequence = events(output)
    assert [event["seq"] for event in sequence] == list(range(1, len(sequence) + 1))
    assert sum(call["capability"] == "parameter_linear_range" for call in _calls(trajectory)) == 1
    runner.resume_sample(output)
    assert events(output) == sequence
