"""Exercise exact mathematics and the authoritative student-led context protocol."""

import asyncio
import json
from copy import deepcopy

import pytest
import sympy as s
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shuxueshuo_server.tutor_demo.api import create_app, require_tutor_user
from shuxueshuo_server.tutor_demo.explanation.context import ExplanationContext, Problem
from shuxueshuo_server.tutor_demo.explanation.contracts import (
    ExplanationEvent,
    ExplanationProposal,
    Operation,
    ProposedOperation,
)
from shuxueshuo_server.tutor_demo.explanation.legacy_api import (
    create_explanation_router,
)
from shuxueshuo_server.tutor_demo.explanation.math import MathIssue, MathState
from shuxueshuo_server.tutor_demo.explanation.session import ExplanationSession
from shuxueshuo_server.tutor_demo.llm import TutorUnavailable

from .auth_helpers import TeachingOnlyBudget


def operation(op, a="", b="", name="", source=""):
    return Operation(op=op, a=a, b=b, name=name, source=source)


def proposed(op, a="", b="", name="", source="", inferred=(), id=""):
    return ProposedOperation(op=op, a=a, b=b, name=name, source=source, inferred=list(inferred), id=id)


def propose(*operations, judgments=(), clarifications=()):
    return ExplanationProposal(intent="propose", operations=list(operations),
                               judgments=list(judgments), clarifications=list(clarifications))


class Interpreter:
    """Returns queued proposals in order; the last one repeats."""

    def __init__(self, *proposals):
        self.proposals = list(proposals) or [ExplanationProposal(intent="question", reply="你打算对哪两项应用？")]
        self.calls = []

    @property
    def proposal(self):
        return self.proposals[0]

    @proposal.setter
    def proposal(self, value):
        self.proposals = [value]

    async def respond(self, **data):
        self.calls.append(data)
        return self.proposals.pop(0) if len(self.proposals) > 1 else self.proposals[0]


def client_and_session(interpreter=None):
    owner = {"id": "00000000-0000-0000-0000-000000000001"}
    app = FastAPI()
    app.include_router(create_explanation_router(require_tutor_user, interpreter or Interpreter(), TeachingOnlyBudget()), prefix="/api/tutor-demo")
    app.dependency_overrides[require_tutor_user] = lambda: owner
    client = TestClient(app)
    view = client.post("/api/tutor-demo/explanation/sessions", json={}).json()
    return client, view, owner


def send(client, view, op=None, **kwargs):
    payload = {"event_id": str(view["revision"]), "revision": view["revision"],
               "kind": "operation" if op else "text", "text": "我的讲解", **kwargs}
    if op:
        payload["operation"] = op.model_dump()
    return client.post(f"/api/tutor-demo/explanation/sessions/{view['session_id']}/events", json=payload)


def say(context, text, proposal, selected=(), kind="text"):
    return context.apply_turn(context.focused(), text, list(selected), kind, proposal)


def words(context, step):
    return [context.turn(t).text for t in step["turn_ids"] if context.turn(t).speaker == "student"]


# ---- mathematics -----------------------------------------------------------

@pytest.mark.parametrize("aliases", [False, True])
def test_actual_student_routes_reach_bound_then_attainment(aliases):
    state = MathState()
    if aliases:
        state.execute(operation("substitute", "2*m+1", name="u"))
        assert state.view()["conditions"] == ["n + u=7", "u>1", "n>0"]
        assert state.lower is None
        state.execute(operation("substitute", "n+1", name="v"))
        factor, a, b, left, right = "(u+v)/8", "v/u", "u/v", "u", "v"
    else:
        factor, a, b, left, right = "(2*m+n+2)/8", "(n+1)/(2*m+1)", "(2*m+1)/(n+1)", "2*m+1", "n+1"
    state.execute(operation("multiply", factor))
    assert state.lower is None
    state.execute(operation("amgm", a, b))
    assert state.lower == s.Rational(1, 2)
    assert not state.complete
    with pytest.raises(MathIssue, match="没有达到"):
        state.execute(operation("attain", "m", "n"))
    assert not state.complete
    state.execute(operation("attain", left, right))
    assert state.complete


