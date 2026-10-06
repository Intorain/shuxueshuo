"""Generic LLM workflow: lifecycle correctness, not a mathematical proof oracle."""

import asyncio
import json
from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from shuxueshuo_server.tutor_demo.api import create_app, require_tutor_user
from shuxueshuo_server.tutor_demo.explanation.generated_contracts import (
    GeneratedEvent,
    GeneratedTurn,
    ProblemSpec,
)
from shuxueshuo_server.tutor_demo.explanation.generated_session import (
    GeneratedSession,
    load_problem,
)
from shuxueshuo_server.tutor_demo.explanation.references import load_references
from shuxueshuo_server.tutor_demo.limits import DialogueLimited
from shuxueshuo_server.tutor_demo.llm import TutorUnavailable
from shuxueshuo_server.tutor_demo.session import Conflict

from .auth_helpers import TeachingOnlyBudget

PROBLEM = ProblemSpec(id="other", statement="已知 a+b=10，求 a²+b² 的最小值。",
                      conditions=["a+b=10"], target="min(a²+b²)")


def state(expression="a^2+b^2", facts=None, complete=False):
    return {"expression": expression, "facts": facts or ["a+b=10"], "definitions": [],
            "symbols": ["a", "b"], "objects": [{"expression": "a+b", "latex": "a+b"}], "complete": complete}


def initial():
    return {"outcome": "initial", "state": state(), "candidates": [
        {"label": "将 $a=b=5$ 代入原式"}, {"label": "展开 $(a+b)^2$"}]}


def step(number=1, complete=False):
    return {"outcome": "step", "step": {"title": f"推导 {number}", "change": {"before": "a+b=10", "after": "(a+b)^2=100"}, "highlight": {"kind": "conclusion", "content": "$(a+b)^2=100$"}, "lines": [r"\because a+b=10", r"\therefore (a+b)^2=100"]},
            "state": state(f"expression{number}", complete=complete),
            "candidates": [] if complete else [{"label": f"下一操作 {number}"}]}


