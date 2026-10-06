"""Experimental explanation support must not change the established tutor contract."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from shuxueshuo_server.tutor_demo.api import create_app
from shuxueshuo_server.tutor_demo.limits import BudgetedTutor, DialogueLimited
from shuxueshuo_server.tutor_demo.llm import DeepSeekTutor, Proposal, TutorUnavailable
from shuxueshuo_server.tutor_demo.session import load_lesson

VALID = {"reply": "先看固定的条件。", "intent": "question", "evidence": [], "actions": []}


class Budget:
    def __init__(self, blocked=False):
        self.blocked, self.calls, self.failures = blocked, 0, 0

    def reserve(self, session_id, *, user_id):
        if self.blocked:
            raise DialogueLimited("daily_limit", "quota exhausted")
        self.calls += 1
        return 49

    def failed(self, session_id):
        self.failures += 1


def setup_legacy(response, *, finish="stop", blocked=False):
    calls, budget, tutor = [], Budget(blocked), DeepSeekTutor()

    async def create(**kwargs):
        calls.append(kwargs)
        if isinstance(response, Exception):
            raise response
        return SimpleNamespace(choices=[SimpleNamespace(
            finish_reason=finish, message=SimpleNamespace(content=response))])

    tutor.key = "test-only"
    tutor.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    data = {"lesson": load_lesson("q01"), "context": {"node": load_lesson("q01")["routes"]["direct"]["nodes"][1]},
            "completed": [], "messages": [], "event": {"kind": "text", "text": "怎么做？"}}
    return BudgetedTutor(tutor, budget, "session", user_id="owner"), budget, calls, data


def test_legacy_success_keeps_request_parameters_proposal_and_single_reservation():
    async def run():
        tutor, budget, calls, data = setup_legacy(json.dumps(VALID))
        result = await tutor.respond(**data)
        assert isinstance(result, Proposal) and result.model_dump() == VALID
        assert len(calls) == budget.calls == 1 and budget.failures == 0
        assert tutor.remaining == 49
        assert calls[0]["max_tokens"] == 1600
        assert calls[0]["response_format"] == {"type": "json_object"}
        assert calls[0]["extra_body"] == {"thinking": {"type": "disabled"}}
        assert "amgm_relation" in calls[0]["messages"][1]["content"]
        assert "reference_solutions" not in str(calls[0]["messages"])
    asyncio.run(run())


@pytest.mark.parametrize("response, finish", [
    (json.dumps(VALID).replace('"reply":', '"reply"'), "stop"),  # Repairable only in explanation mode.
    ('{"reply":"missing fields"}', "stop"),
    (json.dumps(VALID), "length"),
    (TimeoutError("provider"), "stop"),
])
def test_legacy_errors_do_not_enable_json_repair_or_an_extra_model_call(response, finish):
    async def run():
        tutor, budget, calls, data = setup_legacy(response, finish=finish)
        with pytest.raises(TutorUnavailable):
            await tutor.respond(**data)
        assert len(calls) == budget.calls == budget.failures == 1
    asyncio.run(run())


def test_legacy_quota_still_blocks_before_provider_call():
    async def run():
        tutor, budget, calls, data = setup_legacy(json.dumps(VALID), blocked=True)
        with pytest.raises(DialogueLimited):
            await tutor.respond(**data)
        assert not calls and budget.calls == budget.failures == 0
    asyncio.run(run())


def test_default_router_does_not_construct_or_register_explanation(monkeypatch):
    from shuxueshuo_server.tutor_demo.explanation import api

    def forbidden():
        pytest.fail("default entry must not initialize the experiment")

    monkeypatch.setattr(api, "ExplanationGenerator", forbidden)
    with TestClient(create_app()) as client:
        paths = {p for p in client.get("/openapi.json").json()["paths"] if p.startswith("/api/tutor-demo/")}
        assert paths == {"/api/tutor-demo/sessions", "/api/tutor-demo/sessions/{session_id}",
                         "/api/tutor-demo/sessions/{session_id}/events"}
        assert client.post("/api/tutor-demo/explanation/sessions", json={}).status_code == 404


def test_default_q12_page_has_no_explanation_entry():
    with TestClient(create_app()) as client:
        response = client.get("/1/q12/")
        assert response.status_code == 200
        assert "/1/q12/explain/" not in response.text
