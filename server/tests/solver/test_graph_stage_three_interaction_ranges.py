"""Range questions retain only mathematically different, scoped alternatives."""

import json

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_three import interaction, interaction_ranges
from shuxueshuo_server.graph_lesson.stage_three.capabilities import (
    select_quantifier_policy,
)
from shuxueshuo_server.graph_lesson.stage_three.capabilities.ranges import (
    endpoint_values_extremum,
)
from tests.solver.test_graph_stage_three_interactions import _known, _seed

x, a = sp.symbols("x a", real=True)


@pytest.fixture
def sources():
    return interaction_ranges.register(interaction.EXTENSION_API)["answers"]


@pytest.mark.parametrize("domain,reverse", [(sp.Interval.Lopen(0, 2), False),
                                            (sp.Interval.Ropen(-2, 0), True)])
def test_division_uses_strict_sign_including_open_zero_boundary(sources, domain, reverse):
    data = sources["division_direction"]["facts"]({"divisor": x}, {"x": x, "domain": domain})
    assert data["reverse"] is reverse


@pytest.mark.parametrize("domain", [sp.Interval(0, 2), sp.Interval(-1, 1)])
def test_division_never_asks_same_or_reverse_when_divisor_may_vanish(sources, domain):
    with pytest.raises(interaction.NotInteractive, match="divisor_sign_unknown"):
        sources["division_direction"]["facts"]({"divisor": x}, {"x": x, "domain": domain})


def endpoint_data(sources, function, domain=None, known=sp.S.Reals):
    domain = domain if domain is not None else sp.Interval(-1, 1)
    bound = endpoint_values_extremum(function, x, a, domain, {"bound": "sup"})["outputs"]["range"]
    values = {"function": function, "x": x, "domain": domain, "range": bound}
    context = {"x": x, "domain": domain, "parameter": a}
    source = sources["endpoint_candidates"]
    data = {**source["facts"](values, context), "known": known}
    item, = source["answer"](data)
    candidates = source["generators"]["omit_endpoint"](data, item)
    return source, data, values, context, item, candidates


def test_equal_endpoint_values_do_not_make_omission_a_wrong_answer(sources):
    source, data, values, context, item, candidates = endpoint_data(sources, x**2)
    kept, records, _ = source["validate"](data, values, context, item, candidates)
    assert not kept
    assert all(row[1] == "unproven" for row in records)


def test_endpoint_comparison_uses_parameter_witnesses_within_known_scope(sources):
    args = endpoint_data(sources, x**2+a*x, known=sp.Interval.open(0, sp.oo))
    source, data, values, context, item, candidates = args
    kept, records, _ = source["validate"](data, values, context, item, candidates)
    assert [candidate.value for candidate in kept] == [(-1,)]
    assert records[1][1] == "unproven"  # right endpoint alone is enough when a > 0
    assert records[0][2] in {sp.latex(point) for point in interaction.representatives(values, context, data["known"])
                             if point > 0}


def test_endpoint_attainment_distinguishes_equal_values(sources):
    args = endpoint_data(sources, x**2, domain=sp.Interval.Lopen(-1, 1))
    source, data, values, context, item, candidates = args
    kept, _, _ = source["validate"](data, values, context, item, candidates)
    assert [candidate.value for candidate in kept] == [(-1,)]


def test_endpoint_rule_becomes_readonly_if_every_omission_is_equivalent(sources):
    _, _, values, context, _, _ = endpoint_data(sources, x**2)
    seed = _seed("endpoint_bounds", values, context)
    chunk, records = interaction.build_chunk([seed], interaction.load_registry(), {"previous": 0})
    assert chunk["status"] == "readonly" and chunk["reason"] == "insufficient_options"
    assert not any(row.get("result") == "witness" for row in records)


def test_numeric_function_values_are_not_restricted_by_parameter_domain(sources):
    source = sources["certified_range"]
    values = {"range": {"set": sp.Interval(-sp.oo, -1)}, "function": -x**2-1, "after": []}
    context = {"x": x, "parameter": a, "domain": sp.S.Reals}
    data = {**source["facts"](values, context), "known": sp.Interval(0, sp.oo)}
    item, = source["answer"](data)
    candidate = interaction._set_candidate("wrong", sp.Interval.open(-sp.oo, -1))
    kept, records, _ = source["validate"](data, values, context, item, [candidate])
    assert kept == [candidate] and records[0][1] == "witness"


@pytest.mark.parametrize("template", ["range_evidence", "numeric_range"])
def test_range_is_compiled_from_this_card_and_keeps_unattained_endpoint(template):
    seed = _seed(template, {"before": [x], "after": [sp.Interval.open(0, 1)],
                                   "range": {"set": sp.Interval.open(0, 1)}, "function": x},
                 {"x": x, "domain": sp.Interval.open(0, 1), "parameter": a},
                 known=_known("a>0", "∀x∈(0,1):x+a>0"))
    chunk, records = interaction.build_chunk([seed], interaction.load_registry(), {"previous": 0})
    assert chunk["status"] == "interactive", records
    interaction.validate_chunk(chunk)
    part, = chunk["parts"]
    correct = [option for option in part["interaction"]["options"]
               if option["value"] in part["expected_answer"]["one_of"]]
    assert len(correct) == 1 and r"\left(0, 1\right)" in correct[0]["label"]


def test_movement_question_is_only_about_moving_terms_not_swapping_sides():
    seed = _seed("moved", {"before": [sp.Gt(2*a+x**2, 0, evaluate=False)]}, {})
    chunk, diagnostics = interaction.build_chunk([seed], interaction.load_registry(), {"previous": 0})
    assert chunk["status"] == "interactive", diagnostics
    part, = chunk["parts"]
    assert "不交换两边" in part["question"]
    slot, = part["interaction"]["slots"]
    answer, = part["expected_answer"]["terms"]
    assert next(option["label"] for option in slot["options"] if option["value"] == answer) == "保持不变"


@pytest.mark.parametrize("operator", ["<", "<=", ">", ">="])
@pytest.mark.parametrize("closed", [False, True])
def test_existential_bound_answer_and_display_match_attainment(operator, closed):
    domain = sp.Interval(0, 1) if closed else sp.Interval.open(0, 1)
    policy = select_quantifier_policy("∃", operator, domain)["outputs"]["policy"]
    values = {"function": x, "parameter_expression": a, "policy": policy, "x": x}
    context = {"x": x, "domain": domain, "parameter": a, "quantifier": "∃"}
    data = interaction._policy_facts(values, context)
    item, = interaction._policy_answer(data)
    for parameter in map(sp.Rational, [-1, 0, .5, 1, 2]):
        # A monotone identity on an interval: direct interior/end samples suffice
        # at these exact candidate values, independently of the policy code.
        points = [sp.Rational(1, 4), sp.Rational(1, 2), sp.Rational(3, 4)]
        if closed:
            points += [sp.S.Zero, sp.S.One]
        expected = any(sp.Rel(parameter, point, operator) is sp.true for point in points)
        assert item["answer"].value(parameter) is expected
    assert ("等号成立时" in item["answer"].label) == (operator in ("<=", ">="))


def test_every_presentation_template_has_an_explicit_rule():
    presentation = json.loads((interaction.ROOT / "site/data/knowledge-next/execution/presentation-registry.json")
                              .read_text())
    registry = interaction.load_registry()
    assert set(presentation["templates"]) <= set(registry["templates"])
    assert len(registry["templates"]) == 33
