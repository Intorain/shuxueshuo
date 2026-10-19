"""Original-input completeness proofs, independent of method calculations."""

import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from textwrap import dedent

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_three import verification
from shuxueshuo_server.graph_lesson.stage_three.context import build_context
from shuxueshuo_server.graph_lesson.stage_three.goals import finalize_goal
from shuxueshuo_server.graph_lesson.stage_three.verification import (
    VerificationGap,
    apply_visible_constraints,
    endpoint_check,
    verify,
)

TARGET = "/root/goals/0"
Q01_SET = sp.Union(sp.Interval(-sp.oo, -1), sp.Interval(4, sp.oo))
CORPUS = Path(__file__).parent / "fixtures/graph-guided-stage-one/quadratic-always"


def problem(*facts, symbol="a", kind="find_range"):
    return {"original_text": " ".join(facts), "root": {"facts": list(facts), "goals": [
        {"kind": kind, "symbol" if kind == "find_range" else "expression": symbol}
    ]}}


def check(candidate, feasible_set, target=TARGET):
    return verify(candidate, target, build_context(candidate, target), feasible_set)


def q01():
    return json.loads((CORPUS / "q01/notation.gold.json").read_text())


def test_q01_complete_partition_independent_of_proposed_endpoints():
    valid = check(q01(), Q01_SET)
    assert valid["status"] == "verified"
    assert valid["proof"]["invariance"]["proved"] is True
    assert {"-1", "4"} <= {p["expression"] for p in valid["proof"]["critical_points"]}
    missing = check(q01(), sp.Interval(4, sp.oo))
    assert missing["status"] == "math_failed"
    assert missing["counterexample"]["reason"] == "missing_feasible_point"
    assert missing["counterexample"]["parameter"]["expression"] == "-2"


@pytest.mark.parametrize("candidate_set", [
    sp.Union(sp.Interval.open(-sp.oo, -1), sp.Interval(4, sp.oo)),
    sp.Union(sp.Interval(-sp.oo, -1), sp.Interval.open(4, sp.oo)),
    sp.S.Reals, sp.S.EmptySet,
])
def test_wrong_endpoint_or_segment_is_rejected(candidate_set):
    result = check(q01(), candidate_set)
    assert result["status"] == "math_failed"
    c = result["counterexample"]
    assert c["original_holds"] != c["candidate_includes"]


@pytest.mark.parametrize("fact,solution", [
    ("∀x∈ℝ:x^2-a^2>=0", sp.FiniteSet(0)),
    ("∀x∈ℝ:x^2+(a-2)^2>=0", sp.S.Reals),
    ("∀x∈ℝ:x^2-a^2-1>=0", sp.S.EmptySet),
    ("∀x∈ℝ:x^2+2*a*x+a^2>=0", sp.S.Reals),
    ("∀x∈ℝ:x^2+a^4-1>=0", sp.Union(sp.Interval(-sp.oo, -1), sp.Interval(1, sp.oo))),
])
def test_singleton_real_empty_repeated_root_and_parameter_polynomial(fact, solution):
    result = check(problem(fact), solution)
    assert result["status"] == "verified", result
    assert json.dumps(result)


def test_isolated_feasible_point_cannot_be_lost():
    result = check(problem("∀x∈ℝ:x^2-(a-2)^2>=0"), sp.S.EmptySet)
    assert result["status"] == "math_failed"
    assert result["counterexample"]["parameter"]["expression"] == "2"


def test_changed_symbols_and_coefficients_use_same_proof():
    candidate = problem("∀t∈ℝ:-2*t^2+8*t+7<=b^2-5*b", symbol="b")
    expected = sp.Union(sp.Interval(-sp.oo, (5-sp.sqrt(85))/2), sp.Interval((5+sp.sqrt(85))/2, sp.oo))
    result = check(candidate, expected)
    assert result["status"] == "verified", result


