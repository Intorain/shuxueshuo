"""Axis controls preserve the original quadratic family and its parameter scope."""

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_three import interaction_graphs as drawing

x, p, other = sp.symbols("x p other", real=True)
DOMAIN = sp.Interval(-1, 2)


def _explorer(function, variable=x, parameter=p, domain=DOMAIN, **kwargs):
    return drawing.axis_explorer(function, variable, parameter, domain, **{
        "breakpoints": [sp.S.Zero, sp.S.One], "start": sp.S.Zero, "target": "min",
        "title": "移动对称轴", "description": "保持原函数族", **kwargs,
    })


@pytest.mark.parametrize(("names", "leading", "slope", "offset", "constant"), [
    (("x", "m"), 1, -1, 0, (0, -1, 15)),
    (("t", "k"), -2, 4, 6, (3, -7, 4)),
    (("u", "q"), sp.Rational(3, 2), -2, 5, (-2, 4, -9)),
    (("z", "r"), -sp.Rational(1, 2), -4, -3, (sp.Rational(1, 2), 0, 0)),
    (("s", "v"), 2, 4, 3, (0, 0, 7)),
])
def test_axis_protocol_is_identical_to_original_family(names, leading, slope, offset, constant):
    variable, parameter = sp.symbols(" ".join(names), real=True)
    quadratic, linear, fixed = constant
    original = leading * variable**2 + (slope * parameter + offset) * variable + \
        quadratic * parameter**2 + linear * parameter + fixed
    params = _explorer(original, variable, parameter)["params"]
    mapping = params["parameter"]
    assert params["variable"] == names[0] and mapping["name"] == names[1]
    h = sp.Symbol("h", real=True)
    exact = lambda value: sp.Rational(str(value))
    parameter_at_axis = exact(mapping["scale"]) * h + exact(mapping["offset"])
    extension = params.get("constant_by_axis", {"linear": 0, "quadratic": 0})
    constant_at_axis = exact(params["constant"]) + exact(extension["linear"]) * h + \
        exact(extension["quadratic"]) * h**2
    reconstructed = exact(params["coefficient"]) * (variable - h)**2 + constant_at_axis - \
        exact(params["coefficient"]) * h**2
    assert sp.expand(original.subs(parameter, parameter_at_axis) - reconstructed) == 0
    assert sp.expand((slope * parameter_at_axis + offset) + 2 * leading * h) == 0
    assert ("constant_by_axis" in params) is bool(quadratic or linear)
    for axis in (params["axis"]["min"], params["axis"]["value"], params["axis"]["max"]):
        parameter_value = mapping["scale"] * axis + mapping["offset"]
        c = params["constant"] + extension["linear"] * axis + extension["quadratic"] * axis**2
        for point in (-1, 0.37, 2, axis):
            actual = params["coefficient"] * (point - axis)**2 + c - params["coefficient"] * axis**2
            expected = float(original.subs({variable: point, parameter: parameter_value}))
            assert actual == pytest.approx(expected)


def test_irrational_finite_coefficients_are_accepted_and_preserve_values():
    original = sp.sqrt(2) * x**2 + (sp.sqrt(3) * p + 1) * x + sp.pi * p**2 - sp.sqrt(5) * p
    params = _explorer(original)["params"]
    mapping, extension = params["parameter"], params["constant_by_axis"]
    for axis in (-0.3, 0.7, 1.4):
        parameter = mapping["scale"] * axis + mapping["offset"]
        c = params["constant"] + extension["linear"] * axis + extension["quadratic"] * axis**2
        for point in (-1, 0, 2):
            actual = params["coefficient"] * point**2 - 2 * params["coefficient"] * axis * point + c
            assert actual == pytest.approx(float(original.subs({x: point, p: parameter})))


@pytest.mark.parametrize(("function", "domain", "breakpoints"), [
    (x**2 - 2 * p * x + 3 * p**2 - p / 7 - 10, sp.Interval(0, 1), [0, 1]),
    (x**2 - 2 * p * x + 5 * p**2 + 10 * p + 2, sp.Interval(2, 3), [-5, 0]),
    (-x**2 + 2 * p * x - 3 * p**2 + p / 7 + 10, sp.Interval.open(0, 1), [0, 1]),
])
def test_common_viewport_uses_exact_endpoint_and_vertex_extrema(function, domain, breakpoints):
    params = _explorer(function, domain=domain, breakpoints=breakpoints)["params"]
    low, high = (sp.Rational(str(params["axis"][side])) for side in ("min", "max"))
    candidates = [sp.S.Zero]
    for expression, start, end in (
        (function.subs(x, domain.start), low, high),
        (function.subs(x, domain.end), low, high),
        (function.subs(x, p), max(low, domain.start), min(high, domain.end)),
    ):
        points = [start, end] + [root for root in sp.solve(sp.diff(expression, p), p)
                                 if start <= root <= end]
        candidates.extend(expression.subs(p, point) for point in points)
    minimum, maximum = float(min(candidates)), float(max(candidates))
    padding = max(maximum - minimum, 1) * 0.15
    assert params["bounds"][2:] == pytest.approx([minimum - padding, maximum + padding], abs=1e-12)
    # Case views use the common full track for their viewport even while their control is restricted.
    restricted = _explorer(function, domain=domain, breakpoints=breakpoints, within=sp.Interval.open(0, 1))
    assert restricted["params"]["bounds"] == params["bounds"]


@pytest.mark.parametrize("slope", [-4, 4])
@pytest.mark.parametrize("closure", [(True, True), (True, False), (False, True), (False, False)])
def test_parameter_mapping_preserves_known_and_case_intervals(slope, closure):
    left_open, right_open = closure
    known = sp.Interval(-2, 3, left_open=left_open, right_open=right_open)
    within = sp.Interval(-1, 2, left_open=left_open, right_open=right_open)
    params = _explorer(-2 * x**2 + (slope * p + 2) * x + p**2 + p,
                       allowed=known, within=within)["params"]
    mapping, axis = params["parameter"], params["axis"]
    for index in range(101):
        position = sp.Rational(str(axis["min"])) + \
            (sp.Rational(str(axis["max"])) - sp.Rational(str(axis["min"]))) * index / 100
        value = sp.Rational(str(mapping["scale"])) * position + sp.Rational(str(mapping["offset"]))
        assert known.contains(value) is sp.true and within.contains(value) is sp.true
    assert axis["min"] <= axis["value"] <= axis["max"]


@pytest.mark.parametrize("unsupported", [
    p * x**2 + p * x + p**2,
    x**2 + p**2 * x + p,
    x**2 + x / p + p,
    x**2 + p * x + 1 / p,
    x**2 + p * x + p**3,
    x**2 + p * x + sp.sin(p),
    x**2 + p * x + other,
    x**2 + (p + sp.I) * x,
    sp.I * x**2 + p * x,
    x**2 + p * x + sp.I * p**2,
    x**2 + p * x + sp.oo,
    x**2 + x + p,
    sp.Integer(10)**400 * x**2 + p * x,
    x**2 + p * x + sp.Integer(10)**400,
])
def test_unsupported_or_nonfinite_families_are_refused(unsupported):
    with pytest.raises(drawing.GraphUnavailable):
        _explorer(unsupported)


@pytest.mark.parametrize("keyword", ["allowed", "within"])
def test_disconnected_parameter_scopes_remain_unsupported(keyword):
    disconnected = sp.Union(sp.Interval(-3, -1), sp.Interval(1, 3))
    with pytest.raises(drawing.GraphUnavailable, match="axis_parameter_domain_unsupported"):
        _explorer(x**2 - p * x - p + 15, **{keyword: disconnected})
