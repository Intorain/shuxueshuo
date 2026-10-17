"""Stage-one orchestration with real contracts/ledger and no network traffic."""

import json
from copy import deepcopy
from pathlib import Path
from shutil import copytree

import pytest
from _math_notation_test_support import Recorded

from shuxueshuo_server.graph_lesson.stage_one import runner
from shuxueshuo_server.graph_lesson.stage_one.contracts import CONTRACT
from shuxueshuo_server.graph_lesson.stage_one.extraction import (
    REPAIR_SCOPE,
    GraphStageOneContract,
    changed_paths,
    scope_policy,
    validate_candidate,
)
from shuxueshuo_server.problem_understanding.identity import revision
from shuxueshuo_server.problem_understanding.notation_compile import NotationValidator
from shuxueshuo_server.problem_understanding.workflow_ledger import save
from shuxueshuo_server.solver.extraction.artifacts import ExtractionArtifactStore

CONFIRMED = {"status": "confirmed", "findings": []}


class Sequence(Recorded):
    """Prepare actual provider requests; supply deterministic transport responses."""

    def __init__(self, *responses):
        super().__init__("")
        self.responses = list(responses)
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        if not self.responses:
            raise AssertionError("unexpected additional provider call")
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            self.calls += 1
            raise response
        self.text = (
            response
            if isinstance(response, str)
            else json.dumps(response, ensure_ascii=False)
        )
        return super().complete(request)


def read(path):
    return json.loads(Path(path).read_text())


def candidate(case="q01"):
    return read(runner.CORPUS / case / "notation.gold.json")


def correction(path="/root/facts/1"):
    return {
        "status": "correction_required",
        "findings": [
            {
                "path": path,
                "kind": "wrong_expression",
                "source_excerpt": "小于或等于",
                "message": "原图关系带等号，恢复为非严格不等式。",
            }
        ],
    }


def run(tmp_path, provider, name="sample"):
    output = tmp_path / name
    summary = runner.run_sample(
        "q01", output, provider, run_id="offline-mechanism-test"
    )
    return output, summary, read(output / "workflow/workflow-result.json")


def test_family_free_extraction_and_image_review_take_two_calls(tmp_path):
    value = candidate()
    provider = Sequence(value, CONFIRMED)
    output, summary, workflow = run(tmp_path, provider)
    assert summary["passed"], read(output / "evaluation.json")
    assert workflow["status"] == "reviewed_candidate"
    assert workflow["output_contract"] == CONTRACT
    assert workflow["source_reviewed"]
    assert workflow["candidate"] == value
    assert provider.calls == summary["semantic_calls"] == 2
    assert summary["content_calls"] == summary["review_calls"] == 1
    assert len(read(output / "workflow/ledger.json")["calls"]) == 2
    assert (
        read(output / "stage-one-result.json")["statuses"]["human_review"] == "pending"
    )
    assert not (output / "source-map.json").exists()
    assert len(list((output / "candidates").glob("*-adopted.json"))) == 1


def test_missing_words_review_repairs_only_transcription_and_is_rechecked(
    tmp_path,
):
    corrected = candidate()
    original = deepcopy(corrected)
    original["original_text"] = original["original_text"].replace("恒成立", "成立")
    assert original["original_text"] != corrected["original_text"]
    finding = {
        "status": "correction_required",
        "findings": [
            {
                "path": "/original_text",
                "kind": "wrong_transcription",
                "source_excerpt": "恒成立",
                "message": "原图为“恒成立”，转录漏了“恒”字；只恢复题文，保留正确的数学题意。",
            }
        ],
    }
    provider = Sequence(original, finding, corrected, CONFIRMED)
    output, summary, workflow = run(tmp_path, provider)
    assert not summary["first_passed"]
    assert summary["passed"], read(output / "evaluation.json")
    assert summary["semantic_calls"] == 4
    assert summary["repair_calls"] == 1 and summary["review_calls"] == 2
    assert workflow["first_candidate"] == original
    assert workflow["candidate"] == corrected
    assert changed_paths(original, corrected) == ["/original_text"]
    repair_payload = json.loads(provider.requests[2].prompt.user_prefix)
    assert repair_payload["diagnostics"][0]["path"] == "/original_text"
    assert json.loads(provider.requests[3].prompt.user_prefix)["candidate"] == corrected
    assert workflow["review"]["revision"] == revision(corrected)


def test_request_contains_only_image_and_common_contracts_before_review(tmp_path):
    request = runner.build_request(
        runner.CORPUS / "q01", ExtractionArtifactStore(tmp_path / "inputs")
    )
    payload = json.loads(request.prompt.user_prefix)
    assert set(payload) == {"response_schema", "math_expression_catalog"}
    assert not any(
        name in payload["response_schema"]["properties"]
        for name in ("family_id", "match_status", "match_reason")
    )
    assert request.evidence_pack.printed_text == ()
    assert request.evidence_pack.recognized_formulas == ()
    assert request.evidence_pack.region_index == ()
    assert len(request.images) == 1
    assert request.images[0].content == (runner.CORPUS / "q01/source.png").read_bytes()
    prompt = (
        request.prompt.system + request.prompt.user_prefix + request.prompt.user_suffix
    )
    assert candidate()["original_text"] not in prompt
    assert "features.gold.json" not in prompt and "registered_families" not in prompt

    provider = Sequence(candidate(), CONFIRMED)
    output, _, _ = run(tmp_path, provider)
    review = provider.requests[1]
    assert review.images[0].content == request.images[0].content
    review_payload = json.loads(review.prompt.user_prefix)
    assert review_payload["candidate"] == candidate()
    assert review_payload["code_validation"]["candidate_revision"] == revision(
        candidate()
    )
    assert review_payload["code_validation"]["image_alignment_verified"] is False
    assert "features" not in review_payload and "gold" not in review_payload
    assert read(output / "frozen.json")["source_kind"] == "synthetic-rendered"


def test_rejected_repair_does_not_expand_authority_or_replace_base(tmp_path):
    corrected = candidate()
    original = deepcopy(corrected)
    original["root"]["facts"][1] = (
        original["root"]["facts"][1].replace("≤", "<").replace("<=", "<")
    )
    assert original != corrected
    unauthorized = deepcopy(corrected)
    unauthorized["root"]["goals"][0]["symbol"] = "b"
    provider = Sequence(original, correction(), unauthorized, corrected, CONFIRMED)
    output, summary, workflow = run(tmp_path, provider)
    assert summary["passed"], workflow
    assert provider.calls == 5
    assert workflow["candidate"] == corrected
    assert workflow["first_candidate"] == original
    rejected = workflow["events"][2]
    assert not rejected["adopted"]
    assert rejected["repair_rejected"] == [
        {
            "code": "repair.outside_authorized_path",
            "path": "/root/goals/0/symbol",
            "message": REPAIR_SCOPE,
        }
    ]
    for request in provider.requests[2:4]:
        payload = json.loads(request.prompt.user_prefix)
        assert payload["base_candidate"] == original
        assert payload["diagnostics"][0]["path"] == "/root/facts/1"
    last_repair = json.loads(provider.requests[3].prompt.user_prefix)
    assert last_repair["repair_feedback"][0]["code"] == "repair.outside_authorized_path"
    assert read(output / "candidates/03-proposed.json") == unauthorized
    assert not (output / "candidates/03-adopted.json").exists()
    assert read(output / "candidates/04-adopted.json") == corrected
    assert json.loads(provider.requests[4].prompt.user_prefix)["candidate"] == corrected


