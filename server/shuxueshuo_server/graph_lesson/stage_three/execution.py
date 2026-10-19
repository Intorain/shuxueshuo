"""Route orchestration: atomic progress, independent verification and handoff.

The driver interprets methods; this layer owns lifecycle and finalization. It
never selects mathematical operations by question identifier or source formula.
"""

import json
import traceback
from copy import deepcopy

from jsonschema import Draft202012Validator

from . import driver, verification
from .checkpoint import export_json, make_checkpoint
from .contracts import ROOT
from .handoff import complete_route
from .route_calculations import RouteCalculations

TERMINAL = {"verified", "capability_gap", "math_failed", "execution_error"}


def _event(kind, state, payload):
    return {"type": kind, "target_ref": state["target_ref"], "route_id": state["route_id"], "payload": payload}


def _checkpoint(store, state, *, phase="method", status="running"):
    return make_checkpoint(
        store.identity, state["target_ref"], state["route_id"], driver_state=state,
        status=status, phase=phase, next_instance=len(state["fragments"]),
        compute_seconds={"solve": state["compute_seconds"], "verification": state.get("verification_seconds", 0)},
    )


def _commit(store, state, suffix, *, events=(), phase="method", status="running", hooks=None):
    checkpoint = _checkpoint(store, state, phase=phase, status=status)
    commit_id = f"{state['target_ref']}:{state['route_id']}:{suffix}"
    hooks = hooks or {}
    # Hooks are observer/fault-injection seams, outside the measured arithmetic.
    def callback(name):
        function = hooks.get(name)
        return (lambda: function(state, store)) if function else None

    store.commit_route(checkpoint, commit_id=commit_id, math_steps=state["fragments"], events=events,
                       before_commit=callback("before_commit"), after_commit=callback("after_commit"))
    store.export()
    if hooks.get("committed"):
        hooks["committed"](state, store)


def _artifact(state, context, folder):
    refs = []
    for step in state["fragments"]:
        path = folder / "math-steps" / state["route_id"] / (step["step_id"] + ".json")
        export_json(path, step)
        refs.append({"step_id": step["step_id"], "math_step_sha256": step["math_step_sha256"],
                     "source_refs": step["source_refs"], "file": str(path.relative_to(folder.parents[1]))})
    resolved_context = deepcopy(context)
    applied = next((item for item in state.get("finalization", [])
                    if item.get("capability") == "apply_visible_constraints"), None)
    if applied:
        for entry in resolved_context["entries"]:
            evidence = [row for row in applied["processing"] if row["source_ref"] == entry["source_ref"]]
            if evidence:
                entry["processing"] = {"status": "processed", "evidence": evidence}
        pending = [entry["source_ref"] for entry in resolved_context["entries"]
                   if entry["processing"]["status"] == "pending"]
        resolved_context["processing"] = {"status": "complete" if not pending else "pending",
                                           "unprocessed_source_refs": pending}
    route = {
        "contract": "graph-stage-three-route/v1",
        **{key: state[key] for key in ("run_id", "lesson_version", "target_ref", "route_id", "branch", "method", "revisions")},
        "status": state["status"], "steps": state["trajectory"]["steps"], "math_steps": refs,
        "constraint_context": resolved_context, "finalization": state.get("finalization", []),
        "result": state.get("verified_result"), "diagnostics": state.get("diagnostics", []),
        "verification_timing": {
            "budget_seconds": state.get("verification_budget_seconds"),
            "elapsed_seconds": state.get("verification_seconds", 0),
            "operations": state.get("verification_timing", []),
        },
        "solve_timing": {
            "budget_seconds": state.get("solve_budget_seconds"),
            "elapsed_seconds": state.get("compute_seconds", 0),
            "operations": state.get("solve_timing", []),
        },
        "budget_accounting": state.get("budget_accounting", {}),
    }
    route.update({key: state["trajectory"][key] for key in ("gap", "error") if key in state["trajectory"]})
    schema = json.loads((ROOT / "internal/schemas/graph-stage-three-route-v1.schema.json").read_text())
    Draft202012Validator(schema).validate(route)
    return route


def _mark_failure(state, exc):
    if isinstance(exc, verification.ContextMismatch):
        state["status"] = "math_failed"
        diagnostic = {"code": "constraint_context_mismatch", "message": str(exc)}
    elif isinstance(exc, verification.VerificationGap):
        state["status"] = "capability_gap"
        diagnostic = {"code": str(exc)}
    else:
        state["status"] = "execution_error"
        diagnostic = {"code": "execution.route_error", "message": str(exc),
                      "exception_type": type(exc).__name__, "traceback": traceback.format_exc()}
    state.setdefault("diagnostics", []).append(diagnostic)


def prepare_route(goal, branch, store, calculator):
    """Bound admission and initial bindings before publishing the D4 plan."""
    arguments = {
        "features": goal["features"], "context": goal["constraint_context"], "method": branch["target"],
        "route_id": branch["route_id"], "branch": branch["branch"], "target_ref": goal["target_ref"],
        "run_id": store.identity["run_id"], "lesson_version": store.identity["lesson_version"],
        "revisions": store.identity["revisions"], "solve_budget_seconds": calculator.limits["solve"],
    }
    state = driver.empty_state(**arguments)
    try:
        state = calculator.call("initialize", {"operation": "initialize", "arguments": arguments})
    except Exception as exc:  # noqa: BLE001 -- isolate admission failures without hiding their diagnostics.
        _mark_failure(state, exc)
    return calculator.sync_state(state)


