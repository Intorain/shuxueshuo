"""Admission, scoped failures and durable stage-two results over real stage-one output."""

import json
import socket
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from shuxueshuo_server.graph_lesson.stage_two.contracts import (
    validate_input,
    validate_result,
)
from shuxueshuo_server.graph_lesson.stage_two.runner import (
    record_run,
    replay_run,
    run_result,
    run_sample,
)

RECORDED = Path(__file__).parent / "fixtures/graph-guided-stage-one/recorded/live-v2-20261017-02"


def accepted(case="q01"):
    return json.loads((RECORDED / case / "sample-01/stage-one-result.json").read_text())


def forbidden():
    raise AssertionError("must not construct a provider")


@pytest.mark.parametrize("field", ["source_reviewed", "features", "evaluation", "passed"])
@pytest.mark.parametrize("mode", ["missing", "false", "truthy"])
def test_incomplete_acceptance_flags_are_rejected(field, mode):
    value = accepted()
    if mode == "missing":
        del value["statuses"][field]
    else:
        value["statuses"][field] = False if mode == "false" else 1
    checked = validate_input(value)
    assert not checked["ok"]
    assert any(issue["path"] == f"/statuses/{field}" for issue in checked["diagnostics"])


@pytest.mark.parametrize("corruption", ["contract", "candidate", "extraction", "target", "scope", "duplicate", "missing", "no_targets"])
def test_invalid_input_never_runs_recognition_or_provider(tmp_path, monkeypatch, corruption):
    from shuxueshuo_server.graph_lesson.stage_two import recognition

    value = accepted()
    if corruption == "contract":
        value["contract"] = "graph-stage-one-result/v1"
    elif corruption == "candidate":
        value["candidate"] = None
    elif corruption == "extraction":
        value["statuses"]["extraction"] = "workflow.budget_exhausted"
    elif corruption == "target":
        value["features"][0]["target_ref"] = "/root/goals/9"
    elif corruption == "scope":
        value["features"][0]["scope"] = "/root/children/0"
    elif corruption == "duplicate":
        value["features"].append(deepcopy(value["features"][0]))
    elif corruption == "missing":
        value["features"].pop()
    else:
        value["candidate"]["root"]["goals"] = []
        value["features"] = []
    monkeypatch.setattr(recognition, "evaluate_types", lambda *a, **k: forbidden())
    output = tmp_path / "run"
    result = run_result(value, output, provider=forbidden, unsupported_root=tmp_path / "pending")
    assert result["status"] == "input_error"
    assert not result["goals"] and not (tmp_path / "pending").exists()
    assert result["llm"]["new_network_attempts"] == 0
    assert (output / "index.html").is_file()
    validate_result(result)


def test_unknown_features_and_pending_human_review_do_not_reject_input():
    value = accepted("q11")
    assert any(row["status"] == "unknown" for row in value["features"])
    assert value["statuses"]["human_review"] == "pending"
    assert validate_input(value)["ok"]


def test_unsupported_question_does_not_block_its_supported_sibling(tmp_path):
    output = tmp_path / "q11"
    result = run_result(accepted("q11"), output, provider=forbidden, unsupported_root=tmp_path / "pending")
    first, second = result["goals"]
    assert result["status"] == "completed"
    assert first["status"] == "unsupported" and first["knowledge"]["items"] == []
    assert first["d1"] is first["d2"] is first["primary"] is None
    assert (output / first["unsupported_record"]).is_file()
    saved = json.loads((output / first["unsupported_record"]).read_text())
    assert saved["target_ref"] == first["target_ref"]
    assert saved["features"] and saved["types"] and saved["created_at"]
    assert second["status"] == "resolved" and second["primary_source"] == "program"
    assert second["d1"] and second["d2"]
    assert result["llm"]["new_network_attempts"] == 0
    validate_result(result)


def test_multiple_matches_without_provider_are_selection_failure(tmp_path):
    result = run_result(accepted(), tmp_path / "q01", verify=True)
    goal, = result["goals"]
    assert len(goal["supported"]) == 2
    assert result["status"] == "failed" and goal["status"] == "selection_failed"
    assert goal["primary"] is goal["primary_source"] is goal["d1"] is goal["d2"] is None
    assert goal["llm"] is not None and goal["diagnostics"]
    assert "unsupported_record" not in goal
    validate_result(result)


def test_existing_run_cannot_be_overwritten(tmp_path):
    output = tmp_path / "existing"
    output.mkdir()
    with pytest.raises(FileExistsError):
        run_result(accepted(), output)


def test_unparseable_input_generates_a_debuggable_input_error(tmp_path):
    source = tmp_path / "broken.json"
    source.write_text('{"candidate":')
    result = run_sample(source, tmp_path / "output", provider=forbidden)
    assert result["status"] == "input_error"
    assert any(issue["code"] == "input.read" for issue in result["input_diagnostics"])
    assert (tmp_path / "output/index.html").is_file()


def test_result_schema_rejects_success_disguising_failed_selection(tmp_path):
    result = run_result(accepted(), tmp_path / "q01", verify=True)
    result["status"] = "completed"
    with pytest.raises(ValueError, match="aggregate_status"):
        validate_result(result)


def universal_alternative():
    """A catalog fixture deliberately independent of AMGM and Q01 verification."""
    from shuxueshuo_server.graph_lesson.stage_two.recognition import load_contracts

    catalog = load_contracts()
    extra = deepcopy(next(row for row in catalog if row["type_id"] == "type-quantified-quadratic"))
    extra["type_id"] = "test-universal-alternative"
    for branch in extra["branches"]:
        branch["checks"].append({"id": "only-universal", "feature_id": "quantifier", "op": "eq", "expected": "∀"})
    return [*catalog, extra]


