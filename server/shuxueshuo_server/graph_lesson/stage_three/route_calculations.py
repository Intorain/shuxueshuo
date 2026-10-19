"""Route-owned leases and durable, reusable isolated calculation receipts."""

from contextlib import ExitStack
from copy import deepcopy
from time import monotonic, sleep

from shuxueshuo_server.problem_understanding.identity import revision

from . import bounded, calculations, verification
from .budget import BudgetExhausted, BudgetLedger, BudgetPending

_ACCOUNTING = {"compute_seconds", "verification_seconds", "solve_timing", "verification_timing", "budget_accounting"}


def _input_hash(payload):
    stable = deepcopy(payload)
    if "state" in stable:
        for key in _ACCOUNTING:
            stable["state"].pop(key, None)
    return revision(stable)


def _raise_receipt(receipt, bucket, operation):
    if receipt["status"] == "returned":
        return deepcopy(receipt["result"])
    if receipt["status"] == "timeout":
        if bucket == "verification":
            raise verification.VerificationGap("verification_incomplete:timeout:" + operation)
        raise TimeoutError("execution.solve_timeout:" + operation)
    error = receipt.get("error", {})
    if error.get("exception_module") == verification.__name__:
        if error.get("exception_type") == "ContextMismatch":
            raise verification.ContextMismatch(error["message"])
        if error.get("exception_type") == "VerificationGap":
            raise verification.VerificationGap(error["message"])
    raise bounded.CalculationWorkerError(
        exception_type=error.get("exception_type", "CalculationInterrupted"),
        exception_module=error.get("exception_module", __name__),
        message=error.get("message", receipt["status"]), traceback=error.get("traceback", ""),
        phase=error.get("phase", "calculation"), elapsed_seconds=receipt["elapsed_seconds"],
    )


class RouteCalculations:
    def __init__(self, store, target, route, *, solve_budget_seconds, verification_budget_seconds, hooks=None):
        self.store, self.target, self.route = store, target, route
        self.ledger = BudgetLedger(store)
        self.limits = {"solve": solve_budget_seconds, "verification": verification_budget_seconds}
        self.hooks = hooks or {}
        self._stack = ExitStack()

    def __enter__(self):
        try:
            self.owner = self._stack.enter_context(self.ledger.route_lease(self.target, self.route))
            for bucket, limit in self.limits.items():
                self.ledger.configure(self.target, self.route, bucket, limit)
            # A killed parent's supervisor may still be reaping its child and
            # atomically writing the receipt. Wait only for that bounded cleanup.
            deadline = monotonic() + 1.5
            while True:
                recovered = self.ledger.recover(self.target, self.route, self.owner)
                if not any(row["status"] == "interrupted_unknown" for row in recovered["recovered"]):
                    break
                if monotonic() >= deadline:
                    break
                sleep(0.02)
            self.session = self._stack.enter_context(bounded.JsonCalculationSession(
                self.hooks.get("calculation_dispatch", calculations.dispatch),
            ))
            return self
        except BaseException:
            self._stack.close()
            raise

    def __exit__(self, *args):
        return self._stack.__exit__(*args)

    def call(self, operation, payload, *, bucket="solve"):
        try:
            attempt = self.ledger.begin(self.target, self.route, bucket, operation, _input_hash(payload), self.owner)
        except (BudgetExhausted, BudgetPending) as exc:
            if bucket == "verification":
                raise verification.VerificationGap("verification_incomplete:budget_unavailable:" + operation) from exc
            raise TimeoutError("execution.solve_budget_unavailable:" + operation) from exc
        if attempt["reused"]:
            return _raise_receipt(attempt["receipt"], bucket, operation)
        failure = None
        try:
            self.session.run(payload, timeout_seconds=attempt["remaining_seconds"],
                             receipt_path=attempt["receipt_path"], attempt_id=attempt["attempt_id"])
        except (bounded.CalculationTimeout, bounded.CalculationWorkerError) as exc:
            # The supervisor records the same terminal result before responding.
            # Never reconstruct a different outcome from a parent-side timer.
            failure = exc
        if self.hooks.get("calculation_returned"):
            self.hooks["calculation_returned"](attempt, self.store)
        try:
            settled = self.ledger.finish(attempt["attempt_id"], self.owner)
        except BudgetPending as exc:
            if isinstance(failure, bounded.CalculationWorkerError):
                # Storage/protocol failures are programming/infrastructure
                # errors, not an unproved mathematical statement.
                raise failure from exc
            if bucket == "verification":
                raise verification.VerificationGap("verification_incomplete:receipt_missing:" + operation) from exc
            raise TimeoutError("execution.solve_receipt_missing:" + operation) from exc
        return _raise_receipt(settled["receipt"], bucket, operation)

    def sync_state(self, state):
        state["budget_accounting"] = {}
        for bucket, seconds_key, timing_key in (("solve", "compute_seconds", "solve_timing"),
                                                ("verification", "verification_seconds", "verification_timing")):
            summary = self.ledger.summary(self.target, self.route, bucket)
            state["budget_accounting"][bucket] = {key: value for key, value in summary.items() if key != "operations"}
            # Unknown interrupted work remains an explicit reservation, never
            # misreported as measured time. The ledger enforces actual+reserved.
            state[seconds_key] = summary["actual_seconds"]
            cumulative, timing = summary["initial_seconds"], []
            for row in summary["operations"]:
                cumulative += row["elapsed_seconds"]
                record = {"operation": row["operation_key"], "attempt_id": row["attempt_id"],
                          "timeout_seconds": row["allowance_seconds"], "status": row["outcome"] or row["status"],
                          "elapsed_seconds": row["elapsed_seconds"], "cumulative_seconds": cumulative,
                          "reserved_upper_seconds": row["reserved_upper_seconds"]}
                if row.get("error"):
                    record.update({key: value for key, value in row["error"].items() if key != "ok"})
                timing.append(record)
            state[timing_key] = timing
        state.update(solve_budget_seconds=self.limits["solve"], verification_budget_seconds=self.limits["verification"])
        return state