def execute_route(candidate, goal, branch, folder, store, *, previous=(), hooks=None,
                  solve_budget_seconds=10, verification_budget_seconds=20, calculator=None, prepared=None):
    """Resume at a durable boundary, reusing receipts for completed computations."""
    ref, route_id = goal["target_ref"], branch["route_id"]
    if calculator is None:
        with RouteCalculations(store, ref, route_id, solve_budget_seconds=solve_budget_seconds,
                               verification_budget_seconds=verification_budget_seconds, hooks=hooks) as owned:
            return execute_route(candidate, goal, branch, folder, store, previous=previous, hooks=hooks,
                                 solve_budget_seconds=solve_budget_seconds,
                                 verification_budget_seconds=verification_budget_seconds, calculator=owned,
                                 prepared=prepare_route(goal, branch, store, owned))
    checkpoint = store.checkpoint(ref, route_id)
    if checkpoint:
        state = checkpoint["driver_state"]
    else:
        state = deepcopy(prepared)
        _commit(store, state, "start", events=[_event("lesson.route_status", state, {"status": "running"})], hooks=hooks)
    calculator.sync_state(state)
    if state["status"] not in TERMINAL:
        try:
            while state["status"] == "running":
                index = state.get("commit_index", 0) + 1
                state = calculator.call(f"advance:{index}", {"operation": "advance", "state": state})
                state["commit_index"] = index
                calculator.sync_state(state)
                _commit(store, state, f"operation-{index}",
                        events=[_event("solver.step_completed", state, {
                            "operation": index, "status": state["status"],
                            "trajectory": state["trajectory"]["steps"][-1:]})], hooks=hooks)
            if state["status"] == "method_complete":
                finalization = state.setdefault("finalization", [])
                common = {"candidate": candidate, "target_ref": ref, "context": goal["constraint_context"]}
                if not state.get("constraints_applied"):
                    result = calculator.call("apply_visible_constraints", {
                        **common, "operation": "constraints", "state": state,
                    }, bucket="verification")
                    state["feasible_set_exact"] = result["feasible_set_exact"]
                    state["constraints_applied"] = True
                    finalization.append({"capability": "apply_visible_constraints", "processing": result["processing"],
                                         "feasible_set": result["feasible_set"]})
                    calculator.sync_state(state)
                    _commit(store, state, "constraints", phase="verification", hooks=hooks)
                common["feasible_set_exact"] = state["feasible_set_exact"]
                if "verification" not in state:
                    if hooks and hooks.get("before_verification"):
                        hooks["before_verification"](state, store)
                    state["verification"] = calculator.call("independent_verification", {
                        **common, "operation": "verify",
                    }, bucket="verification")
                    finalization.append({"capability": "independent_verification", **state["verification"]})
                    calculator.sync_state(state)
                    _commit(store, state, "verification", phase="verification", hooks=hooks)
                if state["verification"]["status"] != "verified":
                    state["status"] = state["verification"]["status"]
                    state.setdefault("diagnostics", []).extend(state["verification"].get("diagnostics", []))
                else:
                    if "endpoint_evidence" not in state:
                        result = calculator.call("endpoint_check", {
                            **common, "operation": "endpoints", "state": state,
                        }, bucket="verification")
                        state = result["state"]
                        state["endpoint_evidence"] = result["evidence"]
                        calculator.sync_state(state)
                        _commit(store, state, "endpoints", phase="finalization", hooks=hooks)
                    if state["endpoint_evidence"]["status"] != "passed":
                        state["status"] = "math_failed"
                        state.setdefault("diagnostics", []).append({"code": "verification.endpoint_failed"})
                    else:
                        result = calculator.call("goal_finalize_and_consistency", {
                            "operation": "finish", "goal": goal["goal"],
                            "feasible_set_exact": state["feasible_set_exact"], "previous": list(previous),
                        }, bucket="verification")
                        state["verified_result"] = {"feasible_set": result["feasible_set"], "answer": result["answer"]}
                        state["finalization"].append({"capability": "finalize_goal", "answer": result["answer"]})
                        state["status"] = "verified"
                        state["consistency"] = result["consistency"]
        except Exception as exc:  # noqa: BLE001 -- retain route evidence, never turn bugs into unknown.
            _mark_failure(state, exc)
        finally:
            calculator.sync_state(state)
    # Mathematical receipts and publication commits have independent durability.
    # A crash between them reuses the receipt and completes this boundary once.
    if store.checkpoint(ref, route_id)["status"] not in TERMINAL:
        route = _artifact(state, goal["constraint_context"], folder)
        if state["status"] == "verified":
            complete_route(store, _checkpoint(store, state, phase="complete", status="verified"), route=route,
                           verification=state["verification"], feasible_set=state["verified_result"]["feasible_set"],
                           answer=state["verified_result"]["answer"], commit_id=f"{ref}:{route_id}:complete",
                           consistency=state["consistency"])
        else:
            _commit(store, state, "terminal", status=state["status"], phase="complete",
                    events=[_event("lesson.route_status", state, {"status": state["status"], "diagnostics": state["diagnostics"]})],
                    hooks=hooks)
    route = _artifact(state, goal["constraint_context"], folder)
    path = folder / "routes" / (route_id + ".json")
    export_json(path, route)
    snapshot = store.export()
    for handoff in snapshot["handoffs"]:
        if handoff["target_ref"] == ref:
            export_json(folder / "handoff" / (handoff["route_id"] + ".json"), handoff)
    return {
        "route_id": route_id, "branch": branch["branch"], "method": branch["target"],
        "status": state["status"], "trajectory": str(path.relative_to(folder.parents[1])),
        "answer": state.get("verified_result", {}).get("answer"),
        "feasible_set": state.get("verified_result", {}).get("feasible_set"),
        "feasible_set_exact": deepcopy(state.get("feasible_set_exact")),
        "consistency": state.get("consistency"), "diagnostics": state.get("diagnostics", []),
    }