def test_selection_failure_does_not_block_another_goal(tmp_path):
    result = run_result(accepted("q10"), tmp_path / "partial", contracts=universal_alternative())
    first, second = result["goals"]
    assert result["status"] == "partial"
    assert first["status"] == "selection_failed" and len(first["supported"]) == 2
    assert first["d1"] is first["d2"] is None
    assert "unsupported_record" not in first
    assert second["status"] == "resolved" and second["primary_source"] == "program"
    assert second["d1"] and second["d2"]


@pytest.mark.parametrize("layout", ["original", "missing_labels", "inline_fullwidth"])
def test_non_q01_multimatch_uses_llm_and_full_run_replays_offline(tmp_path, monkeypatch, layout):
    from shuxueshuo_server.solver.extraction.multimodal_provider import (
        DeepSeekTextProblemDomainProvider,
    )

    calls = []

    def complete(**kwargs):
        payload = json.loads(kwargs["messages"][1]["content"])
        calls.append(payload)
        selected = next(row for row in payload["supported_types"] if row["type_id"] == "type-quantified-quadratic")
        branch = next(row for row in selected["branches"] if row["status"] == "supported")
        choice = {"contract": "graph-stage-two-selection/v1", "target_ref": payload["target_ref"],
                  "primary_type_id": selected["type_id"], "branch_id": branch["branch_id"],
                  "check_ids": [check["check_id"] for check in branch["checks"]], "reason": "量词与二次结构支持该题型。"}
        return SimpleNamespace(model="test", usage=None, choices=[SimpleNamespace(
            finish_reason="stop", message=SimpleNamespace(content=json.dumps(choice)))])

    provider = DeepSeekTextProblemDomainProvider(
        api_key="test", base_url="https://test.invalid", model="test", request_timeout=30,
        client_factory=lambda **_: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=complete))),
    )
    value = accepted("q10")
    if layout == "missing_labels":
        for child in value["candidate"]["root"]["children"]:
            del child["label"]
    elif layout == "inline_fullwidth":
        value["candidate"]["original_text"] = value["candidate"]["original_text"].replace(
            "已知函数 $f(x)=x^2-2ax+3$。", "已知函数 f(x)=x^2-2ax+3 ").replace("\n", "")
        assert "f(x)=x^2-2ax+3 （1）" in value["candidate"]["original_text"]
    original = run_result(value, tmp_path / "original", contracts=universal_alternative(), provider=provider)
    assert original["status"] == "completed" and len(calls) == 1
    assert original["goals"][0]["primary_source"] == "llm"
    assert original["goals"][1]["primary_source"] == "program"
    assert all(g["d1"] is not None and g["d2"]["options"] for g in original["goals"])
    if layout == "missing_labels":
        assert calls[0]["original_text"] == value["candidate"]["original_text"]
        assert calls[0]["original_text_fallback"]["code"] == "selection.scope_text_fallback"
        assert original["goals"][0]["llm"]["input_warnings"]
        assert not original["goals"][0]["d1"]["fragments"]
        assert "未能按小问截取" in (tmp_path / "original/index.html").read_text()
    else:
        assert "original_text_fallback" not in calls[0]
        assert all(any(f["fragment_kind"] == "relation" for f in g["d1"]["fragments"])
                   for g in original["goals"])
    assert original["llm"]["new_semantic_calls"] == original["llm"]["new_network_attempts"] == 1
    record_run(tmp_path / "original", tmp_path / "recording")
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: forbidden())
    replay = replay_run(tmp_path / "recording", tmp_path / "replay")
    assert replay["status"] == "completed"
    assert replay["historical"]["llm"]["new_network_attempts"] == 1
    assert replay["llm"]["new_semantic_calls"] == replay["llm"]["new_network_attempts"] == 0
    assert [g["primary"] for g in original["goals"]] == [g["primary"] for g in replay["goals"]]
    record_run(tmp_path / "replay", tmp_path / "second-recording")
    again = replay_run(tmp_path / "second-recording", tmp_path / "second-replay")
    assert again["historical"] == replay["historical"]
    assert again["historical"]["llm"]["new_network_attempts"] == 1
    assert again["previous_run"]["llm"]["new_network_attempts"] == 0
    assert again["llm"]["new_network_attempts"] == 0


def test_program_only_recording_and_tamper_detection(tmp_path):
    run_result(accepted("q02"), tmp_path / "original", provider=forbidden)
    record_run(tmp_path / "original", tmp_path / "recording")
    replay = replay_run(tmp_path / "recording", tmp_path / "replay")
    assert replay["status"] == "completed" and replay["llm"]["new_semantic_calls"] == 0
    path = tmp_path / "recording/input.json"
    path.write_text(path.read_text() + " ")
    with pytest.raises(ValueError, match="hash_mismatch"):
        replay_run(tmp_path / "recording", tmp_path / "tampered")


def test_invalid_raw_input_is_visible_and_retained_in_recording(tmp_path):
    source = tmp_path / "broken.json"
    source.write_text('{"candidate":<script>alert(1)</script>')
    run_sample(source, tmp_path / "original")
    html = (tmp_path / "original/index.html").read_text()
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    record_run(tmp_path / "original", tmp_path / "recording")
    replay = replay_run(tmp_path / "recording", tmp_path / "replay")
    assert replay["status"] == "input_error"
    assert (tmp_path / "replay/input-raw.txt").read_text() == source.read_text()
    assert any(issue["code"] == "input.read" for issue in replay["historical"]["input_diagnostics"])
