"""Case frames, guarded outputs and traceable joins are real execution boundaries."""

import json
from copy import deepcopy

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_three import (
    driver,
    execution_contracts,
    judgments,
)
from shuxueshuo_server.graph_lesson.stage_three.trajectory import decode_value
from tests.solver.test_graph_stage_three_methods import CORPUS, finish, start

Q03 = json.loads((CORPUS / "q03/notation.gold.json").read_text())


def test_case_frames_are_isolated_collected_and_provenanced():
    state = start(Q03)
    paths = []
    while state["status"] == "running":
        before = deepcopy(state)
        state = driver.advance(json.loads(json.dumps(state)))
        assert before["fragments"] == state["fragments"][: len(before["fragments"])]
        if len(state["frames"]) == 2 and "descriptor" in state["frames"][-1]:
            parent, child = state["frames"]
            parent_values = decode_value(parent["bindings"])
            child_values = decode_value(child["bindings"])
            assert "case" not in parent_values
            assert "degenerate_solution" not in parent_values
            assert child_values["case"]["id"] == child["case_path"][-1]
            if child["case_path"] not in paths:
                paths.append(child["case_path"])
    assert state["status"] == "method_complete", state["diagnostics"]
    assert paths == [["degenerate-0"], ["degenerate-1"], ["nondegenerate"]]
    assert driver.export_values(state)["feasible_set"] == sp.Interval.Lopen(
        -sp.Rational(3, 5), 1
    )
    collection = next(
        row["case_results"]
        for row in state["trajectory"]["steps"]
        if "case_results" in row
    )
    assert [row["case_path"] for row in collection] == paths
    for record in collection:
        assert record["source_refs"]
        for reference in record["source_refs"]:
            _, _, index, category, position = reference.split("/")
            merge = state["trajectory"]["steps"][int(index)][category][int(position)]
            assert merge["case_path"] == record["case_path"] and merge["source_refs"]
    for step in state["trajectory"]["steps"]:
        for call in step["calls"]:
            assert call["case_path"] == step["case_path"]
            if call["capability"] == "degenerate_case_check":
                assert step["case_path"][-1].startswith("degenerate-")
            if call["capability"] == "quadratic_sign_condition":
                assert step["case_path"] == ["nondegenerate"]


def test_resume_after_each_case_keeps_ids_paths_and_sources():
    state = start(Q03)
    checkpoints = []
    seen = set()
    while state["status"] == "running":
        state = driver.advance(state)
        pending = state["frames"][0].get("pending_cases") if state["frames"] else None
        if pending and pending["index"] and pending["index"] not in seen:
            seen.add(pending["index"])
            checkpoints.append(json.loads(json.dumps(state)))
    assert len(checkpoints) == 2
    for checkpoint in checkpoints:
        resumed = finish(checkpoint)
        assert resumed["status"] == "method_complete"
        assert resumed["trajectory"] == state["trajectory"]
        assert resumed["fragments"] == state["fragments"]
        assert resumed["result"] == state["result"]


@pytest.mark.parametrize(
    "mutation",
    ["case_leak", "wrong_branch", "range_leak", "cases_future", "cases_public"],
)
def test_contract_rejects_unmerged_or_foreign_case_bindings(mutation):
    contract = execution_contracts.read("method-discriminant")
    if mutation == "case_leak":
        contract["outputs"]["candidate_set"] = "$case_solution"
    elif mutation == "wrong_branch":
        contract["steps"][3]["merges"][1]["branches"][1]["bindings"][
            "case_solution"
        ] = "$degenerate_solution"
    elif mutation == "range_leak":
        contract = execution_contracts.read("method-separation")
        contract["steps"][3]["calls"][0]["inputs"]["range"] = "$square_function_range"
    elif mutation == "cases_future":
        contract["steps"][0]["cases"]["source"] = "case_solution"
    elif mutation == "cases_public":
        contract["steps"][0]["cases"]["entry"]["calls"][0]["public_ref"] = (
            "skill-simplify"
        )
    with pytest.raises(ValueError):
        execution_contracts.validate_contract(contract)


def test_range_judgment_controls_child_execution(monkeypatch):
    def choose_interval(**_):
        return {"selected": "interval", "choice": "interval", "denominator": None}

    monkeypatch.setitem(judgments.REGISTRY, "range_skill", choose_interval)
    state = finish(start(method="method-separation"))
    assert state["status"] == "method_complete", state["diagnostics"]
    assert driver.export_values(state)["feasible_set"] == sp.Union(sp.Interval(-sp.oo, -1), sp.Interval(4, sp.oo))
    calls = [call for step in state["trajectory"]["steps"] for call in step["calls"]]
    assert any(call["capability"] == "quadratic_interval_range" for call in calls)
    assert not any(call["public_ref"] == "method-square-extremum" for call in calls)
    skipped = [
        call for step in state["trajectory"]["steps"] for call in step["skipped_calls"]
    ]
    square = next(
        call for call in skipped if call["public_ref"] == "method-square-extremum"
    )
    assert square["reason"] == "not_selected" and square["evidence_refs"]


