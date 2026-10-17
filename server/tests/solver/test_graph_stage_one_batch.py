"""An interrupted run or a local debug case must not look like formal acceptance."""

import json
from pathlib import Path
from time import perf_counter

import pytest

from shuxueshuo_server.graph_lesson.stage_one import runner
from shuxueshuo_server.graph_lesson.stage_one.runner import (
    CASES,
    batch_summary,
    collect_case_batches,
    reserve_live_session,
)
from shuxueshuo_server.problem_understanding.workflow_ledger import save


def row(case, sample):
    return {
        "case_id": case,
        "sample_id": sample,
        "passed": True,
        "frozen_implementation": "same",
        "semantic_calls": 2,
        "source_reviewed": True,
        "sample_dir": f"{case}/sample-{sample:02d}",
    }


def test_partial_results_never_pass_formal_acceptance():
    result = batch_summary(Path("batch"), [row("q01", 1)], perf_counter())
    assert (
        not result["complete"] and not result["passed"] and not result["formal_passed"]
    )
    assert result["expected_samples"] == 2 * len(runner.CASES)


def test_debug_pass_is_distinguished_from_formal_pass():
    result = batch_summary(
        Path("batch"), [row("q01", 1)], perf_counter(), cases=("q01",), samples=1
    )
    assert result["complete"] and result["passed"]
    assert not result["formal_complete"] and not result["formal_passed"]
    assert result["purpose"] == "partial_debug"


def test_duplicate_missing_or_mixed_version_samples_cannot_pass():
    rows = [row(case, sample) for case in CASES for sample in (1, 2)]
    assert batch_summary(Path("batch"), rows, perf_counter())["formal_passed"]
    duplicate = rows[:-1] + [rows[0]]
    assert not batch_summary(Path("batch"), duplicate, perf_counter())["passed"]
    rows[-1]["frozen_implementation"] = "different"
    assert not batch_summary(Path("batch"), rows, perf_counter())["passed"]


def test_pytest_collection_requires_all_requested_cases(tmp_path):
    save(
        tmp_path / "q01/batch-summary.json", {"results": [row("q01", 1), row("q01", 2)]}
    )
    partial = collect_case_batches(tmp_path)
    assert not partial["complete"]
    for case in CASES[1:]:
        save(
            tmp_path / case / "batch-summary.json",
            {"results": [row(case, 1), row(case, 2)]},
        )
    complete = collect_case_batches(tmp_path)
    assert complete["formal_passed"]
    assert complete["results"][0]["sample_dir"] == "q01/q01/sample-01"


def test_workers_share_one_session_but_new_invocations_cannot_reuse_it(tmp_path):
    reserve_live_session(tmp_path, "first-invocation")
    reserve_live_session(tmp_path, "first-invocation")
    with pytest.raises(ValueError, match="already_reserved"):
        reserve_live_session(tmp_path, "later-invocation")


def test_old_sample_directories_cannot_be_adopted_by_a_new_live_session(tmp_path):
    (tmp_path / "q01").mkdir()
    with pytest.raises(ValueError, match="existing_samples"):
        reserve_live_session(tmp_path, "new-invocation")


def replay_batch_fixture(tmp_path, monkeypatch, *, requested=CASES):
    batch = tmp_path / "saved"
    rows = [row("q01", sample) for sample in (1, 2)]
    summary = batch_summary(batch, rows, perf_counter(), cases=requested, samples=2)
    save(batch / "batch-summary.json", summary)
    save(
        batch / "batch-manifest.json",
        {
            "requested_cases": list(requested),
            "samples_per_case": 2,
            "expected_samples": len(requested) * 2,
        },
    )
    for value in rows:
        save(batch / value["sample_dir"] / "summary.json", value)

    def replay_saved_summary(sample, output):
        # Sample-level hash/re-evaluation is covered separately; these checks
        # exercise the batch's independently declared expected sample set.
        return json.loads((sample / "summary.json").read_text())

    monkeypatch.setattr(runner, "replay_sample", replay_saved_summary)
    return batch


