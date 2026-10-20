"""Incremental card publication without weakening immutable-prefix or retry gates."""

from copy import deepcopy

import pytest

from shuxueshuo_server.graph_lesson.stage_three.events import EventStore
from shuxueshuo_server.graph_lesson.stage_three.execution import _accept_state, _commit
from tests.solver.test_graph_stage_three_events import IDENTITY, TARGET, fragment


def state():
    return {"target_ref": TARGET, "route_id": "discriminant", "fragments": [], "compute_seconds": 0}


def test_each_card_is_submitted_once_and_ordinary_commits_do_not_export(tmp_path, monkeypatch):
    durable = EventStore(tmp_path, IDENTITY, create=True)
    submitted = []
    commit = durable.commit_route

    def record(checkpoint, **kwargs):
        submitted.extend(step["ordinal"] for step in kwargs["math_steps"])
        return commit(checkpoint, **kwargs)

    def no_export():
        pytest.fail("a normal step must not read/write the full debug export")

    monkeypatch.setattr(durable, "commit_route", record)
    monkeypatch.setattr(durable, "export", no_export)
    current = state()
    _commit(durable, current, "start")
    for number in range(1, 31):
        current["fragments"].append(fragment(ordinal=number))
        _commit(durable, current, f"operation-{number}")
    _commit(durable, current, "verification", phase="verification")
    assert submitted == list(range(1, 31))
    assert not (tmp_path / "checkpoint.json").exists()
    assert not (tmp_path / "events.jsonl").exists()
    assert durable.snapshot()["math_steps"] == current["fragments"]
    resumed = EventStore(tmp_path, IDENTITY).checkpoint(TARGET, "discriminant")["driver_state"]
    resumed["fragments"].append(fragment(ordinal=31))
    _commit(durable, resumed, "operation-31")
    assert submitted == list(range(1, 32))


def test_same_logical_commit_retries_the_same_delta_after_reopening(tmp_path):
    durable = EventStore(tmp_path, IDENTITY, create=True)
    current = state()
    for number in range(1, 3):
        current["fragments"].append(fragment(ordinal=number))
        _commit(durable, current, f"operation-{number}")
    before = durable.events()
    _commit(durable, current, "operation-2")
    reopened = EventStore(tmp_path, IDENTITY)
    saved = reopened.checkpoint(TARGET, "discriminant")["driver_state"]
    _commit(reopened, saved, "operation-2")
    assert reopened.events() == before
    assert len(reopened.snapshot()["math_steps"]) == 2


@pytest.mark.parametrize("position", ["checkpoint", "before_commit", "after_commit"])
def test_failed_publication_does_not_advance_the_in_memory_cursor(tmp_path, monkeypatch, position):
    durable = EventStore(tmp_path, IDENTITY, create=True)
    current = state()
    _commit(durable, current, "start")
    before = deepcopy(current["publication_cursor"])
    current["fragments"].append(fragment())

    def stop(*_, **__):
        raise RuntimeError("publication interrupted")

    with monkeypatch.context() as patch:
        if position == "checkpoint":
            patch.setattr("shuxueshuo_server.graph_lesson.stage_three.execution._checkpoint", stop)
        with pytest.raises(RuntimeError, match="interrupted"):
            _commit(durable, current, "operation-1", hooks={position: stop})
    assert current["publication_cursor"] == before
    _commit(durable, current, "operation-1")
    assert len(durable.events()) == 1
    assert durable.snapshot()["math_steps"] == current["fragments"]


@pytest.mark.parametrize("change", ["formula", "remove", "cursor"])
def test_worker_cannot_rewrite_published_prefix_or_publication_cursor(change):
    previous = state()
    previous["fragments"] = [fragment()]
    previous["publication_cursor"] = {"commit_id": "first", "from": 0, "through": 1}
    updated = deepcopy(previous)
    if change == "formula":
        updated["fragments"][0]["after"][0]["expression"] = "1<0"
    elif change == "remove":
        updated["fragments"] = []
    else:
        updated.pop("publication_cursor")
    with pytest.raises(ValueError, match="immutable_step"):
        _accept_state(previous, updated)
    assert previous["fragments"][0]["after"][0]["expression"] == "1>0"


def test_legacy_state_rechecks_old_steps_once_then_uses_deltas(tmp_path):
    durable = EventStore(tmp_path, IDENTITY, create=True)
    current = state()
    current["fragments"] = [fragment()]
    _commit(durable, current, "operation-1")
    current.pop("publication_cursor")
    current["fragments"].append(fragment(ordinal=2))
    _commit(durable, current, "operation-2")
    assert [event["payload"]["chunk"]["ordinal"] for event in durable.events()] == [1, 2]
    assert current["publication_cursor"]["through"] == 2
