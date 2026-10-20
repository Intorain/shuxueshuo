"""Schedule step-interaction compilation beside, never inside, route mathematics.

Seeds and per-card states are already committed with the mathematical cards.
This scheduler only reads them, compiles decided groups in its own supervised
worker with its own leases and budget, and commits one terminal result per
group. Failures become read-only results with a reason; mathematics, its
budgets and its route status are never touched.
"""

import logging
import threading
from contextlib import ExitStack
from pathlib import Path
from uuid import uuid4

from . import bounded, calculations, interaction
from .budget import BudgetConflict
from .events import goal_unavailable
from .route_calculations import DurableCalculations, InteractionUnavailable

_LOG = logging.getLogger(__name__)
# Scheduling code, revisioned with the interaction side rather than mathematics.
ORCHESTRATION_FILES = (Path(__file__).resolve(),)
GROUP_SECONDS = 5.0
ROUTE_SECONDS = 30.0
FAILURE_LIMIT = 3
# Routes that can no longer append cards; anything else may still grow.
FINAL = frozenset({"verified", "capability_gap", "math_failed", "execution_error"})
UNAVAILABLE = frozenset({"capability_gap", "math_failed", "execution_error"})
LEASE_SUFFIX = "#interaction"


def _timeout_reason(exc):
    return {"timeout": "compile_timeout", "budget_unavailable": "budget_exhausted"}.get(exc.reason, "compile_error")