def test_invalid_json_is_repaired_with_no_invented_base(tmp_path):
    provider = Sequence("{", candidate(), CONFIRMED)
    output, summary, workflow = run(tmp_path, provider)
    assert summary["passed"], workflow
    assert provider.calls == 3
    assert workflow["first_candidate"] is None
    assert json.loads(provider.requests[1].prompt.user_prefix)["base_candidate"] is None
    ledger = read(output / "workflow/ledger.json")
    first_response = read(output / "workflow" / ledger["calls"][0]["response_file"])
    assert first_response["text"] == "{"


def test_invalid_json_budget_is_finite_and_failed_result_is_saved(tmp_path):
    provider = Sequence("{", "{", "{")
    output, summary, workflow = run(tmp_path, provider)
    assert not summary["passed"]
    assert summary["status"] == "workflow.budget_exhausted"
    assert provider.calls == summary["content_calls"] == 3
    assert summary["review_calls"] == 0
    assert workflow["candidate"] is None
    assert read(output / "stage-one-result.json")["candidate"] is None
    assert not read(output / "features.json")["ok"]
    assert len(read(output / "workflow/ledger.json")["calls"]) == 3


def test_timeout_retains_failed_reservation_and_never_invites_semantic_repair(tmp_path):
    provider = Sequence(TimeoutError("sensitive transport details"))
    output, summary, workflow = run(tmp_path, provider)
    assert not summary["passed"] and not workflow["source_reviewed"]
    assert summary["status"] == "workflow.provider_failed"
    assert provider.calls == 1
    ledger = read(output / "workflow/ledger.json")
    assert len(ledger["calls"]) == 1
    entry = ledger["calls"][0]
    assert entry["status"] == "failed" and entry["error_type"] == "TimeoutError"
    assert (output / "workflow" / entry["directory"] / "request.json").is_file()
    assert "response_file" not in entry
    assert (
        "sensitive transport details"
        not in (output / "workflow/ledger.json").read_text()
    )


def test_fresh_sample_refuses_existing_directory_before_provider_call(tmp_path):
    output, _, _ = run(tmp_path, Sequence(candidate(), CONFIRMED))
    frozen = (output / "frozen.json").read_bytes()
    provider = Sequence()
    with pytest.raises(FileExistsError):
        runner.run_sample("q01", output, provider)
    assert not provider.requests
    assert (output / "frozen.json").read_bytes() == frozen


def make_recording(tmp_path):
    live = tmp_path / "record-source"
    provider = Sequence(candidate(), CONFIRMED)
    runner.run_batch(live, lambda: provider, cases=("q01",), samples=1, workers=1)
    recorded = runner.record_batch(live, tmp_path / "recorded")
    return recorded, provider


def test_recording_replays_offline_and_retains_historical_call_counts(
    tmp_path, monkeypatch
):
    recorded, provider = make_recording(tmp_path)
    historical_calls = provider.calls

    def no_provider(*args, **kwargs):
        raise AssertionError("offline replay attempted a model/provider call")

    monkeypatch.setattr(Sequence, "prepare_request", no_provider)
    monkeypatch.setattr(Sequence, "complete", no_provider)
    monkeypatch.setattr(runner, "run_workflow", no_provider)
    sample = recorded / "q01/sample-01"
    assert not (sample / "fixture/source.png").exists()
    summary = runner.replay_sample(sample, tmp_path / "replay")
    assert summary["passed"], read(tmp_path / "replay/evaluation.json")
    assert summary["mode"] == "offline_replay"
    assert summary["new_semantic_calls"] == summary["new_network_attempts"] == 0
    assert summary["historical_live"]["semantic_calls"] == historical_calls == 2
    assert read(tmp_path / "replay/stage-one-result.json")["statuses"][
        "source_reviewed"
    ]


@pytest.mark.parametrize(
    "part", ["response", "request", "fixture", "adopted_candidate"]
)
def test_replay_refuses_tampered_evidence_before_acceptance(tmp_path, part):
    recorded, _ = make_recording(tmp_path)
    sample = recorded / "q01/sample-01"
    ledger = read(sample / "workflow/ledger.json")
    if part == "response":
        path = sample / "workflow" / ledger["calls"][0]["response_file"]
        value = read(path)
        value["text"] = "{}"
        save(path, value)
        reason = "response_hash_mismatch"
    elif part == "request":
        path = sample / "workflow" / ledger["calls"][0]["directory"] / "request.json"
        value = read(path)
        value["tampered"] = True
        save(path, value)
        reason = "request_hash_mismatch"
    elif part == "fixture":
        path = sample / "fixture/notation.gold.json"
        path.write_text(path.read_text() + "\n")
        reason = "fixture_hash_mismatch"
    else:
        path = sample / "workflow/workflow-result.json"
        value = read(path)
        value["candidate"]["root"]["goals"][0]["symbol"] = "b"
        save(path, value)
        reason = "candidate_not_backed_by_response"
    with pytest.raises(ValueError, match=reason):
        runner.replay_sample(sample, tmp_path / "replay")


def test_source_review_does_not_accept_a_nonexistent_pointer():
    review = correction("/root/facts/99")
    with pytest.raises((ValueError, IndexError)):
        GraphStageOneContract().validate_review(json.dumps(review), candidate())


def test_replay_cannot_reuse_final_review_for_an_earlier_candidate(tmp_path):
    original = candidate()
    repaired = deepcopy(original)
    repaired["original_text"] += "\n"
    review = {
        "status": "correction_required",
        "findings": [
            {
                "path": "/original_text",
                "kind": "wrong_transcription",
                "source_excerpt": "取值范围。",
                "message": "恢复末尾排版换行。",
            }
        ],
    }
    output, summary, workflow = run(
        tmp_path, Sequence(original, review, repaired, CONFIRMED)
    )
    assert summary["passed"]
    assert workflow["candidate"] == repaired
    workflow["candidate"] = original
    save(output / "workflow/workflow-result.json", workflow)
    replayed = runner.replay_sample(output, tmp_path / "replay")
    assert not replayed["passed"]
    assert not replayed["source_reviewed"]


def test_provider_initialization_failure_is_saved_for_every_batch_sample(tmp_path):
    factory_calls = []

    def unavailable_provider():
        factory_calls.append(True)
        raise RuntimeError("private configuration detail")

    output = tmp_path / "failed-batch"
    result = runner.run_batch(
        output, unavailable_provider, cases=("q01", "q02"), samples=2, workers=2
    )
    assert not result["passed"]
    assert len(factory_calls) == len(result["results"]) == 4
    persisted = read(output / "batch-summary.json")
    assert persisted["results"] == result["results"]
    assert {(row["case_id"], row["sample_id"]) for row in result["results"]} == {
        ("q01", 1),
        ("q01", 2),
        ("q02", 1),
        ("q02", 2),
    }
    for row in result["results"]:
        sample = output / row["sample_dir"]
        assert row["status"] == "runner.failed" and not row["passed"]
        failure = read(sample / "failure.json")
        assert failure["error_type"] == "RuntimeError"
        assert failure["frames"]
        assert not (sample / "workflow/ledger.json").exists()
        assert (
            "private configuration detail" not in (sample / "failure.json").read_text()
        )