@pytest.mark.parametrize("restriction, expected", [
    ("a<1", sp.Interval.Ropen(0, 1)), ("a∈(-1,1]", sp.Interval(0, 1)),
    ("a=1", sp.FiniteSet(1)),
    ("a!=1", sp.Union(sp.Interval.Ropen(0, 1), sp.Interval.open(1, sp.oo))),
    ("a<0", sp.S.EmptySet), ("a∈(-∞,+∞)", sp.Interval(0, sp.oo)),
])
def test_full_visible_parameter_constraints_are_applied_and_verified(restriction, expected):
    candidate = problem(restriction, "∀x∈ℝ:x^2+a>=0")
    context = build_context(candidate, TARGET)
    actual, processing = apply_visible_constraints(candidate, TARGET, context, sp.Interval(0, sp.oo))
    assert actual == expected
    assert {p["source_ref"] for p in processing} == {"/root/facts/0", "/root/facts/1"}
    assert verify(candidate, TARGET, context, actual)["status"] == "verified"


def test_omitted_restriction_from_candidate_answer_is_refuted():
    result = check(problem("a<1", "∀x∈ℝ:x^2+a>=0"), sp.Interval(0, sp.oo))
    assert result["status"] == "math_failed"
    assert any(e["source_ref"] == "/root/facts/0" and not e["holds"] for e in result["counterexample"]["evidence"])


@pytest.mark.parametrize("field", ["entries", "symbols", "default_domains", "bound_symbols"])
def test_independent_collection_detects_driver_context_omissions(field):
    candidate = problem("a<1", "∀x∈ℝ:x^2+a>=0")
    context = build_context(candidate, TARGET)
    context[field] = []
    result = verify(candidate, TARGET, context, sp.Interval.Ropen(0, 1))
    assert result["status"] == "math_failed"
    assert result["diagnostics"][0]["code"] == "constraint_context_mismatch"


def test_changed_source_ast_and_extra_context_cannot_be_trusted():
    candidate = problem("a<1", "∀x∈ℝ:x^2+a>=0")
    for mutation in ("ast", "source", "extra"):
        context = build_context(candidate, TARGET)
        if mutation == "ast":
            context["entries"][0]["ast"][0] = ">"
        elif mutation == "source":
            context["entries"][0]["source_ref"] = "/root/facts/99"
        else:
            context["entries"].append(deepcopy(context["entries"][0]))
        assert verify(candidate, TARGET, context, sp.Interval.Ropen(0, 1))["status"] == "math_failed"


def test_original_canceled_denominator_is_preserved():
    candidate = problem("∀x∈ℝ:x^2+(a-1)/(a-1)>=0")
    context = build_context(candidate, TARGET)
    expected = sp.S.Reals - sp.FiniteSet(1)
    actual, processing = apply_visible_constraints(candidate, TARGET, context, sp.S.Reals)
    assert actual == expected
    assert any(p["status"] == "original_denominator_nonzero" for p in processing)
    assert verify(candidate, TARGET, context, expected)["status"] == "verified"
    result = verify(candidate, TARGET, context, sp.S.Reals)
    assert result["status"] == "math_failed"
    assert result["counterexample"]["parameter"]["expression"] == "1"
    assert result["counterexample"]["evidence"][0]["kind"] == "definedness"
    context["well_definedness"] = []
    assert verify(candidate, TARGET, context, expected)["status"] == "math_failed"


def test_negative_power_definition_condition_survives_simplification():
    candidate = problem("∀x∈ℝ:x^2+(a-1)*(a-1)^(-1)>=0")
    assert check(candidate, sp.S.Reals - sp.FiniteSet(1))["status"] == "verified"
    assert check(candidate, sp.S.Reals)["status"] == "math_failed"


@pytest.mark.parametrize("facts", [
    ["∀x∈ℝ:x^2+1/a>=0"], ["∀x∈ℝ:x^3+a>0"], ["∃x∈ℝ:x^2+a>=0"],
    ["∀x∈[0,1]:x^2+a>=0"], ["a^2<1", "∀x∈ℝ:x^2+a>=0"],
    ["∀x∈ℝ:x^2+a>=0", "∀t∈ℝ:t^2+a>=0"],
    ["b>0", "∀x∈ℝ:x^2+a>=0"], ["∀x∈ℝ:x^2+x/x+a>=0"],
])
def test_unregistered_input_categories_are_explicit_gaps(facts):
    result = check(problem(*facts), sp.S.Reals)
    assert result["status"] == "capability_gap", result
    assert result["diagnostics"][0]["code"] == "verification_incomplete"