class InteractionScheduler:
    """One run's interaction work; call :meth:`step` directly or run it in a thread."""

    def __init__(self, store, *, dispatch=None, group_seconds=None, route_seconds=None,
                 hooks=None):
        self.store = store
        self.settings = store.interaction_settings()
        if self.settings is None:
            raise ValueError("interaction.disabled_run")
        self.dispatch = dispatch or calculations.dispatch
        budget = self.settings.get("budget")
        # Resuming a run must not replace its original allowance with today's
        # defaults (or the caller's new overrides).
        if budget is not None:
            self.group_seconds, self.route_seconds = budget["group_seconds"], budget["route_seconds"]
        else:
            self.group_seconds = GROUP_SECONDS if group_seconds is None else group_seconds
            self.route_seconds = ROUTE_SECONDS if route_seconds is None else route_seconds
        self.hooks = hooks or {}
        self.errors = []
        self._attempt_id = uuid4().hex
        self._calculators = {}
        self._skipped = set()
        self._busy = set()
        self._watermark = None
        self._changed = False
        self._wake = threading.Event()
        self._thread, self._stop, self._finishing = None, threading.Event(), threading.Event()

    # --- Lifecycle -------------------------------------------------------------------

    def close(self):
        for stack, _ in self._calculators.values():
            stack.close()
        self._calculators.clear()

    def start(self, *, poll_seconds=0.05):
        def loop():
            delay = min(1.0, poll_seconds)
            try:
                while not self._stop.is_set():
                    finishing = self._finishing.is_set()
                    committed = self.step()
                    if committed == 0 and finishing and not self._busy:
                        break
                    delay = min(1.0, poll_seconds) if committed or self._changed else min(1.0, delay * 2)
                    if committed == 0 or self._busy:
                        self._wake.wait(delay)
                        self._wake.clear()
            except Exception as exc:  # noqa: BLE001 -- a scheduler fault must not end the math run.
                _LOG.exception("Interaction scheduler stopped")
                self.errors.append({"route": None, "exception_type": type(exc).__name__, "message": str(exc)[:300]})
            finally:
                self.close()

        self._thread = threading.Thread(target=loop, name="interaction-scheduler", daemon=True)
        self._thread.start()
        return self

    def finish(self, timeout=None):
        """Drain decided work; return False if the timeout leaves a retry in progress."""
        self._finishing.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout)
        return self._thread is None or not self._thread.is_alive()

    def stop(self):
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join()

    # --- One scheduling pass ------------------------------------------------------------

    def step(self):
        """Commit every group decidable now; return how many results were committed."""
        watermark = self.store.commit_watermark()
        self._changed = watermark != self._watermark
        if not self._changed and not self._busy:
            return 0
        self._watermark = watermark
        self._busy.clear()
        routes = {}
        for row in self.store.interaction_states():
            key = (row["target_ref"], row["route_id"])
            if row["status"] == "pending" and key not in self._skipped:
                routes.setdefault(key, []).append({field: row[field] for field in ("step_id", "math_step_sha256")})
        committed = 0
        for (target, route), pending_steps in routes.items():
            try:
                # Read seeds and card states from one committed generation.
                # Retain the initial ids if a damaged checkpoint cannot be read.
                checkpoint, states = self.store.interaction_context(target, route)
                pending_steps = [{field: row[field] for field in ("step_id", "math_step_sha256")}
                                 for row in states if row["status"] == "pending"]
                progress = self._route(target, route, checkpoint, states)
                committed += progress
                if progress:
                    self.store.clear_interaction_failure(target, route, attempt_id=self._attempt_id)
            except Exception as exc:  # noqa: BLE001 -- isolate one route's scheduler fault.
                if isinstance(exc, BudgetConflict) and str(exc) == "budget.lease_busy":
                    # A live owner can finish or release this lease later. Do
                    # not turn that temporary contention into a skipped route.
                    self._busy.add((target, route))
                    continue
                _LOG.exception("Interaction scheduling failed for %s %s", target, route)
                self._skipped.add((target, route))
                self.errors.append({"route": [target, route], "exception_type": type(exc).__name__,
                                    "message": str(exc)[:300]})
                try:
                    failure = self.store.record_interaction_failure(
                        target, route, self.errors[-1], pending_steps=pending_steps,
                        attempt_id=self._attempt_id, limit=FAILURE_LIMIT)
                    committed += failure["resolved_count"]
                except Exception as storage_exc:  # noqa: BLE001 -- a broken store cannot record a terminal decision.
                    _LOG.exception("Could not persist interaction scheduling failure for %s %s", target, route)
                    self.errors.append({"route": [target, route], "phase": "failure_recording",
                                        "exception_type": type(storage_exc).__name__, "message": str(storage_exc)[:300]})
        if self._busy:
            # All calls are synchronous and their receipts are durable. Drop
            # idle leases before waiting so concurrent schedulers cannot each
            # hold one route while waiting for the other's route.
            self.close()
        return committed

    def _route(self, target, route, checkpoint, rows):
        states = {row["step_id"]: row for row in rows}
        seeds = self._seeds(checkpoint, states)
        pending = [seed for seed in seeds if states[seed["step_id"]]["status"] == "pending"]
        reason = self._blocked(target, checkpoint)
        if reason is not None:
            return sum(self._commit(interaction.readonly_chunk([seed], self.settings["revision"], reason),
                                    [{"result": "readonly", "reason": reason}]) for seed in pending)
        registry, revision = self.settings["registry"], self.settings["revision"]
        groups, _ = interaction.plan_groups(seeds, registry, final=checkpoint["status"] in FINAL)
        position = {seed["step_id"]: index for index, seed in enumerate(seeds)}
        committed = 0
        for group in groups:
            open_members = [seed for seed in group if states[seed["step_id"]]["status"] == "pending"]
            if not open_members:
                continue
            # A group whose other member is already resolved compiles its open card alone.
            for members in ([group] if len(open_members) == len(group) else [[seed] for seed in open_members]):
                context = interaction.repeat_context(seeds, position[members[0]["step_id"]])
                committed += self._compile(target, route, members, context, registry, revision)
        return committed

    def _seeds(self, checkpoint, states):
        """Do not silently strand pending cards whose frozen input is damaged."""
        values = checkpoint["driver_state"].get("interaction_seeds", [])
        if not isinstance(values, list):
            raise TypeError("interaction.scheduler_seed_invalid")
        indexed = {}
        for seed in values:
            if not isinstance(seed, dict) or not isinstance(seed.get("step_id"), str):
                raise TypeError("interaction.scheduler_seed_invalid")
            identifier = seed["step_id"]
            if identifier not in states:
                continue
            if identifier in indexed:
                raise ValueError("interaction.scheduler_seed_duplicate")
            expected = {**{key: self.store.identity[key] for key in ("run_id", "lesson_version")},
                        **{key: states[identifier][key] for key in (
                            "target_ref", "route_id", "step_id", "ordinal", "math_step_sha256")}}
            if any(seed.get(key) != value for key, value in expected.items()):
                raise ValueError("interaction.scheduler_seed_mismatch")
            indexed[identifier] = seed
        result = []
        for identifier, state in states.items():
            if identifier not in indexed:
                if state["status"] == "pending":
                    raise ValueError("interaction.scheduler_seed_missing")
                # A card already made read-only without a seed still separates
                # its neighbours; a merge prefix need not wait past that card.
                result.append({**state, "status": "unavailable", "template": None, "display_unit": None})
            else:
                result.append(indexed[identifier])
        return result

    def _blocked(self, target, checkpoint):
        if self.settings["engine_revision"] != interaction.engine_revision():
            return "engine_unavailable"
        if checkpoint["status"] in UNAVAILABLE:
            return "route_unavailable"
        if goal_unavailable(self.store.goal(target)):
            return "route_unavailable"
        return None

    def _calculator(self, target, route):
        key = (target, route)
        if key not in self._calculators:
            stack = ExitStack()
            calculator = DurableCalculations(
                self.store, target, route + LEASE_SUFFIX, limits={"interaction": self.route_seconds},
                dispatch=self.dispatch, hooks={"calculation_returned": self.hooks.get("interaction_calculation_returned")})
            if "budget" not in self.settings:
                # Legacy runs froze only their per-route ledger limit. Reuse
                # it rather than configuring a different limit on recovery.
                try:
                    saved = calculator.ledger.summary(target, route + LEASE_SUFFIX, "interaction")
                except ValueError as exc:
                    if str(exc) != "budget.not_configured":
                        raise
                else:
                    calculator.limits["interaction"] = saved["limit_seconds"]
            calculator = stack.enter_context(calculator)
            self._calculators[key] = (stack, calculator)
        return self._calculators[key][1]

    def _call(self, target, route, operation, payload):
        calculator = self._calculator(target, route)
        try:
            return calculator.call(operation, payload, bucket="interaction", timeout_seconds=self.group_seconds)
        except (InteractionUnavailable, bounded.CalculationWorkerError):
            # A timed-out or failed worker is gone; the next group starts a new one.
            self._calculators.pop((target, route))[0].close()
            raise

    def _compile(self, target, route, seeds, context, registry, revision):
        if seeds[0].get("status") != "ready":
            reason = seeds[0].get("reason", "seed_missing")
            return self._commit(interaction.readonly_chunk(seeds, revision, reason),
                                [{"result": "readonly", "reason": reason}])
        if len(seeds) == 1 and interaction.select_rule(registry, seeds) is None:
            # Decided from the frozen rules alone: no worker needed.
            return self._commit(interaction.readonly_chunk(seeds, revision, "no_rule"),
                                [{"result": "readonly", "reason": "no_rule"}])
        identifier = interaction.interaction_identity(seeds, revision)
        payload = {"operation": "interaction", "seeds": seeds, "registry": registry,
                   "repeat_context": context, "revision": revision}
        try:
            result = self._call(target, route, f"interaction:{identifier}", payload)
            chunk, diagnostics = result["chunk"], result["diagnostics"]
        except InteractionUnavailable as exc:
            reason = _timeout_reason(exc)
            chunk, diagnostics = interaction.readonly_chunk(seeds, revision, reason), [{"result": "readonly",
                                                                                         "reason": reason}]
        except bounded.CalculationWorkerError as exc:
            chunk = interaction.readonly_chunk(seeds, revision, "compile_error")
            diagnostics = [{"result": "compile_error", "exception_type": exc.exception_type,
                            "message": str(exc)[:300]}]
        if self.hooks.get("interaction_returned"):
            self.hooks["interaction_returned"](chunk, self.store)
        return self._commit(chunk, diagnostics)

    def _commit(self, chunk, diagnostics):
        result = self.store.commit_interaction(chunk, diagnostics=diagnostics)
        return 1 if result.get("committed") else 0


def run_pending(store, **options):
    """Synchronously resolve whatever is decidable now (tests and offline tools)."""
    scheduler = InteractionScheduler(store, **options)
    try:
        total = 0
        while True:
            count = scheduler.step()
            total += count
            if count == 0:
                return total, scheduler.errors
    finally:
        scheduler.close()
