"""Interaction failures and diagnostics never borrow the mathematical test seams."""

from shuxueshuo_server.graph_lesson.stage_three import (
    calculations,
    interaction_jobs,
    runner,
)
from tests.solver.test_graph_stage_three_interaction_scheduler import (
    _store,
    sessions,  # noqa: F401 -- real budget/receipt fixture, only the worker is replaced
)


def forbidden(*args, **kwargs):
    raise AssertionError("mathematical fault injection must not run for interactions")


def test_interaction_receipt_has_its_own_fault_hook(tmp_path, sessions):  # noqa: F811 -- imported pytest fixture
    durable = _store(tmp_path)
    received = []

    def returned(attempt, store):
        assert store is durable
        received.append(attempt["attempt_id"])

    assert interaction_jobs.run_pending(durable, hooks={
        "calculation_returned": forbidden, "interaction_calculation_returned": returned,
    }) == (1, [])
    assert len(received) == len(sessions) == 1


def test_runner_does_not_reuse_mathematical_dispatch(tmp_path, monkeypatch):
    durable = _store(tmp_path)

    class Scheduler:
        def __init__(self, store, *, dispatch, hooks):
            assert store is durable
            self.dispatch = dispatch

        def start(self):
            return self

    monkeypatch.setattr(interaction_jobs, "InteractionScheduler", Scheduler)
    assert runner._interaction_scheduler(durable, {"calculation_dispatch": forbidden}).dispatch is calculations.dispatch
    assert runner._interaction_scheduler(durable, {"interaction_dispatch": forbidden}).dispatch is forbidden


def test_unready_seed_keeps_its_reason_in_diagnostics(tmp_path):
    durable = _store(tmp_path)
    scheduler = interaction_jobs.InteractionScheduler(durable, dispatch=forbidden)
    seed = durable.checkpoint("/root/goals/0", "discriminant")["driver_state"]["interaction_seeds"][0]
    seed.update(status="unavailable", reason="seed_hash_mismatch")
    try:
        assert scheduler._compile(seed["target_ref"], seed["route_id"], [seed], {},
                                  scheduler.settings["registry"], scheduler.settings["revision"]) == 1
    finally:
        scheduler.close()
    chunk = durable.snapshot()["interactions"][0]
    assert chunk["reason"] == "seed_hash_mismatch"
    assert durable.interaction(chunk["interaction_id"])["diagnostics"] == [
        {"result": "readonly", "reason": "seed_hash_mismatch"},
    ]