@pytest.mark.parametrize("fact,expected", [
    ("∀x∈ℝ:a*x^2+1>=0", sp.Interval(0, sp.oo)),
    ("∀x∈ℝ:x^2+a>0", sp.Interval.open(0, sp.oo)),
    ("∀x∈ℝ:-x^2+a>=0", sp.S.EmptySet),
    ("∀x∈ℝ:a^2*x^2+a*x>=0", sp.FiniteSet(0)),
    ("∀x∈ℝ:a^2*x^2+a*x>0", sp.S.EmptySet),
    ("∀x∈ℝ:a*x^2+1<=0", sp.S.EmptySet),
])
def test_parameter_leading_coefficient_strictness_and_degenerate_original_proofs(fact, expected):
    candidate = problem(fact)
    correct = check(candidate, expected)
    assert correct["status"] == "verified", correct
    wrong = check(candidate, sp.S.Reals if expected != sp.S.Reals else sp.S.EmptySet)
    assert wrong["status"] == "math_failed", wrong
    assert correct["proof"]["cells"] == wrong["proof"]["cells"]
    for cell in correct["proof"]["cells"]:
        evidence = cell["evidence"][-1]
        if not evidence["holds"]:
            witness = evidence["counterexample"]
            assert witness["bound_variable"]["expression"]
            assert witness["value"]["expression"]


def test_lexical_ancestry_keeps_parent_and_excludes_sibling():
    candidate = {"original_text": "", "root": {"facts": ["a<1"], "children": [
        {"facts": ["∀x∈ℝ:x^2+a>=0"], "goals": [{"kind": "find_range", "symbol": "a"}]},
        {"facts": ["a<0"], "goals": [{"kind": "find_range", "symbol": "a"}]}
    ]}}
    target = "/root/children/0/goals/0"
    result = check(candidate, sp.Interval.Ropen(0, 1), target)
    assert result["status"] == "verified", result
    assert result["proof"]["source_refs"] == ["/root/facts/0", "/root/children/0/facts/0"]


def test_function_definition_expansion_uses_original_source():
    candidate = json.loads((CORPUS / "q10/notation.gold.json").read_text())
    result = check(candidate, sp.Interval(-sp.sqrt(3), sp.sqrt(3)), "/root/children/0/goals/0")
    assert result["status"] == "verified", result
    assert "/root/definitions/0" in result["proof"]["source_refs"]


def test_endpoint_evidence_and_typed_range_closure_include_empty_set():
    result = endpoint_check(q01(), TARGET, Q01_SET)
    assert result["status"] == "passed"
    assert {p["point"]["expression"] for p in result["points"]} == {"-1", "4"}
    assert all(p["included"] and p["holds"] for p in result["points"])
    assert finalize_goal({"kind": "find_range"}, sp.S.EmptySet) == {
        "kind": "find_range", "status": "set", "set": {"expression": "EmptySet", "latex": r"\emptyset"}
    }
    with pytest.raises(VerificationGap, match="unsupported_kind"):
        finalize_goal({"kind": "find_minimum"}, sp.Interval(0, 1))


def test_algebraic_parameter_domain_is_partitioned_at_its_exact_boundary():
    candidate = problem("a∈[0,sqrt(2))", "∀x∈ℝ:x^2+a>=0")
    expected = sp.Interval.Ropen(0, sp.sqrt(2))
    result = check(candidate, expected)
    assert result["status"] == "verified", result
    assert any(p["expression"] == "sqrt(2)" for p in result["proof"]["critical_points"])
    assert any(p["isolating_intervals"] for p in result["proof"]["critical_polynomials"])


def test_unused_function_definition_cannot_hide_parameter_denominator():
    candidate = problem("∀x∈ℝ:x^2+1>=0")
    candidate["root"]["definitions"] = ["f(t)=(a-1)/(a-1)"]
    expected = sp.S.Reals - sp.FiniteSet(1)
    result = check(candidate, expected)
    assert result["status"] == "verified", result
    invalid = check(candidate, sp.S.Reals)
    assert invalid["status"] == "math_failed"
    assert invalid["counterexample"]["evidence"][0]["source_ref"] == "/root/definitions/0"


