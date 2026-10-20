"""Step interactions run beside mathematics: own worker, budget, states and events.

Every case runs the real Q13 recording offline through supervised workers.
"""

import sqlite3
import time
from contextlib import closing
from copy import deepcopy

import pytest

from shuxueshuo_server.graph_lesson.stage_three import (
    interaction,
    interaction_jobs,
    runner,
)
from shuxueshuo_server.graph_lesson.stage_three.budget import BudgetLedger
from shuxueshuo_server.graph_lesson.stage_three.contracts import ROOT
from shuxueshuo_server.graph_lesson.stage_three.handoff import invalidate_goal
from shuxueshuo_server.graph_lesson.stage_three.storage_validation import (
    validate_schema,
)
from tests.solver.graph_stage_three_faults import offline_dispatch
from tests.solver.test_graph_stage_three_batch_six import _source
from tests.solver.test_graph_stage_three_execution import store
from tests.solver.test_graph_stage_three_recorded import (
    forbid_live_providers_and_network,  # noqa: F401 — shared autouse fixture
)

TARGET = "/root/goals/0"


def slow_dispatch(payload):
    if payload["operation"] == "interaction":
        time.sleep(5)
    return offline_dispatch(payload)


def broken_dispatch(payload):
    if payload["operation"] == "interaction":
        raise RuntimeError("injected interaction fault")
    return offline_dispatch(payload)


def _run(directory, *, interactions=True, **hooks):
    source, _, _ = _source(directory)
    output = directory / "stage-three"
    result = runner.run_sample(source, output, interactions=interactions,
                               hooks={"calculation_dispatch": offline_dispatch, "interaction_dispatch": offline_dispatch,
                                      **hooks})
    assert result["status"] == "completed"
    return result, store(output)


RUN_FIELDS = {"run_id", "lesson_version", "step_id", "math_step_sha256", "revisions_ref"}


def _math(durable):
    """Mathematical content, independent of the run identity embedded in ids and hashes."""
    snapshot = durable.snapshot()
    return ([{key: value for key, value in step.items() if key not in RUN_FIELDS} for step in snapshot["math_steps"]],
            {(row["route_id"], row["status"]) for row in snapshot["checkpoints"]},
            snapshot["goals"])


def _by_route(rows):
    routes = {}
    for row in rows:
        routes.setdefault(row["route_id"], []).append(row)
    return routes


@pytest.fixture(scope="module")
def plain(tmp_path_factory):
    return _run(tmp_path_factory.mktemp("plain") / "q13", interactions=False)


@pytest.fixture(scope="module")
def live(tmp_path_factory):
    return _run(tmp_path_factory.mktemp("live") / "q13")


@pytest.fixture
def paused(tmp_path):
    return _run(tmp_path / "q13", interaction_scheduler=False)


# --- A normal run ------------------------------------------------------------------

def test_run_resolves_every_card_with_the_frozen_rules(live):
    _, durable = live
    settings = durable.interaction_settings()
    assert settings["protocol"] == "graph-step-interaction/v1"
    assert settings["revision"] == interaction.registry_revision(settings["registry"])
    snapshot = durable.snapshot()
    validate_schema(ROOT / "internal/schemas/graph-stage-three-snapshot-v2.schema.json", snapshot)
    assert snapshot["interaction_protocol"] == "graph-step-interaction/v1"
    assert all(row["status"] != "pending" for row in snapshot["interaction_states"])
    assert len(snapshot["interaction_states"]) == len(snapshot["math_steps"])
    assert all("diagnostics" not in chunk for chunk in snapshot["interactions"])
    for route, states in _by_route(snapshot["interaction_states"]).items():
        seeds = durable.checkpoint(TARGET, route)["driver_state"]["interaction_seeds"]
        expected = [chunk for chunk, _ in interaction.compile_route(seeds, settings["registry"])[0]]
        published = [chunk for chunk in snapshot["interactions"] if chunk["route_id"] == route]
        assert published == expected
        covered = {step["step_id"]: chunk["interaction_id"] for chunk in published for step in chunk["steps"]}
        assert {row["step_id"]: row["interaction_id"] for row in states} == covered
    closing_pair = [chunk for chunk in snapshot["interactions"] if len(chunk["steps"]) == 2]
    assert {chunk["route_id"] for chunk in closing_pair} == {"interval", "extremum"}