def test_amgm_denominators_and_candidate_before_proof():
    state = MathState()
    state.execute(operation("attain", "2*m+1", "n+1"))
    assert not state.complete and state.lower is None
    state.execute(operation("amgm", "2*m+1", "n+1"))
    assert state.lower == s.Rational(1, 2) and not state.complete
    state.execute(operation("attain", "m", "3/2"))
    assert state.complete


def test_valid_amgm_without_target_bound_does_not_invent_one():
    state = MathState()
    state.execute(operation("amgm", "m", "n"))
    assert state.lower is None
    # The ratio terms have not appeared in the current expression yet.
    state.execute(operation("amgm", "(n+1)/(2*m+1)", "(2*m+1)/(n+1)"))
    assert state.lower is None


@pytest.mark.parametrize("expr", ["__import__('os')", "m.__class__", "[m][0]", "sin(m)", "1/0", "(m-1)/(m-1)", "x", "m**1000", "((m**4)**4)**4", "(((1000**4)**4)**4)**4"])
def test_restricted_parser_and_original_domain(expr):
    with pytest.raises(MathIssue):
        MathState().parse(expr)


def test_result_keys_compare_form_not_value():
    state = MathState()
    first = state.execute(operation("claim", "(2*m+1)+(n+1)", "8"))["key"]
    state.execute(operation("substitute", "2*m+1", name="x"))
    state.execute(operation("substitute", "n+1", name="y"))
    assert state.execute(operation("claim", "x+y", "8"))["key"] == first
    assert state.execute(operation("claim", "x", "x"))["key"] is None
    assert state.execute(operation("multiply", "1"))["key"] is None
    rewritten = state.execute(operation("multiply", "(x+y)/8"))["key"]
    assert rewritten and state.execute(operation("expand"))["key"] is None


def test_combine_groups_terms_over_the_same_denominator():
    state = MathState()
    state.execute(operation("multiply", "(2*m+n)/6"))
    assert len(state.terms()) == 5
    step = state.execute(operation("combine"))
    assert step["key"].startswith("board:") and step["status"] == "verified"
    assert [str(t) for t in state.terms()] == ["1/3", "(n - 1)/(6*(2*m + 1))", "(2*m - 1)/(6*(n + 1))"]
    assert state.execute(operation("combine"))["key"] is None
    state.execute(operation("substitute", "2*m+1", name="x"))
    assert [str(t) for t in state.terms()] == ["1/3", "(n - 1)/(6*x)", "(x - 2)/(6*(n + 1))"]
    assert state.execute(operation("expand"))["key"].startswith("board:") and len(state.terms()) == 5


def test_marked_expression_keeps_whole_denominators_clickable():
    state = MathState()
    state.execute(operation("multiply", "((2*m+1)+(n+1))/8"))
    view = state.view()
    assert view["marked"].startswith("\\frac{1}{4}+")
    assert "8 \\left(\\htmlData{obj=0}{2 m + 1}\\right)" in view["marked"]
    assert [o["expression"] for o in view["objects"]][:2] == ["2*m + 1", "n + 1"]


def test_reference_routes_replay_to_the_same_bound():
    problem = Problem.load()
    assert {r["id"] for r in problem.routes} == {"substitution", "direct"}
    # Different routes, same AM-GM application and same attainment point.
    assert problem.routes[0]["keys"][-2:] == problem.routes[1]["keys"][-2:]


# ---- context: what becomes a step -------------------------------------------

def test_partial_turn_keeps_the_verified_part_and_follow_up_joins_the_same_step():
    context = ExplanationContext()
    feedback, _ = say(context, "两个分母加起来是8，所以可以乘一个1", propose(
        proposed("claim", "(2*m+1)+(n+1)", "8", source="两个分母加起来是8"),
        clarifications=[{"kind": "missing_arg", "question": "这个 1 怎么构造？", "op": "multiply", "missing": "a"}]))
    assert feedback["status"] == "clarify" and len(context.branch.steps) == 1
    assert context.focused().clarifications[0]["op"] == "multiply"
    say(context, "用它们的和除以8", propose(proposed("multiply", "((2*m+1)+(n+1))/8", source="用它们的和除以8")))
    second = context.branch.steps[1]
    assert words(context, second) == ["两个分母加起来是8，所以可以乘一个1", "用它们的和除以8"]
    assert not context.focused().turn_ids  # resolved; a fresh discussion starts


