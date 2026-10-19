"""Validated contracts are session data, not checkpoint or dispatch behavior."""

import json
import os
import shutil
from copy import deepcopy
from unittest.mock import patch

import pytest

from shuxueshuo_server.graph_lesson.stage_one.features import extract_features
from shuxueshuo_server.graph_lesson.stage_three import (
    calculations,
    driver,
    execution_contracts,
    runner,
)
from shuxueshuo_server.graph_lesson.stage_three.context import build_context
from shuxueshuo_server.graph_lesson.stage_three.json_bounded import (
    JsonCalculationSession,
)
from tests.solver.graph_stage_three_faults import failed_local_check
from tests.solver.test_graph_stage_three_methods import Q01, TARGET

_WORKER_LOADS = 0


@pytest.fixture(autouse=True)
def isolated_contract_cache():
    calculations._session_contracts.cache_clear()
    yield
    calculations._session_contracts.cache_clear()


@pytest.fixture
def contract_directory(monkeypatch, tmp_path):
    directory = tmp_path / "execution"
    shutil.copytree(execution_contracts.DIRECTORY, directory)
    monkeypatch.setattr(execution_contracts, "DIRECTORY", directory)
    return directory


def _change_revision(directory):
    path = directory / "method-discriminant.json"
    # Alter real contract bytes without changing its valid execution meaning.
    path.write_text(path.read_text() + "\n")


def counting_dispatch(payload):
    """An importable wrapper measures loads in the actual spawned worker."""
    original = execution_contracts.load_contracts

    def counted():
        global _WORKER_LOADS
        _WORKER_LOADS += 1
        return original()

    with patch.object(execution_contracts, "load_contracts", counted):
        state = calculations.dispatch(payload)
    return {"state": state, "loads": _WORKER_LOADS, "pid": os.getpid()}


def _arguments(method="method-discriminant"):
    return {
        "features": extract_features(Q01)["features"],
        "context": build_context(Q01, TARGET),
        "method": method,
        "route_id": "discriminant" if method == "method-discriminant" else "extremum",
        "branch": "discriminant" if method == "method-discriminant" else "separation",
        "target_ref": TARGET,
        "run_id": "contract-cache",
        "lesson_version": "v1",
        "revisions": execution_contracts.revisions(),
    }


def _finish(state, advance):
    for _ in range(200):
        if state["status"] != "running":
            return state
        # Exercise the same JSON separation as a persisted/restored checkpoint.
        state = advance(json.loads(json.dumps(state)))
    raise AssertionError("route did not terminate")


def _without_timing(state):
    state = deepcopy(state)
    state.pop("compute_seconds")
    return state


@pytest.mark.parametrize("method", ["method-discriminant", "method-separation"])
def test_cached_route_matches_direct_execution_and_does_not_mutate_contracts(monkeypatch, method):
    arguments = _arguments(method)
    expected = _finish(driver.create_state(**arguments), driver.advance)
    assert expected["status"] == "method_complete"
    original = execution_contracts.load_contracts
    loaded, snapshots = [], []

    def counted():
        contracts = original()
        loaded.append(contracts)
        snapshots.append(deepcopy(contracts))
        return contracts

    monkeypatch.setattr(execution_contracts, "load_contracts", counted)
    state = calculations.dispatch({"operation": "initialize", "arguments": arguments})
    actual = _finish(state, lambda value: calculations.dispatch({"operation": "advance", "state": value}))
    assert _without_timing(actual) == _without_timing(expected)
    assert len(loaded) == 1
    assert loaded == snapshots
    # Contract documents themselves never become persisted driver bindings.
    assert "contracts" not in actual


def test_direct_driver_still_validates_each_call_and_explicit_contracts_skip_reload(monkeypatch):
    arguments = _arguments()
    original = execution_contracts.load_contracts
    loads = []

    def counted():
        contracts = original()
        loads.append(contracts)
        return contracts

    monkeypatch.setattr(execution_contracts, "load_contracts", counted)
    state = driver.create_state(**arguments)
    state = driver.advance(state)
    state = driver.advance(state)
    assert state["status"] == "running"
    assert len(loads) == 3
    state = driver.create_state(contracts=loads[0], **arguments)
    state = driver.advance(state, contracts=loads[0])
    assert state["status"] == "running"
    assert len(loads) == 3


