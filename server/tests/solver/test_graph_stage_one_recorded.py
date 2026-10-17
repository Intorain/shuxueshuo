"""Every retained live sample is replayed with networking explicitly forbidden.

The catalog is an acceptance artifact, not an optional test dependency: absent
recordings fail with a useful message instead of producing an empty/skip suite.
Historical failures remain visible independently of current offline results.
"""

import json
import socket
from pathlib import Path

import pytest

from shuxueshuo_server.graph_lesson.stage_one import runner
from shuxueshuo_server.problem_understanding import batch_smoke
from shuxueshuo_server.solver.extraction import multimodal_provider

RECORDED = Path(__file__).parent / "fixtures/graph-guided-stage-one/recorded"
EXPECTED_CASES = set(runner.CASES)
EXPECTED_PAIRS = {(case, sample) for case in EXPECTED_CASES for sample in (1, 2)}
REQUIRED_HASHES = {
    "source.png",
    "problem.md",
    "source-manifest.json",
    "notation.gold.json",
    "features.gold.json",
    "acceptance.json",
}


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def recorded_batches():
    return [
        (path.parent, read(path))
        for path in sorted(RECORDED.glob("*/batch-summary.json"))
    ]


def recorded_samples():
    return [
        pytest.param(
            batch,
            row,
            id=f"{batch.name}-{row['case_id']}-sample-{row['sample_id']:02d}",
        )
        for batch, summary in recorded_batches()
        for row in summary["results"]
    ] or [pytest.param(None, None, id="missing-recorded-samples")]


@pytest.fixture
def network_forbidden(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError(
            "recorded stage-one tests must never construct a provider or use the network"
        )

    monkeypatch.setattr(batch_smoke, "live_provider_factory", forbidden)
    monkeypatch.setattr(multimodal_provider, "_default_client_factory", forbidden)
    monkeypatch.setattr(runner, "run_workflow", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)


@pytest.mark.parametrize("batch,row", recorded_samples())
def test_each_recorded_sample_replays_without_network(
    batch, row, tmp_path, network_forbidden
):
    assert batch is not None, (
        "No recorded stage-one samples. Retain the complete two-sample-per-case live batch "
        "under fixtures/graph-guided-stage-one/recorded."
    )
    sample = (batch / row["sample_dir"]).resolve()
    assert sample.is_relative_to(batch.resolve()), (
        "recorded sample path escapes its batch"
    )
    historical = read(sample / "summary.json")
    assert historical["case_id"] == row["case_id"]
    assert historical["sample_id"] == row["sample_id"]
    assert historical["passed"] is row["passed"]
    if (sample / "workflow/ledger.json").exists():
        frozen, responses = runner.verify_recorded_sample(sample)
        assert REQUIRED_HASHES <= set(frozen["fixture_hashes"])
        assert frozen["case_id"] == row["case_id"]
        assert frozen["sample_id"] == row["sample_id"]
        ledger = read(sample / "workflow/ledger.json")
        assert ledger["calls"], (
            "a retained live invocation must preserve its call reservation"
        )
        for call in ledger["calls"]:
            assert (sample / "workflow" / call["directory"] / "request.json").is_file()
            assert len(call["request_hash"]) == 64
            if call["status"] == "completed":
                assert len(call["response_hash"]) == 64
                response = read(sample / "workflow" / call["response_file"])
                assert isinstance(response["text"], str)
                assert response["network_attempts"] >= 1
        if historical["passed"]:
            assert historical["source_reviewed"]
            assert historical["semantic_calls"] >= 2
            assert {response["stage"] for response in responses} >= {
                "extract",
                "review",
            }
    else:
        assert not historical["passed"]
        assert (sample / "failure.json").is_file(), (
            "a pre-call failure still requires durable diagnostics"
        )

    output = tmp_path / "replay"
    current = runner.replay_sample(sample, output)
    assert current["mode"] == "offline_replay"
    assert current["new_semantic_calls"] == current["new_network_attempts"] == 0
    assert current["historical_live"] == historical
    assert current["historical_live"]["passed"] is row["passed"]
    assert read(output / "summary.json") == current
    if historical["passed"]:
        assert current["passed"], read(output / "evaluation.json")


def test_recording_catalog_contains_a_complete_successful_batch():
    batches = recorded_batches()
    assert batches, "The required real-LLM recording catalog has not been exported."
    complete_successes = []
    successful_cases = set()
    for batch, summary in batches:
        rows = summary["results"]
        pairs = [(row["case_id"], row["sample_id"]) for row in rows]
        assert len(pairs) == len(set(pairs)), f"duplicate sample identity in {batch}"
        for row in rows:
            sample = batch / row["sample_dir"]
            assert sample.is_dir()
            assert read(sample / "summary.json")["passed"] is row["passed"]
            if row["passed"]:
                successful_cases.add(row["case_id"])
        live = summary.get("mode") != "offline_replay" and summary.get("historical_live") is None
        if live and summary.get("formal_passed") and summary.get("formal_complete"):
            assert summary.get("passed") and summary.get("complete")
            assert summary.get("expected_samples") == len(EXPECTED_PAIRS)
            assert len(rows) == len(EXPECTED_PAIRS) and set(pairs) == EXPECTED_PAIRS
            assert all(row["passed"] for row in rows)
            assert summary.get("single_frozen_version") is True
            for row in rows:
                sample = batch / row["sample_dir"]
                saved = read(sample / "summary.json")
                # Each sample's verdict is its own live result, not an offline re-evaluation.
                assert saved.get("historical_live") is None
                assert saved.get("mode") != "offline_replay"
                assert saved["passed"] and saved["source_reviewed"]
                assert saved["semantic_calls"] >= 2
                calls = read(sample / "workflow/ledger.json")["calls"]
                attempts = [
                    read(sample / "workflow" / call["response_file"])["network_attempts"]
                    for call in calls
                    if call["status"] == "completed"
                ]
                assert len(attempts) >= 2 and all(n >= 1 for n in attempts)
            versions = {
                json.dumps(
                    read(batch / row["sample_dir"] / "frozen.json")["implementation"],
                    sort_keys=True,
                )
                for row in rows
            }
            assert len(versions) == 1, (
                "a complete batch cannot combine different frozen implementations"
            )
            complete_successes.append(batch)
    assert complete_successes, (
        "No single complete two-sample-per-case formally passed live batch is retained; "
        "an offline replay cannot substitute for historical live acceptance."
    )
    assert successful_cases == EXPECTED_CASES
