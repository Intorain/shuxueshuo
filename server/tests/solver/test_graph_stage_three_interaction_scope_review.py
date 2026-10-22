"""Interactive pictures and feedback preserve the current mathematical scope."""

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_three import interaction
from shuxueshuo_server.graph_lesson.stage_three import interaction_graphs as drawing
from tests.solver.test_graph_stage_three_interaction_ranges import separation_seed
from tests.solver.test_graph_stage_three_interactions import _cases, _known, _seed, a, x


@pytest.mark.parametrize("condition", ["a!=1/4", "(a=-2)∨(a=-1/2)∨(a=1)"])
def test_disconnected_parameter_scope_does_not_publish_an_unrestricted_case_slider(condition):
    function, domain = x**2 + a*x + 1, sp.Interval.Lopen(0, sp.Rational(1, 2))
    seed = _seed(
        "interval_cases", {"before": [function], "after": [], "cases": _cases(function, domain), "parameter": a},
        {"x": x, "domain": domain, "parameter": a},
        known=_known("∀x∈(0,1/2]:x^2+a*x+1>=0", condition),
    )
    chunk, diagnostics = interaction.build_chunk([seed], interaction.load_registry(), {"previous": 0})
    assert chunk["status"] == "interactive", diagnostics
    interaction.validate_chunk(chunk)
    for part in chunk["parts"]:
        # A valid static sample may remain, but a continuous slider cannot
        # represent either a hole in the parameter domain or isolated values.
        assert part.get("graph", {}).get("kind") != "axis_explorer"
        assert "completion_graphs" not in part
    assert any(row.get("reason") == "axis_parameter_domain_unsupported" for row in diagnostics)


@pytest.mark.parametrize("scope", [sp.S.Reals - sp.FiniteSet(sp.Rational(1, 4)), sp.FiniteSet(-2, -1, 1)])
@pytest.mark.parametrize("field", ["allowed", "within"])
def test_axis_builder_rejects_disconnected_scope_in_either_input(scope, field):
    with pytest.raises(drawing.GraphUnavailable, match="axis_parameter_domain_unsupported"):
        drawing.axis_explorer(
            x**2 + a*x + 4, x, a, sp.Interval(1, 2), breakpoints=[-4, -2], start=-3,
            target="min", title="t", description="d", **{field: scope},
        )


@pytest.mark.parametrize("slope", [a, -a])
@pytest.mark.parametrize("field", ["allowed", "within"])
def test_axis_track_and_initial_value_stay_inside_open_parameter_interval(slope, field):
    scope = sp.Interval.open(-4, -2) if slope == a else sp.Interval.open(2, 4)
    graph = drawing.axis_explorer(
        x**2 + slope*x + 4, x, a, sp.Interval(1, 2), breakpoints=[-4, -2] if slope == a else [2, 4],
        start=scope.start, target="min", title="t", description="d", **{field: scope},
    )
    axis = graph["params"]["axis"]
    assert 1 < axis["min"] <= axis["value"] <= axis["max"] < 2
    for key in ("min", "max", "value"):
        parameter = sp.Rational(str(axis[key])) * (-2 if slope == a else 2)
        assert scope.contains(parameter) is sp.true


@pytest.mark.parametrize("relation,domain,fact,template,divisor", [
    (sp.Ge(x**2-a+1, 0), sp.S.Reals, "∀x∈ℝ:x^2-a+1>=0", "constant_divided", "-1"),
    (sp.Ge(x**2+a*x+2, 0), sp.Interval.open(-sp.oo, 0), "∀x∈(-∞,0):x^2+a*x+2>=0", "negative_divided", "x"),
    (sp.Ge(x**2+a*x+1, 0), sp.Interval.Lopen(0, sp.Rational(1, 2)),
     "∀x∈(0,1/2]:x^2+a*x+1>=0", "divided", "x"),
])
def test_division_sign_error_feedback_uses_the_real_divisor(relation, domain, fact, template, divisor):
    seed, _, _ = separation_seed(relation, domain, fact)
    assert seed["template"] == template
    chunk, diagnostics = interaction.build_chunk([seed], interaction.load_registry(), {"previous": 0})
    assert chunk["status"] == "interactive", diagnostics
    result = chunk["parts"][-1]
    wrong_label = next(row["label"] for row in diagnostics
                       if row.get("generator") == "division_sign_error" and row["result"] == "witness")
    option = next(option for option in result["interaction"]["options"] if option["label"] == wrong_label)
    assert option["value"] not in result["expected_answer"]["one_of"]
    assert option["feedback"] == f"右边每一项都要除以 ${divisor}$。除以负数时，各项的正负与不等号方向都要改变。"
    if divisor == "-1":
        assert wrong_label == r"$a \leq - x^{2} - 1$"
        assert next(option["label"] for option in result["interaction"]["options"]
                    if option["value"] in result["expected_answer"]["one_of"]) == r"$a \leq x^{2} + 1$"
