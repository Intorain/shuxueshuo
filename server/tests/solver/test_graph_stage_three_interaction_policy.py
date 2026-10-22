"""Policy witnesses come from this frozen card's exact relation and domain."""

from copy import deepcopy

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_three import interaction
from shuxueshuo_server.graph_lesson.stage_three.capabilities import (
    CapabilityGap,
    select_quantifier_policy,
)
from shuxueshuo_server.graph_lesson.stage_three.trajectory import (
    decode_value,
    encode_value,
)
from tests.solver.test_graph_stage_three_interactions import (
    _correct,
    _diagnostic,
    _known,
    _seed,
)

x, a = sp.symbols("x a", real=True)
DOMAIN = sp.Interval(1, 4)


def _policy(function, *, expression=sp.S.Zero, domain=DOMAIN, quantifier="∃", operator=">=",
            method="method-interval-extremum#quantifier", known=None):
    values = {"function": function, "parameter_expression": expression, "x": x,
              "policy": select_quantifier_policy(quantifier, operator, domain)["outputs"]["policy"]}
    kwargs = {"known": known} if known is not None else {}
    return _seed("policy", values, {"x": x, "parameter": a, "domain": domain}, method=method, **kwargs)


def _facts(seed):
    values, context = decode_value(seed["values"]), decode_value(seed["context"])
    facts = interaction._policy_facts(values, context)
    facts["known"] = interaction.known_set(seed)
    return facts, values, context


@pytest.mark.parametrize("offset,scale,constant", [(0, 1, 15), (1000, 7, 15), (-120, 3, 14)])
def test_policy_derives_exact_quadratic_equality_witnesses(offset, scale, constant):
    parameter_expression = (a - offset) / scale
    function = x**2 - parameter_expression * (x + 1) + constant
    seed = _policy(function)
    facts, values, context = _facts(seed)
    boundary = offset + scale * (-2 + 2 * sp.sqrt(constant + 1))
    points = interaction._policy_representatives(facts, values, context)
    assert boundary in points
    assert len(points) <= interaction.MAX_POLICY_REPRESENTATIVES
    assert all(point.is_real is True and point.is_finite is True and not point.has(sp.Float) for point in points)
    # At the vertex the function equals zero exactly, so allowing equality is
    # decisive even when every old grid point misses this parameter threshold.
    vertex = sp.simplify(parameter_expression.subs(a, boundary) / 2)
    assert sp.Interval(1, 4).contains(vertex) is sp.true
    assert sp.simplify(function.subs({a: boundary, x: vertex})) == 0
    chunk, diagnostics = interaction.build_chunk([seed], interaction.load_registry(), {"previous": 0})
    assert chunk["status"] == "interactive", diagnostics
    interaction.validate_chunk(chunk)
    strictness, = _diagnostic(diagnostics, "flip_strictness")
    assert strictness["result"] == "witness"
    assert _diagnostic(diagnostics, "require_attained")[0]["result"] == "unproven"
    assert _diagnostic(diagnostics, "swap_quantifier")[0]["result"] == "duplicate"
    assert "\\min" in _correct(chunk["parts"][0])[0]
    assert "值域" not in chunk["parts"][0]["question"]


@pytest.mark.parametrize("case", [False, True])
def test_policy_breakpoints_include_endpoint_thresholds_and_respect_visible_scope(case):
    known = None if case else _known("a>6", "a<7", "∃x∈[1,4]:x^2-a*x-a+15<=0")
    seed = _policy(x**2 - a * (x + 1) + 15, known=known)
    if case:
        values = decode_value(seed["values"])
        seed["values"] = encode_value({**values, "case": {"domain": sp.Interval.open(6, 7)}})
        seed["case_path"] = ["case:inside"]
    facts, values, context = _facts(seed)
    points = interaction._policy_representatives(facts, values, context)
    assert sp.Rational(31, 5) in points
    assert all(6 < point < 7 for point in points)
    _, diagnostics = interaction.build_chunk([seed], interaction.load_registry(), {"previous": 0})
    # Within this known open interval the non-strict/strict tests agree. A root
    # outside the visible scope must never be used to mark an option wrong.
    assert _diagnostic(diagnostics, "flip_strictness")[0]["result"] == "unproven"


