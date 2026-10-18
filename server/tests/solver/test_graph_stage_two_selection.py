"""Selection failures, bounded shared transport, and exact-request replay."""

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from shuxueshuo_server.graph_lesson.stage_two.selection import (
    CONTRACT,
    RecordedSelectionProvider,
    SelectionError,
    build_request,
    live_provider_factory,
    select_primary,
)
from shuxueshuo_server.solver.extraction.multimodal_provider import (
    DeepSeekTextProblemDomainProvider,
)

TARGET = "/root/goals/0"
CANDIDATE = {"original_text": "求 a 的范围。", "root": {
    "facts": ["∀x∈ℝ:x^2>=a"], "goals": [{"kind": "find_range", "symbol": "a"}],
}}


def reports():
    return [{"type_id": name, "status": state, "branches": [{
        "branch_id": "main", "status": state, "checks": [{
            "check_id": f"{name}/main/domain", "feature_id": "domain",
            "status": state, "actual": "real", "expected": "real",
        }],
    }]} for name, state in [("quantified", "supported"), ("alternative", "supported"),
                           ("conflicting", "conflict"), ("uncertain", "unknown")]]


def choice(target=TARGET, primary="quantified"):
    return {"contract": CONTRACT, "target_ref": target, "primary_type_id": primary,
            "branch_id": "main", "check_ids": [f"{primary}/main/domain"],
            "reason": "量词与所求直接对应该题型。"}


def response(value=None, finish="stop"):
    text = json.dumps(choice() if value is None else value, ensure_ascii=False) if not isinstance(value, str) else value
    return SimpleNamespace(model="test-model", usage=None, choices=[SimpleNamespace(
        finish_reason=finish, message=SimpleNamespace(content=text))])


def transport(*responses):
    """Use the real shared provider; only its SDK client's network is replaced."""
    calls, options, pending = [], [], iter(responses or [response()])

    def create(**kwargs):
        calls.append(kwargs)
        item = next(pending)
        if isinstance(item, Exception):
            raise item
        return item

    def factory(**kwargs):
        options.append(kwargs)
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    provider = DeepSeekTextProblemDomainProvider(
        api_key="test-secret", base_url="https://test.invalid", model="test-model",
        client_factory=factory, request_timeout=30, sleeper=lambda _: None,
    )
    return provider, calls, options


def test_supported_candidates_only_and_visible_scopes_only():
    candidate = deepcopy(CANDIDATE)
    candidate["original_text"] = "已知函数 f(x)=x²。\n（1）若 a>0，求 a 的范围。\n（2）若 b<0，求 b 的范围。"
    candidate["root"]["definitions"] = ["f(x)=x^2"]
    candidate["root"]["children"] = [
        {"label": "（1）", "facts": ["a>0"], "goals": [{"kind": "find_range", "symbol": "a"}]},
        {"label": "（2）", "facts": ["b<0"], "goals": [{"kind": "find_range", "symbol": "b"}]},
    ]
    request = build_request(candidate, "/root/children/0/goals/0", reports())
    payload = json.loads(request.prompt.user_prefix)
    assert [r["type_id"] for r in payload["supported_types"]] == ["quantified", "alternative"]
    assert [s["scope"] for s in payload["visible_scopes"]] == ["/root", "/root/children/0"]
    assert "b<0" not in request.prompt.user_prefix
    assert "求 b 的范围" not in payload["original_text"]
    assert "已知函数 f(x)=x²" in payload["original_text"]
    assert "若 a>0，求 a 的范围" in payload["original_text"]
    assert payload["visible_scopes"][0]["definitions"] == ["f(x)=x^2"]
    assert request.images == ()