def multiplied(context):
    """Direct route: the multiply-by-one step with its reasons; returns the two ratio terms."""
    say(context, "给整个式子乘它们的和除以8，这个就是1", propose(
        proposed("multiply", "((2*m+1)+(n+1))/8", source="给整个式子乘它们的和除以8", id="op1"),
        judgments=[judged("scope", "给整个式子乘", operation="op1"), judged("unit_factor", "这个就是1", operation="op1")]))
    assert {j["key"] for j in context.branch.steps[-1]["judgments"] if j["correct"]} == {"scope", "unit_factor"}
    return [o["expression"] for o in context.branch.state.view()["objects"]][2:]


def judged(key, quote, value="", operation="", step=None, objects=()):
    return {"key": key, "quote": quote, "value": value, "operation": operation, "step": step, "objects": list(objects)}


def test_verified_step_is_not_followed_by_questions_and_later_reasons_still_attach():
    context = ExplanationContext()
    terms = multiplied(context)
    feedback, _ = say(context, "那两个分式用基本不等式",
                      propose(proposed("amgm", *terms, source="那两个分式用基本不等式", inferred=["a", "b"])))
    step = context.branch.steps[-1]
    assert step["inferred"] == ["a", "b"] and "missing" not in step and "required" not in step
    assert "还需说明" not in feedback["reply"] and context.focused().anchor is None
    context.set_focus(step["id"])
    feedback, _ = say(context, "因为两项乘起来是定值", propose(judgments=[judged("fixed_product", "两项乘起来是定值", step=2)]))
    assert feedback["status"] == "explained" and "因为两项乘起来是定值" in words(context, step)
    assert any(j["key"] == "fixed_product" and j["correct"] for j in step["judgments"])
    say(context, "两项相等时取等，2m+1=n+1", propose(
        proposed("attain", "2*m+1", "n+1", source="2m+1=n+1"),
        judgments=[judged("fixed_product", "两项相等")]))
    assert "两项相等时取等，2m+1=n+1" not in words(context, step)
    assert context.branch.state.complete


def test_wrong_judgments_are_recorded_and_reported():
    context = ExplanationContext()
    terms = multiplied(context)
    feedback, _ = say(context, "这两项和是定值，用基本不等式，和至少是1/2", propose(
        proposed("amgm", *terms, source="用基本不等式", id="op1"),
        judgments=[judged("fixed_sum", "这两项和是定值", operation="op1"),
                   judged("relation_written", "和至少是1/2", value="1/2", operation="op1")]))
    step = context.branch.steps[-1]
    said = [j for j in step["judgments"] if not j.get("implied")]
    assert [j["correct"] for j in said] == [False, False]
    assert feedback["reply"].count("不成立") == 2


def test_hint_then_prompted_judgment_is_marked_prompted():
    context = ExplanationContext()
    terms = multiplied(context)
    say(context, "用基本不等式，求它们和的最小值，和至少是1/4", propose(
        proposed("amgm", *terms, source="用基本不等式", id="op1"),
        judgments=[judged("sum_target", "求它们和的最小值", operation="op1"),
                   judged("relation_written", "和至少是1/4", value="1/4", operation="op1")]))
    say(context, "", ExplanationProposal(intent="question", reply="想想它们的积。"), kind="help")
    say(context, "积是定值", propose(judgments=[judged("fixed_product", "积是定值", step=2)]))
    mark = next(j for j in context.branch.steps[-1]["judgments"] if j["key"] == "fixed_product")
    assert mark["correct"] and mark["source"] == "prompted"


