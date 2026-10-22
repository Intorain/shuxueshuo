"""Separation displays follow checked output producers, including pure moves."""

from copy import deepcopy

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_three import capabilities, driver
from shuxueshuo_server.graph_lesson.stage_three.capabilities import separation
from shuxueshuo_server.graph_lesson.stage_three.trajectory import decode_value
from tests.solver.test_graph_stage_three_methods import Q01, candidate, finish, start


@pytest.mark.parametrize("value,unit,source", [
    (Q01, "separated", 0),
    (candidate("∀x∈[1,2]:x^2+a*x+4<0"), "divided", 1),
    (candidate("∀x∈ℝ:2*a+x^2>0"), "constant_divided", 1),
])
def test_separation_card_is_committed_by_its_checked_producer_before_any_skip(value, unit, source):
    state = start(value, method="method-separation")
    state = driver.advance(state)  # inspect
    if source:
        assert state["fragments"] == []
        state = driver.advance(state)  # inequality
    card, = state["fragments"]
    assert card["display_unit"] == unit
    trace, = state["trajectory"]["steps"]
    assert trace["skipped_calls"] == []
    assert f"/steps/0/calls/{source}" in card["source_refs"]
    values = decode_value(state["frames"][0]["bindings"])
    output = "separation_candidate" if source == 0 else "applied_separation"
    assert state["frames"][0]["binding_sources"][output] == f"/steps/0/calls/{source}"
    assert card["after"][-1]["expression"] == sp.sstr(values[output]["separated_relation"])
    if unit in ("divided", "negative_divided"):
        assert card["after"][0]["expression"] == sp.sstr(values[output]["moved_relation"])
    if source:
        assert trace["calls"][source]["public_ref"] == "skill-inequality-transform"
        assert trace["calls"][source]["source_refs"] == ["/steps/0/calls/0"]
    if unit == "moved":
        assert "移项" in card["title"]
        assert "除" not in card["explanation"]
        assert trace["calls"][source]["operations"] == ["add_both_sides"]
    completed = finish(state)
    assert completed["status"] == "method_complete", completed["diagnostics"]
    assert completed["fragments"][0] == card
    merge, = completed["trajectory"]["steps"][0]["merges"]
    # The selected merge branch also relies on inspect's guard, in addition
    # to the checked mathematical output it forwards.
    assert merge["source_refs"] == sorted({"/steps/0/calls/0", f"/steps/0/calls/{source}"})


def test_public_transform_consumes_prepared_candidate_without_rederiving_it(monkeypatch):
    x, a = sp.symbols("x a", real=True)
    relation = capabilities.relation(x*x + a*x + 4, "<")
    domain = sp.Interval(1, 2)
    prepared = capabilities.separate_parameter(relation, a, x, domain)["outputs"]["candidate"]

    def forbidden(*args, **kwargs):
        raise AssertionError("public transform must reuse the inspected candidate")

    monkeypatch.setattr(separation, "inspect_separation", forbidden)
    computed = capabilities.separation_division(relation, a, x, domain, prepared=prepared)
    assert computed["outputs"]["separated_relation"] == prepared["separated_relation"]
    assert all(check["passed"] for check in computed["checks"])
    assert computed["operations"] == ["add_both_sides", "multiply_positive"]
    for operator, rhs in (("<=", prepared["function"]), ("<", prepared["function"] + 1)):
        altered = deepcopy(prepared)
        altered.update(operator=operator, function=rhs,
                       separated_relation=capabilities.relation(a, operator, rhs))
        with pytest.raises(capabilities.LocalCheckFailed):
            capabilities.separation_division(relation, a, x, domain, prepared=altered)
    for moved in (capabilities.relation(a*x, "<", x*x + 4), capabilities.relation(a*x, ">", -x*x - 4)):
        with pytest.raises(capabilities.LocalCheckFailed):
            capabilities.separation_division(relation, a, x, domain, prepared={**prepared, "moved_relation": moved})


def test_failed_public_transform_never_publishes_its_prepared_math(monkeypatch):
    original = capabilities.REGISTRY["separation_division"]

    def failed(**inputs):
        result = original(**inputs)
        result["checks"][0]["passed"] = False
        return result

    monkeypatch.setitem(capabilities.REGISTRY, "separation_division", failed)
    state = finish(start(candidate("∀x∈ℝ:2*a+x^2>0"), method="method-separation"))
    assert state["status"] == "math_failed"
    assert state["fragments"] == []
    values = decode_value(state["frames"][0]["bindings"])
    assert "separation_candidate" in values and "applied_separation" not in values
    assert state["trajectory"]["steps"][0]["merges"] == []
