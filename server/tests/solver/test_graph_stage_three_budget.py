"""Calculation receipts and reservations survive interruption without timing downtime."""

import json
import multiprocessing as mp
import time
from pathlib import Path

import pytest

from shuxueshuo_server.graph_lesson.stage_three.budget import (
    BudgetConflict,
    BudgetExhausted,
    BudgetLedger,
    BudgetPending,
)
from shuxueshuo_server.graph_lesson.stage_three.checkpoint import export_json
from shuxueshuo_server.graph_lesson.stage_three.events import EventStore
from tests.solver.test_graph_stage_three_events import IDENTITY, TARGET

ROUTE = "discriminant"


def make_ledger(tmp_path):
    store = EventStore(tmp_path, IDENTITY, create=True)
    return BudgetLedger(store), store


def receipt(attempt, *, elapsed=0.25, status="returned", result=None):
    value = {"schema_version": "bounded-calculation-receipt/v1", "attempt_id": attempt["attempt_id"],
             "status": status, "elapsed_seconds": elapsed}
    if status == "returned":
        value["result"] = result if result is not None else {"answer": ["rational", 1, 2]}
    else:
        value["error"] = {"exception_type": "Interrupted", "message": "test worker interruption"}
    return value


def begin(ledger, owner, operation="advance:1", *, bucket="solve", input_hash="input-a"):
    return ledger.begin(TARGET, ROUTE, bucket, operation, input_hash, owner)


def test_reservation_precedes_launch_and_settlement_releases_only_unspent_allowance(tmp_path):
    ledger, store = make_ledger(tmp_path)
    ledger.configure(TARGET, ROUTE, "solve", 10, initial_seconds=2)
    with ledger.route_lease(TARGET, ROUTE) as owner:
        attempt = begin(ledger, owner)
        assert not attempt["reused"] and attempt["remaining_seconds"] == 8
        assert attempt["summary"]["actual_seconds"] == 2
        assert attempt["summary"]["reserved_upper_seconds"] == 8
        assert attempt["summary"]["remaining_seconds"] == 0
        settled = ledger.finish(attempt["attempt_id"], owner, receipt(attempt))
        assert settled["summary"]["actual_seconds"] == 2.25
        assert settled["summary"]["reserved_upper_seconds"] == 0
        assert settled["summary"]["remaining_seconds"] == 7.75
        assert ledger.finish(attempt["attempt_id"], owner) == settled
        assert begin(ledger, owner)["receipt"] == settled["receipt"]
        assert len(settled["summary"]["operations"]) == 1
    assert not store.events() and store.checkpoint(TARGET, ROUTE) is None
    assert ledger.configure(TARGET, ROUTE, "solve", 10, initial_seconds=9)["actual_seconds"] == 2.25
    with pytest.raises(BudgetConflict, match="limit_mismatch"):
        ledger.configure(TARGET, ROUTE, "solve", 20)


def test_completed_receipt_is_reused_without_checkpoint_or_receipt_file(tmp_path):
    ledger, store = make_ledger(tmp_path)
    ledger.configure(TARGET, ROUTE, "verification", 20)
    with ledger.route_lease(TARGET, ROUTE) as owner:
        attempt = begin(ledger, owner, "independent_verification", bucket="verification")
        expected = receipt(attempt, result={"status": "verified", "proof": {"complete": True}})
        export_json(attempt["receipt_path"], expected)
    reopened = BudgetLedger(EventStore(tmp_path, IDENTITY))
    with reopened.route_lease(TARGET, ROUTE) as owner:
        first = reopened.recover(TARGET, ROUTE, owner)
        assert first["summaries"]["verification"]["actual_seconds"] == 0.25
        assert reopened.recover(TARGET, ROUTE, owner)["recovered"] == []
        Path(attempt["receipt_path"]).unlink()
        reused = begin(reopened, owner, "independent_verification", bucket="verification")
        assert reused["reused"] is True and reused["attempt_id"] == attempt["attempt_id"]
        assert reused["receipt"] == expected
        assert len(reused["summary"]["operations"]) == 1
        with pytest.raises(BudgetConflict, match="receipt_reuse_mismatch"):
            reopened.finish(attempt["attempt_id"], owner, receipt(attempt, elapsed=1))
    assert store.checkpoint(TARGET, ROUTE) is None