def test_replay_keeps_missing_cases_in_the_declared_formal_batch(tmp_path, monkeypatch):
    batch = replay_batch_fixture(tmp_path, monkeypatch)
    replayed = runner.replay_batch(batch, tmp_path / "replay")
    assert replayed["expected_samples"] == 2 * len(runner.CASES)
    assert replayed["requested_cases"] == list(CASES)
    assert not replayed["complete"] and not replayed["passed"]
    assert replayed["historical_live"]["complete"] is False


def test_replay_cannot_pass_when_the_explicit_case_is_absent(tmp_path, monkeypatch):
    batch = replay_batch_fixture(tmp_path, monkeypatch, requested=("q01",))
    with pytest.raises(ValueError, match="replay"):
        runner.replay_batch(batch, tmp_path / "replay", cases=("q09",))


@pytest.mark.parametrize("local_recording", [False, True])
def test_valid_local_replay_is_complete_only_for_its_requested_subset(
    tmp_path, monkeypatch, local_recording
):
    batch = replay_batch_fixture(
        tmp_path, monkeypatch, requested=("q01",) if local_recording else CASES
    )
    options = {} if local_recording else {"cases": ("q01",)}
    replayed = runner.replay_batch(batch, tmp_path / "replay", **options)
    assert replayed["passed"] and replayed["complete"]
    assert replayed["expected_samples"] == 2
    assert replayed["requested_cases"] == ["q01"]
    assert not replayed["formal_passed"]


@pytest.fixture
def unfinished_recording(tmp_path, monkeypatch):
    from test_graph_stage_one_workflow import CONFIRMED, Sequence, candidate

    original_save = runner.StageOneStorage.save

    def fail_terminal_save(self, name, value):
        if name == "workflow-result.json":
            raise OSError("temporary storage failure")
        return original_save(self, name, value)

    monkeypatch.setattr(runner.StageOneStorage, "save", fail_terminal_save)
    live = tmp_path / "live"
    result = runner.run_batch(
        live,
        lambda: Sequence(candidate(), CONFIRMED),
        cases=("q01",),
        samples=1,
        workers=1,
    )
    assert result["results"][0]["status"] == "runner.failed"
    monkeypatch.setattr(runner.StageOneStorage, "save", original_save)
    recorded = runner.record_batch(live, tmp_path / "recorded")

    def forbid_network_workflow(*args, **kwargs):
        pytest.fail("offline replay must not start an extraction workflow")

    monkeypatch.setattr(runner, "run_workflow", forbid_network_workflow)
    return recorded / "q01/sample-01"


def test_recording_retains_failure_materials_when_a_ledger_already_exists(
    unfinished_recording,
):
    assert (unfinished_recording / "failure.json").is_file()
    assert (unfinished_recording / "preflight.json").is_file()
    assert (unfinished_recording / "workflow/ledger.json").is_file()


def test_unfinished_recording_replays_as_failed_without_inventing_a_terminal_result(
    tmp_path, unfinished_recording
):
    output = tmp_path / "replay"
    replayed = runner.replay_sample(unfinished_recording, output)
    assert not replayed["passed"]
    assert replayed["status"] == "runner.failed"
    assert replayed["historical_live"]["passed"] is False
    assert replayed["new_semantic_calls"] == replayed["new_network_attempts"] == 0
    assert (output / "failure.json").is_file()
    assert (output / "workflow/ledger.json").is_file()
    assert not (output / "workflow/workflow-result.json").exists()


def test_unfinished_recording_replay_still_verifies_raw_call_hashes(
    tmp_path, unfinished_recording
):
    request = unfinished_recording / "workflow/calls/01-extract/request.json"
    data = json.loads(request.read_text())
    data["tampered"] = True
    save(request, data)
    with pytest.raises(ValueError, match="recording.request_hash_mismatch"):
        runner.replay_sample(unfinished_recording, tmp_path / "replay")