def test_revision_change_revalidates_and_mapping_order_does_not(monkeypatch, contract_directory):
    arguments = _arguments()
    original = execution_contracts.load_contracts
    loads = []

    def counted():
        loads.append(True)
        return original()

    monkeypatch.setattr(execution_contracts, "load_contracts", counted)
    state = calculations.dispatch({"operation": "initialize", "arguments": arguments})
    state["revisions"] = dict(reversed(list(state["revisions"].items())))
    state = calculations.dispatch({"operation": "advance", "state": state})
    assert len(loads) == 1
    _change_revision(contract_directory)
    state["revisions"] = execution_contracts.revisions()
    state = calculations.dispatch({"operation": "advance", "state": state})
    assert state["status"] == "running"
    assert len(loads) == 2


def test_cache_hit_does_not_read_disk_revisions(monkeypatch):
    arguments = _arguments()
    state = calculations.dispatch({"operation": "initialize", "arguments": arguments})

    def unexpected_read():
        raise AssertionError("cache hit read disk revisions")

    monkeypatch.setattr(execution_contracts, "revisions", unexpected_read)
    state["revisions"] = dict(reversed(list(state["revisions"].items())))
    state = calculations.dispatch({"operation": "advance", "state": state})
    assert state["status"] == "running"


def test_complete_pipeline_fingerprint_is_validated_without_replacing_checkpoint_identity(monkeypatch):
    arguments = _arguments()
    arguments["revisions"] = runner.fingerprint()
    expected = deepcopy(arguments["revisions"])
    state = calculations.dispatch({"operation": "initialize", "arguments": arguments})

    def unexpected_read():
        raise AssertionError("cache hit reread pipeline fingerprint")

    monkeypatch.setattr(runner, "fingerprint", unexpected_read)
    state = calculations.dispatch({"operation": "advance", "state": state})
    assert state["status"] == "running" and state["revisions"] == expected


@pytest.mark.parametrize("change", ["stale", "missing", "extra"])
def test_changed_or_incomplete_pipeline_fingerprint_is_rejected_before_loading(monkeypatch, change):
    arguments = _arguments()
    current = runner.fingerprint()
    arguments["revisions"] = deepcopy(current)
    path = "server/shuxueshuo_server/graph_lesson/stage_one/features.py"
    assert path in current
    if change == "stale":
        arguments["revisions"][path] = "0" * 64
    elif change == "missing":
        del arguments["revisions"][path]
    else:
        arguments["revisions"]["unrecognized/revision"] = "0" * 64
    original = execution_contracts.load_contracts
    loads = []

    def counted():
        loads.append(True)
        return original()

    monkeypatch.setattr(execution_contracts, "load_contracts", counted)
    payload = {"operation": "initialize", "arguments": arguments}
    with pytest.raises(ValueError, match="^execution.contract_revisions_changed$"):
        calculations.dispatch(payload)
    assert loads == [] and calculations._session_contracts.cache_info().currsize == 0
    arguments["revisions"] = current
    state = calculations.dispatch(payload)
    assert state["status"] == "running" and len(loads) == 1


def test_pipeline_fingerprint_changed_during_load_is_not_cached(monkeypatch):
    arguments = _arguments()
    arguments["revisions"] = runner.fingerprint()
    current = deepcopy(arguments["revisions"])
    changed = deepcopy(current)
    changed["server/shuxueshuo_server/graph_lesson/stage_one/features.py"] = "0" * 64
    reads = iter((current, changed))
    monkeypatch.setattr(runner, "fingerprint", lambda: next(reads))
    with pytest.raises(ValueError, match="^execution.contract_revisions_changed$"):
        calculations.dispatch({"operation": "initialize", "arguments": arguments})
    assert calculations._session_contracts.cache_info().currsize == 0