def test_candidate_check_then_proof_then_attainment_is_not_swallowed():
    context = ExplanationContext()
    say(context, "先看2m+1=n+1的时候", propose(proposed("attain", "2*m+1", "n+1", source="2m+1=n+1")))
    assert len(context.branch.steps) == 1 and not context.branch.state.complete
    terms = multiplied(context)
    say(context, "对两项用基本不等式", propose(proposed("amgm", *terms, source="对两项用基本不等式")))
    feedback, _ = say(context, "所以2m+1=n+1时取等", propose(proposed("attain", "2*m+1", "n+1", source="2m+1=n+1")))
    assert len(context.branch.steps) == 4 and context.branch.state.complete
    assert "已经得到" not in feedback["reply"]
    feedback, _ = say(context, "就是2m+1=n+1", propose(proposed("attain", "2*m+1", "n+1", source="2m+1=n+1")))
    assert len(context.branch.steps) == 4 and "第 4 步已经得到" in feedback["reply"]


def test_reason_that_fits_several_steps_is_neither_guessed_nor_asked():
    context = ExplanationContext()
    feedback, _ = say(context, "乘(2m+n+2)/8，再乘一次(2m+n+2)/8，它等于1", propose(
        proposed("multiply", "(2*m+n+2)/8", source="乘(2m+n+2)/8", id="op1"),
        proposed("multiply", "(2*m+n+2)/8", source="再乘一次(2m+n+2)/8", id="op2"),
        judgments=[judged("unit_factor", "它等于1")]))
    assert len(context.branch.steps) == 2 and all(not s["judgments"] for s in context.branch.steps)
    assert feedback["status"] == "verified" and not context.focused().clarifications


def test_optional_reason_with_several_owners_is_neither_guessed_nor_asked():
    context = ExplanationContext()
    say(context, "两个分母和是8，乘它们的和除以8，因为分母和是定值", propose(
        proposed("claim", "(2*m+1)+(n+1)", "8", source="两个分母和是8", id="op1"),
        proposed("multiply", "((2*m+1)+(n+1))/8", source="乘它们的和除以8", id="op2"),
        judgments=[judged("denominator_sum", "分母和是定值")]))
    assert all(not [j for j in s["judgments"] if not j.get("implied")] for s in context.branch.steps)
    assert not any("解释哪一步" in c["question"] for c in context.threads[context.branch.frontier].clarifications)


def test_turn_without_any_effect_asks_for_a_concrete_step():
    context = ExplanationContext()
    feedback, _ = say(context, "m=n的时候取等", propose(judgments=[judged("relation_written", "m=n的时候取等")]))
    assert "可以验算的一步" in feedback["reply"]


def test_explicit_target_binds_to_that_step_only():
    context = ExplanationContext()
    say(context, "两个分母和是8，乘它们的和除以8，因为分母和是定值", propose(
        proposed("claim", "(2*m+1)+(n+1)", "8", source="两个分母和是8", id="op1"),
        proposed("multiply", "((2*m+1)+(n+1))/8", source="乘它们的和除以8", id="op2"),
        judgments=[judged("denominator_sum", "分母和是定值", operation="op1")]))
    claim, multiply = context.branch.steps
    assert [j["key"] for j in claim["judgments"]] == ["denominator_sum"] and not multiply["judgments"]


def test_reason_said_before_its_step_binds_once_the_step_is_unique():
    context = ExplanationContext()
    say(context, "两个分母加起来是8，所以可以乘一个1", propose(
        proposed("claim", "(2*m+1)+(n+1)", "8", source="两个分母加起来是8", id="op1"),
        judgments=[judged("unit_factor", "可以乘一个1")],
        clarifications=[{"kind": "missing_arg", "question": "这个 1 怎么构造？", "op": "multiply", "missing": "a"}]))
    assert context.focused().pending
    say(context, "用它们的和除以8，乘到整个F上", propose(
        proposed("multiply", "((2*m+1)+(n+1))/8", source="用它们的和除以8", id="op1"),
        judgments=[judged("scope", "乘到整个F上", operation="op1")]))
    step = context.branch.steps[-1]
    assert {j["key"] for j in step["judgments"]} == {"unit_factor", "scope"}


