"""Execution, exact math, public-call and immutable display boundaries."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
import sympy as sp
from jsonschema import Draft202012Validator

from shuxueshuo_server.graph_lesson.stage_one.features import extract_features
from shuxueshuo_server.graph_lesson.stage_three import (
    capabilities,
    driver,
    execution_contracts,
)
from shuxueshuo_server.graph_lesson.stage_three.context import build_context
from shuxueshuo_server.graph_lesson.stage_three.presentation import math_step_hash
from shuxueshuo_server.graph_lesson.stage_three.trajectory import (
    decode_value,
    encode_value,
)
from shuxueshuo_server.graph_lesson.stage_three.verification import endpoint_check

ROOT = Path(__file__).resolve().parents[3]
TARGET = "/root/goals/0"
CORPUS = Path(__file__).parent / "fixtures/graph-guided-stage-one/quadratic-always"
Q01 = json.loads((CORPUS / "q01/notation.gold.json").read_text())


def candidate(fact, parameter="a", extra=()):
    return {
        "original_text": fact,
        "root": {
            "facts": [*extra, fact],
            "goals": [{"kind": "find_range", "symbol": parameter}],
        },
    }


def start(value=Q01, method="method-discriminant"):
    return driver.create_state(
        features=extract_features(value)["features"],
        context=build_context(value, TARGET),
        method=method,
        route_id="discriminant" if method == "method-discriminant" else "extremum",
        branch="discriminant" if method == "method-discriminant" else "separation",
        target_ref=TARGET,
        run_id="test",
        lesson_version="v1",
    )


def finish(state):
    for _ in range(200):
        if state["status"] != "running":
            return state
        previous = deepcopy(state)
        state = driver.advance(json.loads(json.dumps(state)))
        assert state["fragments"][: len(previous["fragments"])] == previous["fragments"]
    raise AssertionError("nonterminating")


@pytest.mark.parametrize("method", ["method-discriminant", "method-separation"])
def test_q01_exact_result_and_checkpoint_round_trip(method):
    state = finish(start(method=method))
    assert state["status"] == "method_complete", state["trajectory"]
    value = driver.export_values(state)["feasible_set"]
    assert value == sp.Union(sp.Interval(-sp.oo, -1), sp.Interval(4, sp.oo))
    state = driver.append_endpoint(state, value, endpoint_check(Q01, TARGET, value))
    assert len(state["fragments"]) == 5
    schema = json.loads(
        (ROOT / "internal/schemas/graph-math-step-v1.schema.json").read_text()
    )
    for fragment in state["fragments"]:
        Draft202012Validator(schema).validate(fragment)
        assert fragment["math_step_sha256"] == math_step_hash(fragment)
        assert all(
            "*" not in expr["display"]
            for expr in fragment["before"] + fragment["after"]
        )
    assert state["frames"] == []


@pytest.mark.parametrize("method", ["method-discriminant", "method-separation"])
@pytest.mark.parametrize(
    ("fact", "symbol", "expected"),
    [
        (
            "∀t∈ℝ: -2*t^2+8*t+1 <= b^2-2*b",
            "b",
            sp.Union(
                sp.Interval(-sp.oo, 1 - sp.sqrt(10)),
                sp.Interval(1 + sp.sqrt(10), sp.oo),
            ),
        ),
        ("∀x∈ℝ:x^2+a>=0", "a", sp.Interval(0, sp.oo)),
        ("∀z∈ℝ:z^2+4>=n^2", "n", sp.Interval(-2, 2)),
        ("∀x∈ℝ:x^2+1>=0", "a", sp.S.Reals),
        ("∀x∈ℝ:x^2-1>=0", "a", sp.S.EmptySet),
    ],
)
def test_role_based_variants(fact, symbol, expected, method):
    value = candidate(fact, symbol)
    state = finish(start(value, method))
    if method == "method-separation" and state["status"] == "capability_gap":
        assert state["trajectory"]["gap"]["code"] == "method_input_class_unavailable"
        return
    assert state["status"] == "method_complete", state["trajectory"].get("error")
    assert driver.export_values(state)["feasible_set"] == expected


def grouped_calls(steps):
    grouped = {}
    for step in steps:
        group = grouped.setdefault((step["method"], step["step"]), {})
        for call in step["calls"]:
            if call["public_ref"]:
                group.setdefault(call["public_ref"], set()).update(call["used_basis"])
    return {k: v for k, v in grouped.items() if v}


@pytest.mark.parametrize(
    "method,route",
    [("method-discriminant", "discriminant"), ("method-separation", "extremum")],
)
def test_demo_public_calls_order_basis_skips_and_step_boundaries(method, route):
    state = finish(start(method=method))
    value = driver.export_values(state)["feasible_set"]
    state = driver.append_endpoint(state, value, endpoint_check(Q01, TARGET, value))
    demo = json.loads(
        (ROOT / "site/data/graph-walk/quadratic-always-q01.source.json").read_text()
    )["routes"][route]
    expected = {}
    for step in demo["steps"]:
        for call in step["effects"]["calls"]:
            group = expected.setdefault((call["method"], call["step"]), {})
            group.setdefault(call["ref"], set()).update(call["usedBasis"])
    exceptions = json.loads(
        (
            Path(__file__).parent
            / "fixtures/graph-guided-stage-three/demo-alignment-exceptions.json"
        ).read_text()
    )["exceptions"]
    applicable = [item for item in exceptions if item["route"] == route]
    # Record the actual difference; pending review is not accepted alignment.
    for item in applicable:
        assert item["status"] in ("pending_human_confirmation", "confirmed")
        assert isinstance(item.get("reason"), str) and item["reason"].strip()
        actual_calls = [
            call
            for step in state["trajectory"]["steps"]
            if (step["method"], step["step"]) == (item["method"], item["step"])
            for call in step["calls"]
            if call["public_ref"] == item["public_ref"]
        ]
        assert actual_calls and all(
            call["capability"] == item["capability"] for call in actual_calls
        )
        group = expected[(item["method"], item["step"])]
        assert item["public_ref"] not in group
        assert item["order_before"] in group
        expanded = {}
        for reference, basis in group.items():
            if reference == item["order_before"]:
                expanded[item["public_ref"]] = set(item["used_basis"])
            expanded[reference] = basis
        expected[(item["method"], item["step"])] = expanded
    actual = grouped_calls(state["trajectory"]["steps"])
    assert actual == expected
    for key in actual:
        assert list(actual[key]) == list(expected[key])
    skipped = {
        (step["method"], step["step"], call["public_ref"])
        for step in state["trajectory"]["steps"]
        for call in step["skipped_calls"]
    }
    for step in demo["steps"]:
        assert {
            (c["method"], c["step"], c["ref"]) for c in step.get("skippedCalls", [])
        } <= skipped
    mapping = json.loads(
        (
            Path(__file__).parent
            / "fixtures/graph-guided-stage-three/demo-step-alignment.json"
        ).read_text()
    )["routes"][route]
    aligned = [mapping[f["display_unit"]] for f in state["fragments"]]
    assert aligned == [step["id"] for step in demo["steps"]]
    assert "d_basis" not in aligned
    for fragment, demo_step in zip(state["fragments"], demo["steps"]):
        allowed = {
            (call["method"], call["step"], call["ref"]): set(call["usedBasis"])
            for call in demo_step["effects"]["calls"]
        }
        for item in applicable:
            if item["demo_step"] == demo_step["id"]:
                allowed[(item["method"], item["step"], item["public_ref"])] = set(
                    item["used_basis"]
                )
        for reference in fragment["source_refs"]:
            parts = reference.split("/")
            if len(parts) != 5 or parts[3] != "calls":
                continue
            trace = state["trajectory"]["steps"][int(parts[2])]
            call = trace["calls"][int(parts[4])]
            if call["public_ref"] is None:
                continue
            key = (trace["method"], trace["step"], call["public_ref"])
            assert key in allowed, (demo_step["id"], reference)
            assert set(call["used_basis"]) <= allowed[key]
    assert len(applicable) == (1 if route == "extremum" else 0)


def test_parameter_strategy_precedes_range_and_application():
    state = finish(start(method="method-separation"))
    calls = [
        c["capability"] for step in state["trajectory"]["steps"] for c in step["calls"]
    ]
    assert (
        calls.index("select_quantifier_policy")
        < calls.index("complete_square")
        < calls.index("apply_quantifier_policy")
    )
    child = [s for s in state["trajectory"]["steps"] if s["depth"] == 1]
    assert child and all(s["parent_call"] for s in child)


@pytest.mark.parametrize("method", ["method-discriminant", "method-separation"])
def test_restart_at_every_operation_has_same_math_and_trace(method):
    first = start(method=method)
    final = finish(first)
    state = first
    while state["status"] == "running":
        state = driver.advance(state)
        restarted = finish(json.loads(json.dumps(state)))
        assert restarted["fragments"] == final["fragments"]
        assert restarted["trajectory"] == final["trajectory"]
        assert restarted["result"] == final["result"]


def test_bad_local_check_does_not_publish(monkeypatch):
    state = start()
    while not state["fragments"]:
        state = driver.advance(state)
    prefix = deepcopy(state["fragments"])
    original = capabilities.REGISTRY["quadratic_sign_condition"]

    def broken(**inputs):
        value = original(**inputs)
        value["checks"] = [{"kind": "tampered", "passed": False}]
        return value

    monkeypatch.setitem(capabilities.REGISTRY, "quadratic_sign_condition", broken)
    state = finish(state)
    assert state["status"] == "math_failed"
    assert state["fragments"] == prefix
    failed = state["trajectory"]["steps"][-1]["calls"][-1]
    assert failed["inputs"] and failed["outputs"]
    assert failed["postconditions"] == [{"kind": "tampered", "passed": False}]
    assert "opening" not in decode_value(state["frames"][-1]["bindings"])


def test_budget_is_retained_and_discards_uncommitted_operation():
    state = start()
    state["solve_budget_seconds"] = 0
    finished = driver.advance(state)
    assert finished["status"] == "execution_error"
    assert finished["trajectory"]["error"]["exception_type"] == "TimeoutError"
    assert finished["fragments"] == []
    assert state["status"] == "running"


@pytest.mark.parametrize("mutation", ["future", "public", "conditional", "display"])
def test_contract_self_checks(mutation):
    value = execution_contracts.read("method-discriminant")
    call = value["steps"][1]["calls"][0]
    if mutation == "future":
        call["inputs"]["relation"] = "$candidate_set"
    elif mutation == "public":
        call["public_ref"] = "skill-reciprocal-range"
    elif mutation == "conditional":
        call["guard"] = {"constant": False}
    elif mutation == "display":
        value["steps"][1]["display_units"][0]["bindings"]["after"] = ["$candidate_set"]
    with pytest.raises(ValueError):
        execution_contracts.validate_contract(value)


@pytest.mark.parametrize(
    "expression,strict,expected",
    [
        (lambda x: (x - 1) ** 2, False, sp.S.Reals),
        (lambda x: (x - 1) ** 2, True, sp.Complement(sp.S.Reals, sp.FiniteSet(1))),
        (lambda x: -x * x - 1, False, sp.S.EmptySet),
        (lambda x: -x * x, False, sp.FiniteSet(0)),
        (lambda x: sp.S.Zero, True, sp.S.EmptySet),
    ],
)
def test_sign_partition_edges(expression, strict, expected):
    x = sp.Symbol("z", real=True)
    expr = expression(x)
    roots = capabilities.solve_quadratic(expr, x)["outputs"]
    value = capabilities.quadratic_sign_pattern(expr, x, strict=strict, **roots)[
        "outputs"
    ]["solution"]
    assert value == expected


def test_codec_rejects_expression_evaluation():
    with pytest.raises(ValueError):
        decode_value({"$math": "sympify", "args": ['__import__("os")']})
    value = sp.Union(sp.Interval(-sp.oo, -sp.sqrt(2)), sp.FiniteSet(sp.sqrt(3)))
    assert decode_value(json.loads(json.dumps(encode_value(value)))) == value


def test_endpoint_source_resolves_after_existing_finalization():
    state = finish(start())
    value = driver.export_values(state)["feasible_set"]
    state["finalization"] = [
        {"capability": "constraints"},
        {"capability": "verification"},
    ]
    state = driver.append_endpoint(state, value, endpoint_check(Q01, TARGET, value))
    fragment = state["fragments"][-1]
    assert fragment["source_refs"] == ["/finalization/2"]
    assert state["finalization"][2]["capability"] == "endpoint_check"
    assert state["trajectory"]["finalization"] == state["finalization"]


@pytest.mark.parametrize(
    "roots,all_zero",
    [([-1], False), ([-1, -1], False), ([-1, 3], False), ([-1, 4], True)],
)
def test_sign_chart_rejects_incomplete_or_forged_roots(roots, all_zero):
    x = sp.Symbol("x", real=True)
    with pytest.raises(capabilities.LocalCheckFailed):
        capabilities.quadratic_sign_pattern(
            x * x - 3 * x - 4, x, [sp.Integer(r) for r in roots], False, all_zero
        )


def test_square_range_rechecks_coefficient_and_vertex():
    x = sp.Symbol("x", real=True)
    with pytest.raises(capabilities.LocalCheckFailed):
        capabilities.square_extremum(
            x * x, x, sp.S.Reals, x * x, sp.Integer(-1), sp.S.Zero, sp.S.Zero
        )
    with pytest.raises(capabilities.LocalCheckFailed):
        capabilities.square_extremum(
            x * x, x, sp.S.Reals, x * x, sp.S.One, sp.S.One, sp.S.One
        )


def test_all_method_contracts_match_frozen_schema():
    schema = json.loads(
        (ROOT / "internal/schemas/graph-method-execution-v1.schema.json").read_text()
    )
    for contract in execution_contracts.load_contracts().values():
        Draft202012Validator(schema).validate(contract)
        assert isinstance(contract["inputs"], dict)
        assert isinstance(contract["exits"], dict)


@pytest.mark.parametrize(
    "mutation",
    [
        "schema",
        "duplicate_order",
        "unknown_judgment",
        "future_judgment_dependency",
        "missing_judgment_dependency",
        "option_id",
        "future_display_dependency",
        "missing_display_dependency",
        "extra_display_binding",
        "unknown_template",
        "duplicate_display",
    ],
)
def test_execution_semantic_readiness_checks(mutation):
    contract = execution_contracts.read("method-discriminant")
    judge = contract["steps"][0]["judgments"][0]
    unit = contract["steps"][1]["display_units"][0]
    if mutation == "schema":
        contract["inputs"] = list(contract["inputs"])
        with pytest.raises(Exception) as error:
            execution_contracts.validate_contract(contract)
        assert type(error.value).__name__ == "ValidationError"
        return
    if mutation == "duplicate_order":
        contract["steps"][1]["calls"][1]["order"] = 0
    elif mutation == "unknown_judgment":
        judge["function"] = "no_such_judge"
    elif mutation == "future_judgment_dependency":
        judge["inputs"]["expression"] = "$candidate_set"
        judge["depends_on"] = ["candidate_set", "x"]
    elif mutation == "missing_judgment_dependency":
        judge["depends_on"] = ["x"]
    elif mutation == "option_id":
        judge["options"][0] = {"label": "nondegenerate"}
    elif mutation == "future_display_dependency":
        unit["bindings"]["after"] = ["$candidate_set"]
        unit["depends_on"] = ["candidate_set", "relation"]
    elif mutation == "missing_display_dependency":
        unit["depends_on"] = ["relation"]
    elif mutation == "extra_display_binding":
        unit["bindings"]["invisible"] = "$relation"
    elif mutation == "unknown_template":
        unit["template"] = "no_such_template"
    elif mutation == "duplicate_display":
        contract["steps"][2]["display_units"][0]["id"] = unit["id"]
    with pytest.raises(ValueError):
        execution_contracts.validate_contract(contract)


def test_display_bindings_drive_actual_rendering(monkeypatch):
    contracts = execution_contracts.load_contracts()
    unit = contracts["method-discriminant"]["steps"][1]["display_units"][0]
    unit["bindings"]["after"] = ["$normal_expression"]
    unit["depends_on"] = ["normal_expression", "relation"]
    execution_contracts.validate_contract(contracts["method-discriminant"])
    monkeypatch.setattr(
        execution_contracts, "load_contracts", lambda: deepcopy(contracts)
    )
    state = start()
    while not state["fragments"]:
        state = driver.advance(state)
    assert (
        state["fragments"][0]["after"][0]["expression"] == "a**2 - 3*a + x**2 - 2*x - 3"
    )
    assert not state["fragments"][0]["after"][0]["display"].endswith("0")


@pytest.mark.parametrize("mode", ["empty", "raised"])
def test_missing_or_raised_local_checks_keep_failed_evidence(monkeypatch, mode):
    original = capabilities.REGISTRY["normalize_to_zero"]

    def broken(**inputs):
        output = original(**inputs)
        if mode == "empty":
            output["checks"] = []
            return output
        return capabilities.result(
            output["outputs"],
            output["operations"],
            [{"kind": "raised_failure", "passed": False}],
        )

    monkeypatch.setitem(capabilities.REGISTRY, "normalize_to_zero", broken)
    state = finish(start())
    assert state["status"] == "math_failed"
    assert state["fragments"] == []
    call = state["trajectory"]["steps"][-1]["calls"][-1]
    assert call["inputs"] and call["outputs"]
    assert call["postconditions"][0]["passed"] is False
    assert "normalized" not in decode_value(state["frames"][-1]["bindings"])


def test_explicit_empty_result_checks_are_rejected():
    with pytest.raises(capabilities.LocalCheckFailed) as error:
        capabilities.result({"value": sp.S.One}, checks=[])
    assert error.value.evidence["outputs"] == {"value": sp.S.One}


def test_contract_preparation_is_not_charged_to_math_budget(monkeypatch):
    import time

    load = execution_contracts.load_contracts

    def delayed():
        time.sleep(0.03)
        return load()

    state = start()
    state["solve_budget_seconds"] = 0.02
    monkeypatch.setattr(execution_contracts, "load_contracts", delayed)
    state = driver.advance(state)
    assert state["status"] == "running"
    assert state["compute_seconds"] < 0.02


def test_separation_binding_is_a_checked_contract_call_not_initial_state(monkeypatch):
    original = capabilities.REGISTRY["separate_parameter"]
    calls = []

    def observe(**inputs):
        calls.append(deepcopy(inputs))
        return original(**inputs)

    monkeypatch.setitem(capabilities.REGISTRY, "separate_parameter", observe)
    monkeypatch.setattr(capabilities, "separate_parameter", observe)
    state = start(method="method-separation")
    assert calls == []
    assert "parameter_expression" not in decode_value(state["frames"][0]["bindings"])
    state = driver.advance(state)
    assert len(calls) == 1
    trace = state["trajectory"]["steps"][0]
    call = trace["calls"][0]
    assert call["capability"] == "separate_parameter"
    assert call["public_ref"] is None
    assert {check["kind"] for check in call["postconditions"]} == {
        "separated_symbol_roles",
        "direction_residual",
    }
    assert all(check["passed"] for check in call["postconditions"])
    bindings = decode_value(state["frames"][0]["bindings"])
    assert "parameter_expression" in bindings["separation_candidate"]
    assert "parameter_expression" not in bindings  # Merged only after the branch completes.
    state = finish(state)
    for skipped in state["trajectory"]["steps"][0]["skipped_calls"]:
        if skipped["public_ref"] == "skill-equality-transform":
            assert skipped["reason"] == "not_applicable"
            assert skipped["guard_bindings"] == {"relation_kind": "inequality"}
            continue
        assert skipped["reason"] == "already_satisfied"
        assert skipped["guard"] == {"ref": "already_separated", "equals": False}
        assert skipped["guard_bindings"] == {"already_separated": True}
        assert skipped["evidence_refs"] == ["/steps/0/calls/0"]


def test_policy_application_and_restore_transformation_are_distinct_calls():
    state = finish(start(method="method-separation"))
    restore = next(
        step
        for step in state["trajectory"]["steps"]
        if step["method"] == "method-separation" and step["step"] == "restore"
    )
    apply, transform, solve = restore["calls"]
    assert [call["capability"] for call in restore["calls"]] == [
        "apply_quantifier_policy",
        "normalize_to_zero",
        "submethod",
    ]
    assert apply["operations"] == ["quantified_bound"]
    assert apply["outputs"]["condition"]["expression"] == "a**2 - 3*a >= 4"
    assert transform["inputs"]["relation"] == apply["outputs"]["condition"]
    assert transform["public_ref"] == "skill-inequality-transform"
    assert transform["outputs"]["relation"]["expression"] == "a**2 - 3*a - 4 >= 0"
    assert transform["operations"] == ["add_both_sides"]
    assert transform["used_basis"] == ["inequality-properties#addition"]
    assert solve["inputs"]["relation"] == transform["outputs"]["relation"]
    assert not restore["skipped_calls"]


def test_full_real_square_does_not_claim_interval_computation_already_done():
    state = finish(start(method="method-separation"))
    step = next(
        step
        for step in state["trajectory"]["steps"]
        if step["method"] == "method-square-extremum" and step["step"] == "range"
    )
    skipped = step["skipped_calls"][0]
    assert skipped["reason"] == "not_selected"
    assert skipped["guard_bindings"] == {"requires_interval": False}
    assert skipped["evidence_refs"]
    assert (
        step["judgments"][0]["evidence"]["evidence"]["reason"]
        == "whole_real_square_range"
    )


def test_restore_transform_failure_never_calls_solver_or_publishes_range(monkeypatch):
    original = capabilities.REGISTRY["normalize_to_zero"]

    def bad(**inputs):
        output = original(**inputs)
        output["checks"] = [{"kind": "injected_restore_failure", "passed": False}]
        return output

    monkeypatch.setitem(capabilities.REGISTRY, "normalize_to_zero", bad)
    state = finish(start(method="method-separation"))
    assert state["status"] == "math_failed"
    assert [fragment["display_unit"] for fragment in state["fragments"]] == [
        "separated",
        "policy",
        "range",
    ]
    restore = state["trajectory"]["steps"][-1]
    assert restore["calls"][-1]["capability"] == "normalize_to_zero"
    assert not any(call["capability"] == "submethod" for call in restore["calls"])
    assert "parameter_condition" not in decode_value(state["frames"][-1]["bindings"])


def test_failed_preseparation_check_publishes_neither_skip_claim_nor_math(monkeypatch):
    original = capabilities.REGISTRY["separate_parameter"]

    def failed(**inputs):
        output = original(**inputs)
        output["checks"] = [{"kind": "separation_direction", "passed": False}]
        return output

    monkeypatch.setitem(capabilities.REGISTRY, "separate_parameter", failed)
    state = finish(start(method="method-separation"))
    assert state["status"] == "math_failed"
    assert state["fragments"] == []
    assert state["trajectory"]["steps"][0]["skipped_calls"] == []
    assert (
        state["trajectory"]["steps"][0]["calls"][0]["postconditions"][0]["passed"]
        is False
    )
    assert "already_separated" not in decode_value(state["frames"][0]["bindings"])