def cubic_root():
    variable = sp.Symbol("t")
    return sp.CRootOf(variable**3-variable-1, 0)


@pytest.mark.parametrize("fact", [
    "∀x∈ℝ:x^2+a^3-a-1>=0",
    "∀x∈ℝ:x^2+2*a*x+a^2+a^3-a-1>=0",
])
def test_rootof_critical_boundary_is_included_with_an_exact_zero_certificate(fact):
    root = cubic_root()
    candidate = problem(fact)
    closed = sp.Interval(root, sp.oo)
    result = check(candidate, closed)
    assert result["status"] == "verified", result
    point = next(cell for cell in result["proof"]["cells"]
                 if cell["kind"] == "critical_point" and "CRootOf" in cell["sample"]["expression"])
    certificate = point["evidence"][-1]["certificate"]
    assert point["holds"] is True
    assert certificate["identity_verified"] is True
    assert certificate["minimum"]["expression"] == "0" and certificate["minimum_sign"] == 0
    assert endpoint_check(candidate, TARGET, closed)["status"] == "passed"

    opened = sp.Interval.open(root, sp.oo)
    wrong = check(candidate, opened)
    assert wrong["status"] == "math_failed", wrong
    assert wrong["counterexample"]["reason"] == "missing_feasible_point"
    assert wrong["counterexample"]["original_holds"] is True
    boundary = endpoint_check(candidate, TARGET, opened)
    assert boundary["status"] == "failed"
    assert boundary["points"][0]["holds"] is True and boundary["points"][0]["included"] is False


@pytest.mark.parametrize("fact,solution", [
    ("∀x∈ℝ:x^2+(a^3-a-1)^2>=0", sp.S.Reals),
    ("∀x∈ℝ:x^2-(a^3-a-1)^2>=0", "singleton"),
])
def test_repeated_rootof_critical_point_never_becomes_a_hole(fact, solution):
    root = cubic_root()
    expected = sp.FiniteSet(root) if solution == "singleton" else solution
    candidate = problem(fact)
    assert check(candidate, expected)["status"] == "verified"
    omitted = check(candidate, expected - sp.FiniteSet(root))
    assert omitted["status"] == "math_failed"
    assert omitted["counterexample"]["reason"] == "missing_feasible_point"


@pytest.mark.parametrize("value,expected", [
    (cubic_root(), 1), (-cubic_root(), -1),
    (cubic_root()**2-cubic_root(), 1),
    (cubic_root()**3-cubic_root()-1, 0),
    (sp.sqrt(2)-sp.sqrt(3), -1),
    (sp.sqrt(3)-sp.sqrt(2), 1),
    (sp.sqrt(2)+sp.sqrt(3)-sp.sqrt(5+2*sp.sqrt(6)), 0),
])
def test_algebraic_sign_is_proved_by_minimal_polynomial_or_rational_bounds(value, expected):
    assert verification._algebraic_sign(value) == expected


def test_nonzero_rootof_coefficients_have_exact_positive_and_negative_point_verdicts():
    candidate = problem("∀x∈ℝ:x^2+2*a*x+a^2+a>=0")
    original = verification.read_problem(candidate, TARGET)
    for value, expected in ((cubic_root(), True), (-cubic_root(), False)):
        holds, evidence = verification._point(original, value)
        assert holds is expected
        assert evidence[-1]["certificate"]["minimum_sign"] == (1 if expected else -1)
        assert evidence[-1]["certificate"]["identity_verified"] is True
        if not expected:
            counterexample = evidence[-1]["counterexample"]
            assert counterexample["bound_variable"] == verification.math_value(verification._algebraic_value(-value))
            assert counterexample["value"] == verification.math_value(verification._algebraic_value(value))
            actual = original.expression.subs(original.parameter, value).subs(original.x, -value)
            assert verification._algebraic_value(actual - value) == 0
            assert verification._algebraic_sign(actual) == -1


