"""Affine substitution cards preserve variable roles and certified attainment."""

from copy import deepcopy

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_three import execution_contracts
from shuxueshuo_server.graph_lesson.stage_three.capabilities.ranges import (
    reciprocal_range,
)
from shuxueshuo_server.graph_lesson.stage_three.math_values import math_value
from shuxueshuo_server.graph_lesson.stage_three.presentation_templates import (
    render_highlight,
    render_template,
    validate_registry,
)

u, q = sp.symbols("u q", real=True)


def specification(name):
    registry = execution_contracts.read("presentation-registry")
    validate_registry(registry)
    return registry["templates"][name]


@pytest.mark.parametrize("slope,original_domain", [
    (2, sp.Interval(-1, 0)),
    (-2, sp.Interval(0, 1)),
])
@pytest.mark.parametrize("function_name", ["h", ""])
def test_substitution_keeps_the_original_function_argument_and_exact_domain(slope, original_domain, function_name):
    forward = slope * u + 3
    expression = q + 4 / q + 1
    original = expression.subs(q, forward)
    bindings = {"before": [original], "after": [expression, sp.Interval(1, 3)],
                "original_expression": original, "original_variable": u, "original_domain": original_domain,
                "new_variable": q, "forward": forward, "inverse": (q - 3) / slope,
                "expression": expression, "domain": sp.Interval(1, 3), "function_name": function_name}
    spec = specification("affine_substitution")
    before, after, text = render_template(spec, bindings)
    highlight = render_highlight(spec, bindings)
    assert before == bindings["before"] and after == bindings["after"]
    assert f"令 $q={math_value(forward)['latex']}$" in text
    assert f"$u \\in {math_value(original_domain)['latex']}$ 对应 $q \\in \\left[1, 3\\right]$" in text
    assert ("h(u)=" in text) == bool(function_name)
    assert "h(q)" not in text and "x=" not in text
    assert highlight["items"][-1]["math"] == math_value(expression)["latex"]


def restored_bindings():
    return {
        "before": [sp.Interval(5, 6)], "after": [sp.Interval(5, 6)],
        "original_variable": u, "new_variable": q, "inverse": (q - 3) / 2,
        "points": [{"point": -sp.Rational(1, 2), "transformed_point": sp.Integer(2),
                    "value": sp.Integer(5), "attained": True}],
        "endpoints": [
            {"point": sp.Integer(-1), "transformed_point": sp.Integer(1),
             "value": sp.Integer(6), "attained": True},
            {"point": sp.Integer(0), "transformed_point": sp.Integer(3),
             "value": sp.Rational(16, 3), "attained": True},
        ],
        "turn": {"point": -sp.Rational(1, 2), "transformed_point": sp.Integer(2),
                 "value": sp.Integer(5), "minimum": True, "attained": True},
        "range": {"inf": sp.Integer(5), "sup": sp.Integer(6),
                  "inf_attained": True, "sup_attained": True, "set": sp.Interval(5, 6)},
    }


def test_restore_reports_actual_points_and_attained_extrema():
    bindings = restored_bindings()
    frozen = deepcopy(bindings)
    spec = specification("affine_restore")
    _, _, text = render_template(spec, bindings)
    highlight = render_highlight(spec, bindings)
    assert bindings == frozen
    assert r"当 $q=2$ 时，$u=- \frac{1}{2}$，原函数值为 $5$，可以取得" in text
    assert "当 $q=1$ 时，$u=-1$" in text
    assert "当 $q=3$ 时，$u=0$" in text
    assert "最小值为 $5$，可以取得" in text and "最大值为 $6$，可以取得" in text
    assert "不属于题目区间" not in text and "x=" not in text
    assert highlight["result"] == r"原函数的值域为 $\left[5, 6\right]$"


@pytest.mark.parametrize("right_closed", [False, True])
def test_open_turning_endpoint_is_an_unattained_bound(right_closed):
    bindings = restored_bindings()
    bindings["points"] = []
    bindings["endpoints"][0] = {**bindings["turn"], "attained": False}
    bindings["endpoints"][1]["attained"] = right_closed
    bindings["turn"]["attained"] = False
    bindings["range"] = {"inf": sp.Integer(5), "sup": sp.Rational(16, 3),
                         "inf_attained": False, "sup_attained": right_closed,
                         "set": sp.Interval(5, sp.Rational(16, 3), True, not right_closed)}
    _, _, text = render_template(specification("affine_restore"), bindings)
    assert r"$q \to 2$ 对应 $u \to - \frac{1}{2}$" in text
    assert "该点不属于题目区间" in text
    assert "值域下端为 $5$，只能趋近、不能取得" in text and "最小值" not in text
    assert ("最大值" in text) == right_closed
    assert ("值域上端" in text) != right_closed
    assert "确界" not in text