class Generator:
    prompt_version = "generated-test"

    def __init__(self, *responses):
        self.responses, self.calls = list(responses), []

    async def respond(self, **kwargs):
        self.calls.append(deepcopy(kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return deepcopy(response)


def event(view, kind, event_id=None, **fields):
    return GeneratedEvent(revision=view["revision"], event_id=event_id or str(view["revision"]), kind=kind, **fields)


def test_ranked_choices_are_deduplicated_and_capped_for_initial_step_and_undo():
    async def run():
        many = [{"label": label} for label in ["  展开平方  ", "展开平方", "消去变量", "配方", "通分", "换元"]]
        start, advance = initial(), step()
        start["candidates"] = many
        advance["candidates"] = list(reversed(many))
        session = GeneratedSession("owner", PROBLEM)
        generator = Generator(start, advance)
        first = await session.generate_initial(generator)
        assert [c["label"] for c in first["choices"]["candidates"]] == ["展开平方", "消去变量", "配方"]
        one = await session.handle(event(first, "candidate", candidate_id=first["choices"]["candidates"][0]["id"]), generator)
        assert len(one["steps"]) == 1
        assert [c["label"] for c in one["choices"]["candidates"]] == ["换元", "通分", "配方"]
        undone = await session.handle(event(one, "undo"), generator)
        assert undone["choices"] == first["choices"] and len(generator.calls) == 2
    asyncio.run(run())
    assert GeneratedTurn.model_json_schema()["properties"]["candidates"]["maxItems"] == 3
    assert len(GeneratedTurn.model_validate(initial()).candidates) == 2  # Never pad.


def test_generic_multistep_cached_choices_atomic_undo_switch_and_idempotence():
    async def run():
        session = GeneratedSession("owner", PROBLEM)
        generator = Generator(initial(), step(), step(2, complete=True), step(3))
        first = await session.generate_initial(generator)
        assert await session.generate_initial(generator) == first
        assert len(generator.calls) == 1
        pick = event(first, "candidate", candidate_id=first["choices"]["candidates"][0]["id"])
        one = await session.handle(pick, generator)
        assert len(one["steps"]) == 1 and one["steps"][0]["provenance"] == "llm_generated"
        assert one["steps"][0]["highlight"] == step()["step"]["highlight"]
        assert one["steps"][0]["change"] == step()["step"]["change"]
        assert one["choices"]["candidates"][0]["label"] == "下一操作 1"
        assert generator.calls[-1]["projection"]["request"]["action"] == "将 $a=b=5$ 代入原式"
        assert await session.handle(pick, generator) == one and len(generator.calls) == 2
        with pytest.raises(Conflict):
            await session.handle(event(one, "candidate", candidate_id=first["choices"]["candidates"][0]["id"]), generator)
        two = await session.handle(event(one, "candidate", candidate_id=one["choices"]["candidates"][0]["id"]), generator)
        assert two["state"]["complete"] and not two["choices"]["candidates"]
        assert len(generator.calls[-1]["projection"]["steps"]) == 1
        assert generator.calls[-1]["projection"]["steps"][0]["highlight"] == one["steps"][0]["highlight"]
        assert generator.calls[-1]["projection"]["steps"][0]["change"] == one["steps"][0]["change"]
        undone = await session.handle(event(two, "undo"), generator)
        assert undone["state"] == one["state"] and undone["choices"] == one["choices"]
        assert len(undone["steps"]) == 1 and len(generator.calls) == 3
        alternate = await session.handle(event(undone, "candidate", candidate_id=undone["choices"]["candidates"][0]["id"]), generator)
        assert len(alternate["steps"]) == 2
        assert "expression2" not in str(generator.calls[-1]["projection"])
        restored = await session.handle(event(alternate, "switch", branch_id=two["branch_id"]), generator)
        assert restored["state"] == two["state"] and restored["steps"] == two["steps"]
        with pytest.raises(Conflict):
            await session.handle(event(one, "undo", "stale"), generator)
        assert len(generator.calls) == 4
    asyncio.run(run())


def test_failures_and_invalid_responses_never_publish_partial_state_and_retry_once():
    async def run():
        session = GeneratedSession("owner", PROBLEM)
        malformed = step()
        del malformed["state"]
        generator = Generator(initial(), TutorUnavailable(), malformed, step())
        first = await session.generate_initial(generator)
        pick = event(first, "candidate", candidate_id=first["choices"]["candidates"][0]["id"])
        for _ in range(2):
            with pytest.raises(TutorUnavailable):
                await session.handle(pick, generator)
            assert session.view() == first and not session.events and len(session.audit) == 1
        result = await session.handle(pick, generator)
        assert len(result["steps"]) == 1
        assert await session.handle(pick, generator) == result and len(generator.calls) == 4
    asyncio.run(run())


def test_help_question_rejection_and_focused_discussion_do_not_advance():
    async def run():
        feedback = {"outcome": "feedback", "reply": "这只是下界，还需要检验能否取到。"}
        session = GeneratedSession("owner", PROBLEM)
        generator = Generator(initial(), step(), step(), feedback, feedback, feedback)
        first = await session.generate_initial(generator)
        with pytest.raises(TutorUnavailable):
            await session.handle(event(first, "help"), generator)
        assert session.view() == first
        one = await session.handle(event(first, "text", text="展开平方"), generator)
        focused = await session.handle(event(one, "focus", step_id=one["steps"][0]["id"]), generator)
        discussed = await session.handle(event(focused, "text", text="为什么？"), generator)
        assert generator.calls[-1]["projection"]["request"]["kind"] == "discuss"
        assert discussed["state"] == one["state"] and discussed["choices"] == one["choices"]
        clear = await session.handle(event(discussed, "focus"), generator)
        failed = await session.handle(event(clear, "text", text="最小值为零"), generator)
        assert failed["steps"] == one["steps"] and failed["state"] == one["state"]
        helped = await session.handle(event(failed, "help"), generator)
        assert helped["state"] == one["state"]
        assert generator.calls[-1]["projection"]["discussion"][-1]["text"] == feedback["reply"]
    asyncio.run(run())


def test_empty_choices_are_not_completion_and_refresh_cannot_change_math():
    async def run():
        empty = {**initial(), "candidates": [], "reply": "暂未找到下一步，可以重新生成或自己写一步。"}
        changed = initial()
        changed["state"]["expression"] = "different"
        session = GeneratedSession("owner", PROBLEM)
        generator = Generator(empty, changed, initial())
        first = await session.generate_initial(generator)
        assert not first["state"]["complete"] and not first["choices"]["candidates"]
        with pytest.raises(TutorUnavailable):
            await session.handle(event(first, "refresh"), generator)
        assert session.view() == first
        updated = await session.handle(event(first, "refresh"), generator)
        assert updated["choices"]["candidates"] and not updated["steps"]
    asyncio.run(run())


def test_problem_loader_only_projects_problem_data():
    problem = load_problem("q12")
    assert set(problem.model_dump()) == {"id", "statement", "conditions", "target"}
    assert "reference_routes" not in str(GeneratedSession("owner", problem).project({"kind": "initial"}))


def test_unknown_model_metadata_is_discarded_without_weakening_required_fields():
    raw = step()
    raw["step"].update(student_action="untrusted extra", lines_note=None)
    raw["state"]["verified"] = True
    parsed = GeneratedTurn.model_validate(raw).model_dump()
    assert "student_action" not in parsed["step"] and "lines_note" not in parsed["step"]
    assert "verified" not in parsed["state"]
    del raw["step"]["lines"]
    with pytest.raises(ValueError):
        GeneratedTurn.model_validate(raw)


def test_step_requires_separate_problem_or_conclusion_highlight():
    raw = step()
    del raw["step"]["highlight"]
    with pytest.raises(ValueError):
        GeneratedTurn.model_validate(raw)
    raw["step"]["highlight"] = {"kind": "problem", "content": "已知 $a+b=10$，求 $a^2+b^2$ 的最小值。"}
    assert GeneratedTurn.model_validate(raw).step.highlight.kind == "problem"
    raw["step"]["highlight"]["kind"] = "guessed_answer"
    with pytest.raises(ValueError):
        GeneratedTurn.model_validate(raw)


@pytest.mark.parametrize("bad_change", [None, {"before": "a+b=10", "after": ""}])
def test_missing_or_invalid_change_never_commits_partial_step(bad_change):
    async def run():
        invalid = step()
        if bad_change is None:
            del invalid["step"]["change"]
        else:
            invalid["step"]["change"] = bad_change
        generator = Generator(initial(), invalid)
        session = GeneratedSession("owner", PROBLEM)
        first = await session.generate_initial(generator)
        with pytest.raises(TutorUnavailable):
            await session.handle(event(first, "text", text="展开平方"), generator)
        assert session.view() == first and not session.events
    asyncio.run(run())


def test_reference_context_uses_existing_family_prose_and_math_routes_only():
    references = load_references("q12")
    family = references["family_guidance"]
    repo = Path(__file__).resolve().parents[3]
    authored = json.loads((repo / family["source"]).read_text())
    assert family["family_id"] == "basic_inequality"
    assert family["methods"] == authored["methods"] and len(family["methods"]) == 6
    assert family["strategy_overview"] == authored["strategy_overview"]
    routes = {r["id"]: r for r in references["reference_solutions"]}
    assert set(routes) == {"substitution", "direct"}
    assert len(routes["substitution"]["derivation"]) == 6
    assert routes["direct"]["operations"]
    assert "criteria" not in str(references) and "必须" not in str(routes)
    session = GeneratedSession("owner", load_problem("q12"), references)
    projection = session.project({"kind": "initial"})
    assert projection["reference_solutions"] == references["reference_solutions"]
    assert projection["family_guidance"] == family
    assert projection["state"] is None and projection["steps"] == []
    public = session.view()
    assert "reference_solutions" not in public and "family_guidance" not in public
    # Mutating an outgoing projection cannot modify future context or snapshots.
    projection["reference_solutions"].clear()
    assert session.project({"kind": "initial"})["reference_solutions"]


def test_live_router_uses_new_engine_and_enforces_auth_owner_conflicts():
    owner = {"id": "00000000-0000-0000-0000-000000000001"}
    generator = Generator(initial(), step())
    budget = TeachingOnlyBudget()
    app = create_app(explanation_interpreter=generator, budget=budget, enable_explanation=True)
    app.dependency_overrides[require_tutor_user] = lambda: owner
    with TestClient(app) as client:
        first = client.post("/api/tutor-demo/explanation/sessions", json={}).json()
        assert first["engine"] == "llm"
        base = f"/api/tutor-demo/explanation/sessions/{first['session_id']}"
        ready = client.post(base + "/candidates", json={}).json()
        assert set(ready["choices"]["candidates"][0]) == {"id", "label"}
        assert "audit" not in ready
        owner["id"] = "00000000-0000-0000-0000-000000000002"
        assert client.get(base).status_code == 404
        assert client.post(base + "/candidates", json={}).status_code == 404
        owner["id"] = "00000000-0000-0000-0000-000000000001"
        body = event(ready, "candidate", candidate_id=ready["choices"]["candidates"][0]["id"]).model_dump()
        response = client.post(base + "/events", json=body)
        assert response.status_code == 200 and len(response.json()["steps"]) == 1
        assert client.post(base + "/events", json=body).json() == response.json()
        assert client.post(base + "/events", json={**body, "event_id": "stale"}).status_code == 409
        assert client.post("/api/tutor-demo/explanation/sessions", json={"problem_id": "../../bad"}).status_code == 422
    with TestClient(create_app(enable_explanation=True)) as anonymous:
        assert anonymous.post("/api/tutor-demo/explanation/sessions", json={}).status_code == 503


def test_quota_blocks_new_generation_but_not_undo_or_switch():
    class Budget(TeachingOnlyBudget):
        blocked = False

        def reserve(self, *args, **kwargs):
            if self.blocked:
                raise DialogueLimited("test_limit", "limit", 5)

    budget, generator = Budget(), Generator(initial(), step())
    app = create_app(explanation_interpreter=generator, budget=budget, enable_explanation=True)
    app.dependency_overrides[require_tutor_user] = lambda: {"id": "owner"}
    with TestClient(app) as client:
        first = client.post("/api/tutor-demo/explanation/sessions", json={}).json()
        base = f"/api/tutor-demo/explanation/sessions/{first['session_id']}"
        ready = client.post(base + "/candidates", json={}).json()
        one = client.post(base + "/events", json=event(ready, "candidate",
            candidate_id=ready["choices"]["candidates"][0]["id"]).model_dump()).json()
        budget.blocked = True
        assert client.post(base + "/events", json=event(one, "help").model_dump()).status_code == 429
        assert client.get(base).json()["revision"] == one["revision"]
        undone = client.post(base + "/events", json=event(one, "undo").model_dump()).json()
        assert not undone["steps"] and undone["choices"] == ready["choices"]
        switched = client.post(base + "/events", json=event(undone, "switch", branch_id=one["branch_id"]).model_dump())
        assert switched.status_code == 200 and switched.json()["state"] == one["state"]
        assert len(generator.calls) == 2


def test_custom_operation_is_not_limited_to_historical_q12_executor():
    async def run():
        session, generator = GeneratedSession("owner", PROBLEM), Generator(initial(), step())
        first = await session.generate_initial(generator)
        result = await session.handle(event(first, "operation", operation={"op": "differentiate", "a": "a^2+(10-a)^2"}), generator)
        assert len(result["steps"]) == 1
        assert generator.calls[-1]["projection"]["request"]["operation"]["op"] == "differentiate"
        assert generator.calls[-1]["projection"]["problem"] == PROBLEM.model_dump()
    asyncio.run(run())
