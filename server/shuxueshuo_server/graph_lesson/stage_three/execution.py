"""Route orchestration: atomic progress, independent verification and handoff.

The driver interprets methods; this layer owns lifecycle and finalization. It
never selects mathematical operations by question identifier or source formula.
"""

import json
import traceback
from copy import deepcopy
from time import perf_counter

import sympy as sp
from jsonschema import Draft202012Validator

from . import bounded, driver, verification
from .checkpoint import export_json, make_checkpoint
from .contracts import ROOT
from .goals import finalize_goal
from .handoff import complete_route
from .trajectory import decode_value, encode_value

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
    }
    route.update({key: state["trajectory"][key] for key in ("gap", "error") if key in state["trajectory"]})
    schema = json.loads((ROOT / "internal/schemas/graph-stage-three-route-v1.schema.json").read_text())
    Draft202012Validator(schema).validate(route)
    return route


def _consistency(candidate_set, answer, previous):
    for route in previous:
        if route["status"] != "verified":
            continue
        earlier = decode_value(route["feasible_set_exact"])
        delta = sp.SymmetricDifference(candidate_set, earlier)
        if delta == sp.S.EmptySet:
            if answer != route["answer"]:
                return "conflict"
        elif delta.is_empty is False:
            return "conflict"
        else:
            return "unknown"
    return "consistent"


def _finish_answer(goal, feasible_set, previous, consistency_function):
    """Keep symbolic goal closure and cross-route comparison inside the deadline."""
    answer = finalize_goal(goal, feasible_set)
    return answer, consistency_function(feasible_set, answer, previous)


def _run_verification(state, operation, function, *args):
    """Share one cumulative wall-time allowance across finalization operations.

    Each operation gets only the unspent budget. Spawn and result transfer count;
    persistence, UI waits and observer hooks do not. The caller commits usage
    with each result or terminal failure, so resume preserves spent allowance.
    """
    consumed = state.get("verification_seconds", 0)
    remaining = state["verification_budget_seconds"] - consumed
    elapsed = 0.0
    timing = {"operation": operation, "timeout_seconds": max(0, remaining), "status": "interrupted"}
    started = perf_counter()
    try:
        if remaining <= 0:
            timing["status"] = "timeout"
            raise verification.VerificationGap("verification_incomplete:budget_exhausted:" + operation)
        value, elapsed = bounded.run_bounded(function, *args, timeout_seconds=remaining)
        timing["status"] = "returned"
        return value
    except bounded.CalculationTimeout as exc:
        elapsed = exc.elapsed_seconds
        timing.update(status="timeout", phase=exc.phase)
        raise verification.VerificationGap("verification_incomplete:timeout:" + operation) from exc
    except bounded.CalculationWorkerError as exc:
        elapsed = exc.elapsed_seconds
        timing.update(status="worker_error", exception_type=exc.exception_type,
                      exception_module=exc.exception_module, message=exc.message, traceback=exc.traceback)
        if exc.exception_module == verification.__name__:
            if exc.exception_type == "ContextMismatch":
                raise verification.ContextMismatch(exc.message) from exc
            if exc.exception_type == "VerificationGap":
                raise verification.VerificationGap(exc.message) from exc
        raise
    finally:
        if timing["status"] == "interrupted":
            elapsed = perf_counter() - started
        state["verification_seconds"] = consumed + elapsed
        timing.update(elapsed_seconds=elapsed, cumulative_seconds=state["verification_seconds"])
        state.setdefault("verification_timing", []).append(timing)