def test_judgment_about_other_objects_is_not_counted():
    context = ExplanationContext()
    terms = multiplied(context)
    feedback, _ = say(context, "对两项用基本不等式，m和n乘起来是定值", propose(
        proposed("amgm", *terms, source="对两项用基本不等式", id="op1"),
        judgments=[judged("fixed_product", "m和n乘起来是定值", operation="op1", objects=["m", "n"])]))
    assert not [j for j in context.branch.steps[-1]["judgments"] if not j.get("implied")]
    assert "没有计入" in feedback["reply"]


def test_wrong_degree_on_the_substitution_route_is_reported():
    context = ExplanationContext()
    say(context, "设x=2m+1，y=n+1", propose(proposed("substitute", "2*m+1", name="x", source="设x=2m+1"),
                                          proposed("substitute", "n+1", name="y", source="y=n+1")))
    feedback, _ = say(context, "给整个式子乘(x+y)/8，目标是正一次的", propose(
        proposed("multiply", "(x+y)/8", source="给整个式子乘(x+y)/8", id="op1"),
        judgments=[judged("target_degree", "目标是正一次的", value="1", operation="op1")]))
    assert len(context.branch.steps) == 3 and "不成立" in feedback["reply"] and "还需说明" not in feedback["reply"]


def test_unresolvable_inferred_reference_asks_instead_of_guessing():
    context = ExplanationContext()
    feedback, _ = say(context, "对那两项用基本不等式",
                      propose(proposed("amgm", "m", "n", source="对那两项用基本不等式", inferred=["a", "b"])))
    assert feedback["status"] == "clarify" and not context.branch.steps
    assert context.focused().clarifications[0]["kind"] == "ambiguous_ref"


def test_selected_object_is_not_counted_as_inferred():
    context = ExplanationContext()
    say(context, "设这个整体为x", propose(proposed("substitute", "2*m+1", name="x", source="设这个整体为x",
                                                     inferred=["a"])), selected=["2*m + 1"])
    assert context.branch.steps[0]["inferred"] == []


def test_composed_reference_is_flagged_not_blocked():
    context = ExplanationContext()
    say(context, "这两个加起来是8", propose(proposed("claim", "(2*m+1)+(n+1)", "8", source="这两个加起来是8",
                                                    inferred=["a"])), selected=["2*m + 1", "n + 1"])
    assert context.branch.steps[0]["inferred"] == []
    say(context, "两个分母乘它们的和除以8", propose(proposed("multiply", "((2*m+1)+(n+1))/8", source="乘它们的和除以8",
                                                         inferred=["a"])))
    assert len(context.branch.steps) == 2 and context.branch.steps[1]["inferred"] == ["a"]


def test_equivalent_result_is_not_a_new_step():
    context = ExplanationContext()
    say(context, "两个分母和是8", propose(proposed("claim", "(2*m+1)+(n+1)", "8", source="两个分母和是8")))
    feedback, _ = say(context, "也就是2m+n+2等于8", propose(proposed("claim", "2*m+n+2", "8", source="2m+n+2等于8")))
    assert len(context.branch.steps) == 1 and "第 1 步已经得到" in feedback["reply"]
    assert "也就是2m+n+2等于8" in words(context, context.branch.steps[0])
    say(context, "展开一下", propose(proposed("expand", source="展开一下")))
    assert len(context.branch.steps) == 1


def test_operation_only_from_a_hint_is_not_a_student_step():
    context = ExplanationContext()
    say(context, "", ExplanationProposal(intent="question", reply="想想两个分母的和。"), kind="help")
    feedback, _ = say(context, "嗯", propose(proposed("claim", "(2*m+1)+(n+1)", "8", source="嗯")))
    assert not context.branch.steps and feedback["status"] == "clarify"
    feedback, _ = say(context, "好", propose(proposed("claim", "(2*m+1)+(n+1)", "8", source="两个分母的和")))
    assert not context.branch.steps


def test_failed_attempt_stays_in_the_discussion_as_a_draft():
    context = ExplanationContext()
    feedback, _ = say(context, "两个分母和是7", propose(proposed("claim", "(2*m+1)+(n+1)", "7", source="两个分母和是7")))
    assert feedback["status"] == "invalid" and not context.branch.steps
    attempt = context.focused().attempts[0]
    assert attempt["status"] == "invalid" and attempt["echo"][-1]["math"] == "7"