def test_preflight_failure_is_recordable_and_stays_failed_on_replay(
    tmp_path, monkeypatch
):
    corpus = tmp_path / "bad-corpus"
    copytree(runner.CORPUS / "q01", corpus / "q01")
    (corpus / "q01/source.png").write_bytes(b"not the frozen image")
    original_run_sample = runner.run_sample
    provider = Sequence()

    def run_bad_fixture(*args, **kwargs):
        return original_run_sample(*args, **kwargs, corpus=corpus)

    monkeypatch.setattr(runner, "run_sample", run_bad_fixture)
    output = tmp_path / "failed-preflight"
    result = runner.run_batch(
        output, lambda: provider, cases=("q01",), samples=1, workers=1
    )
    assert not result["passed"]
    sample = output / "q01/sample-01"
    preflight = read(sample / "preflight.json")
    assert not preflight["ok"] and preflight["diagnostics"]
    assert read(sample / "failure.json")["error_type"] == "ValueError"
    assert not provider.requests
    assert not (sample / "workflow/ledger.json").exists()

    recorded = runner.record_batch(output, tmp_path / "recorded-failure")
    assert read(recorded / "q01/sample-01/preflight.json") == preflight
    replayed = runner.replay_batch(
        recorded, tmp_path / "replayed-failure", cases=("q01",)
    )
    assert not replayed["passed"]
    assert replayed["new_semantic_calls"] == replayed["new_network_attempts"] == 0
    row = replayed["results"][0]
    assert row["status"] == "runner.failed" and not row["passed"]
    assert row["historical_live"]["status"] == "runner.failed"
    assert read(tmp_path / "replayed-failure/q01/sample-01/preflight.json") == preflight


def test_review_request_binds_the_ledger_candidate_revision(tmp_path):
    recorded, _ = make_recording(tmp_path)
    sample = recorded / "q01/sample-01"
    ledger = read(sample / "workflow/ledger.json")
    ledger["calls"][1]["base_revision"] = "0" * 64
    save(sample / "workflow/ledger.json", ledger)
    with pytest.raises(
        ValueError, match="recording.request_candidate_revision_mismatch"
    ):
        runner.replay_sample(sample, tmp_path / "replay")


class Killed(BaseException):
    """A hard stop that the batch's per-sample error handling cannot catch."""


@pytest.mark.parametrize(
    "target,phase",
    [
        ("validate_fixture", "reserved"),
        ("build_request", "frozen"),
        ("finish_sample", "workflow_finished"),
    ],
)
def test_interrupted_sample_survives_record_replay_and_rerecord(
    tmp_path, monkeypatch, target, phase
):
    def kill(*args, **kwargs):
        raise Killed

    monkeypatch.setattr(runner, target, kill)
    live = tmp_path / "live"
    with pytest.raises(Killed):
        runner.run_batch(live, lambda: Sequence(candidate(), CONFIRMED), cases=("q01",), samples=1, workers=1)
    monkeypatch.undo()
    assert read(live / "q01/sample-01/sample-state.json")["phase"] == phase

    recorded = runner.record_batch(live, tmp_path / "recorded")
    assert read(recorded / "batch-summary.json")["unrecorded_samples"] == ["q01/sample-01"]
    first = runner.replay_batch(recorded, tmp_path / "replay-1", cases=("q01",))
    assert [(row["incomplete"], row["passed"]) for row in first["results"]] == [(True, False)]
    assert first["results"][0]["status"] == f"incomplete:{phase}"
    again = runner.record_batch(tmp_path / "replay-1", tmp_path / "rerecorded")
    second = runner.replay_batch(again, tmp_path / "replay-2", cases=("q01",))
    assert second["results"][0]["status"] == f"incomplete:{phase}"
    assert read(again / "q01/sample-01/sample-state.json")["phase"] == phase


def test_pytest_session_stopped_before_teardown_can_be_recorded_and_replayed(tmp_path):
    session = tmp_path / "session"
    cases = ("q01", "q02")
    runner.reserve_live_session(session, "uid", cases=cases, samples=1)
    for case in cases:
        runner.run_batch(session / case, lambda c=case: Sequence(candidate(c), CONFIRMED),
                         cases=(case,), samples=1, workers=1)
        runner.collect_case_batches(session)
    incremental = read(session / "batch-summary.json")
    assert incremental["complete"] and incremental["passed"]
    assert incremental["requested_cases"] == list(cases)
    # A crash can still leave no session summary; per-case summaries rebuild it.
    (session / "batch-summary.json").unlink()
    recorded = runner.record_batch(session, tmp_path / "recorded")
    summary = read(recorded / "batch-summary.json")
    assert summary["rebuilt_after_interruption"] and summary["complete"]
    assert [row["sample_dir"] for row in summary["results"]] == ["q01/q01/sample-01", "q02/q02/sample-01"]
    replayed = runner.replay_batch(session, tmp_path / "replay", cases=cases)
    assert replayed["complete"] and replayed["passed"] and not replayed["formal_passed"]
    assert runner.replay_batch(recorded, tmp_path / "replay-recorded", cases=cases)["passed"]


def test_invalid_initial_json_repair_recording_keeps_a_null_base(tmp_path):
    provider = Sequence("{", candidate(), CONFIRMED)
    output = tmp_path / "repaired-record-source"
    result = runner.run_batch(
        output, lambda: provider, cases=("q01",), samples=1, workers=1
    )
    assert result["passed"]
    recorded = runner.record_batch(output, tmp_path / "repaired-recording")
    summary = runner.replay_sample(recorded / "q01/sample-01", tmp_path / "replay")
    assert summary["passed"]
    assert summary["historical_live"]["semantic_calls"] == 3
    assert summary["new_semantic_calls"] == 0


@pytest.mark.parametrize(
    "before,after",
    [
        (["a>0", "b>0", "c>0"], ["a>0", "c>0"]),
        (["a>0", "c>0"], ["a>0", "b>0", "c>0"]),
    ],
    ids=["delete-one-item", "insert-one-item"],
)
def test_single_item_repair_keeps_unchanged_neighbor_authority(before, after):
    original = {"root": {"facts": before}}
    repaired = {"root": {"facts": after}}
    diagnostics = [{"path": "/root/facts/1", "action": "repair"}]
    assert changed_paths(original, repaired) == ["/root/facts/1"]
    assert not GraphStageOneContract().repair_diagnostics(
        original, repaired, diagnostics
    )


@pytest.mark.parametrize(
    "before,after",
    [
        (["a>0", "b>0", "c>0"], ["a>1", "c>0"]),
        (["a>0", "b>0", "c>0"], ["a>0", "c>1"]),
        (["a>0", "c>0"], ["a>1", "b>0", "c>0"]),
        (["a>0", "c>0"], ["a>0", "b>0", "c>1"]),
    ],
    ids=[
        "delete-and-change-prefix",
        "delete-and-change-suffix",
        "insert-and-change-prefix",
        "insert-and-change-suffix",
    ],
)
def test_item_insert_or_delete_does_not_grant_neighbor_rewrite(before, after):
    original = {"root": {"facts": before}}
    proposed = {"root": {"facts": after}}
    diagnostics = [{"path": "/root/facts/1", "action": "repair"}]
    issues = GraphStageOneContract().repair_diagnostics(original, proposed, diagnostics)
    assert issues
    assert all(issue["code"] == "repair.outside_authorized_path" for issue in issues)


