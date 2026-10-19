"""Route consistency compares mathematics, independently of set presentation."""

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_three import calculations, verification
from shuxueshuo_server.graph_lesson.stage_three.goals import finalize_goal
from shuxueshuo_server.graph_lesson.stage_three.trajectory import encode_value


def previous(value):
    return [{"status": "verified", "feasible_set_exact": encode_value(value),
             "answer": finalize_goal({"kind": "find_range"}, value)}]


@pytest.mark.parametrize("first,second", [
    (sp.S.Reals, sp.Interval.open(-sp.oo, sp.oo)),
    (sp.Interval.open(-sp.oo, sp.oo), sp.S.Reals),
    (sp.Union(sp.Interval(-sp.oo, 0), sp.Interval.open(0, sp.oo), evaluate=False), sp.S.Reals),
])
def test_equal_sets_with_distinct_representations_do_not_revoke_verified_routes(first, second):
    answer = finalize_goal({"kind": "find_range"}, second)
    assert calculations.consistency(second, answer, previous(first)) == "consistent"


def test_equivalent_range_answers_may_have_different_latex():
    earlier = previous(sp.Interval(0, 1))
    earlier[0]["answer"]["set"]["latex"] = r"\{a\mid 0\le a\le1\}"
    answer = finalize_goal({"kind": "find_range"}, sp.Interval(0, 1))
    assert calculations.consistency(sp.Interval(0, 1), answer, earlier) == "consistent"


def test_different_endpoint_membership_still_revokes_the_route():
    answer = finalize_goal({"kind": "find_range"}, sp.Interval.open(0, 1))
    assert calculations.consistency(sp.Interval.open(0, 1), answer, previous(sp.Interval(0, 1))) == "conflict"


@pytest.mark.parametrize("field,value", [("kind", "find_minimum"), ("status", "unbounded")])
def test_goal_kind_and_answer_status_still_have_to_agree(field, value):
    earlier = previous(sp.S.Reals)
    earlier[0]["answer"][field] = value
    answer = finalize_goal({"kind": "find_range"}, sp.S.Reals)
    assert calculations.consistency(sp.S.Reals, answer, earlier) == "conflict"


def test_unknown_set_comparison_cannot_become_consistent(monkeypatch):
    def unknown(*_):
        raise verification.VerificationGap("test_unknown_set_comparison")

    monkeypatch.setattr(verification, "_set_mismatch", unknown)
    answer = finalize_goal({"kind": "find_range"}, sp.S.Reals)
    assert calculations.consistency(sp.S.Reals, answer, previous(sp.S.Reals)) == "unknown"