def test_duplicate_case_identity_is_rejected_before_any_case_executes(monkeypatch):
    original = judgments.REGISTRY["degenerate_branches"]

    def duplicate(**inputs):
        value = original(**inputs)
        value["cases"][1]["id"] = value["cases"][0]["id"]
        return value

    monkeypatch.setitem(judgments.REGISTRY, "degenerate_branches", duplicate)
    state = finish(start(Q03))
    assert state["status"] == "execution_error"
    assert state["diagnostics"][-1]["code"] == "execution.invalid_case_manifest"
    assert not any(step["case_path"] for step in state["trajectory"]["steps"])


def test_omitted_case_is_not_silently_union_merged(monkeypatch):
    original = judgments.REGISTRY["degenerate_branches"]

    def omitted(**inputs):
        value = original(**inputs)
        value["cases"] = value["cases"][1:]
        return value

    monkeypatch.setitem(judgments.REGISTRY, "degenerate_branches", omitted)
    state = finish(start(Q03))
    assert state["status"] == "math_failed"
    assert state["diagnostics"][-1]["code"] == "incomplete_case_partition"
    assert state["result"] is None


def test_conditional_join_requires_exactly_one_active_branch(monkeypatch):
    contracts = execution_contracts.load_contracts()
    join = contracts["method-separation"]["steps"][2]["merges"][0]
    join["branches"].append(deepcopy(join["branches"][0]))
    monkeypatch.setattr(
        execution_contracts, "load_contracts", lambda: deepcopy(contracts)
    )
    state = finish(start(method="method-separation"))
    assert state["status"] == "capability_gap"
    assert state["diagnostics"][-1]["code"] == "execution.merge_choice_incomplete"
    assert state["result"] is None


@pytest.mark.parametrize(
    "fact,expected",
    [
        ("∀x∈ℝ:x^2+a^3>=0", sp.Interval(0, sp.oo)),
        ("∀x∈ℝ:a^3*x^2+1>=0", sp.Interval(0, sp.oo)),
        ("∀x∈ℝ:x^2+a^4>=0", sp.S.Reals),
    ],
)
def test_higher_parameter_degree_uses_explicit_polynomial_solver(fact, expected):
    from tests.solver.test_graph_stage_three_methods import candidate

    state = finish(start(candidate(fact)))
    assert state["status"] == "method_complete", state["diagnostics"]
    assert driver.export_values(state)["feasible_set"] == expected
    calls = [call for step in state["trajectory"]["steps"] for call in step["calls"]]
    assert any(call["capability"] == "solve_parameter_relation" for call in calls)


def test_uncheckpointable_parameter_root_remains_an_explicit_gap():
    from tests.solver.test_graph_stage_three_methods import candidate

    state = finish(start(candidate("∀x∈ℝ:x^2+a^3-a-1>=0")))
    assert state["status"] == "capability_gap"
    assert state["diagnostics"][-1]["code"] == "parameter_root_checkpoint_unavailable"
    assert state["result"] is None


def test_reordered_conjunction_skips_unavailable_sibling_bindings(monkeypatch):
    contracts = execution_contracts.load_contracts()
    discriminant = contracts["method-discriminant"]
    for action in discriminant["steps"][3]["calls"]:
        if "all" in action.get("guard", {}):
            action["guard"]["all"].reverse()
    execution_contracts.validate_contract(discriminant)
    monkeypatch.setattr(
        execution_contracts, "load_contracts", lambda: deepcopy(contracts)
    )
    state = finish(start(Q03))
    assert state["status"] == "method_complete", state["diagnostics"]
    assert driver.export_values(state)["feasible_set"] == sp.Interval.Lopen(
        -sp.Rational(3, 5), 1
    )
    skipped = [
        call
        for step in state["trajectory"]["steps"]
        if step["case_path"] and step["case_path"][-1].startswith("degenerate-")
        for call in step["skipped_calls"]
        if call["action_id"] == "solve"
    ]
    assert len(skipped) == 2
    assert all(
        call["reason"] == "guard_false" and call["evidence_refs"] for call in skipped
    )


@pytest.mark.parametrize("reverse", [False, True])
def test_conjunction_keeps_missing_binding_errors_unless_another_condition_is_false(
    reverse,
):
    missing = {"ref": "unavailable", "equals": "ready"}
    known = {"ref": "case.kind", "equals": "nondegenerate"}
    clauses = [missing, known]
    if reverse:
        clauses.reverse()
    guard = {"all": clauses}
    assert driver._guard(guard, {"case": {"kind": "degenerate"}}) is False
    with pytest.raises(KeyError, match="unavailable"):
        driver._guard(guard, {"case": {"kind": "nondegenerate"}})
    assert (
        driver._guard(
            guard, {"case": {"kind": "nondegenerate"}, "unavailable": "ready"}
        )
        is True
    )