def test_non_adjacent_deletions_keep_surviving_items_unchanged():
    original = {"root": {"facts": ["a=1", "a∈ℝ", "b=2", "∀x∈ℝ:x^2+a>0"]}}
    diagnostics = [
        {"path": f"/root/facts/{i}", "code": "unsupported_addition", "action": "repair"}
        for i in (0, 2)
    ]
    contract = GraphStageOneContract()
    repaired = {"root": {"facts": ["a∈ℝ", "∀x∈ℝ:x^2+a>0"]}}
    assert changed_paths(original, repaired) == ["/root/facts/0", "/root/facts/2"]
    assert contract.repair_diagnostics(original, repaired, diagnostics) == []
    rewritten = {"root": {"facts": ["a>0", "∀x∈ℝ:x^2+a>0"]}}
    assert {i["path"] for i in contract.repair_diagnostics(original, rewritten, diagnostics)} == {
        "/root/facts/1"
    }


def test_missing_condition_only_appends_at_its_scope():
    current = _parts(
        {"facts": ["a>0"], "goals": [{"kind": "find_range", "symbol": "x"}]},
        {"facts": ["b>0"], "goals": [{"kind": "find_range", "symbol": "y"}]},
    )
    diagnostics = [{"path": "/root", "code": "missing_condition", "action": "repair"}]
    contract = GraphStageOneContract()
    appended = deepcopy(current)
    appended["root"]["facts"] = ["c>0"]
    assert contract.repair_diagnostics(current, appended, diagnostics) == []
    rewritten = deepcopy(appended)
    rewritten["root"]["children"][1]["facts"] = ["b<0"]
    assert {i["path"] for i in contract.repair_diagnostics(current, rewritten, diagnostics)} == {
        "/root/children/1/facts/0"
    }
    child_append = deepcopy(current)
    child_append["root"]["children"][0]["facts"].append("c>0")
    assert contract.repair_diagnostics(current, child_append, diagnostics)


def test_wrong_scope_may_move_but_not_rewrite_conditions():
    current = _parts(
        {"facts": ["c>0", "a>0"], "goals": [{"kind": "find_range", "symbol": "x"}]},
        {"facts": ["b>0"], "goals": [{"kind": "find_range", "symbol": "y"}]},
    )
    diagnostics = [{"path": "/root", "code": "wrong_scope", "action": "repair"}]
    contract = GraphStageOneContract()
    moved = deepcopy(current)
    moved["root"]["facts"] = [moved["root"]["children"][0]["facts"].pop(0)]
    assert contract.repair_diagnostics(current, moved, diagnostics) == []
    moved["root"]["children"][1]["facts"] = ["b<0"]
    assert {i["path"] for i in contract.repair_diagnostics(current, moved, diagnostics)} == {
        "/root/children/1/facts/0"
    }


def test_scope_move_and_expression_fix_combine_in_one_repair():
    correct = candidate("q11")
    current = deepcopy(correct)
    current["root"]["facts"].append(current["root"]["children"][0]["facts"].pop(0))
    current["root"]["children"][1]["facts"][0] = "∀x∈[1,3]: f(x) <= -m+5"
    diagnostics = [
        {"path": "/root", "code": "wrong_scope", "action": "repair"},
        {"path": "/root/children/1/facts/0", "code": "wrong_expression", "action": "repair"},
    ]
    contract = GraphStageOneContract()
    assert contract.repair_diagnostics(current, correct, diagnostics) == []
    extra = deepcopy(correct)
    extra["root"]["children"][0]["facts"][1] = "f(x) <= 0"
    rejected = contract.repair_diagnostics(current, extra, diagnostics)
    assert {i["path"] for i in rejected} == {"/root/children/0/facts/0"}


def test_one_item_grant_cannot_both_replace_and_delete_a_duplicate():
    original = {"root": {"facts": ["a>0", "a>0", "b>0"]}}
    diagnostics = [{"path": "/root/facts/0", "code": "wrong_expression", "action": "repair"}]
    contract = GraphStageOneContract()
    assert contract.repair_diagnostics(original, {"root": {"facts": ["a>-1", "a>0", "b>0"]}}, diagnostics) == []
    rejected = contract.repair_diagnostics(original, {"root": {"facts": ["a>-1", "b>0"]}}, diagnostics)
    assert {i["path"] for i in rejected} == {"/root/facts/1"}


def test_combined_grants_keep_their_own_places_and_kinds():
    current = _parts(
        {"facts": ["c>0", "a>0"], "goals": [{"kind": "find_range", "symbol": "x"}]},
        {"facts": ["b>0"], "goals": [{"kind": "find_range", "symbol": "y"}]},
    )
    moved = deepcopy(current)
    moved["root"]["facts"] = [moved["root"]["children"][0]["facts"].pop(0)]
    contract = GraphStageOneContract()
    scoped_append = [
        {"path": "/root", "code": "wrong_scope", "action": "repair"},
        {"path": "/root/children/0", "code": "missing_condition", "action": "repair"},
    ]
    appended = deepcopy(moved)
    appended["root"]["children"][0]["facts"].append("d>0")
    assert contract.repair_diagnostics(current, appended, scoped_append) == []
    stray_goal = deepcopy(moved)
    stray_goal["root"]["children"][1]["goals"].append({"kind": "find_range", "symbol": "z"})
    assert {i["path"] for i in contract.repair_diagnostics(current, stray_goal, scoped_append)} == {
        "/root/children/1/goals/1"
    }
    # A correction grant cannot be exchanged for a deletion plus an addition elsewhere.
    corrected = [
        {"path": "/root", "code": "wrong_scope", "action": "repair"},
        {"path": "/root/children/1/facts/0", "code": "wrong_expression", "action": "repair"},
    ]
    exchanged = deepcopy(moved)
    exchanged["root"]["children"][1]["facts"] = []
    exchanged["root"]["children"][0]["goals"].append({"kind": "find_range", "symbol": "z"})
    assert {i["path"] for i in contract.repair_diagnostics(current, exchanged, corrected)} == {
        "/root/children/1/facts/0",
        "/root/children/0/goals/1",
    }


def test_scope_move_combines_with_a_goal_field_correction():
    correct = candidate("q11")
    current = deepcopy(correct)
    current["root"]["facts"].append(current["root"]["children"][0]["facts"].pop(0))
    current["root"]["children"][1]["goals"][0]["symbol"] = "x"
    diagnostics = [
        {"path": "/root", "code": "wrong_scope", "action": "repair"},
        {"path": "/root/children/1/goals/0/symbol", "code": "wrong_goal", "action": "repair"},
    ]
    contract = GraphStageOneContract()
    assert contract.repair_diagnostics(current, correct, diagnostics) == []
    kind_changed = deepcopy(correct)
    kind_changed["root"]["children"][1]["goals"][0]["kind"] = "find_value"
    assert {i["path"] for i in contract.repair_diagnostics(current, kind_changed, diagnostics)} == {
        "/root/children/1/goals/0/kind"
    }