def test_nested_selection_text_keeps_each_ancestor_without_siblings():
    candidate = {"original_text": "定义 f(x)=x²。甲、定义 g(x)=f(x)+1。"
                 "（1）求 a 的范围。（2）兄弟题求 b。乙、外层兄弟题求 c。",
                 "root": {"children": [
                     {"label": "甲、", "definitions": ["g(x)=f(x)+1"], "children": [
                         {"label": "（1）", "goals": [{"kind": "find_range", "symbol": "a"}]},
                         {"label": "（2）", "goals": [{"kind": "find_range", "symbol": "b"}]},
                     ]},
                     {"label": "乙、", "goals": [{"kind": "find_range", "symbol": "c"}]},
                 ]}}
    request = build_request(candidate, "/root/children/0/children/0/goals/0", reports())
    payload = json.loads(request.prompt.user_prefix)
    assert payload["original_text"] == "定义 f(x)=x²。\n定义 g(x)=f(x)+1。\n求 a 的范围。"
    assert [scope["scope"] for scope in payload["visible_scopes"]] == [
        "/root", "/root/children/0", "/root/children/0/children/0"]
    assert "兄弟题" not in request.prompt.user_prefix


@pytest.mark.parametrize("text,with_labels", [
    ("没有标签，求 a。", True), ("（1）求 a。（1）重复标签。（2）求 b。", True),
    ("（1）求 a。（2）求 b。", False),
])
def test_ambiguous_selection_text_falls_back_without_blocking_provider(tmp_path, text, with_labels):
    candidate = {"original_text": text, "root": {"children": [
        {"label": "（1）", "goals": [{"kind": "find_range", "symbol": "a"}]},
        {"label": "（2）", "goals": [{"kind": "find_range", "symbol": "b"}]},
    ]}}
    if not with_labels:
        for child in candidate["root"]["children"]:
            del child["label"]
    target = "/root/children/0/goals/0"
    provider, calls, _ = transport(response(choice(target=target)))
    result = select_primary(candidate, target, reports(), tmp_path / "call", provider)
    assert result["ok"] and result["primary"] == "quantified"
    assert not result["diagnostics"]
    assert result["llm"]["new_semantic_calls"] == result["llm"]["new_network_attempts"] == 1
    payload = json.loads(calls[0]["messages"][1]["content"])
    assert payload["original_text"] == text
    assert payload["target_ref"] == target and payload["goal"]["symbol"] == "a"
    assert [s["scope"] for s in payload["visible_scopes"]] == ["/root", "/root/children/0"]
    assert payload["original_text_fallback"]["code"] == "selection.scope_text_fallback"
    assert "未能按小问截取" in payload["original_text_fallback"]["message"]
    assert result["llm"]["input_warnings"] == [payload["original_text_fallback"]]
    recorded = RecordedSelectionProvider(tmp_path / "call")
    replay = select_primary(candidate, target, reports(), tmp_path / "replay", recorded)
    assert replay["ok"] and replay["llm"]["input_warnings"] == result["llm"]["input_warnings"]
    assert replay["llm"]["new_network_attempts"] == 0


def test_single_scope_request_preserves_original_text_and_real_recording(tmp_path):
    source = Path(__file__).parent / "fixtures/graph-guided-stage-two/recorded/q01-20261018-01"
    candidate = json.loads((source / "input.json").read_text())["candidate"]
    recorded = RecordedSelectionProvider(source / "calls/goal-001")
    payload = json.loads(recorded.request["messages"][1]["content"])
    request = recorded.prepare_request(build_request(candidate, TARGET, payload["supported_types"]))
    assert json.loads(request.prompt.user_prefix)["original_text"] == candidate["original_text"]
    assert request.redacted_payload() == recorded.request
    result = select_primary(candidate, TARGET, payload["supported_types"], tmp_path / "replay", recorded)
    assert result["ok"] and result["primary"] == "type-quantified-quadratic"
    assert result["llm"]["new_semantic_calls"] == result["llm"]["new_network_attempts"] == 0


def test_success_uses_shared_text_transport_and_records(tmp_path):
    provider, calls, options = transport()
    result = select_primary(CANDIDATE, TARGET, reports(), tmp_path / "call", provider)
    assert result["ok"] and result["primary"] == "quantified"
    assert result["llm"]["new_semantic_calls"] == result["llm"]["new_network_attempts"] == 1
    assert len(calls) == 1 and options[0]["max_retries"] == 0
    assert calls[0]["timeout"] == 30 and calls[0]["max_tokens"] == 4096
    assert all(isinstance(message["content"], str) for message in calls[0]["messages"])
    assert {p.name for p in (tmp_path / "call").iterdir()} == {
        "request.json", "response.json", "selection-result.json", "recording.json"}
    with pytest.raises(FileExistsError):
        select_primary(CANDIDATE, TARGET, reports(), tmp_path / "call", provider)
    assert len(calls) == 1


