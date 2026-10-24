"""The student resume endpoint also recovers unfinished interaction work."""

import json
import time
from copy import deepcopy

import pytest

from shuxueshuo_server.graph_lesson.stage_three import runner
from shuxueshuo_server.graph_lesson.stage_three.budget import BudgetLedger
from shuxueshuo_server.graph_lesson.stage_three.preview import open_store
from shuxueshuo_server.search import stage_three
from tests.search.test_stage_three_api import (
    client_for,
    forbidden,
    no_live_llm,  # noqa: F401 -- shared autouse fixture
    seed,
    status,
    wait_done,
)
from tests.solver.graph_stage_three_faults import offline_dispatch


def interaction_only_dispatch(payload):
    assert payload["operation"] == "interaction", "completed mathematics must never be executed again"
    return offline_dispatch(payload)


def test_product_resume_drains_completed_math_without_recalculation(tmp_path, monkeypatch):
    root, directory = seed(tmp_path)
    armed = True

    def interrupt(chunk, durable):
        nonlocal armed
        if armed:
            armed = False
            raise RuntimeError("interrupted after interaction receipt")

    result = stage_three.run_stage_three(directory / "stage-two-1", hooks={
        "calculation_dispatch": offline_dispatch, "interaction_returned": interrupt,
        "interaction_budget": (6.0, 17.0),
    })
    assert result["status"] == "completed" and not armed
    output = directory / "stage-two-1/stage-three"
    durable = open_store(output)
    assert durable.has_pending_interactions()
    assert durable.interaction_settings()["budget"] == {"group_seconds": 6.0, "route_seconds": 17.0}
    before = durable.snapshot()
    prefix = durable.events()
    checkpoints = {tuple(row[key] for key in ("target_ref", "route_id")):
                   durable.checkpoint(row["target_ref"], row["route_id"])
                   for row in before["checkpoints"]}
    ledger = BudgetLedger(durable)
    budgets = {(target, route, bucket): deepcopy(ledger.summary(target, route, bucket))
               for target, route in checkpoints for bucket in ("solve", "verification")}
    receipts = {(row["target_ref"], row["route_id"], row["step_id"]): row for row in durable.interaction_states()
                if row["status"] != "pending"}
    monkeypatch.setattr(runner, "run_sample", forbidden)
    monkeypatch.setattr(runner, "resume_sample", forbidden)

    with client_for(root, hooks={"interaction_dispatch": interaction_only_dispatch}) as client:
        stopped = status(client)
        assert stopped["execution_status"] == "interrupted"
        resume_url = f"/api/search/problems/{directory.name}/lesson/{result['run_id']}/resume"
        response = client.post(resume_url)
        assert response.status_code == 200 and response.json()["status"] == "running"
        completed = wait_done(client)
        assert completed["stream"] == stopped["stream"]
        assert not durable.has_pending_interactions()
        assert client.post(resume_url).json()["status"] == "completed"

    after = durable.snapshot()
    assert after["math_steps"] == before["math_steps"]
    assert after["goals"] == before["goals"]
    assert after["handoffs"] == before["handoffs"]
    assert durable.events()[:len(prefix)] == prefix
    for (target, route), checkpoint in checkpoints.items():
        assert durable.checkpoint(target, route) == checkpoint
    for (target, route, bucket), budget in budgets.items():
        assert ledger.summary(target, route, bucket) == budget
    for row in durable.interaction_states():
        previous = receipts.get((row["target_ref"], row["route_id"], row["step_id"]))
        if previous:
            assert row == previous
    for route in {row["route_id"] for row in after["interactions"]}:
        # A route containing only no_rule cards does not need a worker/budget.
        if any(row["route_id"] == route and row["status"] == "interactive" for row in after["interactions"]):
            budget = ledger.summary("/root/goals/0", route + "#interaction", "interaction")
            assert budget["limit_seconds"] == 17.0
            assert all(row["allowance_seconds"] <= 6.0 for row in budget["operations"])
    saved = json.loads((output / "stage-three-result.json").read_text())
    assert saved["status"] == "completed" and saved["goals"] == result["goals"]
    assert saved["events"]["last_seq"] == after["last_seq"]
    assert json.loads((output / "interaction-diagnostics.json").read_text()) == {"errors": []}


def test_repeated_interaction_failure_eventually_removes_the_resume_action(tmp_path, monkeypatch):
    root, directory = seed(tmp_path)

    def fail(chunk, durable):
        raise RuntimeError("persistent scheduling fault")

    result = stage_three.run_stage_three(directory / "stage-two-1", hooks={
        "calculation_dispatch": offline_dispatch, "interaction_dispatch": interaction_only_dispatch,
        "interaction_returned": fail,
    })
    output = directory / "stage-two-1/stage-three"
    durable = open_store(output)
    before = durable.snapshot()
    assert result["status"] == "completed" and durable.has_pending_interactions()
    monkeypatch.setattr(runner, "run_sample", forbidden)
    monkeypatch.setattr(runner, "resume_sample", forbidden)
    resume_url = f"/api/search/problems/{directory.name}/lesson/{result['run_id']}/resume"
    with client_for(root, hooks={"interaction_dispatch": interaction_only_dispatch,
                                "interaction_returned": fail}) as client:
        assert status(client)["execution_status"] == "interrupted"
        for expected in ("interrupted", "completed"):
            response = client.post(resume_url)
            assert response.status_code == 200 and response.json()["status"] == "running"
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                current = status(client)
                if current["execution_status"] not in ("starting", "running"):
                    break
                time.sleep(0.025)
            else:
                pytest.fail("interaction resume did not finish")
            assert current["execution_status"] == expected
        assert client.post(resume_url).json()["status"] == "completed"
    after = durable.snapshot()
    assert not durable.has_pending_interactions()
    for key in ("math_steps", "goals", "handoffs", "checkpoints"):
        assert after[key] == before[key]
    closed = [row for row in after["interactions"] if row.get("reason") == "scheduler_error"]
    assert closed and all(row["status"] == "readonly" for row in closed)