def execute_route(candidate, goal, branch, folder, store, *, previous=(), hooks=None,
                  solve_budget_seconds=10, verification_budget_seconds=20):
    """Resume a route at its last durable boundary and return its summary."""
    ref, route_id = goal["target_ref"], branch["route_id"]
    checkpoint = store.checkpoint(ref, route_id)
    if checkpoint:
        state = checkpoint["driver_state"]
    else:
        state = driver.create_state(
            features=goal["features"], context=goal["constraint_context"], method=branch["target"],
            route_id=route_id, branch=branch["branch"], target_ref=ref,
            run_id=store.identity["run_id"], lesson_version=store.identity["lesson_version"],
            revisions=store.identity["revisions"],
        )
        state["solve_budget_seconds"] = solve_budget_seconds
        state["verification_budget_seconds"] = verification_budget_seconds
        _commit(store, state, "start", events=[_event("lesson.route_status", state, {"status": "running"})], hooks=hooks)
    state.setdefault("verification_budget_seconds", verification_budget_seconds)
    if state["status"] not in TERMINAL:
        try:
            while state["status"] == "running":
                state = driver.advance(state)
                state["commit_index"] = state.get("commit_index", 0) + 1
                if state["compute_seconds"] > solve_budget_seconds:
                    state["status"] = "execution_error"
                    state.setdefault("diagnostics", []).append({"code": "execution.solve_timeout"})
                _commit(store, state, f"operation-{state['commit_index']}",
                        events=[_event("solver.step_completed", state, {
                            "operation": state["commit_index"], "status": state["status"],
                            "trajectory": state["trajectory"]["steps"][-1:]})], hooks=hooks)
            if state["status"] == "method_complete":
                # Each finalization boundary is persisted as well; resuming a
                # later boundary never recomputes already committed arithmetic.
                finalization = state.setdefault("finalization", [])
                if not state.get("constraints_applied"):
                    candidate_set = driver.export_values(state)["feasible_set"]
                    feasible, processing = _run_verification(
                        state, "apply_visible_constraints", verification.apply_visible_constraints,
                        candidate, ref, goal["constraint_context"], candidate_set,
                    )
                    state["feasible_set_exact"] = encode_value(feasible)
                    state["constraints_applied"] = True
                    finalization.append({"capability": "apply_visible_constraints", "processing": processing,
                                         "feasible_set": verification.math_value(feasible)})
                    _commit(store, state, "constraints", phase="verification", hooks=hooks)
                feasible = decode_value(state["feasible_set_exact"])
                if "verification" not in state:
                    if hooks and hooks.get("before_verification"):
                        hooks["before_verification"](state, store)
                    state["verification"] = _run_verification(
                        state, "independent_verification", verification.verify,
                        candidate, ref, goal["constraint_context"], feasible,
                    )
                    finalization.append({"capability": "independent_verification", **state["verification"]})
                    _commit(store, state, "verification", phase="verification", hooks=hooks)
                if state["verification"]["status"] != "verified":
                    state["status"] = state["verification"]["status"]
                    state.setdefault("diagnostics", []).extend(state["verification"].get("diagnostics", []))
                else:
                    if "endpoint_evidence" not in state:
                        evidence = _run_verification(state, "endpoint_check", verification.endpoint_check,
                                                     candidate, ref, feasible)
                        state = driver.append_endpoint(state, feasible, evidence)
                        state["endpoint_evidence"] = evidence
                        _commit(store, state, "endpoints", phase="finalization", hooks=hooks)
                    answer, consistency = _run_verification(
                        state, "goal_finalize_and_consistency", _finish_answer,
                        goal["goal"], feasible, previous, _consistency,
                    )
                    state["verified_result"] = {"feasible_set": verification.math_value(feasible), "answer": answer}
                    state["finalization"].append({"capability": "finalize_goal", "answer": answer})
                    state["status"] = "verified"
                    state["consistency"] = consistency
        except verification.ContextMismatch as exc:
            state["status"] = "math_failed"
            state.setdefault("diagnostics", []).append({"code": "constraint_context_mismatch", "message": str(exc)})
        except verification.VerificationGap as exc:
            state["status"] = "capability_gap"
            state.setdefault("diagnostics", []).append({"code": str(exc)})
        except Exception as exc:  # noqa: BLE001 — retain route evidence at the orchestration boundary
            state["status"] = "execution_error"
            state.setdefault("diagnostics", []).append({"code": "execution.route_error", "message": str(exc),
                "exception_type": type(exc).__name__, "traceback": traceback.format_exc()})
    # A process may die after persisting a failed operation, before publishing
    # its terminal route status. The driver state then is terminal while the
    # durable wrapper is still running; finish that boundary on resume too.
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
