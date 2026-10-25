"""Offline transport checks for the request-bound search expense stop switch."""

from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from types import SimpleNamespace

import pytest

from shuxueshuo_server.graph_lesson.stage_two.selection import SelectionRequest
from shuxueshuo_server.search.storage import SearchError
from shuxueshuo_server.solver.extraction.multimodal_provider import (
    DeepSeekTextProblemDomainProvider,
    MultimodalExtractionPrompt,
)
from shuxueshuo_server.solver.extraction.request_guard import (
    ModelRequestScopeRequired,
    check_model_request,
    model_request_scope,
    require_model_request_scope,
)


def request():
    return SelectionRequest(
        MultimodalExtractionPrompt('offline-system', 'offline-user', '', includes_images=False),
        {},
    )


def response(text='{"offline": true}'):
    return SimpleNamespace(model='offline-model', usage=None, choices=[
        SimpleNamespace(message=SimpleNamespace(content=text), finish_reason='stop'),
    ])


def fake_provider(outputs, *, sleeper=lambda _seconds: None):
    calls, options = [], {}

    def create(**payload):
        calls.append(payload)
        result = outputs.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def factory(**values):
        options.update(values)
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    provider = DeepSeekTextProblemDomainProvider(
        api_key='offline-fixture-only', base_url='https://invalid.example',
        client_factory=factory, sleeper=sleeper,
    )
    return provider, calls, options


def stopped():
    raise SearchError('search.generation_paused', 503)


def test_search_scope_requirement_fails_closed_without_changing_optional_transport_guard():
    with pytest.raises(ModelRequestScopeRequired, match='model.request_scope_required'):
        require_model_request_scope()
    check_model_request()
    provider, calls, _options = fake_provider([response()])
    assert provider.complete(request()).text == '{"offline": true}'
    assert len(calls) == 1


def test_search_scope_requirement_is_presence_only_and_restored_after_exit():
    checks = []
    with model_request_scope(lambda: checks.append('authorized')):
        require_model_request_scope()
        assert checks == []
        check_model_request()
        assert checks == ['authorized']
    with pytest.raises(ModelRequestScopeRequired, match='model.request_scope_required'):
        require_model_request_scope()


def test_stopped_scope_prevents_actual_text_provider_transport():
    provider, calls, options = fake_provider([response()])
    with model_request_scope(stopped), pytest.raises(SearchError, match='search.generation_paused'):
        provider.complete(request())
    assert calls == []
    assert provider.last_completion_started is False
    assert provider.last_provider_attempts == ()
    assert options['max_retries'] == 0


@pytest.mark.parametrize('first_result', [TimeoutError('offline timeout'), response('')])
def test_hot_stop_between_attempts_blocks_retry_without_a_second_request(first_result):
    state = {'enabled': True, 'checks': 0, 'delays': []}

    def guard():
        state['checks'] += 1
        if not state['enabled']:
            stopped()

    def stop_during_backoff(delay):
        state['delays'].append(delay)
        state['enabled'] = False

    provider, calls, _options = fake_provider([first_result, response()], sleeper=stop_during_backoff)
    with model_request_scope(guard), pytest.raises(SearchError, match='search.generation_paused'):
        provider.complete(request())
    assert len(calls) == 1
    assert state['checks'] == 3
    assert state['delays'] == [.25]
    assert len(provider.last_provider_attempts) == 1


def test_stop_after_request_preparation_still_prevents_transport(monkeypatch):
    state = {'enabled': True}
    provider, calls, _options = fake_provider([response()])
    original = provider._messages_for_attempt

    def messages(current, attempt):
        prepared = original(current, attempt)
        state['enabled'] = False
        return prepared

    def guard():
        if not state['enabled']:
            stopped()

    monkeypatch.setattr(provider, '_messages_for_attempt', messages)
    with model_request_scope(guard), pytest.raises(SearchError, match='search.generation_paused'):
        provider.complete(request())
    assert calls == []
    assert provider.last_completion_started is False


def test_scope_restores_outer_guard_and_unscoped_provider_after_exception():
    calls = []
    with model_request_scope(lambda: calls.append('outer')):
        check_model_request()
        with model_request_scope(stopped), pytest.raises(SearchError):
            check_model_request()
        check_model_request()
    check_model_request()
    assert calls == ['outer', 'outer']
    provider, transport, _options = fake_provider([response()])
    assert provider.complete(request()).text == '{"offline": true}'
    assert len(transport) == 1


def test_copied_scope_reaches_worker_but_does_not_leak_to_later_jobs():
    with ThreadPoolExecutor(max_workers=1) as executor:
        with model_request_scope(stopped):
            executor.submit(check_model_request).result(timeout=5)
            copied = copy_context()
            with pytest.raises(SearchError, match='search.generation_paused'):
                executor.submit(copied.run, check_model_request).result(timeout=5)
        executor.submit(check_model_request).result(timeout=5)
        provider, calls, _options = fake_provider([response()])
        assert executor.submit(provider.complete, request()).result(timeout=5).text == '{"offline": true}'
        assert len(calls) == 1


def test_disabled_request_scope_in_worker_does_not_leak_after_failure():
    def scoped():
        with model_request_scope(stopped):
            check_model_request()

    with ThreadPoolExecutor(max_workers=1) as executor:
        with pytest.raises(SearchError, match='search.generation_paused'):
            executor.submit(scoped).result(timeout=5)
        executor.submit(check_model_request).result(timeout=5)
