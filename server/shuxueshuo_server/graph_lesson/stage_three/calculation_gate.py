"""Serialize one run's worker operations before their independent budgets start.

This is a process-local scheduler, shared by every EventStore for the same run
directory. Product entry points separately hold the run's cross-process lock.
It does not isolate different runs or reserve CPU from unrelated processes.
"""

import threading
from contextlib import contextmanager
from pathlib import Path
from weakref import WeakValueDictionary

_GATES = WeakValueDictionary()
_REGISTRY_LOCK = threading.Lock()


class CalculationGate:
    """Math waiters precede new interaction work; running calls are nonpreemptive."""

    def __init__(self):
        self._condition = threading.Condition()
        self._owner = None
        self._waiting = {"math": 0, "interaction": 0}

    @contextmanager
    def operation(self, bucket):
        role = "interaction" if bucket == "interaction" else "math"
        owner = threading.get_ident()
        with self._condition:
            # Fault-injection hooks run inside the operation. Starting another
            # calculation in that same hook is unsupported, never a silent deadlock.
            if self._owner == owner:
                raise RuntimeError("calculation_gate.reentrant_operation")
            self._waiting[role] += 1
            self._condition.notify_all()
            try:
                self._condition.wait_for(lambda: self._owner is None and (
                    role == "math" or self._waiting["math"] == 0))
                self._owner = owner
            finally:
                self._waiting[role] -= 1
                self._condition.notify_all()
        try:
            yield
        finally:
            with self._condition:
                self._owner = None
                self._condition.notify_all()


def for_directory(directory):
    """Hold the returned gate for the worker session, including idle boundaries."""
    key = str(Path(directory).resolve())
    with _REGISTRY_LOCK:
        gate = _GATES.get(key)
        if gate is None:
            gate = CalculationGate()
            _GATES[key] = gate
        return gate
