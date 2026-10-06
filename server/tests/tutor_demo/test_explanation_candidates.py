"""Initial LLM choices: exact filtering, authentication, atomic selection and replay."""

import asyncio
from copy import deepcopy

from fastapi import FastAPI
from fastapi.testclient import TestClient

from shuxueshuo_server.tutor_demo.explanation.legacy_api import create_explanation_router
from shuxueshuo_server.tutor_demo.explanation.candidates import CandidateProposal, projection, verify
from shuxueshuo_server.tutor_demo.explanation.context import ExplanationContext
from shuxueshuo_server.tutor_demo.explanation.contracts import ExplanationEvent
from shuxueshuo_server.tutor_demo.explanation.session import ExplanationSession

from .auth_helpers import TeachingOnlyBudget


def sample():
    return CandidateProposal(candidates=[
        {"operations": [{"op": "substitute", "a": "2*m+1", "name": "x"},
                        {"op": "substitute", "a": "n+1", "name": "y"}]},
        {"operations": [{"op": "evaluate", "a": "(2*m+1)+(n+1)"}]},
        {"operations": [{"op": "amgm", "a": "1/(2*m+1)", "b": "1/(n+1)"}]},
        {"operations": [{"op": "multiply", "a": "((2*m+1)+(n+1))/8"}]},
    ])


class Generator:
    prompt_version = "candidate-test"

    def __init__(self):
        self.calls = 0

    async def respond(self, **kwargs):
        self.calls += 1
        return sample()


def test_trial_isolation_filters_bad_incomplete_duplicate_and_no_change():
    context = ExplanationContext()
    before = deepcopy(context.view())
    proposals = sample()
    proposals.candidates += [
        {"operations": [{"op": "multiply", "a": "2*m+n"}]},
        {"operations": [{"op": "amgm", "a": "m"}]},
        {"operations": [{"op": "expand"}]},
        {"operations": [{"op": "evaluate", "a": "(2*m+1)+(n+1)"}]},
        # The first substitution is valid; the second must discard the entire choice.
        {"operations": [{"op": "substitute", "a": "2*m+1", "name": "x"},
                        {"op": "substitute", "a": "m", "name": "y"}]},
    ]
    result = verify(context, proposals)
    assert len(result["candidates"]) == 4
    assert len(result["rejected"]) == 5
    assert context.view() == before
    assert result["candidates"][1]["echo"][0] == {"text": "计算 "}
    # A valid AM-GM that does not yield a constant bound is still offered.
    assert result["candidates"][2]["operations"][0]["op"] == "amgm"
    assert "reference_routes" not in str(projection(context))
    assert "interpretation_examples" not in str(projection(context))


def test_atomic_choice_cached_generation_undo_and_idempotence():
    async def run():
        session, generator = ExplanationSession("owner"), Generator()
        first = await session.generate_initial(generator, generator.prompt_version)
        assert await session.generate_initial(generator, generator.prompt_version) == first
        assert generator.calls == 1 and session.revision == 0
        assert not first["steps"] and not first["state"]["aliases"]
        pick = ExplanationEvent(kind="candidate", event_id="pick", revision=0,
                                candidate_id=first["initial_choices"]["candidates"][0]["id"])
        result = await session.handle(pick, generator)
        assert len(result["steps"]) == 2
        assert len(result["board_steps"]) == 1
        board = result["board_steps"][0]
        assert board["step_count"] == 2
        assert board["title"] == "换元"
        assert [r["lead"] for r in board["derivation"]] == ["设", "因为", "所以", "原式可化为"]
        proof = str(board["derivation"])
        assert "x=2 m + 1" in proof and "y=n + 1" in proof
        assert "x + y=8" in proof and "x>1" in proof and "y>1" in proof
        assert "F" not in proof
        assert "第 2 步" not in result["feedback"]["reply"]
        assert result["branches"][0]["steps"] == 1
        assert set(result["state"]["aliases"]) == {"x", "y"}
        assert {s["via"] for s in result["steps"]} == {"candidate"}
        assert result["initial_choices"] is None
        assert await session.handle(pick, generator) == result
        undone = await session.handle(ExplanationEvent(kind="undo", event_id="undo", revision=1), generator)
        assert not undone["steps"] and not undone["state"]["aliases"]
        assert undone["initial_choices"] == first["initial_choices"]
        assert generator.calls == 1
        # Follow a different cached choice without calling the model again.
        calc = await session.handle(ExplanationEvent(kind="candidate", event_id="calc", revision=2,
                                    candidate_id=first["initial_choices"]["candidates"][1]["id"]), generator)
        assert calc["steps"][0]["result"].endswith("=8")
    asyncio.run(run())


def test_group_boundary_and_following_step_number():
    async def run():
        session, generator = ExplanationSession("owner"), Generator()
        first = await session.generate_initial(generator, generator.prompt_version)
        await session.handle(ExplanationEvent(kind="candidate", event_id="pick", revision=0,
                             candidate_id=first["initial_choices"]["candidates"][0]["id"]), generator)
        from shuxueshuo_server.tutor_demo.contracts import InvalidAction
        import pytest
        with pytest.raises(InvalidAction, match="完整操作"):
            await session.handle(ExplanationEvent(kind="fork", event_id="half", revision=1, step_count=1), generator)
        branched = await session.handle(ExplanationEvent(kind="fork", event_id="full", revision=1, step_count=2), generator)
        assert len(branched["board_steps"]) == 1
        result = await session.handle(ExplanationEvent(kind="operation", event_id="next", revision=2,
            operation={"op": "multiply", "a": "(x+y)/8"}), generator)
        assert len(result["board_steps"]) == 2
        assert "第 2 步" in result["feedback"]["reply"]
        undone = await session.handle(ExplanationEvent(kind="undo", event_id="back", revision=3), generator)
        assert len(undone["board_steps"]) == 1
        assert set(undone["state"]["aliases"]) == {"x", "y"}
    asyncio.run(run())


def test_related_substitutions_are_one_choice_instead_of_repeated_singletons():
    proposed = sample()
    proposed.candidates.append({"operations": [{"op": "substitute", "a": "2*m+1", "name": "u"}]})
    batch = verify(ExplanationContext(), proposed)
    assert len(batch["candidates"]) == 4
    assert len(batch["candidates"][0]["operations"]) == 2


def test_routes_enforce_owner_and_initial_state_and_do_not_expose_raw_proposals():
    owner = {"id": "00000000-0000-0000-0000-000000000001"}
    generator = Generator()
    app = FastAPI()
    app.include_router(create_explanation_router(lambda: owner, budget=TeachingOnlyBudget(),
                                                 candidate_generator=generator))
    with TestClient(app) as client:
        view = client.post("/explanation/sessions", json={}).json()
        base = f"/explanation/sessions/{view['session_id']}"
        response = client.post(base + "/initial-candidates", json={})
        assert response.status_code == 200
        choices = response.json()["initial_choices"]
        assert "raw" not in choices and "rejected" not in choices
        assert set(choices["candidates"][0]) == {"id", "echo"}
        owner["id"] = "00000000-0000-0000-0000-000000000002"
        assert client.post(base + "/initial-candidates", json={}).status_code == 404
        owner["id"] = "00000000-0000-0000-0000-000000000001"
        body = {"kind": "candidate", "candidate_id": choices["candidates"][0]["id"],
                "revision": 0, "event_id": "one"}
        assert client.post(base + "/events", json=body).status_code == 200
        assert client.post(base + "/initial-candidates", json={}).status_code == 422
        body.update(event_id="two", revision=1)
        assert client.post(base + "/events", json=body).status_code == 409
