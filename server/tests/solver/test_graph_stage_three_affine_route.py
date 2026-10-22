"""Affine substitution is a checked, resumable part of the separation route."""

import json

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_three import driver, execution_contracts
from shuxueshuo_server.graph_lesson.stage_three.context import build_context
from shuxueshuo_server.graph_lesson.stage_three.trajectory import decode_value
from shuxueshuo_server.graph_lesson.stage_three.verification import (
    endpoint_check,
    verify,
)
from tests.solver.test_graph_stage_three_methods import TARGET, candidate, finish, start


@pytest.mark.parametrize("fact,symbol,expected", [
    ("∃x∈[1,4]:x^2-m*x-m+15<=0", "m", sp.Interval(6, sp.oo)),
    ("∀x∈[1,4]:x^2-m*x-m+15<=0", "m", sp.Interval(8, sp.oo)),
    ("∀x∈[1,4]:x^2-m*x-m+15<0", "m", sp.Interval.open(8, sp.oo)),
    ("∃x∈[1,4]:x^2-m*x-m+15>0", "m", sp.Interval.open(-sp.oo, 8)),
    ("∃x∈(1,3):x^2-m*x-m+15<=0", "m", sp.Interval.open(6, sp.oo)),
    ("∃x∈[-5,-2]:x^2-m*x-m+15<=0", "m", sp.Interval(-sp.oo, -10)),
    ("∃z∈[0,1]:4*z^2-12*z+13-t*(3-2*z)<=0", "t", sp.Interval(4, sp.oo)),
    ("∃u∈[2,5]:u^2-2*u+10-n*(u-1)<=0", "n", sp.Interval(6, sp.oo)),
])
def test_affine_route_matches_independent_original_problem_verification(fact, symbol, expected):
    value = candidate(fact, symbol)
    completed = finish(start(value, method="method-separation"))
    assert completed["status"] == "method_complete", completed["diagnostics"]
    answer = driver.export_values(completed)["feasible_set"]
    assert answer == expected
    assert verify(value, TARGET, build_context(value, TARGET), answer)["status"] == "verified"
    assert endpoint_check(value, TARGET, answer)["status"] == "passed"
    executed = [call for step in completed["trajectory"]["steps"] for call in step["calls"]]
    operations = [call["capability"] for call in executed]
    assert operations.index("substitution") < operations.index("reciprocal_range") < operations.index("restore_substitution_range")
    for call in executed:
        if call["capability"] in {"substitution", "restore_substitution_range"}:
            assert call["public_ref"] == "method-substitution"
            assert call["postconditions"] and all(row["passed"] for row in call["postconditions"])
    units = [card["display_unit"] for card in completed["fragments"]]
    assert units.index("affine_substitution") < units.index("affine_restore")
    assert "affine_reciprocal_range" in units or "affine_monotone_range" in units
    for card in completed["fragments"]:
        assert card["source_refs"] and card["local_check"] == "passed"
    seed = next(seed for seed in completed["interaction_seeds"] if seed["template"] == "affine_substitution")
    assert str(decode_value(seed["values"])["new_variable"]) != symbol


def test_affine_checkpoint_keeps_committed_cards_and_point_back_substitution():
    value = candidate("∃x∈[1,4]:x^2-m*x-m+15<=0", "m")
    state = start(value, method="method-separation")
    contracts = execution_contracts.load_contracts()
    for _ in range(80):
        if any(card["display_unit"] == "affine_substitution" for card in state["fragments"]):
            break
        state = driver.advance(state, contracts=contracts)
    else:
        pytest.fail("substitution card never committed")
    frozen = json.loads(json.dumps(state["fragments"]))
    complete = finish(json.loads(json.dumps(state)))
    assert complete["status"] == "method_complete"
    assert complete["fragments"][:len(frozen)] == frozen
    restored = next(seed for seed in complete["interaction_seeds"] if seed["template"] == "affine_restore")
    row, = decode_value(restored["values"])["points"]
    assert (row["transformed_point"], row["point"], row["value"], row["attained"]) == (4, 3, 6, True)


@pytest.mark.parametrize("fact", [
    "∃x∈[-2,2]:x^2-m*x-m+15<=0",
    "∃x∈[-1,4]:x^2-m*x-m+15<=0",
])
def test_a_zero_divisor_is_not_admitted_by_the_new_substitution_branch(fact):
    state = start(candidate(fact, "m"), method="method-separation")
    assert state["status"] == "capability_gap"
    assert state["fragments"] == []