def test_missing_receipt_reserves_unknown_upper_without_charging_downtime_and_late_receipt_settles(tmp_path, monkeypatch):
    ledger, _store = make_ledger(tmp_path)
    ledger.configure(TARGET, ROUTE, "solve", 10, initial_seconds=1)
    with ledger.route_lease(TARGET, ROUTE) as owner:
        attempt = begin(ledger, owner)
    monkeypatch.setattr(time, "time", lambda: 9_999_999_999)
    with ledger.route_lease(TARGET, ROUTE) as owner:
        recovered = ledger.recover(TARGET, ROUTE, owner)
        summary = recovered["summaries"]["solve"]
        assert summary["actual_seconds"] == 1
        assert summary["reserved_upper_seconds"] == 9
        assert summary["used_seconds"] == 10 and summary["remaining_seconds"] == 0
        assert summary["operations"][0]["status"] == "interrupted_unknown"
        assert ledger.recover(TARGET, ROUTE, owner)["summaries"]["solve"] == summary
        with pytest.raises(BudgetPending) as pending:
            begin(ledger, owner)
        assert pending.value.attempt["attempt_id"] == attempt["attempt_id"]
        with pytest.raises(BudgetExhausted):
            begin(ledger, owner, "advance:2")
        export_json(attempt["receipt_path"], receipt(attempt, elapsed=0.4))
        exact = ledger.recover(TARGET, ROUTE, owner)["summaries"]["solve"]
        assert exact["actual_seconds"] == 1.4 and exact["reserved_upper_seconds"] == 0
        assert exact["remaining_seconds"] == 8.6
        assert begin(ledger, owner)["reused"] is True


def test_parent_lost_receipt_charges_actual_then_permits_same_operation_retry(tmp_path):
    ledger, _store = make_ledger(tmp_path)
    ledger.configure(TARGET, ROUTE, "solve", 10)
    with ledger.route_lease(TARGET, ROUTE) as owner:
        first = begin(ledger, owner)
        export_json(first["receipt_path"], receipt(first, elapsed=1.5, status="parent_lost"))
    with ledger.route_lease(TARGET, ROUTE) as owner:
        retry = begin(ledger, owner)
        assert not retry["reused"] and retry["ordinal"] == 2
        assert retry["remaining_seconds"] == 8.5
        assert retry["attempt_id"] != first["attempt_id"]
        assert retry["summary"]["actual_seconds"] == 1.5
        result = ledger.finish(retry["attempt_id"], owner, receipt(retry, elapsed=0.5))
        assert result["summary"]["actual_seconds"] == 2
        assert begin(ledger, owner)["receipt"] == result["receipt"]


@pytest.mark.parametrize("status", ["worker_error", "timeout"])
def test_terminal_failure_receipts_are_reused_not_recalculated(tmp_path, status):
    ledger, _store = make_ledger(tmp_path)
    ledger.configure(TARGET, ROUTE, "solve", 1)
    with ledger.route_lease(TARGET, ROUTE) as owner:
        attempt = begin(ledger, owner)
        expected = receipt(attempt, elapsed=1.01, status=status)
        ledger.finish(attempt["attempt_id"], owner, expected)
        reused = begin(ledger, owner)
        assert reused["reused"] is True and reused["receipt"] == expected
        assert reused["summary"]["actual_seconds"] == 1.01
        with pytest.raises(BudgetExhausted):
            begin(ledger, owner, "advance:2")


def test_lease_conflicts_and_stale_owner_cannot_mutate_receipts(tmp_path):
    ledger, store = make_ledger(tmp_path)
    contender = BudgetLedger(store)
    ledger.configure(TARGET, ROUTE, "solve", 10)
    with ledger.route_lease(TARGET, ROUTE) as first_owner:
        attempt = begin(ledger, first_owner)
        with pytest.raises(BudgetConflict, match="lease_busy"), contender.route_lease(TARGET, ROUTE):
            pytest.fail("another owner entered the same route")
        with pytest.raises(BudgetConflict, match="lease_not_owned"):
            contender.begin(TARGET, ROUTE, "solve", "advance:1", "input-a", first_owner)
        with contender.route_lease(TARGET, "separation") as other_owner:
            assert other_owner != first_owner
    with ledger.route_lease(TARGET, ROUTE) as second_owner:
        with pytest.raises(BudgetConflict, match="lease_not_owned"):
            ledger.finish(attempt["attempt_id"], first_owner, receipt(attempt))
        assert ledger.finish(attempt["attempt_id"], second_owner, receipt(attempt))["summary"]["actual_seconds"] == 0.25


def test_buckets_routes_and_targets_have_independent_balances(tmp_path):
    ledger, _store = make_ledger(tmp_path)
    keys = [(TARGET, ROUTE, "solve"), (TARGET, ROUTE, "verification"),
            (TARGET, "separation", "solve"), ("/root/goals/1", ROUTE, "solve")]
    for target, route, bucket in keys:
        ledger.configure(target, route, bucket, 10)
    with ledger.route_lease(TARGET, ROUTE) as owner:
        attempt = begin(ledger, owner)
        ledger.finish(attempt["attempt_id"], owner, receipt(attempt, elapsed=3))
    assert [ledger.summary(*key)["remaining_seconds"] for key in keys] == [7, 10, 10, 10]


