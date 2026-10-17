"""Repair authority follows mathematical sub-questions, including their children."""

import json
from copy import deepcopy

import pytest

from shuxueshuo_server.graph_lesson.stage_one.extraction import (
    GraphStageOneContract,
    validate_candidate,
)


def nested_problem(*, identical=False, shared_parent_fact=False):
    children = []
    for index in range(2):
        child = {
            "label": f"（{index + 1}）",
            "children": [{
                "facts": ["a>0" if identical or index == 0 else "a<0"],
                "goals": [{"kind": "find_value", "expression": "a+1" if identical or index == 0 else "a+2"}],
            }],
        }
        if shared_parent_fact:
            child["facts"] = ["a∈ℝ"]
        children.append(child)
    return {"original_text": "分别求两问的值。", "root": {"facts": ["a∈ℝ"], "children": children}}


def check_repair(before, after, grants):
    assert validate_candidate(before)["contract_valid"]
    assert validate_candidate(after)["contract_valid"]
    contract = GraphStageOneContract()
    review = contract.validate_review(json.dumps({
        "status": "correction_required",
        "findings": [{"kind": kind, "path": path, "source_excerpt": "题面条件", "message": "修正该处。"}
                     for kind, path in grants],
    }, ensure_ascii=False), before)
    return contract.repair_diagnostics(before, after, contract.review_diagnostics(review, before))


@pytest.mark.parametrize("shared_parent_fact", [False, True])
def test_parent_grant_follows_distinct_subtree_when_whole_questions_move(shared_parent_fact):
    before = nested_problem(shared_parent_fact=shared_parent_fact)
    moved = deepcopy(before)
    moved["root"]["children"].reverse()
    grants = [("wrong_scope", "/root"), ("missing_condition", "/root/children/0")]
    correct = deepcopy(moved)
    correct["root"]["children"][1].setdefault("facts", []).append("a<5")
    assert check_repair(before, correct, grants) == []
    wrong = deepcopy(moved)
    wrong["root"]["children"][0].setdefault("facts", []).append("a<5")
    assert check_repair(before, wrong, grants)


@pytest.mark.parametrize("target", [0, 1])
def test_indistinguishable_subtrees_do_not_guess_where_local_grant_went(target):
    before = nested_problem(identical=True)
    after = deepcopy(before)
    after["root"]["children"].reverse()
    after["root"]["children"][target]["facts"] = ["a<5"]
    issues = check_repair(before, after, [("wrong_scope", "/root"), ("missing_condition", "/root/children/0")])
    assert {issue["code"] for issue in issues} == {"repair.ambiguous_scope_mapping"}
    assert {issue["path"] for issue in issues} == {"/root/children/0"}


@pytest.mark.parametrize("unused_local_grant", [False, True])
def test_indistinguishable_subtrees_can_move_without_transferring_local_grants(unused_local_grant):
    before = nested_problem(identical=True)
    after = deepcopy(before)
    after["root"]["children"].reverse()
    grants = [("wrong_scope", "/root")]
    if unused_local_grant:
        grants.append(("missing_condition", "/root/children/0"))
    assert check_repair(before, after, grants) == []


def test_unchanged_order_keeps_local_grant_without_any_scope_move():
    before = nested_problem(identical=True)
    after = deepcopy(before)
    after["root"]["children"][0]["facts"] = ["a<5"]
    assert check_repair(before, after, [("missing_condition", "/root/children/0")]) == []
