"""JSON-only, supervised admission and per-target context/method selection."""

from pathlib import Path
from uuid import uuid4

from .bounded import CalculationTimeout, CalculationWorkerError, JsonCalculationSession
from .route_calculations import DurableCalculations

ADMISSION_BUDGET_SECONDS = 10
SELECTION_BUDGET_SECONDS = 10
PREPARATION_ROUTE = "__preparation__"


def dispatch(payload):
    """All notation compilation and SymPy preconditions execute in this worker."""
    operation = payload["operation"]
    if operation == "admission":
        from .contracts import load_input

        return load_input(payload["source"], reference_base=payload["reference_base"])
    if operation == "build_context":
        from .context import build_context

        return build_context(payload["candidate"], payload["target_ref"])
    if operation == "evaluate_goal":
        from .selection import evaluate_goal

        return evaluate_goal(payload["candidate"], payload["target_ref"], payload["features"], payload["primary"])
    raise ValueError("preparation.unknown_operation:" + operation)


def error_detail(exc):
    """Keep the actual child exception and traceback, rather than its wrapper."""
    if isinstance(exc, CalculationWorkerError):
        return {"exception_type": exc.exception_type, "exception_module": exc.exception_module,
                "message": str(exc), "traceback": exc.traceback, "worker_phase": exc.phase}
    import traceback

    return {"exception_type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc()}


def admit(source, *, output, reference_base=None, budget_seconds=ADMISSION_BUDGET_SECONDS, hooks=None):
    hooks = hooks or {}
    attempt = uuid4().hex
    receipt = Path(output) / "preparation" / ("admission-" + attempt + ".json")
    receipt.parent.mkdir(exist_ok=True)
    payload = {"operation": "admission", "source": str(Path(source).resolve()),
               "reference_base": str(Path(reference_base).resolve()) if reference_base is not None else None,
               "hook_data": hooks.get("preparation_data", {})}
    timing = {"operation": "admission", "budget_seconds": budget_seconds,
              "receipt": str(receipt.relative_to(output))}
    try:
        with JsonCalculationSession(hooks.get("preparation_dispatch", dispatch)) as session:
            loaded, elapsed = session.run(payload, timeout_seconds=budget_seconds,
                                          receipt_path=str(receipt), attempt_id=attempt)
        timing.update(status="returned", elapsed_seconds=elapsed)
    except (CalculationTimeout, CalculationWorkerError) as exc:
        timeout = isinstance(exc, CalculationTimeout)
        timing.update(status="timeout" if timeout else "worker_error", elapsed_seconds=exc.elapsed_seconds)
        diagnostic = {"code": "input.admission_timeout" if timeout else "input.admission_error",
                      "path": "/", "phase": "admission", **error_detail(exc)}
        loaded = {"ok": False, "diagnostics": [diagnostic], "stage_two": None, "stage_one": None,
                  "source": payload["source"], "stage_one_source": None, "admission": None}
    return loaded, timing


class TargetPreparation(DurableCalculations):
    def __init__(self, store, target, *, budget_seconds=SELECTION_BUDGET_SECONDS, hooks=None):
        hooks = hooks or {}
        super().__init__(store, target, PREPARATION_ROUTE, limits={"selection": budget_seconds},
                         dispatch=hooks.get("preparation_dispatch", dispatch), hooks={})
        # Revalidation on resume is deliberate. Give this invocation its own
        # operation keys, while charging the same persistent per-target budget.
        self.invocation = uuid4().hex
        self.hook_data = hooks.get("preparation_data", {})

    def prepare(self, operation, **payload):
        return self.call(self.invocation + ":" + operation,
                         {"operation": operation, **payload, "hook_data": self.hook_data}, bucket="selection")

    def summary(self):
        return self.ledger.summary(self.target, self.route, "selection")