def test_policy_does_not_read_future_card_values():
    seed = _policy(x**2 - a * (x + 1) + 15)
    future = _seed("affine_restore", {"unrelated_answer": sp.FiniteSet(12345)}, {}, ordinal=2)
    registry = interaction.load_registry()
    first, _ = interaction.compile_route([seed, future], registry)
    changed = deepcopy(future)
    changed["values"] = encode_value({"unrelated_answer": sp.FiniteSet(-99999)})
    second, _ = interaction.compile_route([seed, changed], registry)
    assert first[0] == second[0]


def test_policy_unsupported_equations_and_unknown_truths_do_not_supply_wrong_options():
    assert interaction._policy_roots(a**8 - 2, a) == []
    assert interaction._policy_roots(sp.sin(a), a) == []
    assert interaction._policy_roots(a - sp.Float("0.1"), a) == []
    answer = interaction.Candidate("correct", "correct", lambda point: point >= 0)
    unknown = interaction.Candidate("unknown", "unknown", lambda point: None)
    same = interaction.Candidate("same", "same", lambda point: point >= 0)
    kept, records, _ = interaction._proposition_check(answer, [unknown, same], [sp.Integer(-1), sp.S.Zero])
    assert kept == [] and [row[1] for row in records] == ["unproven", "unproven"]


def test_affine_reciprocal_policy_compiles_with_exact_transported_range():
    function = x - 1 + 16 / (x + 1)
    seed = _policy(function, expression=a, method="method-separation#quantifier")
    facts, values, context = _facts(seed)
    points = interaction._policy_representatives(facts, values, context)
    assert {sp.Integer(6), sp.Integer(8)} <= set(points)
    chunk, diagnostics = interaction.build_chunk([seed], interaction.load_registry(), {"previous": 0})
    assert chunk["status"] == "interactive", diagnostics
    interaction.validate_chunk(chunk)
    assert _diagnostic(diagnostics, "swap_bound")[0]["result"] == "witness"
    assert _diagnostic(diagnostics, "require_attained")[0]["result"] == "unproven"
    result = interaction.range_at(function, x, sp.Interval(1, 4))
    assert (result["inf"], result["sup"], result["inf_attained"], result["sup_attained"]) == (6, 8, True, True)
    assert result["positions"] == [
        {"location": "left_endpoint", "point": 1, "value": 8, "attained": True},
        {"location": "right_endpoint", "point": 4, "value": sp.Rational(31, 5), "attained": True},
        {"location": "critical", "point": 3, "value": 6, "attained": True},
    ]


def test_affine_reciprocal_range_restores_reversed_open_interval_coordinates():
    function = 3 - 3 * x + 4 / (2 - 3 * x)
    result = interaction.range_at(function, x, sp.Interval.open(-1, 0))
    assert (result["inf"], result["sup"], result["inf_attained"], result["sup_attained"]) == (
        5, sp.Rational(34, 5), False, False)
    assert result["positions"] == [
        {"location": "left_endpoint", "point": -1, "value": sp.Rational(34, 5), "attained": False},
        {"location": "right_endpoint", "point": 0, "value": 5, "attained": False},
    ]


def test_affine_reciprocal_policy_preserves_original_poles_and_removable_holes():
    with pytest.raises(CapabilityGap):
        interaction.range_at(x - 1 + 16 / (x + 1), x, sp.Interval(-2, 1))
    hole = sp.Mul(x - 2, sp.Pow(x - 2, -1, evaluate=False), evaluate=False)
    function = sp.Add(x - 1 + 16 / (x + 1), hole, evaluate=False)
    ranges = interaction._Ranges(function, x, sp.Interval(1, 4), a)
    assert interaction._attempt(ranges, sp.S.Zero) is None