def test_interaction_events_follow_their_cards_and_carry_the_initial_state(live):
    _, durable = live
    events = durable.events()
    seen, kinds = {}, []
    for event in events:
        payload = event["payload"]
        if event["type"] != "lesson.chunk_ready":
            continue
        if payload["kind"] == "math_step":
            assert payload["interaction_status"] == "pending"
            seen[payload["step_id"]] = payload["math_step_sha256"]
        elif payload["kind"] == "step_interaction":
            kinds.append(payload["status"])
            chunk = payload["chunk"]
            assert payload["interaction_id"] == chunk["interaction_id"]
            assert all(seen.get(step["step_id"]) == step["math_step_sha256"] for step in chunk["steps"])
    assert "interactive" in kinds and "readonly" in kinds


def test_resolved_cards_are_immutable_and_identical_retries_are_idempotent(live):
    _, durable = live
    chunk = durable.snapshot()["interactions"][0]
    record = durable.interaction(chunk["interaction_id"])
    again = durable.commit_interaction(chunk, diagnostics=record["diagnostics"])
    assert again["interaction_id"] == chunk["interaction_id"]
    changed = interaction.readonly_chunk(
        [{**chunk, "step_id": step["step_id"], "math_step_sha256": step["math_step_sha256"]} for step in chunk["steps"]],
        chunk["interaction_revision"], "repeat")
    if changed["interaction_id"] == chunk["interaction_id"]:
        with pytest.raises(ValueError, match="immutable_interaction"):
            durable.commit_interaction(changed, commit_id="other")
    other_revision = interaction.readonly_chunk(
        [{**chunk, "step_id": step["step_id"], "math_step_sha256": step["math_step_sha256"]} for step in chunk["steps"]],
        "f" * 64, "repeat")
    with pytest.raises(ValueError, match="interaction_revision_mismatch"):
        durable.commit_interaction(other_revision)
    tampered = deepcopy(chunk)
    tampered["interaction_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="interaction_hash_mismatch"):
        durable.commit_interaction(tampered, commit_id="tampered")


def test_interaction_code_stays_out_of_the_mathematical_fingerprint():
    paths = runner.fingerprint()
    assert not any(path.endswith(("stage_three/interaction.py", "stage_three/interaction_jobs.py")) for path in paths)


def test_runs_without_the_protocol_publish_mathematics_only(plain, live):
    _, durable = plain
    assert durable.interaction_settings() is None
    snapshot = durable.snapshot()
    assert snapshot["interaction_protocol"] is None and snapshot["interaction_states"] == []
    assert not any("interaction_status" in event["payload"] for event in durable.events())
    assert _math(durable)[0] == _math(live[1])[0]


# --- Isolation and failures ------------------------------------------------------------

@pytest.mark.parametrize("dispatch,budget,reasons", [
    (slow_dispatch, (0.5, 1.2), {"compile_timeout", "budget_exhausted"}),
    (broken_dispatch, (5.0, 30.0), {"compile_error"}),
])
def test_interaction_failures_become_readonly_without_touching_mathematics(
        tmp_path, plain, dispatch, budget, reasons):
    _, durable = _run(tmp_path / "q13", interaction_dispatch=dispatch, interaction_budget=budget)
    assert _math(durable) == _math(plain[1])
    snapshot = durable.snapshot()
    assert all(row["status"] == "readonly" for row in snapshot["interaction_states"])
    produced = {chunk["reason"] for chunk in snapshot["interactions"]}
    assert reasons <= produced <= reasons | {"no_rule"}
    ledger = BudgetLedger(durable)
    for route in ("interval", "extremum"):
        math = {row["operation_key"] for bucket in ("solve", "verification")
                for row in ledger.summary(TARGET, route, bucket)["operations"]}
        assert not any(key.startswith("interaction:") for key in math)
        spent = ledger.summary(TARGET, route + interaction_jobs.LEASE_SUFFIX, "interaction")
        assert spent["used_seconds"] <= budget[1] + 1


# --- Ordering, recovery and lifecycle -----------------------------------------------------

def test_merge_prefix_stays_pending_until_its_follower_is_committed(tmp_path):
    observed, holder = [], {}

    def committed(state, durable):
        scheduler = holder.setdefault("scheduler", interaction_jobs.InteractionScheduler(
            durable, dispatch=offline_dispatch))
        scheduler.step()
        units = {seed["step_id"]: seed["display_unit"] for seed in state.get("interaction_seeds", [])}
        rows = durable.interaction_states(state["target_ref"], state["route_id"])
        observed.append([(units.get(row["step_id"]), row["status"]) for row in rows])

    try:
        _, durable = _run(tmp_path / "q13", interaction_scheduler=False, committed=committed)
    finally:
        if "scheduler" in holder:
            holder["scheduler"].close()
    boundary_waits = [rows for rows in observed if rows and rows[-1][0] == "boundary"]
    assert boundary_waits and all(rows[-1][1] == "pending" for rows in boundary_waits)
    final = durable.snapshot()
    pairs = [chunk for chunk in final["interactions"] if len(chunk["steps"]) == 2]
    assert len(pairs) == 2 and all(chunk["status"] == "interactive" for chunk in pairs)


def test_a_returned_result_survives_a_crash_before_its_commit(paused):
    _, durable = paused
    fault = {"armed": True}

    def crash(chunk, _store):
        if fault["armed"]:
            fault["armed"] = False
            raise RuntimeError("crash after the worker returned")

    _total, errors = interaction_jobs.run_pending(durable, dispatch=offline_dispatch,
                                                  hooks={"interaction_returned": crash})
    assert errors and errors[0]["message"] == "crash after the worker returned"
    before = BudgetLedger(durable)
    pending = [row for row in durable.interaction_states() if row["status"] == "pending"]
    assert pending
    _total, errors = interaction_jobs.run_pending(durable, dispatch=offline_dispatch)
    assert errors == [] and all(row["status"] != "pending" for row in durable.interaction_states())
    for route in ("interval", "extremum"):
        operations = before.summary(TARGET, route + interaction_jobs.LEASE_SUFFIX, "interaction")["operations"]
        keys = [row["operation_key"] for row in operations]
        assert len(keys) == len(set(keys)), "a returned receipt must be reused, not recomputed"


def test_unavailable_engine_or_goal_resolves_pending_cards_readonly(paused, tmp_path):
    _, durable = paused
    with closing(sqlite3.connect(durable.path)) as db:
        settings = durable.interaction_settings()
        settings["engine_revision"] = "0" * 64
        db.execute("UPDATE metadata SET value=? WHERE key='interactions'", (interaction._canonical(settings),))
        db.commit()
    interaction_jobs.run_pending(durable, dispatch=offline_dispatch)
    assert {chunk["reason"] for chunk in durable.snapshot()["interactions"]} == {"engine_unavailable"}

    _, other = _run(tmp_path / "revoked", interaction_scheduler=False)
    invalidate_goal(other, TARGET, status="no_verified_route", reason="test.revoked", commit_id="revoke")
    interaction_jobs.run_pending(other, dispatch=offline_dispatch)
    assert {chunk["reason"] for chunk in other.snapshot()["interactions"]} == {"route_unavailable"}
    assert all(row["status"] == "readonly" for row in other.interaction_states())


def test_resume_drains_interactions_left_pending_by_an_earlier_process(paused):
    _result, durable = paused
    assert any(row["status"] == "pending" for row in durable.interaction_states())
    runner.resume_sample(durable.directory, hooks={"calculation_dispatch": offline_dispatch})
    assert all(row["status"] != "pending" for row in durable.interaction_states())