def test_projection_hides_reference_routes_and_hint_gets_only_the_next_gap():
    context = ExplanationContext()
    projection = context.project(context.focused(), "我想想", [], "explain")
    text = json.dumps(projection, ensure_ascii=False)
    assert "reference_routes" not in text and "(x+y)/8" not in text and "hint_gap" not in projection
    say(context, "两个分母和是8", propose(proposed("claim", "(2*m+1)+(n+1)", "8", source="两个分母和是8")))
    hint = context.project(context.focused(), "给点提示", [], "hint")["hint_gap"]
    assert hint == {"type": "next_operation", "capability": "给式子乘一个因子"}


def test_branches_share_one_dialogue_timeline():
    context = ExplanationContext()
    say(context, "设x=2m+1", propose(proposed("substitute", "2*m+1", name="x", source="设x=2m+1")))
    before = len(context.turns)
    context.fork(0)
    assert len(context.turns) == before and not context.branch.steps
    assert context.focused().branch_id == context.active


def test_focus_on_a_step_routes_questions_to_that_step():
    context = ExplanationContext()
    say(context, "设x=2m+1", propose(proposed("substitute", "2*m+1", name="x", source="设x=2m+1")))
    step = context.branch.steps[0]
    context.set_focus(step["id"])
    say(context, "为什么要换元？", ExplanationProposal(intent="question", reply="换元让分母更简单。"))
    thread = context.focused()
    assert thread.anchor == step["id"] and len(thread.turn_ids) == 2
    context.set_focus(None)
    assert context.focused().anchor is None


def test_switching_branches_restores_each_branch_focus():
    context = ExplanationContext()
    say(context, "设x=2m+1", propose(proposed("substitute", "2*m+1", name="x", source="设x=2m+1")))
    first, step = context.active, context.branch.steps[0]
    context.set_focus(step["id"])
    asked = context.focus
    context.fork(0)
    assert context.focused().anchor is None
    second = context.active
    context.switch(first)
    assert context.focus == asked
    context.switch(second)
    assert context.focused().anchor is None and context.focused().branch_id == second


def test_abandoning_keeps_the_discussion_and_starts_fresh():
    context = ExplanationContext()
    say(context, "两个分母和是7", propose(proposed("claim", "(2*m+1)+(n+1)", "7", source="两个分母和是7")))
    old = context.focused()
    context.abandon()
    assert old.status == "abandoned" and old.attempts
    assert context.focused() is not old and not context.focused().attempts
    assert len(context.turns) == 2


def test_clarify_with_committable_parts_is_treated_as_propose():
    proposal = ExplanationProposal.model_validate({
        "intent": "clarify", "operations": [{"op": "claim", "a": "(2*m+1)+(n+1)", "b": "8", "source": "加起来是8"}],
        "clarifications": [{"kind": "missing_arg", "question": "这个 1 怎么构造？", "op": "multiply", "missing": "a"}]})
    assert proposal.intent == "propose"
    incomplete = ExplanationProposal.model_validate({
        "intent": "propose",
        "operations": [{"id": "op1", "op": "claim", "a": "(2*m+1)+(n+1)", "b": "8", "source": "加起来是8"},
                       {"id": "op2", "op": "multiply", "a": "", "source": "乘一个1"}],
        "judgments": [judged("unit_factor", "乘一个1", operation="op2")]})
    assert [o.op for o in incomplete.operations] == ["claim"]
    assert incomplete.clarifications[0].op == "multiply" and incomplete.clarifications[0].missing == "a"
    assert incomplete.judgments[0].operation == ""
    with pytest.raises(ValueError):
        ExplanationProposal.model_validate({"intent": "question", "judgments": [judged("fixed_product", "积是定值")]})


def test_turn_records_the_prompt_version():
    context = ExplanationContext()
    context.apply_turn(context.focused(), "设x=2m+1", [], "text",
                       propose(proposed("substitute", "2*m+1", name="x", source="设x=2m+1")), "interpret:abc")
    assert context.turns[0].prompt == "interpret:abc"


# ---- protocol over HTTP ------------------------------------------------------