def test_scope_move_restores_flattened_sub_questions():
    correct = candidate("q10")
    flattened = deepcopy(correct)
    children = flattened["root"].pop("children")
    for field in ("definitions", "facts", "goals"):
        merged = flattened["root"].get(field, []) + [x for c in children for x in c.get(field, [])]
        if merged:
            flattened["root"][field] = merged
    diagnostics = [{"path": "/root", "code": "wrong_scope", "action": "repair"}]
    contract = GraphStageOneContract()
    assert contract.repair_diagnostics(flattened, correct, diagnostics) == []
    rewritten = deepcopy(correct)
    rewritten["root"]["children"][1]["facts"][0] = rewritten["root"]["children"][1]["facts"][0].replace("<", "<=")
    assert contract.repair_diagnostics(flattened, rewritten, diagnostics)
    # Without the scope finding the same restructuring stays unauthorized.
    assert contract.repair_diagnostics(flattened, correct, [])


def test_grants_follow_sub_questions_when_they_are_reordered():
    first = {"facts": ["a>0"], "goals": [{"kind": "find_range", "symbol": "a"}]}
    second = {"facts": ["b>0"], "goals": [{"kind": "find_range", "symbol": "b"}]}
    swapped = _parts(second, first)
    swapped["root"]["children"][0]["label"], swapped["root"]["children"][1]["label"] = "（2）", "（1）"
    diagnostics = [
        {"path": "/root", "code": "wrong_scope", "action": "repair"},
        {"path": "/root/children/0/facts", "code": "missing_condition", "action": "repair"},
    ]
    contract = GraphStageOneContract()
    fixed = _parts(first, {**second, "facts": ["b>0", "b<5"]})
    assert contract.repair_diagnostics(swapped, fixed, diagnostics) == []
    misplaced = _parts({**first, "facts": ["a>0", "b<5"]}, second)
    assert contract.repair_diagnostics(swapped, misplaced, diagnostics)


def test_removing_a_fabricated_sub_question_does_not_move_the_real_one():
    fabricated = {"facts": ["c>0"], "goals": [{"kind": "find_range", "symbol": "c"}]}
    real = {"facts": ["a>0"], "goals": [{"kind": "find_range", "symbol": "a"}]}
    current = _parts(fabricated, real)
    diagnostics = [{"path": "/root/children/0", "code": "unsupported_addition", "action": "repair"}]
    contract = GraphStageOneContract()
    proposed = deepcopy(current)
    del proposed["root"]["children"][0]
    assert contract.repair_diagnostics(current, proposed, diagnostics) == []
    # The surviving sub-question still may not be edited without its own grant.
    edited = deepcopy(proposed)
    edited["root"]["children"][0]["facts"] = ["a>=0"]
    assert contract.repair_diagnostics(current, edited, diagnostics)


@pytest.mark.parametrize("labels", [(None, None), ("（1）", "（1）")])
def test_sub_questions_cannot_be_swapped_without_a_scope_grant(labels):
    first = {"facts": ["a>0"], "goals": [{"kind": "find_range", "symbol": "a"}]}
    second = {"facts": ["b>0"], "goals": [{"kind": "find_range", "symbol": "b"}]}
    current = _parts(first, second)
    for child, label in zip(current["root"]["children"], labels):
        if label is None:
            del child["label"]
        else:
            child["label"] = label
    swapped = deepcopy(current)
    children = swapped["root"]["children"]
    children[0], children[1] = (
        {**children[0], **second},
        {**children[1], **first},
    )
    diagnostics = [{"path": "/original_text", "code": "wrong_transcription", "action": "repair"}]
    assert GraphStageOneContract().repair_diagnostics(current, swapped, diagnostics)


def test_label_correction_keeps_condition_grants_on_their_sub_question():
    first = {"facts": ["a>0"], "goals": [{"kind": "find_range", "symbol": "a"}]}
    second = {"facts": ["b>0"], "goals": [{"kind": "find_range", "symbol": "b"}]}
    current = _parts(first, second)
    current["root"]["children"][0]["label"], current["root"]["children"][1]["label"] = "（2）", "（1）"
    diagnostics = [
        {"path": "/root/children/0/label", "code": "wrong_transcription", "action": "repair"},
        {"path": "/root/children/1/label", "code": "wrong_transcription", "action": "repair"},
        {"path": "/root/children/0/facts", "code": "missing_condition", "action": "repair"},
    ]
    contract = GraphStageOneContract()
    fixed = _parts({**first, "facts": ["a>0", "a<5"]}, second)
    assert contract.repair_diagnostics(current, fixed, diagnostics) == []
    misplaced = _parts(first, {**second, "facts": ["b>0", "a<5"]})
    assert contract.repair_diagnostics(current, misplaced, diagnostics)


def test_correcting_the_only_goal_keeps_the_sub_question():
    current = {
        "original_text": "（1）…",
        "root": {"children": [{"goals": [{"kind": "find_value", "expression": "a+2"}]}]},
    }
    proposed = deepcopy(current)
    proposed["root"]["children"][0]["goals"][0]["expression"] = "a+1"
    diagnostics = [
        {"path": "/root/children/0/goals/0/expression", "code": "wrong_goal", "action": "repair"}
    ]
    assert GraphStageOneContract().repair_diagnostics(current, proposed, diagnostics) == []


def test_sub_question_moved_to_another_parent_keeps_its_grants():
    one = {"label": "①", "facts": ["a>0"], "goals": [{"kind": "find_range", "symbol": "a"}]}
    two = {"label": "②", "facts": ["b>0"], "goals": [{"kind": "find_range", "symbol": "b"}]}
    current = _parts({"children": [one, two]}, {"goals": [{"kind": "find_range", "symbol": "c"}]})
    diagnostics = [
        {"path": "/root", "code": "wrong_scope", "action": "repair"},
        {"path": "/root/children/0/children/0/facts", "code": "missing_condition", "action": "repair"},
    ]
    contract = GraphStageOneContract()
    moved = _parts({"children": [two]}, {"goals": [{"kind": "find_range", "symbol": "c"}], "children": [one]})
    assert contract.repair_diagnostics(current, moved, diagnostics) == []
    completed = deepcopy(moved)
    completed["root"]["children"][1]["children"][0]["facts"].append("a<5")
    assert contract.repair_diagnostics(current, completed, diagnostics) == []
    misplaced = deepcopy(moved)
    misplaced["root"]["children"][0]["children"][0]["facts"].append("a<5")
    assert contract.repair_diagnostics(current, misplaced, diagnostics)
    # Without the scope finding the move itself stays unauthorized.
    assert contract.repair_diagnostics(current, moved, diagnostics[1:])


@pytest.mark.parametrize("empty", [True, False], ids=["empty-list", "omitted"])
def test_deleting_the_last_fabricated_sub_question_may_omit_children(empty):
    current = {
        "original_text": "求 a。",
        "root": {
            "goals": [{"kind": "find_range", "symbol": "a"}],
            "children": [{"label": "（1）", "goals": [{"kind": "find_range", "symbol": "c"}]}],
        },
    }
    proposed = deepcopy(current)
    if empty:
        proposed["root"]["children"] = []
    else:
        del proposed["root"]["children"]
    diagnostics = [{"path": "/root/children/0", "code": "unsupported_addition", "action": "repair"}]
    contract = GraphStageOneContract()
    assert contract.repair_diagnostics(current, proposed, diagnostics) == []
    assert contract.repair_diagnostics(current, proposed, [])