def test_a_turn_outside_the_interval_is_not_claimed_as_a_value_or_extremum():
    bindings = restored_bindings()
    bindings["points"] = []
    bindings["turn"]["attained"] = False
    bindings["endpoints"] = [bindings["endpoints"][1],
                             {"point": sp.Rational(1, 2), "transformed_point": sp.Integer(4),
                              "value": sp.Integer(6), "attained": True}]
    bindings["range"] = {"inf": sp.Rational(16, 3), "sup": sp.Integer(6),
                         "inf_attained": True, "sup_attained": True,
                         "set": sp.Interval(sp.Rational(16, 3), 6)}
    _, _, text = render_template(specification("affine_restore"), bindings)
    assert "该点不属于题目区间" in text
    assert "原函数值为 $5$" not in text and "最小值为 $5$" not in text
    assert r"最小值为 $\frac{16}{3}$，可以取得" in text


def test_unbounded_range_does_not_describe_infinity_as_a_maximum():
    bindings = restored_bindings()
    bindings["points"] = []
    bindings["turn"]["attained"] = False
    bindings["endpoints"] = [
        {"point": -sp.Rational(3, 2), "transformed_point": sp.Integer(0),
         "value": sp.oo, "attained": False},
        {**bindings["turn"], "attained": False},
    ]
    bindings["range"] = {"inf": sp.Integer(5), "sup": sp.oo,
                         "inf_attained": False, "sup_attained": False, "set": sp.Interval.open(5, sp.oo)}
    _, _, text = render_template(specification("affine_restore"), bindings)
    assert "函数值没有上界" in text
    assert "最大值" not in text and "最小值" not in text
    assert "值域下端为 $5$，只能趋近、不能取得" in text


def test_closed_turning_endpoint_is_reported_once():
    bindings = restored_bindings()
    bindings["endpoints"][0] = dict(bindings["points"][0])
    bindings["range"] = {"inf": sp.Integer(5), "sup": sp.Rational(16, 3),
                         "inf_attained": True, "sup_attained": True,
                         "set": sp.Interval(5, sp.Rational(16, 3))}
    _, _, text = render_template(specification("affine_restore"), bindings)
    assert text.count("当 $q=2$ 时") == 1
    assert "该点不属于题目区间" not in text


def test_excluded_endpoint_does_not_make_a_value_attained_elsewhere_unattainable():
    bindings = restored_bindings()
    bindings["endpoints"][0]["attained"] = False
    bindings["endpoints"][1] = {"point": sp.Rational(1, 2), "transformed_point": sp.Integer(4),
                               "value": sp.Integer(6), "attained": True}
    _, _, text = render_template(specification("affine_restore"), bindings)
    assert r"$q \to 1$ 对应 $u \to -1$，原函数值趋近 $6$，对应端点不能取到" in text
    assert r"当 $q=4$ 时，$u=\frac{1}{2}$，原函数值为 $6$，可以取得" in text
    assert "最大值为 $6$，可以取得" in text and "上确界" not in text


def test_monotone_reciprocal_without_a_turn_restores_only_its_actual_endpoints():
    bindings = restored_bindings()
    bindings["turn"] = None
    bindings["points"] = []
    bindings["endpoints"][0]["value"] = sp.Integer(1)
    bindings["endpoints"][1]["value"] = sp.Rational(1, 3)
    bindings["range"] = {"inf": sp.Rational(1, 3), "sup": sp.Integer(1),
                         "inf_attained": True, "sup_attained": True,
                         "set": sp.Interval(sp.Rational(1, 3), 1)}
    _, _, text = render_template(specification("affine_restore"), bindings)
    assert "拐点" not in text
    assert r"最小值为 $\frac{1}{3}$，可以取得" in text and "最大值为 $1$，可以取得" in text


@pytest.mark.parametrize("sign,extremum", [(1, r"\min"), (-1, r"\max")])
@pytest.mark.parametrize("function_name", ["", "h"])
def test_hook_extremum_subscript_applies_to_the_whole_unnamed_expression(sign, extremum, function_name):
    function, domain = sign * (q + 4 / q + 1), sp.Interval(1, 3)
    result = reciprocal_range(function, q, domain)["outputs"]
    bindings = {"before": [function], "after": [result["range"]["set"]],
                "function": function, "x": q, "domain": domain, "range": result["range"],
                "turn": result["turning_point"], "endpoints": result["endpoint_values"],
                "function_name": function_name}
    _, _, text = render_template(specification("hook_range"), bindings)
    expression = math_value(function)["latex"]
    label = "h(q)" if function_name else rf"\left({expression}\right)"
    assert f"{label}_{{{extremum}}}=" in text
    if not function_name:
        assert f"{expression}_{{{extremum}}}=" not in text