@pytest.mark.parametrize("change,code", [
    ({"target_ref": "/root/goals/1"}, "selection.target_mismatch"),
    ({"primary_type_id": "conflicting"}, "selection.unsupported_type"),
    ({"primary_type_id": "uncertain"}, "selection.unsupported_type"),
    ({"primary_type_id": "new-type"}, "selection.unsupported_type"),
    ({"branch_id": "invented"}, "selection.unsupported_branch"),
    ({"check_ids": ["alternative/main/domain"]}, "selection.invalid_check_reference"),
    ({"check_ids": ["other-goal/quantified/main/domain"]}, "selection.invalid_check_reference"),
    ({"check_ids": []}, "selection.invalid_response"),
    ({"contract": "old"}, "selection.invalid_response"),
    ({"answer": 42}, "selection.invalid_response"),
    ({"reason": "  "}, "selection.invalid_response"),
])
def test_invalid_selection_is_not_retried(tmp_path, change, code):
    value = {**choice(), **change}
    provider, calls, _ = transport(response(value))
    result = select_primary(CANDIDATE, TARGET, reports(), tmp_path / "call", provider)
    assert not result["ok"] and result["primary"] is None
    assert result["diagnostics"][0]["code"] == code
    assert len(calls) == result["llm"]["new_semantic_calls"] == result["llm"]["new_network_attempts"] == 1
    assert (tmp_path / "call/response.json").exists()


@pytest.mark.parametrize("text,finish,code", [
    ("{broken", "stop", "selection.invalid_json"),
    ('{"x":1,"x":2}', "stop", "selection.invalid_json"),
    ('{"x":NaN}', "stop", "selection.invalid_json"),
    ("[]", "stop", "selection.invalid_response"),
    (json.dumps(choice()), "length", "selection.invalid_finish_reason"),
    (json.dumps(choice()), None, "selection.invalid_finish_reason"),
])
def test_invalid_json_or_truncation_is_not_retried(tmp_path, text, finish, code):
    provider, calls, _ = transport(response(text, finish))
    result = select_primary(CANDIDATE, TARGET, reports(), tmp_path / "call", provider)
    assert result["diagnostics"][0]["code"] == code
    assert not result["ok"] and len(calls) == 1


@pytest.mark.parametrize("first", [TimeoutError("test-secret https://private.invalid"), response("")])
def test_only_transport_retries_and_both_attempts_recorded(tmp_path, first):
    provider, calls, _ = transport(first, response())
    result = select_primary(CANDIDATE, TARGET, reports(), tmp_path / "call", provider)
    assert result["ok"] and len(calls) == result["llm"]["network_attempts"] == 2
    assert result["llm"]["semantic_calls"] == 1
    recorded = (tmp_path / "call/response.json").read_text()
    assert "test-secret" not in recorded and "private.invalid" not in recorded
    assert len(json.loads(recorded)["provider_attempts"]) == 2


def test_transport_exhaustion_is_bounded_and_error_is_redacted(tmp_path):
    provider, calls, _ = transport(TimeoutError("test-secret"), TimeoutError("test-secret"))
    result = select_primary(CANDIDATE, TARGET, reports(), tmp_path / "call", provider)
    assert not result["ok"] and len(calls) == result["llm"]["network_attempts"] == 2
    assert result["llm"]["semantic_calls"] == 1
    assert all("test-secret" not in p.read_text() for p in (tmp_path / "call").glob("*.json"))


def test_provider_absence_and_factory_failure_retain_request(tmp_path, monkeypatch):
    monkeypatch.delenv("RUN_LLM_INTEGRATION", raising=False)
    factory = live_provider_factory()  # No credentials are read by construction.
    for name, provider, code in [("missing", None, "selection.provider_required"),
                                 ("optin", factory, "selection.live_opt_in_required")]:
        result = select_primary(CANDIDATE, TARGET, reports(), tmp_path / name, provider)
        assert result["diagnostics"][0]["code"] == code
        assert result["llm"]["semantic_calls"] == result["llm"]["network_attempts"] == 0
        assert (tmp_path / name / "request.json").exists()