def test_combined_delete_and_correct_is_matched_as_a_whole():
    original = {"root": {"facts": ["a>0", "b>0"]}}
    diagnostics = [
        {"path": "/root/facts/0", "code": "unsupported_addition", "action": "repair"},
        {"path": "/root/facts/1", "code": "wrong_expression", "action": "repair"},
    ]
    contract = GraphStageOneContract()
    assert contract.repair_diagnostics(original, {"root": {"facts": ["b>=0"]}}, diagnostics) == []
    assert {i["path"] for i in contract.repair_diagnostics(original, {"root": {"facts": []}}, diagnostics)} == {
        "/root/facts/1"
    }


def test_deleting_one_of_two_equal_items_uses_the_authorized_position():
    original = {"root": {"facts": ["a∈ℝ", "a∈ℝ", "∀x∈ℝ:x^2+a>0"]}}
    repaired = {"root": {"facts": ["a∈ℝ", "∀x∈ℝ:x^2+a>0"]}}
    diagnostics = [{"path": "/root/facts/1", "code": "unsupported_addition", "action": "repair"}]
    assert GraphStageOneContract().repair_diagnostics(original, repaired, diagnostics) == []


def test_missing_goal_at_scope_only_appends_goals():
    current = {"root": {"facts": ["∀x∈ℝ:x^2+a>=0"]}}
    diagnostics = [{"path": "/root", "code": "wrong_goal", "action": "repair"}]
    contract = GraphStageOneContract()
    added = deepcopy(current)
    added["root"]["goals"] = [{"kind": "find_range", "symbol": "a"}]
    assert contract.repair_diagnostics(current, added, diagnostics) == []
    rewritten = deepcopy(added)
    rewritten["root"]["facts"] = ["∀x∈ℝ:x^2+a>0"]
    assert {i["path"] for i in contract.repair_diagnostics(current, rewritten, diagnostics)} == {
        "/root/facts/0"
    }
    # A wrong existing goal is still corrected in place.
    goal = [{"path": "/root/goals/0", "code": "wrong_goal", "action": "repair"}]
    fixed = deepcopy(added)
    fixed["root"]["goals"][0]["symbol"] = "x"
    assert contract.repair_diagnostics(added, fixed, goal) == []


@pytest.mark.parametrize(
    "typed_attempts", [False, True], ids=["dict-attempts", "typed-attempts"]
)
def test_failed_provider_attempts_keep_responses_and_usage_without_secrets(
    tmp_path, typed_attempts
):
    from shuxueshuo_server.solver.extraction.multimodal_provider import (
        ProviderSubAttempt,
    )

    api_key = "test-private-provider-key"
    hidden_error = "secret-from-exception-that-must-not-be-saved"
    hidden_header = "secret-auth-header"
    hidden_url = "https://private.example/complete?token=secret-url-token"
    attempts = []
    for number in (1, 2):
        raw = {
            "model": "model-response-v1",
            "api_key": api_key,
            "headers": {"Authorization": hidden_header},
            "request_url": hidden_url,
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "length",
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "reasoning_content": f"第{number}次：先保留 ∀x∈ℝ，再展开 x^2。",
                        "headers": {"Authorization": hidden_header},
                    },
                }
            ],
            "usage": {
                "prompt_tokens": 12,
                "completion_tokens": 8,
                "total_tokens": 20,
                "completion_tokens_details": {
                    "reasoning_tokens": 8,
                    "api_key": api_key,
                },
            },
        }
        if number == 2:
            raw["choices"][0]["message"]["content"] = (
                f'api_key="{api_key}" Authorization: Bearer {hidden_header} {hidden_url}'
            )
        item = ProviderSubAttempt(
            provider_attempt=number,
            status="completed",
            response_model="model-response-v1",
            usage=raw["usage"],
            finish_reason="length",
            visible_content=False,
            latency_ms=number * 100,
            error_code="extraction.empty_response",
            error_message=hidden_error,
            raw_payload=raw,
        )
        attempts.append(item if typed_attempts else item.to_payload())

    class FailedAfterResponses(Sequence):
        def __init__(self):
            super().__init__(RuntimeError(hidden_error))
            self.api_key = api_key
            self.last_provider_attempts = tuple(attempts)

    output, summary, _ = run(tmp_path, FailedAfterResponses())
    assert not summary["passed"]
    assert summary["status"] == "workflow.provider_failed"
    assert summary["network_attempts"] == 2
    entry = read(output / "workflow/ledger.json")["calls"][0]
    path = output / "workflow" / entry["failed_attempts_file"]
    assert path.name == "failed-attempts.json"
    evidence = read(path)
    assert entry["failed_attempts_hash"] == revision(evidence)
    assert evidence["schema_version"] == "problem-workflow-failed-attempts/v1"
    assert len(evidence["attempts"]) == 2
    for number, attempt in enumerate(evidence["attempts"], 1):
        assert attempt["provider_attempt"] == number
        assert attempt["status"] == "completed"
        assert attempt["error_code"] == "extraction.empty_response"
        assert attempt["latency_ms"] == number * 100
        assert attempt["finish_reason"] == "length"
        assert attempt["usage"]["total_tokens"] == 20
        assert attempt["usage"]["completion_tokens_details"] == {"reasoning_tokens": 8}
        assert (
            attempt["raw_payload"]["choices"][0]["message"]["reasoning_content"]
            == f"第{number}次：先保留 ∀x∈ℝ，再展开 x^2。"
        )
        assert "error_message" not in attempt
    persisted = path.read_text()
    for secret in (
        api_key,
        hidden_error,
        hidden_header,
        hidden_url,
        "secret-url-token",
    ):
        assert secret not in persisted
    assert "headers" not in persisted and "request_url" not in persisted


@pytest.mark.parametrize(
    "invalid_review",
    [
        {**CONFIRMED, "candidate": {"root": {"facts": ["a=9"]}}},
        "{",
        {"status": "confirmed", "findings": [], "explanation": "looks correct"},
    ],
)
def test_graph_review_format_retry_cannot_adopt_an_embedded_candidate(
    tmp_path, invalid_review
):
    value = candidate()
    provider = Sequence(value, invalid_review, CONFIRMED)
    output, summary, workflow = run(tmp_path, provider)
    assert summary["passed"]
    assert provider.calls == 3
    assert summary["content_calls"] == 1 and summary["review_calls"] == 2
    assert workflow["candidate"] == workflow["first_candidate"] == value
    rejected = workflow["events"][1]
    assert rejected["review_validation"]["code"] == "review.invalid_response"
    assert not rejected["adopted"] and "review" not in rejected
    for request in provider.requests[1:]:
        assert json.loads(request.prompt.user_prefix)["candidate"] == value
    last_request = json.loads(provider.requests[2].prompt.user_prefix)
    assert last_request["review_feedback"][0]["code"] == "review.invalid_response"
    assert "status" in last_request["review_feedback"][0]["message"]
    assert "findings" in last_request["review_feedback"][0]["message"]
    ledger = read(output / "workflow/ledger.json")
    invalid = read(output / "workflow" / ledger["calls"][1]["response_file"])
    assert invalid["text"] == (
        invalid_review
        if isinstance(invalid_review, str)
        else json.dumps(invalid_review, ensure_ascii=False)
    )
    assert all(call["base_revision"] == revision(value) for call in ledger["calls"][1:])