def test_perfect_square_with_nonzero_rootof_coefficients_has_zero_minimum():
    candidate = problem("∀x∈ℝ:x^2+2*a*x+a^2>=0")
    original = verification.read_problem(candidate, TARGET)
    holds, evidence = verification._point(original, cubic_root())
    assert holds is True
    certificate = evidence[-1]["certificate"]
    assert certificate["minimum"] == {"expression": "0", "latex": "0"}
    assert certificate["minimum_sign"] == 0 and certificate["identity_verified"] is True
    assert certificate["vertex"] == verification.math_value(verification._algebraic_value(-cubic_root()))


def test_perfect_square_critical_algebraic_boundary_comes_from_extra_constraint():
    candidate = problem("a∈[sqrt(2),2)", "∀x∈ℝ:x^2+2*a*x+a^2>=0")
    feasible = sp.Interval.Ropen(sp.sqrt(2), 2)
    result = check(candidate, feasible)
    assert result["status"] == "verified", result
    boundary = next(p for p in result["proof"]["critical_points"] if p["expression"] == "sqrt(2)")
    assert {source["kind"] for source in boundary["sources"]} == {"parameter_domain_boundary"}
    assert endpoint_check(candidate, TARGET, feasible)["status"] == "passed"
    assert check(candidate, sp.Interval.open(sp.sqrt(2), 2))["status"] == "math_failed"


def test_original_cubic_denominator_zero_is_excluded_at_exact_rootof():
    candidate = problem("∀x∈ℝ:x^2+(a^3-a-1)/(a^3-a-1)>=0")
    root = cubic_root()
    assert check(candidate, sp.S.Reals-sp.FiniteSet(root))["status"] == "verified"
    wrong = check(candidate, sp.S.Reals)
    assert wrong["status"] == "math_failed"
    assert wrong["counterexample"]["evidence"][0]["kind"] == "definedness"
    assert wrong["counterexample"]["evidence"][0]["holds"] is False