def test_bad_inputs_do_not_construct_provider(tmp_path):
    constructed = []
    def factory():
        constructed.append(True)
        raise AssertionError("not reached")
    cases = [(reports()[:1], TARGET), (reports(), "/root/children/9/goals/0")]
    duplicate = reports()
    duplicate[1]["branches"][0]["checks"][0]["check_id"] = "quantified/main/domain"
    cases.append((duplicate, TARGET))
    wrong_target = reports()
    wrong_target[0]["branches"][0]["checks"][0]["target_ref"] = "/root/goals/1"
    cases.append((wrong_target, TARGET))
    for index, (rows, target) in enumerate(cases):
        result = select_primary(CANDIDATE, target, rows, tmp_path / str(index), factory)
        assert not result["ok"] and result["llm"]["semantic_calls"] == 0
    assert constructed == []


def test_unknown_branch_and_foreign_branch_checks_rejected(tmp_path):
    rows = reports()
    rows[0]["branches"].append({"branch_id": "other", "status": "unknown", "checks": [
        {"check_id": "quantified/other/domain", "feature_id": "domain", "status": "unknown"}]})
    for index, change in enumerate([{"branch_id": "other"}, {"check_ids": ["quantified/other/domain"]}]):
        provider, _, _ = transport(response({**choice(), **change}))
        result = select_primary(CANDIDATE, TARGET, rows, tmp_path / str(index), provider)
        assert not result["ok"]


def test_exact_request_replay_and_separate_counts(tmp_path):
    provider, _, _ = transport(TimeoutError("retry"), response())
    original = select_primary(CANDIDATE, TARGET, reports(), tmp_path / "original", provider)
    recorded = RecordedSelectionProvider(tmp_path / "original")
    replay = select_primary(CANDIDATE, TARGET, reports(), tmp_path / "replay", recorded)
    assert replay["ok"] and replay["primary"] == original["primary"]
    assert replay["llm"]["mode"] == "recorded"
    assert replay["llm"]["new_semantic_calls"] == replay["llm"]["new_network_attempts"] == 0
    assert replay["llm"]["historical_counts"] == {"semantic_calls": 1, "network_attempts": 2}
    second = select_primary(CANDIDATE, TARGET, reports(), tmp_path / "second", recorded)
    assert not second["ok"] and second["diagnostics"][0]["code"] == "selection.recording_already_used"


@pytest.mark.parametrize("change", ["candidate", "report", "prompt"])
def test_stale_recording_rejected(tmp_path, monkeypatch, change):
    provider, _, _ = transport()
    select_primary(CANDIDATE, TARGET, reports(), tmp_path / "original", provider)
    candidate, rows = deepcopy(CANDIDATE), reports()
    if change == "candidate":
        candidate["original_text"] += " changed"
    elif change == "report":
        rows[0]["branches"][0]["checks"][0]["actual"] = "positive"
    else:
        from shuxueshuo_server.graph_lesson.stage_two import selection
        prompt = tmp_path / "prompt.md"
        prompt.write_text(selection.PROMPT_PATH.read_text() + "\nchanged")
        monkeypatch.setattr(selection, "PROMPT_PATH", prompt)
    result = select_primary(candidate, TARGET, rows, tmp_path / "replay", RecordedSelectionProvider(tmp_path / "original"))
    assert result["diagnostics"][0]["code"] == "selection.recording_request_mismatch"
    assert not result["ok"] and result["llm"]["new_network_attempts"] == 0


def test_recording_tampering_rejected(tmp_path):
    provider, _, _ = transport()
    select_primary(CANDIDATE, TARGET, reports(), tmp_path / "original", provider)
    path = tmp_path / "original/response.json"
    data = json.loads(path.read_text())
    data["text"] = json.dumps(choice(primary="alternative"))
    path.write_text(json.dumps(data))
    with pytest.raises(SelectionError, match="recording_integrity"):
        RecordedSelectionProvider(tmp_path / "original")