def test_graph_invalid_review_exhausts_existing_review_budget(tmp_path):
    invalid = {**CONFIRMED, "candidate": candidate()}
    provider = Sequence(candidate(), invalid, invalid, invalid)
    output, summary, workflow = run(tmp_path, provider)
    assert not summary["passed"] and not summary["source_reviewed"]
    assert summary["status"] == "workflow.budget_exhausted"
    assert summary["review_calls"] == 3 and summary["content_calls"] == 1
    assert provider.calls == 4
    assert workflow["candidate"] == candidate()
    assert sum("review_validation" in event for event in workflow["events"]) == 3
    assert len(read(output / "workflow/ledger.json")["calls"]) == 4


def test_invalid_json_escape_repair_names_the_parse_error(tmp_path):
    bad = json.dumps(candidate(), ensure_ascii=False).replace(
        '"original_text": "', '"original_text": "\\(x\\) ', 1
    )
    provider = Sequence(bad, candidate(), CONFIRMED)
    _, summary, _ = run(tmp_path, provider)
    assert summary["passed"]
    repair = json.loads(provider.requests[1].prompt.user_prefix)
    diagnostic = repair["diagnostics"][0]
    assert diagnostic["code"] == "json.invalid"
    assert "Invalid \\escape" in diagnostic["issues"][0]
    assert "$…$" in diagnostic["message"] and "\\\\le" in diagnostic["message"]


def test_graph_truncated_review_is_retried_without_content_repair(tmp_path):
    class TruncatedReview(Sequence):
        def complete(self, request):
            response = super().complete(request)
            if self.calls == 2:
                response.finish_reason = "length"
            return response

    provider = TruncatedReview(candidate(), CONFIRMED, CONFIRMED)
    _, summary, workflow = run(tmp_path, provider)
    assert summary["passed"]
    assert summary["content_calls"] == 1 and summary["review_calls"] == 2
    assert workflow["candidate"] == candidate()


@pytest.mark.parametrize("typed_attempts", [False, True])
def test_recovered_provider_failure_is_redacted_without_changing_body_or_usage(
    tmp_path, typed_attempts
):
    from shuxueshuo_server.graph_lesson.stage_one.report import render_batch
    from shuxueshuo_server.solver.extraction.multimodal_provider import (
        ProviderSubAttempt,
    )

    private_key = "synthetic-private-provider-key"
    private_header = "synthetic-authorization-secret"
    private_url = "https://private.example/complete?token=synthetic-query-secret"
    private_error = "arbitrary-sdk-exception-details"
    usage = {
        "prompt_tokens": 17,
        "completion_tokens": 9,
        "total_tokens": 26,
        "completion_tokens_details": {"reasoning_tokens": 4},
    }

    class RecoveredProvider(Sequence):
        api_key = private_key

        def complete(self, request):
            response = super().complete(request)
            if self.calls == 1:
                attempts = [
                    ProviderSubAttempt(
                        provider_attempt=1,
                        status="error",
                        response_model=None,
                        usage=None,
                        finish_reason=None,
                        visible_content=False,
                        latency_ms=11,
                        error_code="extraction.provider_connection_error",
                        error_message=f"{private_error} api_key={private_key} Authorization: Bearer {private_header} {private_url}",
                        raw_payload={
                            "headers": {"Authorization": private_header},
                            "request_url": private_url,
                        },
                    ),
                    ProviderSubAttempt(
                        provider_attempt=2,
                        status="completed",
                        response_model="response-model-v1",
                        usage=usage,
                        finish_reason="stop",
                        visible_content=True,
                        latency_ms=22,
                        raw_payload=deepcopy(response.raw_payload),
                    ),
                ]
                response.provider_attempts = tuple(
                    attempts if typed_attempts else [a.to_payload() for a in attempts]
                )
                metadata = {
                    "provider_attempts": [a.to_payload() for a in attempts],
                    "usage": usage,
                    "usage_complete": False,
                    "file_api_calls": 3,
                }
                response.metadata_payload = lambda: deepcopy(metadata)
                self.original_text, self.original_raw = (
                    response.text,
                    deepcopy(response.raw_payload),
                )
            return response

    provider = RecoveredProvider(candidate(), CONFIRMED)
    output, summary, _ = run(tmp_path, provider)
    assert summary["passed"]
    assert summary["network_attempts"] == 3 and summary["file_api_calls"] == 3
    saved = read(output / "workflow/calls/01-extract/response.json")
    assert saved["text"] == provider.original_text
    assert saved["raw_payload"] == provider.original_raw
    assert saved["metadata"]["usage"] == usage
    assert saved["metadata"]["usage_complete"] is False
    attempts = saved["metadata"]["provider_attempts"]
    assert len(attempts) == 2
    assert attempts[0]["status"] == "error" and attempts[0]["latency_ms"] == 11
    assert attempts[0]["error_code"] == "extraction.provider_connection_error"
    assert "error_message" not in attempts[0]
    assert attempts[1]["usage"] == usage and attempts[1]["latency_ms"] == 22
    assert attempts[1]["raw_payload"] == provider.original_raw
    assert summary["stages"]["extract"]["input_tokens"] == 17
    assert summary["stages"]["extract"]["output_tokens"] == 9
    assert summary["stages"]["extract"]["reasoning_tokens"] == 4
    assert summary["stages"]["extract"]["visible_output_tokens"] == 5
    save(
        tmp_path / "batch-summary.json",
        {"results": [{**summary, "sample_dir": output.name}]},
    )
    report = tmp_path / "report"
    render_batch(tmp_path, report)
    for path in (
        output / "workflow/calls/01-extract/response.json",
        report / "sample-001.html",
    ):
        persisted = path.read_text()
        for secret in (private_key, private_header, private_url, private_error):
            assert secret not in persisted


def test_format_retry_can_report_a_real_correction_before_scoped_repair(tmp_path):
    original = candidate()
    original["root"]["facts"][1] = original["root"]["facts"][1].replace("≤", "<")
    provider = Sequence(
        original,
        {**CONFIRMED, "candidate": candidate()},
        correction(),
        candidate(),
        CONFIRMED,
    )
    _, summary, workflow = run(tmp_path, provider)
    assert summary["passed"]
    assert summary["content_calls"] == 2 and summary["review_calls"] == 3
    repair = json.loads(provider.requests[3].prompt.user_prefix)
    assert repair["base_candidate"] == original
    assert repair["diagnostics"][0]["path"] == "/root/facts/1"
    assert workflow["candidate"] == candidate()


@pytest.mark.parametrize("alias,bound,goal", [("z", "t", "p"), ("w", "b", "s")])
@pytest.mark.parametrize(
    "expanded", [False, True], ids=["unexpanded-body", "redundant-global-definition"]
)
def test_quantifier_dependent_alias_policy_uses_ast_roles(alias, bound, goal, expanded):
    expression = f"{bound}*{goal}^2-({bound}+1)*{goal}+1"
    body = expression if expanded else alias
    value = {
        "root": {
            "definitions": [f"{alias}={expression}"],
            "facts": [f"∀{bound}∈[-1,1]:{body}>0"],
            "goals": [{"kind": "find_range", "symbol": goal}],
        }
    }
    assert NotationValidator().validate_root(value["root"]).ok
    checked = scope_policy(value)
    assert not checked["ok"]
    assert {item["path"] for item in checked["diagnostics"]} == {
        "/root/definitions/0",
        "/root/facts/0",
    }
    diagnostic = checked["diagnostics"][0]
    assert diagnostic["action"] == "repair"
    assert diagnostic["alias"] == alias
    assert diagnostic["bound_variables"] == [bound]
    assert diagnostic["definition_path"] == "/root/definitions/0"
    assert diagnostic["quantified_paths"] == ["/root/facts/0"]