@pytest.mark.parametrize("op", [operation("claim", "2*m+n+2", "7"), operation("multiply", "(2*m+n+2)/7"), operation("amgm", "-m", "n"), operation("attain", "m", "-1")])
def test_wrong_mathematics_cannot_be_committed(op):
    client, view, _ = client_and_session()
    response = send(client, view, op)
    assert response.status_code == 200
    result = response.json()
    assert result["feedback"]["status"] == "invalid"
    assert result["steps"] == [] and result["state"]["lower"] is None
    assert result["focus"]["attempts"]


def test_undo_fork_switch_and_idempotence():
    client, view, _ = client_and_session()
    first = deepcopy(view)
    op = operation("substitute", "2*m+1", name="x")
    view = send(client, view, op).json()
    assert send(client, first, op).json() == view
    assert send(client, first, operation("expand")).status_code == 409
    assert send(client, first, op, event_id="stale").status_code == 409
    original_branch = view["branch_id"]
    view = send(client, view, kind="undo").json()
    assert view["state"]["aliases"] == {} and view["steps"] == []
    assert len(view["branches"]) == 2 and len(view["turns"]) == 2
    view = send(client, view, operation("multiply", "(2*m+n+2)/8")).json()
    assert view["steps"][0]["component"] == "rewrite"
    view = send(client, view, kind="switch", branch_id=original_branch).json()
    assert view["state"]["aliases"] == {"x": "2 m + 1"}
    assert len(view["steps"]) == 1


def test_focus_event_over_http():
    client, view, _ = client_and_session()
    view = send(client, view, operation("substitute", "2*m+1", name="x")).json()
    view = send(client, view, kind="focus", step_id=view["steps"][0]["id"]).json()
    assert view["focus"]["step_id"] == view["steps"][0]["id"] and view["focus"]["step_number"] == 1
    assert send(client, view, kind="focus", step_id="missing").status_code == 422
    view = send(client, view, operation("claim", "2*m+n+2", "7")).json()
    assert view["focus"]["attempts"]
    view = send(client, view, kind="abandon").json()
    assert not view["focus"]["attempts"] and len(view["steps"]) == 1


def test_partial_batch_keeps_verified_prefix_and_stops_dependents():
    text = "设x=2m+1，然后两个分母和为7，给原式乘它们的和除以7"
    model = Interpreter(propose(
        proposed("substitute", "2*m+1", name="x", source="设x=2m+1"),
        proposed("claim", "x+n+1", "7", source="两个分母和为7"),
        proposed("multiply", "(x+n+1)/7", source="给原式乘它们的和除以7"),
    ))
    client, view, _ = client_and_session(model)
    view = send(client, view, text=text).json()
    assert len(view["steps"]) == 1 and len(view["results"]) == 2
    assert view["state"]["aliases"] == {"x": "2 m + 1"}
    assert view["feedback"]["status"] == "invalid"
    assert len(model.calls) == 1 and "projection" in model.calls[0]


def test_question_hint_and_ungrounded_source_never_advance():
    model = Interpreter()
    client, view, _ = client_and_session(model)
    view = send(client, view, text="能不能用其他方法？").json()
    assert not view["steps"]
    view = send(client, view, kind="help").json()
    assert not view["steps"] and model.calls[-1]["request"] == "hint"
    assert "hint_gap" in model.calls[-1]["projection"]
    model.proposal = propose(proposed("expand", source="不存在的原话"))
    view = send(client, view, text="我想用基本不等式").json()
    assert not view["steps"] and view["feedback"]["status"] == "clarify"


def test_owner_isolation_and_anonymous_access():
    client, view, owner = client_and_session()
    owner["id"] = "00000000-0000-0000-0000-000000000002"
    assert client.get(f"/api/tutor-demo/explanation/sessions/{view['session_id']}").status_code == 404
    assert send(client, view, operation("expand")).status_code == 404
    with TestClient(create_app(enable_explanation=True)) as anonymous:
        # No configured auth service: fail closed before allowing any session.
        assert anonymous.post("/api/tutor-demo/explanation/sessions", json={}).status_code == 503