def test_whole_run_router_uses_each_target_recording(tmp_path):
    candidate = deepcopy(CANDIDATE)
    candidate["root"]["goals"].append({"kind": "find_range", "symbol": "b"})
    for index, primary in enumerate(["quantified", "alternative"]):
        target = f"/root/goals/{index}"
        provider, _, _ = transport(response(choice(target, primary)))
        assert select_primary(candidate, target, reports(), tmp_path / "run/calls" / str(index), provider)["ok"]
    router = RecordedSelectionProvider.from_run(tmp_path / "run")
    for index, primary in enumerate(["quantified", "alternative"]):
        result = select_primary(candidate, f"/root/goals/{index}", reports(), tmp_path / f"replay-{index}", router)
        assert result["ok"] and result["primary"] == primary
        assert result["llm"]["historical_counts"]["semantic_calls"] == 1
        assert result["llm"]["new_network_attempts"] == 0


@pytest.mark.parametrize("failure", ["timeout", "missing_provider", "invalid_json"])
def test_failed_attempt_is_replayed_without_network(tmp_path, failure):
    provider = None
    if failure == "timeout":
        provider, _, _ = transport(TimeoutError("private"), TimeoutError("private"))
    elif failure == "invalid_json":
        provider, _, _ = transport(response("bad JSON"))
    original = select_primary(CANDIDATE, TARGET, reports(), tmp_path / "original", provider)
    replay = select_primary(CANDIDATE, TARGET, reports(), tmp_path / "replay", RecordedSelectionProvider(tmp_path / "original"))
    assert not original["ok"] and not replay["ok"]
    assert replay["diagnostics"] == original["diagnostics"]
    assert replay["llm"]["new_network_attempts"] == replay["llm"]["new_semantic_calls"] == 0
    assert replay["llm"]["historical_counts"] == {
        k: original["llm"][k] for k in ("semantic_calls", "network_attempts")}


def test_failed_run_rerecord_and_replay_keep_original_attempt_evidence(tmp_path):
    from shuxueshuo_server.graph_lesson.stage_two.runner import (
        record_run,
        replay_run,
        run_result,
    )

    fixture = Path(__file__).parent / "fixtures/graph-guided-stage-one/recorded/live-v2-20261017-02/q01/sample-01/stage-one-result.json"
    provider, calls, _ = transport(TimeoutError("private"), TimeoutError("private"))
    previous = tmp_path / "original"
    original = run_result(json.loads(fixture.read_text()), previous, provider=provider, verify=True)
    assert original["status"] == "failed" and len(calls) == 2
    evidence = json.loads((previous / "calls/goal-001/provider-attempts.json").read_text())
    assert len(evidence["attempts"]) == 2
    for index in range(2):
        recording, output = tmp_path / f"recording-{index}", tmp_path / f"replay-{index}"
        record_run(previous, recording)
        replay = replay_run(recording, output)
        assert replay["status"] == "failed"
        llm = replay["goals"][0]["llm"]
        assert llm["new_semantic_calls"] == llm["new_network_attempts"] == 0
        assert llm["historical_counts"] == {"semantic_calls": 1, "network_attempts": 2}
        call = output / "calls/goal-001"
        assert json.loads((call / llm["historical_attempts_ref"]).read_text()) == evidence
        assert json.loads((call / "recording.json").read_text())["attempts_hash"]
        previous = output
    assert len(calls) == 2


@pytest.mark.parametrize("change", ["tamper", "delete", "remove_hash"])
def test_recorded_attempt_evidence_cannot_be_changed_or_omitted(tmp_path, change):
    provider, _, _ = transport(TimeoutError("private"), TimeoutError("private"))
    output = tmp_path / "original"
    select_primary(CANDIDATE, TARGET, reports(), output, provider)
    if change == "tamper":
        path = output / "provider-attempts.json"
        evidence = json.loads(path.read_text())
        evidence["attempts"].pop()
        path.write_text(json.dumps(evidence))
    elif change == "delete":
        (output / "provider-attempts.json").unlink()
    else:
        path = output / "recording.json"
        manifest = json.loads(path.read_text())
        del manifest["attempts_hash"]
        path.write_text(json.dumps(manifest))
    with pytest.raises(SelectionError, match="recording_integrity"):
        RecordedSelectionProvider(output)