@pytest.mark.parametrize(
    "definition,goal",
    [
        ("p=t^2+1", "p"),
        ("z=sqrt(t)+p", "p"),
        ("z=t*z+p", "p"),
        ("z=p/t", "p"),
    ],
)
def test_unsupported_or_target_alias_scope_is_a_code_gap(definition, goal):
    value = {
        "root": {
            "definitions": [definition],
            "facts": ["∀t∈[1,2]:t+p>0"],
            "goals": [{"kind": "find_range", "symbol": goal}],
        }
    }
    checked = scope_policy(value)
    assert not checked["ok"]
    assert all(item["action"] == "code_gap" for item in checked["diagnostics"])
    assert all(
        item["code"] == "scope_policy.unsupported_alias_scope"
        for item in checked["diagnostics"]
    )


def test_alias_independent_of_quantified_variable_is_not_rewritten():
    value = {
        "root": {
            "definitions": ["z=p^2+1"],
            "facts": ["∀t∈[1,2]:t+z>0"],
            "goals": [{"kind": "find_range", "symbol": "p"}],
        }
    }
    assert scope_policy(value) == {"ok": True, "diagnostics": []}


@pytest.mark.parametrize("extra", ["z<0", "z=t+2", "w=z+1"])
def test_alias_with_other_global_constraints_has_no_root_repair_grant(extra):
    value = {
        "root": {
            "definitions": ["z=t+1"],
            "facts": [extra, "∀t∈[1,2]:t+p>0"],
            "goals": [{"kind": "find_range", "symbol": "p"}],
        }
    }
    checked = scope_policy(value)
    assert not checked["ok"]
    assert all(item["action"] == "code_gap" for item in checked["diagnostics"])


@pytest.mark.parametrize(
    "expanded", [False, True], ids=["unexpanded", "redundant-global"]
)
def test_scope_policy_drives_one_scoped_repair_then_image_review(tmp_path, expanded):
    correct = candidate("q08")
    invalid = deepcopy(correct)
    invalid["root"]["definitions"] = ["y=m*x^2-m*x-6+m"]
    if not expanded:
        invalid["root"]["facts"][1] = "∀m∈[1,3]:y<0"
    validation = validate_candidate(invalid)
    assert validation["reports"]["ir"]["ok"]
    assert not validation["contract_valid"]
    assert not validation["reports"]["scope_policy"]["ok"]
    provider = Sequence(invalid, correct, CONFIRMED)
    output = tmp_path / "sample"
    summary = runner.run_sample("q08", output, provider, run_id="scope-policy-test")
    assert summary["passed"], read(output / "workflow/workflow-result.json")
    assert provider.calls == 3
    payload = json.loads(provider.requests[1].prompt.user_prefix)
    diagnostics = [
        item for item in payload["diagnostics"] if item["stage"] == "scope_policy"
    ]
    assert {item["path"] for item in diagnostics} == {
        "/root/definitions/0",
        "/root/facts/1",
    }
    assert all(item["action"] == "repair" for item in diagnostics)
    assert payload["base_candidate"] == invalid
    assert read(output / "workflow/workflow-result.json")["candidate"] == correct


@pytest.mark.parametrize(
    "extra_edit", ["goal", "unrelated_fact", "unrelated_definition"]
)
def test_scope_repair_cannot_change_unrelated_math(extra_edit):
    correct = candidate("q08")
    invalid = deepcopy(correct)
    invalid["root"]["definitions"] = ["y=m*x^2-m*x-6+m"]
    invalid["root"]["facts"][1] = "∀m∈[1,3]:y<0"
    if extra_edit == "unrelated_definition":
        invalid["root"]["definitions"].append("z=x^2")
        correct["root"]["definitions"] = ["z=x^2"]
    diagnoses = scope_policy(invalid)["diagnostics"]
    contract = GraphStageOneContract()
    assert contract.repair_diagnostics(invalid, correct, diagnoses) == []
    proposed = deepcopy(correct)
    if extra_edit == "goal":
        proposed["root"]["goals"][0]["symbol"] = "m"
        expected = "/root/goals/0/symbol"
    elif extra_edit == "unrelated_fact":
        proposed["root"]["facts"][0] = "x>0"
        expected = "/root/facts/0"
    else:
        del proposed["root"]["definitions"]
        expected = "/root/definitions/1"
    rejected = contract.repair_diagnostics(invalid, proposed, diagnoses)
    assert {item["path"] for item in rejected} == {expected}


def _parts(first, second):
    return {
        "original_text": "（1）…（2）…",
        "root": {
            "children": [
                {"label": "（1）", **first},
                {"label": "（2）", **second},
            ]
        },
    }


def test_alias_policy_sees_ancestors_and_descendants_not_siblings():
    alias_in_child = _parts(
        {
            "definitions": ["y=m*x^2-m*x-6+m"],
            "facts": ["∀m∈[1,3]:y<0"],
            "goals": [{"kind": "find_range", "symbol": "x"}],
        },
        {"facts": ["∀t∈[0,1]:t+p>0"], "goals": [{"kind": "find_range", "symbol": "p"}]},
    )
    checked = scope_policy(alias_in_child)
    assert {item["path"] for item in checked["diagnostics"]} == {
        "/root/children/0/definitions/0",
        "/root/children/0/facts/0",
    }
    # The sibling's own quantifier does not make the group ambiguous.
    assert all(item["action"] == "repair" for item in checked["diagnostics"])
    alias_in_root = deepcopy(alias_in_child)
    alias_in_root["root"]["definitions"] = alias_in_root["root"]["children"][0].pop(
        "definitions"
    )
    # A root alias is visible to both sub-questions and their two quantifiers.
    checked = scope_policy(alias_in_root)
    assert [item["path"] for item in checked["diagnostics"]] == ["/root/definitions/0"]
    assert checked["diagnostics"][0]["action"] == "code_gap"
    sibling_names = _parts(
        {"facts": ["y=2*a"], "goals": [{"kind": "find_range", "symbol": "a"}]},
        {"facts": ["∀y∈ℝ:y^2+a>0"], "goals": [{"kind": "find_range", "symbol": "a"}]},
    )
    assert scope_policy(sibling_names) == {"ok": True, "diagnostics": []}


def test_repair_may_record_uncertainty_in_any_scope_but_not_move_conditions():
    current = _parts(
        {"facts": ["m=1", "m*x^2-m*x-1<0"], "goals": [{"kind": "find_range", "symbol": "x"}]},
        {"facts": ["∀x∈[1,3]:m*x^2-m*x-1<5-m"], "goals": [{"kind": "find_range", "symbol": "m"}]},
    )
    contract = GraphStageOneContract()
    uncertain = deepcopy(current)
    uncertain["root"]["children"][1]["uncertainties"] = [
        {"kind": "ambiguous_symbol", "text": "（2）中 m 的字迹不清"}
    ]
    assert contract.repair_diagnostics(current, uncertain, []) == []
    leaked = deepcopy(current)
    leaked["root"]["facts"] = [leaked["root"]["children"][0]["facts"].pop(0)]
    assert {item["path"] for item in contract.repair_diagnostics(current, leaked, [])} == {
        "/root/children/0/facts/0",
        "/root/facts",
    }
