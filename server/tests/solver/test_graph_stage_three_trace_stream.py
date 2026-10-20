"""Event-only replay preserves parent returns and collected case provenance."""

from copy import deepcopy

import pytest

from shuxueshuo_server.graph_lesson.stage_three import runner
from tests.solver.test_graph_stage_three_contracts import upstream
from tests.solver.test_graph_stage_three_execution import Interrupted, events, store


def _reference(records, reference):
    parts = reference.strip("/").split("/")
    assert parts[0] == "steps", reference
    value = records[int(parts[1]) + 1]
    for part in parts[2:]:
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def _replay_and_compare(output):
    routes, finalizations, delivered = {}, {}, []
    for event in events(output):
        identity = (event["target_ref"], event["route_id"])
        records = routes.setdefault(identity, {})
        finalization = finalizations.setdefault(identity, {})
        payload = event["payload"]
        if event["type"] == "solver.step_completed":
            for record in payload["trajectory"]:
                # Deltas contain only new/changed rows, not a repeated full trace.
                assert records.get(record["seq"]) != record
                records[record["seq"]] = deepcopy(record)
            delivered.extend(payload["trajectory"])
            for entry in payload.get("finalization", []):
                assert entry["index"] not in finalization
                finalization[entry["index"]] = deepcopy(entry["record"])
        elif event["type"] == "lesson.chunk_ready" and payload.get("kind") == "math_step":
            # A readable card already has every route source available from the
            # preceding events; no snapshot or final-result fetch repairs it.
            for reference in payload["chunk"]["source_refs"]:
                if reference.startswith("/finalization/"):
                    source = finalization[int(reference.rsplit("/", 1)[1])]
                else:
                    source = _reference(records, reference)
                if isinstance(source, dict) and "postconditions" in source:
                    assert source["postconditions"]
                    assert all(check["passed"] is True for check in source["postconditions"])
    snapshot = store(output).internal_snapshot()
    for checkpoint in snapshot["checkpoints"]:
        identity = (checkpoint["target_ref"], checkpoint["route_id"])
        expected = checkpoint["driver_state"]["trajectory"]["steps"]
        actual = [routes[identity][seq] for seq in sorted(routes[identity])]
        assert actual == expected
        finalization = checkpoint["driver_state"]["trajectory"]["finalization"]
        assert finalizations[identity]
        for index, source in finalizations[identity].items():
            assert finalization[index] == source
        for record in expected:
            for case in record.get("case_results", []):
                assert case["source_refs"]
                for reference in case["source_refs"]:
                    source = _reference(routes[identity], reference)
                    assert source["case_path"] == case["case_path"]
                    assert source["source_refs"]
    return delivered


@pytest.mark.parametrize("case", ["q01", "q03"])
def test_event_replay_matches_snapshot_after_child_return_and_case_collection(tmp_path, case):
    output = tmp_path / "run"
    result = runner.run_sample(upstream(tmp_path, case), output, milestone="2")
    assert result["status"] == "completed", result
    delivered = _replay_and_compare(output)
    assert any(record.get("case_results") for record in delivered)
    assert any(call["capability"] == "submethod" and call["postconditions"]
               for record in delivered for call in record["calls"])


@pytest.mark.parametrize("position", ["before_commit", "after_commit"])
def test_resumed_case_collection_replays_its_sources_without_snapshot_repair(tmp_path, position):
    output = tmp_path / "run"
    interrupted = []

    def stop_after_collection(state, _durable):
        if not interrupted and any(record.get("case_results") for record in state["trajectory"]["steps"]):
            interrupted.append(True)
            raise Interrupted()

    with pytest.raises(Interrupted):
        runner.run_sample(upstream(tmp_path, "q03"), output, milestone="2",
                          hooks={position: stop_after_collection})
    prefix = events(output)
    resumed = runner.resume_sample(output)
    assert resumed["status"] == "completed", resumed
    assert events(output)[:len(prefix)] == prefix
    delivered = _replay_and_compare(output)
    collections = [record for record in delivered if record.get("case_results")]
    assert len(collections) == 1
    assert len(collections[0]["case_results"]) == 3


@pytest.mark.parametrize("position", ["before_commit", "after_commit"])
def test_boundary_source_and_card_resume_as_one_commit(tmp_path, position):
    output = tmp_path / "run"
    interrupted = []

    def stop_at_boundary(state, _durable):
        if not interrupted and "endpoint_evidence" in state:
            interrupted.append(True)
            raise Interrupted()

    with pytest.raises(Interrupted):
        runner.run_sample(upstream(tmp_path), output, milestone="1b-1",
                          hooks={position: stop_at_boundary})
    prefix = events(output)
    resumed = runner.resume_sample(output)
    assert resumed["status"] == "completed", resumed
    assert events(output)[:len(prefix)] == prefix
    _replay_and_compare(output)
    sources = [event for event in events(output) if event["payload"].get("finalization")]
    assert [event["payload"]["operation"] for event in sources] == ["endpoint_check", "finalize_goal"]
    assert all(len(event["payload"]["finalization"]) == 1 for event in sources)
    boundary, closure = [event["payload"]["finalization"][0] for event in sources]
    assert boundary["index"] < closure["index"]
