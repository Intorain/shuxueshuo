"""Route interpretation and original-input verification must fail independently."""

import ast as python_ast
from copy import deepcopy
from pathlib import Path

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_three import (
    calculations,
    route_constraints,
    verification,
)
from shuxueshuo_server.graph_lesson.stage_three.context import build_context
from shuxueshuo_server.graph_lesson.stage_three.trajectory import decode_value

TARGET = "/root/goals/0"
REALS = sp.S.Reals


def problem(*facts):
    return {"original_text": " ".join(facts), "root": {
        "facts": list(facts), "goals": [{"kind": "find_range", "symbol": "a"}],
    }}


def apply(candidate, source=REALS, target=TARGET):
    return route_constraints.apply_visible_constraints(build_context(candidate, target), source)


def forbidden(*args, **kwargs):
    raise AssertionError("the other side's semantic interpreter was consulted")


@pytest.mark.parametrize("verifier_entry", [
    "collect_original", "read_problem", "check_context", "_Arithmetic", "_interval",
    "_membership_ast", "_constraint_tree", "_constraint_set", "_constraint_holds",
    "_denominator_zero_set",
])
def test_route_never_calls_verifier_semantic_interpreters(monkeypatch, verifier_entry):
    candidate = problem("a∉{t∈ℝ|1/t>1}", "a∈[-2,2)", "∀x∈ℝ:x^2+1>=0")
    monkeypatch.setattr(verification, verifier_entry, forbidden)
    result, processing = apply(candidate)
    assert result == sp.Union(sp.Interval(-2, 0), sp.Interval.Ropen(1, 2))
    assert {row["source_ref"] for row in processing} == {f"/root/facts/{i}" for i in range(3)}


def test_verifier_does_not_consult_route_compiler_or_relation_sets(monkeypatch):
    for name in ("_RouteArithmetic", "_context_atoms", "_condition_set", "_member_set", "_relation_domain"):
        monkeypatch.setattr(route_constraints, name, forbidden)
    candidate = problem("a∉{t∈ℝ|1/t>1}", "∀x∈ℝ:x^2+1>=0")
    expected = sp.Union(sp.Interval(-sp.oo, 0), sp.Interval(1, sp.oo))
    result = verification.verify(candidate, TARGET, build_context(candidate, TARGET), expected)
    assert result["status"] == "verified", result


def test_production_constraints_dispatch_only_passes_route_context(monkeypatch):
    candidate = problem("a∈(0,1]", "∀x∈ℝ:x^2+1>=0")
    context = build_context(candidate, TARGET)
    monkeypatch.setattr(calculations.driver, "export_values", lambda _state: {"feasible_set": REALS})
    monkeypatch.setattr(verification, "read_problem", forbidden)
    # This operation must run with no candidate or target_ref payload at all.
    result = calculations.dispatch({"operation": "constraints", "context": context, "state": {}})
    assert decode_value(result["feasible_set_exact"]) == sp.Interval.Lopen(0, 1)


def test_route_imports_only_context_free_verification_utilities():
    module = python_ast.parse(Path(route_constraints.__file__).read_text())
    allowed = {"VerificationGap", "_algebraic_sign", "_rational_between", "_sympy_call", "_sympy_gap_boundary", "math_value"}
    imported = {alias.name for node in python_ast.walk(module)
                if isinstance(node, python_ast.ImportFrom) and node.module == "verification" for alias in node.names}
    assert imported == allowed
    assert not any(isinstance(node, python_ast.Import) and any(a.name.endswith("verification") for a in node.names)
                   for node in python_ast.walk(module))