def test_stale_revision_is_rejected_before_load_and_current_revision_can_load(monkeypatch, contract_directory):
    arguments = _arguments()
    _change_revision(contract_directory)
    original = execution_contracts.load_contracts
    loads = []

    def counted():
        loads.append(True)
        return original()

    monkeypatch.setattr(execution_contracts, "load_contracts", counted)
    payload = {"operation": "initialize", "arguments": arguments}
    with pytest.raises(ValueError, match="^execution.contract_revisions_changed$"):
        calculations.dispatch(payload)
    assert loads == []
    assert calculations._session_contracts.cache_info().currsize == 0
    arguments["revisions"] = execution_contracts.revisions()
    state = calculations.dispatch(payload)
    state = calculations.dispatch({"operation": "advance", "state": state})
    assert state["status"] == "running" and len(loads) == 1


def test_revision_changed_during_load_is_rejected_without_caching(monkeypatch, contract_directory):
    arguments = _arguments()
    original = execution_contracts.load_contracts
    loads = []

    def change_once():
        loads.append(True)
        contracts = original()
        if len(loads) == 1:
            _change_revision(contract_directory)
        return contracts

    monkeypatch.setattr(execution_contracts, "load_contracts", change_once)
    payload = {"operation": "initialize", "arguments": arguments}
    with pytest.raises(ValueError, match="^execution.contract_revisions_changed$"):
        calculations.dispatch(payload)
    assert len(loads) == 1
    assert calculations._session_contracts.cache_info().currsize == 0
    # A failed read must not make the old key a successful cache hit.
    with pytest.raises(ValueError, match="^execution.contract_revisions_changed$"):
        calculations.dispatch(payload)
    assert len(loads) == 1
    arguments["revisions"] = execution_contracts.revisions()
    state = calculations.dispatch(payload)
    state = calculations.dispatch({"operation": "advance", "state": state})
    assert state["status"] == "running" and len(loads) == 2


def test_failed_validation_does_not_populate_cache(monkeypatch):
    payload = {"operation": "initialize", "arguments": _arguments()}
    original = execution_contracts.load_contracts
    loads = []

    def fail_once():
        loads.append(True)
        if len(loads) == 1:
            raise ValueError("injected contract validation error")
        return original()

    monkeypatch.setattr(execution_contracts, "load_contracts", fail_once)
    with pytest.raises(ValueError, match="injected contract validation error"):
        calculations.dispatch(payload)
    state = calculations.dispatch(payload)
    state = calculations.dispatch({"operation": "advance", "state": state})
    assert state["status"] == "running"
    assert len(loads) == 2


def test_cached_contracts_preserve_dynamic_capability_fault_injection(monkeypatch):
    arguments = _arguments()
    original = execution_contracts.load_contracts
    loads = []

    def counted():
        loads.append(True)
        return original()

    monkeypatch.setattr(execution_contracts, "load_contracts", counted)
    state = calculations.dispatch({"operation": "initialize", "arguments": arguments})
    state = _finish(state, lambda value: failed_local_check({"operation": "advance", "state": value}))
    assert state["status"] == "math_failed"
    assert len(loads) == 1
    assert any(
        check["kind"] == "injected_failure" and check["passed"] is False
        for step in state["trajectory"]["steps"]
        for call in step["calls"]
        for check in call["postconditions"]
    )


@pytest.mark.parametrize("revision_format", ["execution", "pipeline"])
def test_new_spawn_session_revalidates_when_resuming_with_advance(revision_format):
    arguments = _arguments()
    if revision_format == "pipeline":
        arguments["revisions"] = runner.fingerprint()
    with JsonCalculationSession(counting_dispatch) as session:
        result, _ = session.run({"operation": "initialize", "arguments": arguments}, timeout_seconds=10)
        first_pid = result["pid"]
        assert first_pid != os.getpid() and result["loads"] == 1
        for _ in range(2):
            result, _ = session.run({"operation": "advance", "state": result["state"]}, timeout_seconds=10)
            assert result["pid"] == first_pid and result["loads"] == 1
    restored = json.loads(json.dumps(result["state"]))
    # Receipt replay can skip initialize; the first new worker operation is an advance.
    with JsonCalculationSession(counting_dispatch) as session:
        result, _ = session.run({"operation": "advance", "state": restored}, timeout_seconds=10)
        assert result["pid"] != first_pid and result["loads"] == 1
        result, _ = session.run({"operation": "advance", "state": result["state"]}, timeout_seconds=10)
        assert result["loads"] == 1 and result["state"]["status"] == "running"