def test_input_hash_mismatch_cannot_reuse_or_reset_an_operation(tmp_path):
    ledger, _store = make_ledger(tmp_path)
    ledger.configure(TARGET, ROUTE, "solve", 10)
    with ledger.route_lease(TARGET, ROUTE) as owner:
        attempt = begin(ledger, owner)
        ledger.finish(attempt["attempt_id"], owner, receipt(attempt))
        with pytest.raises(BudgetConflict, match="operation_input_mismatch"):
            begin(ledger, owner, input_hash="different-input")
        assert len(ledger.summary(TARGET, ROUTE, "solve")["operations"]) == 1


@pytest.mark.parametrize("mutation", ["attempt", "negative_elapsed", "nan_elapsed", "missing_result", "schema"])
def test_invalid_receipt_cannot_settle_or_refund_reservation(tmp_path, mutation):
    ledger, _store = make_ledger(tmp_path)
    ledger.configure(TARGET, ROUTE, "solve", 10)
    with ledger.route_lease(TARGET, ROUTE) as owner:
        attempt = begin(ledger, owner)
        invalid = receipt(attempt)
        if mutation == "attempt":
            invalid["attempt_id"] = "unrelated"
        elif mutation == "negative_elapsed":
            invalid["elapsed_seconds"] = -1
        elif mutation == "nan_elapsed":
            invalid["elapsed_seconds"] = float("nan")
        elif mutation == "missing_result":
            invalid.pop("result")
        else:
            invalid["schema_version"] = "unknown/v1"
        with pytest.raises(ValueError):
            ledger.finish(attempt["attempt_id"], owner, invalid)
        summary = ledger.summary(TARGET, ROUTE, "solve")
        assert summary["actual_seconds"] == 0 and summary["reserved_upper_seconds"] == 10


def _hold_lease_until_killed(directory, connection, write_receipt):
    ledger = BudgetLedger(EventStore(directory, IDENTITY))
    ledger.configure(TARGET, ROUTE, "solve", 10)
    with ledger.route_lease(TARGET, ROUTE) as owner:
        attempt = begin(ledger, owner)
        if write_receipt:
            export_json(attempt["receipt_path"], receipt(attempt, elapsed=0.125))
        connection.send(attempt)
        time.sleep(60)


@pytest.mark.parametrize("write_receipt", [False, True])
def test_sigkill_releases_kernel_lease_and_recovers_receipt_or_unknown_upper(tmp_path, write_receipt):
    ledger, _store = make_ledger(tmp_path)
    context = mp.get_context("spawn")
    reader, writer = context.Pipe(duplex=False)
    process = context.Process(target=_hold_lease_until_killed, args=(tmp_path, writer, write_receipt))
    try:
        process.start()
        writer.close()
        assert reader.poll(10), "child failed to reserve the budget"
        attempt = reader.recv()
        with pytest.raises(BudgetConflict, match="lease_busy"), ledger.route_lease(TARGET, ROUTE):
            pytest.fail("a live child still owns the lease")
        process.kill()
        process.join(5)
        assert not process.is_alive()
        with ledger.route_lease(TARGET, ROUTE) as owner:
            recovered = ledger.recover(TARGET, ROUTE, owner)
            summary = recovered["summaries"]["solve"]
            assert summary["actual_seconds"] == (0.125 if write_receipt else 0)
            assert summary["reserved_upper_seconds"] == (0 if write_receipt else 10)
            if write_receipt:
                replay = begin(ledger, owner)
                assert replay["reused"] is True and replay["attempt_id"] == attempt["attempt_id"]
                assert replay["receipt"]["result"] == receipt(attempt)["result"]
            else:
                with pytest.raises(BudgetPending):
                    begin(ledger, owner)
    finally:
        if process.is_alive():
            process.kill()
        process.join(5)
        process.close()
        reader.close()
        writer.close()


def test_receipt_json_is_inert_and_stored_in_authoritative_database(tmp_path):
    ledger, store = make_ledger(tmp_path)
    ledger.configure(TARGET, ROUTE, "verification", 10)
    with ledger.route_lease(TARGET, ROUTE) as owner:
        attempt = begin(ledger, owner, "verify", bucket="verification")
        arbitrary = {"expression": "__import__('os').system('false')", "text": "数学"}
        expected = receipt(attempt, result=arbitrary)
        export_json(attempt["receipt_path"], expected)
        ledger.finish(attempt["attempt_id"], owner)
    with store._connect() as db:
        saved = db.execute("SELECT receipt FROM calculation_attempts WHERE attempt_id=?", (attempt["attempt_id"],)).fetchone()
    assert json.loads(saved[0])["result"] == arbitrary