def test_rootof_single_point_verification_does_not_trust_inequality_solver_sets(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("a structural solution-set comparison is not an exact point proof")

    monkeypatch.setattr(sp, "solve_univariate_inequality", forbidden)
    candidate = problem("∀x∈ℝ:x^2+a^3-a-1>=0")
    assert check(candidate, sp.Interval(cubic_root(), sp.oo))["status"] == "verified"


@pytest.mark.parametrize("value", [sp.Symbol("unresolved", real=True), sp.Float("1.25"), sp.pi])
def test_unproved_algebraic_sign_is_a_gap_never_false(value):
    with pytest.raises(VerificationGap):
        verification._algebraic_sign(value)


def test_unavailable_exact_point_sign_propagates_as_gap_to_verification_and_endpoint(monkeypatch):
    original = verification._algebraic_value

    def unknown(value):
        if value.has(sp.CRootOf):
            raise VerificationGap("verification_incomplete:injected_unknown_sign")
        return original(value)

    monkeypatch.setattr(verification, "_algebraic_value", unknown)
    candidate = problem("∀x∈ℝ:x^2+2*a*x+a^2+a^3-a-1>=0")
    feasible = sp.Interval(cubic_root(), sp.oo)
    result = check(candidate, feasible)
    assert result["status"] == "capability_gap"
    assert result["diagnostics"][0]["code"] == "verification_incomplete"
    with pytest.raises(VerificationGap):
        endpoint_check(candidate, TARGET, feasible)


def test_nested_radical_domain_and_equivalent_rootof_answers_finish_in_bounded_child():
    # The previous nested-generator field construction took over 100 seconds
    # before crashing. A regression must fail without hanging the test process.
    script = dedent('''
        import json
        import sys
        import sympy as sp
        sys.path.insert(0, "tests/solver")
        from test_graph_stage_three_verification import TARGET, check, problem
        from shuxueshuo_server.graph_lesson.stage_three.verification import endpoint_check

        lower = sp.sqrt(1 + sp.sqrt(2))
        z = sp.Symbol("x")
        root = sp.CRootOf(z**4 - 2*z**2 - 1, 1)
        candidate = problem("a∈[sqrt(1+sqrt(2)),5]", "∀x∈ℝ:x^2+a-1>=0")
        answers = [sp.Interval(lower, 5), sp.Interval(root, 5),
                   sp.Interval.Lopen(lower, 5), sp.Interval(1, 5),
                   sp.Union(sp.Interval(lower, 5), sp.Interval(0, sp.Rational(1, 2)))]
        results = [check(candidate, answer) for answer in answers]
        original_points = results[0]["proof"]["critical_points"]
        assert all(row["proof"]["critical_points"] == original_points for row in results)
        assert endpoint_check(candidate, TARGET, answers[0])["status"] == "passed"
        assert endpoint_check(candidate, TARGET, answers[1])["status"] == "passed"
        assert endpoint_check(candidate, TARGET, answers[2])["status"] == "failed"
        print(json.dumps({"statuses": [row["status"] for row in results],
                          "reasons": [row["counterexample"]["reason"] for row in results[2:]]}))
    ''')
    result = subprocess.run([sys.executable, "-c", script], cwd=Path(__file__).resolve().parents[2],
                            capture_output=True, text=True, timeout=15, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == {
        "statuses": ["verified", "verified", "math_failed", "math_failed", "math_failed"],
        "reasons": ["missing_feasible_point", "extraneous_point", "extraneous_point"],
    }


def test_minimal_polynomial_rational_reduction_preserves_exact_nested_identities():
    nested = sp.sqrt(1 + sp.sqrt(2)) * sp.sqrt(sp.sqrt(2) - 1)
    assert verification._algebraic_value(nested) == 1
    assert verification._algebraic_value(cubic_root()**3-cubic_root()) == 1


def test_algebraic_conjugates_keep_their_real_embedding_for_order_and_membership():
    z = sp.Symbol("z")
    roots = [sp.CRootOf(z**3 - 3*z + 1, index) for index in range(3)]
    assert [verification._algebraic_sign(root) for root in roots] == [-1, 1, 1]
    assert verification._compare(roots[1], roots[2]) == -1
    assert verification._contains_exact(sp.FiniteSet(roots[1]), roots[2]) is False
    witness = verification._set_mismatch(sp.Interval(roots[1], sp.oo), sp.Interval(roots[2], sp.oo))
    assert witness is not None
    assert verification._contains_exact(sp.Interval(roots[1], sp.oo), witness) is True
    assert verification._contains_exact(sp.Interval(roots[2], sp.oo), witness) is False


@pytest.mark.parametrize("error_type", [IndexError, ValueError, ZeroDivisionError])
def test_minimal_polynomial_library_failures_become_verification_gaps(monkeypatch, error_type):
    def unavailable(*args, **kwargs):
        raise error_type("injected SymPy computation failure")

    verification._algebraic_value.cache_clear()
    monkeypatch.setattr(sp, "minpoly", unavailable)
    with pytest.raises(VerificationGap, match="sympy_minimal_polynomial"):
        verification._algebraic_value(sp.sqrt(7))
    candidate = problem("a∈[sqrt(2),3]", "∀x∈ℝ:x^2+a-1>=0")
    result = check(candidate, sp.Interval(sp.sqrt(2), 3))
    assert result["status"] == "capability_gap"
    assert result["diagnostics"][0]["code"] == "verification_incomplete"
    assert "sympy_boundary_minimal_polynomial" in result["diagnostics"][0]["message"]
    assert result["diagnostics"][0]["library_exception_type"] == error_type.__name__
    assert result["diagnostics"][0]["library_exception_message"] == "injected SymPy computation failure"


@pytest.mark.parametrize("operation,error_type", [("real_roots", IndexError), ("intervals", ValueError)])
def test_exact_root_library_failures_never_turn_into_false_proofs(monkeypatch, operation, error_type):
    def unavailable(*args, **kwargs):
        raise error_type("injected SymPy root failure")

    monkeypatch.setattr(sp.Poly, operation, unavailable)
    result = check(problem("∀x∈ℝ:x^2+a>=0"), sp.Interval(0, sp.oo))
    assert result["status"] == "capability_gap"
    assert result["diagnostics"][0]["code"] == "verification_incomplete"
    assert result["diagnostics"][0]["library_exception_type"] == error_type.__name__
    assert result["diagnostics"][0]["library_exception_message"] == "injected SymPy root failure"


@pytest.mark.parametrize("error_type", [KeyError, IndexError, ValueError, TypeError])
def test_local_programming_errors_remain_visible(monkeypatch, error_type):
    def broken_partition(*args, **kwargs):
        raise error_type("local partition bookkeeping bug")

    monkeypatch.setattr(verification, "_critical", broken_partition)
    with pytest.raises(error_type, match="local partition bookkeeping bug"):
        check(problem("∀x∈ℝ:x^2+a>=0"), sp.Interval(0, sp.oo))


def test_undecidable_sympy_relational_truth_is_a_gap_at_call_and_verifier_boundaries(monkeypatch):
    def undecidable(*args, **kwargs):
        return bool(sp.Symbol("unknown", real=True) < 0)

    with pytest.raises(VerificationGap, match="sympy_comparison"):
        verification._sympy_call("comparison", undecidable)
    monkeypatch.setattr(verification, "_point", undecidable)
    result = check(problem("∀x∈ℝ:x^2+a>=0"), sp.Interval(0, sp.oo))
    assert result["status"] == "capability_gap"
    assert result["diagnostics"][0]["message"] == "sympy_computation_failed:TypeError"
    assert result["diagnostics"][0]["library_exception_type"] == "TypeError"
    assert result["diagnostics"][0]["library_exception_message"].startswith("cannot determine truth value of Relational")


def test_context_mismatch_remains_math_failure_before_sympy_gap(monkeypatch):
    def unavailable(*args, **kwargs):
        raise IndexError("injected SymPy computation failure")

    candidate = problem("a∈[sqrt(2),3]", "∀x∈ℝ:x^2+a-1>=0")
    context = build_context(candidate, TARGET)
    context["entries"] = []
    monkeypatch.setattr(sp, "minpoly", unavailable)
    result = verify(candidate, TARGET, context, sp.Interval(sp.sqrt(2), 3))
    assert result["status"] == "math_failed"
    assert result["diagnostics"][0]["code"] == "constraint_context_mismatch"


@pytest.mark.parametrize("operation", ["apply_visible_constraints", "endpoint_check"])
@pytest.mark.parametrize("error_type", [IndexError, ValueError])
def test_non_verdict_operations_convert_sympy_internal_errors_to_chained_gaps(monkeypatch, operation, error_type):
    polynomial = sp.Poly(sp.Symbol("z"), sp.Symbol("z"))

    def library_failure(*args, **kwargs):
        # Raise inside actual SymPy code, preserving the library traceback.
        return polynomial.nth(-1) if error_type is IndexError else polynomial.nth(1, 2)

    candidate = problem("a<2", "∀x∈ℝ:x^2+a>=0")
    if operation == "apply_visible_constraints":
        monkeypatch.setattr(verification, "_constraint_set", library_failure)
        args = (candidate, TARGET, build_context(candidate, TARGET), sp.Interval(0, sp.oo))
    else:
        monkeypatch.setattr(verification, "_point", library_failure)
        args = (candidate, TARGET, sp.Interval.Ropen(0, 2))
    with pytest.raises(VerificationGap, match="sympy_" + operation) as caught:
        getattr(verification, operation)(*args)
    assert isinstance(caught.value.__cause__, error_type)
    details = verification._library_exception_details(caught.value)
    assert details["library_exception_type"] == error_type.__name__
    assert details["library_exception_message"] == str(caught.value.__cause__)


@pytest.mark.parametrize("operation", ["apply_visible_constraints", "endpoint_check"])
@pytest.mark.parametrize("error_type", [KeyError, IndexError, ValueError, TypeError, verification.ContextMismatch])
def test_non_verdict_operations_do_not_hide_local_errors_or_context_mismatches(monkeypatch, operation, error_type):
    def local_failure(*args, **kwargs):
        raise error_type("local bookkeeping failure")

    candidate = problem("a<2", "∀x∈ℝ:x^2+a>=0")
    monkeypatch.setattr(verification, "read_problem", local_failure)
    args = ((candidate, TARGET, {}, sp.Interval(0, sp.oo)) if operation == "apply_visible_constraints"
            else (candidate, TARGET, sp.Interval.Ropen(0, 2)))
    with pytest.raises(error_type, match="local bookkeeping failure"):
        getattr(verification, operation)(*args)
