"""Repair syntax without changing math; retry once with atomic, budgeted commits."""

import asyncio
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from shuxueshuo_server.tutor_demo.explanation.generated_llm import ExplanationGenerator
from shuxueshuo_server.tutor_demo.explanation.generated_session import GeneratedSession
from shuxueshuo_server.tutor_demo.explanation.json_format import decode_model_json
from shuxueshuo_server.tutor_demo.limits import BudgetedTutor, DialogueLimited
from shuxueshuo_server.tutor_demo.llm import ModelResponseInvalid, TutorUnavailable

from .test_generated_explanation import PROBLEM, event, initial, step


@pytest.mark.parametrize("source, expected", [
    ('```json\n{"a":1}\n```', {"a": 1}),
    ('{"a" 1, "b" [2]}', {"a": 1, "b": [2]}),
    ('{"a":1 "b":[2 3]}', {"a": 1, "b": [2, 3]}),
    ('{"a":[1,2,],}', {"a": [1, 2]}),
    ('{"a"：1，"b":2}', {"a": 1, "b": 2}),
    (r'{"math":"x\cdot y"}', {"math": r"x\cdot y"}),
    ('{"math":"a=1\nb=2"}', {"math": "a=1\nb=2"}),
    (r'{"math":"x,y:a\\cdot b，c：d"}', {"math": r"x,y:a\cdot b，c：d"}),
])
def test_common_syntax_repairs_preserve_values(source, expected):
    payload, _ = decode_model_json(source)
    assert payload == expected


@pytest.mark.parametrize("source", [
    '{"a":', '{"a":1', '{"a":"unfinished', '{"a":}', '{"a":[1,,2]}',
    '{"a":1} {"a":2}', '{"a":1} explanation', '{"a":1,"a":2}',
    '{"a":NaN}', '[]', '```json\n{"a":1}',
])
def test_ambiguous_missing_or_truncated_content_is_not_invented(source):
    with pytest.raises((ValueError, TypeError)):
        decode_model_json(source)


class Provider:
    def __init__(self, *responses):
        self.responses, self.calls = list(responses), []

    async def create(self, **kwargs):
        self.calls.append(deepcopy(kwargs))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        content, finish = item if isinstance(item, tuple) else (item, "stop")
        return SimpleNamespace(choices=[SimpleNamespace(
            finish_reason=finish, message=SimpleNamespace(content=content))])


class Budget:
    def __init__(self, limit=10):
        self.calls, self.failures, self.limit = 0, 0, limit

    def reserve(self, session_id, *, user_id):
        if self.calls == self.limit:
            raise DialogueLimited("test_limit", "quota exhausted")
        self.calls += 1

    def failed(self, session_id):
        self.failures += 1


def generator_for(*responses, limit=10):
    tutor, budget, provider = ExplanationGenerator(), Budget(limit), Provider(*responses)
    tutor.key = "test-only"
    tutor.client = SimpleNamespace(chat=SimpleNamespace(completions=provider))
    return BudgetedTutor(tutor, budget, "session", user_id="owner"), budget, provider


def test_local_repair_does_not_make_another_provider_call():
    async def run():
        source = json.dumps(initial(), ensure_ascii=False).replace('"outcome":', '"outcome"', 1)
        generator, budget, provider = generator_for(source)
        session = GeneratedSession("owner", PROBLEM)
        view = await session.generate_initial(generator)
        assert view["choices"]["candidates"] and not view["steps"]
        assert budget.calls == len(provider.calls) == 1 and budget.failures == 0
    asyncio.run(run())


@pytest.mark.parametrize("bad", [
    '{"step":',  # Unsafe to finish this JSON in code.
    json.dumps({"outcome": "step", "step": {"title": "missing derivation"}}),
    (json.dumps(step()), "length"),  # Even syntactically valid truncated output is rejected.
])
def test_regeneration_uses_original_context_charges_each_call_and_commits_once(bad):
    async def run():
        generator, budget, provider = generator_for(json.dumps(initial()), bad, json.dumps(step()))
        session = GeneratedSession("owner", PROBLEM)
        before = await session.generate_initial(generator)
        pick = event(before, "candidate", candidate_id=before["choices"]["candidates"][0]["id"])
        after = await session.handle(pick, generator)
        assert len(after["steps"]) == 1 and len(session.audit) == 2
        assert provider.calls[1]["messages"] == provider.calls[2]["messages"]
        assert budget.calls == len(provider.calls) == 3 and budget.failures == 0
        assert await session.handle(pick, generator) == after
        assert len(provider.calls) == 3
    asyncio.run(run())


def test_second_bad_response_preserves_progress_then_user_retry_can_succeed():
    async def run():
        generator, budget, provider = generator_for(
            json.dumps(initial()), '{"step":', '{"step":', json.dumps(step()))
        session = GeneratedSession("owner", PROBLEM)
        before = await session.generate_initial(generator)
        pick = event(before, "candidate", candidate_id=before["choices"]["candidates"][0]["id"])
        with pytest.raises(ModelResponseInvalid):
            await session.handle(pick, generator)
        assert session.view() == before and not session.events
        assert budget.calls == len(provider.calls) == 3 and budget.failures == 1
        after = await session.handle(pick, generator)
        assert len(after["steps"]) == 1 and len(provider.calls) == 4
    asyncio.run(run())


def test_retry_respects_remaining_quota():
    async def run():
        generator, budget, provider = generator_for('{"step":', json.dumps(initial()), limit=1)
        session = GeneratedSession("owner", PROBLEM)
        before = session.view()
        with pytest.raises(DialogueLimited):
            await session.generate_initial(generator)
        assert session.view() == before and budget.calls == len(provider.calls) == 1
    asyncio.run(run())


def test_network_error_is_not_treated_as_a_format_retry():
    async def run():
        generator, budget, provider = generator_for(TimeoutError("network"), json.dumps(initial()))
        with pytest.raises(TutorUnavailable):
            await GeneratedSession("owner", PROBLEM).generate_initial(generator)
        assert budget.calls == len(provider.calls) == 1 and budget.failures == 1
    asyncio.run(run())
