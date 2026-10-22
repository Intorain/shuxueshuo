"""Policy notation may use extrema only with a proof available before the range step."""

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_three import execution_contracts
from shuxueshuo_server.graph_lesson.stage_three.capabilities.quantified import (
    select_quantifier_policy,
)
from shuxueshuo_server.graph_lesson.stage_three.math_values import (
    BOUND_EXPLANATION,
    polynomial_extrema_attained,
)
from shuxueshuo_server.graph_lesson.stage_three.presentation_templates import (
    prepare_values,
    render_highlight,
    render_template,
    validate_registry,
)

u, b = sp.symbols("u b", real=True)


@pytest.mark.parametrize("function,domain,expected", [
    (u**2 - b*u - b + 15, sp.Interval(1, 4), True),
    (b*u + sp.sqrt(2), sp.Interval(-2, 3), True),
    (sp.Integer(7), sp.Interval(-2, 3), True),
    (u**2 + b, sp.Interval(2, 2), True),
    (u**2 + b, sp.FiniteSet(-1, 2), True),
    (u**2 + b, sp.Interval.open(1, 4), False),
    (u**2 + b, sp.Interval.Lopen(1, 4), False),
    (u**2 + b, sp.Interval(1, sp.oo), False),
    (u**2 + b, sp.S.Reals, False),
    (u**2 + b, sp.S.EmptySet, False),
    (u + 1/(u - 2), sp.Interval(1, 4), False),
    (u + 1/b, sp.Interval(1, 4), False),
    (u + sp.Symbol("unknown"), sp.Interval(1, 4), False),
    (u + sp.I, sp.Interval(1, 4), False),
    (u + sp.oo, sp.Interval(1, 4), False),
    (sp.sin(u), sp.Interval(1, 4), False),
    (u**2, sp.Interval(b, b + 1), True),
    (u**2, sp.FiniteSet(u), False),
])
def test_attainment_proof_uses_only_current_real_polynomial_and_compact_domain(function, domain, expected):
    assert polynomial_extrema_attained(function, u, domain) is expected


def test_attainment_proof_does_not_cancel_an_undefined_denominator():
    function = sp.Mul(u - 2, sp.Pow(u - 2, -1, evaluate=False), evaluate=False)
    assert sp.cancel(function) == 1
    assert not polynomial_extrema_attained(function, u, sp.Interval(1, 4))


def test_real_interval_supplies_the_quantified_variables_real_domain():
    variable = sp.Symbol("z")
    assert polynomial_extrema_attained(variable**2 + b, variable, sp.Interval(1, 4))


def policy_bindings(function, domain, quantifier="∃", operator=">="):
    policy = select_quantifier_policy(quantifier, operator, domain)["outputs"]["policy"]
    return {"before": [function], "after": [], "policy": policy, "x": u,
            "parameter_expression": sp.S.Zero, "function": function, "domain": domain,
            "function_name": "g", "define_name": True}


def policy_spec():
    registry = execution_contracts.read("presentation-registry")
    validate_registry(registry)
    return registry["templates"]["policy"]


@pytest.mark.parametrize("function,domain", [
    (u**2 - b*u - b + 15, sp.Interval(1, 4)),
    (b*u + 2, sp.Interval(-2, 3)),
    (u**2 - b*u, sp.FiniteSet(2)),
])
def test_existential_closed_polynomial_card_shows_minimum_without_bound_caveats(function, domain):
    bindings, spec = policy_bindings(function, domain), policy_spec()
    values = prepare_values(spec, bindings)
    _, _, text = render_template(spec, bindings)
    highlight = render_highlight(spec, bindings)
    assert values["policy_attained"] is True
    assert values["bound_explanation"] == ""
    assert highlight["items"][1] == {"label": "只需看最小值", "math": r"g(u)_{\min} \leq 0",
                                      "note": "该最值可以取得。"}
    assert r"$\iff g(u)_{\min} \leq 0$" in text
    assert "下端" not in text and "取到时" not in text and "必须能取到" not in text
    assert "（" not in highlight["result"]
    # No numeric range or critical point was supplied to this policy step.
    assert "range" not in bindings and "points" not in bindings


@pytest.mark.parametrize("operator,condition", [
    ("<", r"g(u)_{\min} > 0"),
    (">", r"g(u)_{\max} < 0"),
    ("<=", r"g(u)_{\min} \geq 0"),
    (">=", r"g(u)_{\max} \leq 0"),
])
def test_universal_attained_extremum_preserves_the_original_strictness(operator, condition):
    bindings = policy_bindings(u**2 + b*u, sp.Interval(-1, 2), "∀", operator)
    _, _, text = render_template(policy_spec(), bindings)
    highlight = render_highlight(policy_spec(), bindings)
    assert highlight["items"][1]["math"] == condition
    assert f"$\\iff {condition}$" in text
    assert "取到时不能相等" not in text and "取到时不能相等" not in highlight["result"]


@pytest.mark.parametrize("function,domain", [
    (u**2 + b*u, sp.Interval.open(1, 4)),
    (u**2 + b*u, sp.Interval(1, sp.oo)),
    (1/(u - 2), sp.Interval(1, 4)),
    (u/b, sp.Interval(1, 4)),
])
def test_unproved_attainment_keeps_bound_notation_and_equality_caveat(function, domain):
    bindings = policy_bindings(function, domain)
    spec = policy_spec()
    values = prepare_values(spec, bindings)
    _, _, text = render_template(spec, bindings)
    highlight = render_highlight(spec, bindings)
    assert values["policy_attained"] is False
    assert values["bound_explanation"] == BOUND_EXPLANATION
    assert r"g(u)_{\text{下端}} \leq 0" == highlight["items"][1]["math"]
    assert "相等时值域下端必须能取到" in text
    assert "无限接近" in text and r"\min" not in text


def test_unproved_universal_strict_bound_still_retains_its_equality_rule():
    bindings = policy_bindings(u**2 + b*u, sp.Interval.open(1, 4), "∀", "<")
    _, _, text = render_template(policy_spec(), bindings)
    assert r"$\iff g(u)_{\text{下端}} \geq 0$" in text
    assert "值域下端取到时不能相等" in text