@pytest.mark.parametrize("fault", ["strictness", "interval_closedness", "missing_denominator", "local_pole_leak"])
def test_verifier_rejects_wrong_route_interpretations_without_context_tampering(monkeypatch, fault):
    if fault == "strictness":
        candidate = problem("a>0", "∀x∈ℝ:x^2+1>=0")
        correct, wrong = sp.Interval.open(0, sp.oo), sp.Interval(0, sp.oo)
        original = route_constraints._condition_set

        def broken(ast, algebra):
            return original([">=", *ast[1:]] if ast[0] == ">" else ast, algebra)

        monkeypatch.setattr(route_constraints, "_condition_set", broken)
    elif fault == "interval_closedness":
        candidate = problem("a∈(0,1]", "∀x∈ℝ:x^2+1>=0")
        correct, wrong = sp.Interval.Lopen(0, 1), sp.Interval(0, 1)
        original = route_constraints._member_set

        def broken(value, domain, algebra):
            copied = deepcopy(domain)
            if copied[0] == "interval":
                copied[1] = True
            return original(value, copied, algebra)

        monkeypatch.setattr(route_constraints, "_member_set", broken)
    elif fault == "missing_denominator":
        candidate = problem("∀x∈ℝ:x^2+(a-1)/(a-1)>=0")
        correct, wrong = REALS - sp.FiniteSet(1), REALS
        original = route_constraints._RouteArithmetic.expr

        def broken(self, ast, depth=0):
            result = original(self, ast, depth)
            self.guards.clear()
            return result

        monkeypatch.setattr(route_constraints._RouteArithmetic, "expr", broken)
    else:
        candidate = problem("a∉{t∈ℝ|1/t>1}", "∀x∈ℝ:x^2+1>=0")
        correct = sp.Union(sp.Interval(-sp.oo, 0), sp.Interval(1, sp.oo))
        wrong = sp.Union(sp.Interval.open(-sp.oo, 0), sp.Interval(1, sp.oo))
        original = route_constraints._member_set

        def broken(value, domain, algebra):
            result = original(value, domain, algebra)
            if domain[0] == "set_builder":
                algebra.guards.append(algebra.parameter)
            return result

        monkeypatch.setattr(route_constraints, "_member_set", broken)
    context = build_context(candidate, TARGET)
    saved = deepcopy(context)
    actual, _ = route_constraints.apply_visible_constraints(context, REALS)
    assert context == saved
    assert actual == wrong and actual != correct
    result = verification.verify(candidate, TARGET, context, actual)
    assert result["status"] == "math_failed", result
    assert result["diagnostics"][0]["code"] == "verification.set_mismatch"
    assert result["counterexample"]["original_holds"] != result["counterexample"]["candidate_includes"]


def test_wrong_verifier_interval_reader_cannot_change_route_domain(monkeypatch):
    candidate = problem("a∈(0,1]", "∀x∈ℝ:x^2+1>=0")
    original = verification._interval

    def wrong_interval(ast, algebra):
        copied = deepcopy(ast)
        if copied[0] == "interval":
            copied[1] = True
        return original(copied, algebra)

    monkeypatch.setattr(verification, "_interval", wrong_interval)
    actual, _ = apply(candidate)
    assert actual == sp.Interval.Lopen(0, 1)
    result = verification.verify(candidate, TARGET, build_context(candidate, TARGET), actual)
    assert result["status"] == "math_failed", result


@pytest.mark.parametrize("restriction,expected", [
    ("a∉{t∈ℝ|1/t>1}", sp.Union(sp.Interval(-sp.oo, 0), sp.Interval(1, sp.oo))),
    ("a∉{t∈ℝ|t/t>0}", sp.FiniteSet(0)),
    ("a∉{t∈ℝ|t*t^(-1)>0}", sp.FiniteSet(0)),
    ("a∉{t∈ℝ|1/(1/t)>0}", sp.Interval(-sp.oo, 0)),
    ("1/a∉{t∈ℝ|1/t>1}", sp.Union(sp.Interval.open(-sp.oo, 0), sp.Interval.Lopen(0, 1))),
    ("(a<=0)∨(1/a>1)", sp.Union(sp.Interval.open(-sp.oo, 0), sp.Interval.open(0, 1))),
    ("a∉{t∈ℝ|(t<=0)∨(1/t>1)}", sp.Union(sp.FiniteSet(0), sp.Interval(1, sp.oo))),
    ("a/a∈({t∈ℝ|1/(t-1)>1}∪{1})", REALS - sp.FiniteSet(0)),
    ("a∈[sqrt(2),sqrt(3))", sp.Interval.Ropen(sp.sqrt(2), sp.sqrt(3))),
])
def test_expected_sets_are_authored_independently_of_either_interpreter(restriction, expected):
    candidate = problem(restriction, "∀x∈ℝ:x^2+1>=0")
    actual, _ = apply(candidate)
    assert actual == expected
    result = verification.verify(candidate, TARGET, build_context(candidate, TARGET), expected)
    assert result["status"] == "verified", result