def test_provider_failure_keeps_retry_possible():
    class Fails:
        async def respond(self, **kwargs):
            raise TutorUnavailable()

    async def run():
        session = ExplanationSession("owner")
        event = ExplanationEvent(event_id="retry", revision=0, kind="text", text="设x=2m+1")
        with pytest.raises(TutorUnavailable):
            await session.handle(event, Fails())
        assert session.revision == 0 and not session.events and not session.context.turns
        model = Interpreter(propose(proposed("substitute", "2*m+1", name="x", source=event.text)))
        view = await session.handle(event, model)
        assert len(view["steps"]) == 1
        assert await session.handle(event, model) == view
        assert len(model.calls) == 1
    asyncio.run(run())


# ---- page-only interaction ---------------------------------------------------

def page_route(client, view, operations):
    for item in operations:
        response = send(client, view, item, text=item.op)
        assert response.status_code == 200, response.text
        view = response.json()
    return view


@pytest.mark.parametrize("route", ["direct", "substitution"])
def test_page_operations_alone_finish_without_questions(route):
    model = Interpreter()
    client, view, _ = client_and_session(model)
    if route == "direct":
        operations = [operation("claim", "(2*m+1)+(n+1)", "8"), operation("multiply", "((2m+1)+(n+1))÷8"),
                      operation("amgm", "(n+1)/(8*(2*m+1))", "(2*m+1)/(8*(n+1))"), operation("attain", "2*m+1", "n+1")]
    else:
        operations = [operation("substitute", "2*m+1", name="x"), operation("substitute", "n+1", name="y"),
                      operation("multiply", "(x+y)/8"), operation("amgm", "y/(8*x)", "x/(8*y)"),
                      operation("attain", "x", "y")]
    for item in operations:
        response = send(client, view, item, text=item.op)
        view = response.json()
        assert "还需说明" not in view["feedback"]["reply"]
        assert view["focus"]["step_id"] is None
    assert view["state"]["complete"] and len(view["steps"]) == len(operations) and not model.calls


def test_only_a_wrong_operation_gets_feedback_beyond_the_board():
    client, view, _ = client_and_session()
    view = send(client, view, operation("claim", "(2*m+1)+(n+1)", "7"), text="claim").json()
    assert view["feedback"]["status"] == "invalid" and not view["steps"] and "不恒成立" in view["feedback"]["reply"]
    view = page_route(client, view, [operation("multiply", "(2*m+n)/6")])
    assert view["feedback"]["reply"] == "第 1 步「乘 1 配式」已整理到板书。"


def pick(client, view, op, **filled):
    """Send the offered candidate for op, filling its blank if it has one."""
    offered = next(c for c in view["candidates"] if c["op"] == op)
    fields = {k: offered[k] for k in ("a", "b", "name")}
    if offered["blank"]:
        fields[offered["blank"]] = filled[offered["blank"]]
    chosen = operation(op, **fields)
    response = send(client, view, chosen, text=op, via="candidate")
    assert response.status_code == 200, response.text
    return response.json()


def test_candidates_follow_the_board_and_established_facts():
    model = Interpreter()
    client, view, _ = client_and_session(model)
    ops = lambda v: [c["op"] for c in v["candidates"]]
    # The key construction is not offered before its premise has been checked.
    assert "multiply" not in ops(view) and "attain" not in ops(view)
    claim = next(c for c in view["candidates"] if c["op"] == "claim")
    assert claim["blank"] == "b" and claim["echo"][-1] == {"blank": True}
    view = pick(client, view, "claim", b="7")
    assert view["feedback"]["status"] != "verified" and "multiply" not in ops(view)
    view = pick(client, view, "claim", b="8")
    assert "claim" not in ops(view)
    factor = next(c for c in view["candidates"] if c["op"] == "multiply")
    assert factor["a"] == "((2*m + 1)+(n + 1))/(8)"
    view = pick(client, view, "multiply")
    assert "multiply" not in ops(view)
    view = pick(client, view, "amgm")
    assert "amgm" not in ops(view) and "attain" in ops(view)
    view = pick(client, view, "attain")
    assert view["state"]["complete"] and view["candidates"] == [] and not model.calls
    assert {s["via"] for s in view["steps"]} == {"candidate"}