@pytest.mark.parametrize("definition", [
    "f(t)=(a-1)/(a-1)", "f(t)=(a-1)*(a-1)^(-1)", "f(t)=1/(1/(a-1))",
])
def test_unused_definition_holes_are_original_obligations(definition):
    candidate = problem("∀x∈ℝ:x^2+1>=0")
    candidate["root"]["definitions"] = [definition]
    actual, processing = apply(candidate)
    assert actual == REALS - sp.FiniteSet(1)
    assert any(row["source_ref"] == "/root/definitions/0" and row["status"] == "original_denominator_nonzero"
               for row in processing)
    assert verification.verify(candidate, TARGET, build_context(candidate, TARGET), actual)["status"] == "verified"


def test_function_expansion_and_sibling_scope_are_route_local():
    candidate = {"original_text": "constructed context test", "root": {
        "definitions": ["f(t)=t^2+(a-1)/(a-1)"], "facts": ["a∈[-2,2]"],
        "children": [
            {"facts": ["a<1", "∀x∈ℝ:f(x)>=0"], "goals": [{"kind": "find_range", "symbol": "a"}]},
            {"facts": ["a>=1", "∀x∈ℝ:f(x)>=0"], "goals": [{"kind": "find_range", "symbol": "a"}]},
        ],
    }}
    for index, expected in enumerate((sp.Interval.Ropen(-2, 1), sp.Interval.Lopen(1, 2))):
        target = f"/root/children/{index}/goals/0"
        actual, processing = apply(candidate, target=target)
        assert actual == expected
        assert all(f"/children/{1-index}/" not in row["source_ref"] for row in processing)
        assert verification.verify(candidate, target, build_context(candidate, target), expected)["status"] == "verified"


@pytest.mark.parametrize("restriction,expected", [
    ("a<1", sp.Interval.Ropen(0, 1)),
    ("1>a", sp.Interval.Ropen(0, 1)),
    ("a<=1", sp.Interval(0, 1)),
    ("1>=a", sp.Interval(0, 1)),
    ("a∈(0,1)", sp.Interval.open(0, 1)),
    ("a∈(0,1]", sp.Interval.Lopen(0, 1)),
    ("a∈[0,1)", sp.Interval.Ropen(0, 1)),
    ("a∈[0,1]", sp.Interval(0, 1)),
])
def test_relation_spellings_and_endpoint_flags_preserve_exact_expected_sets(restriction, expected):
    candidate = problem(restriction, "∀x∈ℝ:x^2+a>=0")
    actual, _ = apply(candidate, sp.Interval(0, sp.oo))
    assert actual == expected
    assert verification.verify(candidate, TARGET, build_context(candidate, TARGET), expected)["status"] == "verified"


@pytest.mark.parametrize("restriction,expected", [
    ("a∈{t∈ℝ|1∈{t∈ℝ|t>0}}", REALS),
    ("a∉{t∈ℝ|t∈{s∈ℝ|1/s>1}}", sp.Union(sp.Interval(-sp.oo, 0), sp.Interval(1, sp.oo))),
])
def test_nested_set_binders_keep_inner_undefinedness_and_shadowing_local(restriction, expected):
    candidate = problem(restriction, "∀x∈ℝ:x^2+1>=0")
    actual, _ = apply(candidate)
    assert actual == expected
    assert verification.verify(candidate, TARGET, build_context(candidate, TARGET), expected)["status"] == "verified"


def test_direct_parameter_domain_preserves_original_nested_radical_endpoint():
    endpoint = sp.sqrt(1 + sp.sqrt(2))
    candidate = problem("a∈[sqrt(1+sqrt(2)),5]", "∀x∈ℝ:x^2+a-1>=0")
    actual, _ = apply(candidate, sp.Interval(1, sp.oo))
    assert actual == sp.Interval(endpoint, 5)
    assert actual.start == endpoint
    assert verification.verify(candidate, TARGET, build_context(candidate, TARGET), actual)["status"] == "verified"
