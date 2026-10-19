"""Freeze verified mathematical routes, then append separately bound QA evidence.

The caller supplies independently checked mathematics. This module enforces
publication identity and atomically checks the latest target availability; it
does not solve a problem or call a language model.
"""

import json
from copy import deepcopy

from shuxueshuo_server.problem_understanding.identity import revision

from .events import _dump, goal_unavailable


def complete_route(store, checkpoint, *, route, verification, feasible_set, answer, commit_id,
                   consistency="consistent", before_commit=None, after_commit=None):
    if verification.get("status") != "verified" or route.get("status") != "verified":
        raise ValueError("handoff.route_not_verified")
    if checkpoint["status"] != "verified" or answer is None or feasible_set is None:
        raise ValueError("handoff.incomplete_finalization")
    if consistency not in {"consistent", "conflict", "unknown"}:
        raise ValueError("handoff.invalid_consistency")
    target, route_id = checkpoint["target_ref"], checkpoint["route_id"]
    for key, expected in (("target_ref", target), ("route_id", route_id)):
        if route.get(key, expected) != expected:
            raise ValueError("handoff.route_identity_mismatch")
    request = {"checkpoint": checkpoint, "route": route, "verification": verification,
               "feasible_set": feasible_set, "answer": answer, "consistency": consistency}

    def mutate(db):
        current = store._goal(db, target)
        steps = store._steps(db, target, route_id)
        if store._checkpoint(db, target, route_id) is None or not steps:
            raise ValueError("handoff.missing_committed_math")
        frozen_steps = [{key: step[key] for key in ("step_id", "ordinal", "math_step_sha256")} for step in steps]
        route_hash = revision({"route": route, "verification": verification, "feasible_set": feasible_set,
                               "answer": answer, "math_steps": frozen_steps, "revisions": store.identity["revisions"]})
        saved = db.execute("SELECT value FROM handoffs WHERE target=? AND route=?", (target, route_id)).fetchone()
        if saved:
            previous = json.loads(saved[0])
            if previous["verified_route_sha256"] != route_hash:
                raise ValueError("handoff.immutable_route")
            return {"checkpoint": store._checkpoint(db, target, route_id), "handoff": previous}
        store._append_event(db, commit_id, {"type": "lesson.route_status", "target_ref": target,
                                            "route_id": route_id, "payload": {"status": "verified"}})
        final_checkpoint = deepcopy(checkpoint)
        final_checkpoint["verified_route_sha256"] = route_hash
        final_checkpoint["finalization"] = {"verification": verification, "feasible_set": feasible_set, "answer": answer}
        if consistency != "consistent" or goal_unavailable(current):
            status = "conflict" if consistency == "conflict" or (current and current["status"] == "conflict") else "no_verified_route"
            reason = "route_conflict" if status == "conflict" else "route_consistency_undecidable"
            goal = {"status": status, "reason": reason, "available": False}
            store._put_goal(db, target, goal)
            store._append_event(db, commit_id, {"type": "lesson.goal_status", "target_ref": target,
                                                "route_id": None, "payload": goal})
            return {"checkpoint": store._put_checkpoint(db, final_checkpoint, commit_id), "handoff": None}
        task = {
            "contract": "graph-stage-four-handoff/v1", "lesson_version": store.identity["lesson_version"],
            "run_id": store.identity["run_id"], "target_ref": target, "route_id": route_id,
            "verified_route_sha256": route_hash, "math_steps": frozen_steps,
            "feasible_set": deepcopy(feasible_set), "answer": deepcopy(answer), "status": "pending", "available": True,
        }
        task["task_id"] = revision({key: task[key] for key in (
            "lesson_version", "run_id", "target_ref", "route_id", "verified_route_sha256",
        )})
        db.execute("INSERT INTO handoffs VALUES (?,?,?)", (target, route_id, _dump(task)))
        goal = {"status": "solved", "available": True, "feasible_set": feasible_set, "answer": answer}
        store._put_goal(db, target, goal)
        store._append_event(db, commit_id, {"type": "lesson.goal_status", "target_ref": target,
                                            "route_id": None, "payload": goal})
        store._append_event(db, commit_id, {"type": "lesson.chunk_ready", "target_ref": target,
            "route_id": route_id, "payload": {"kind": "route_completion", "verified_route_sha256": route_hash,
                "answer": deepcopy(answer), "feasible_set": deepcopy(feasible_set), "status": "verified"}})
        store._append_event(db, commit_id, {"type": "lesson.enrichment_status", "target_ref": target,
                                            "route_id": route_id, "payload": {"status": "pending", "task_id": task["task_id"]}})
        return {"checkpoint": store._put_checkpoint(db, final_checkpoint, commit_id), "handoff": task}

    return store._transaction(commit_id, request, mutate, before_commit=before_commit, after_commit=after_commit)


def invalidate_goal(store, target_ref, *, status, reason, commit_id):
    if status not in {"conflict", "no_verified_route"}:
        raise ValueError("handoff.invalid_goal_status")
    return store.commit_events([{
        "type": "lesson.goal_status", "target_ref": target_ref, "route_id": None,
        "payload": {"status": status, "reason": reason, "available": False},
    }], commit_id=commit_id)


def attach_qa(store, chunk, *, commit_id, before_commit=None, after_commit=None):
    """Attach one immutable QA payload; never accept mathematical replacements."""
    required = {"lesson_version", "run_id", "target_ref", "route_id", "step_id",
                "math_step_sha256", "verified_route_sha256", "qa"}
    if set(chunk) != required or not isinstance(chunk.get("qa"), dict):
        raise ValueError("handoff.invalid_qa_shape")
    if not set(chunk["qa"]) <= {"questions", "possible_questions", "hints", "common_errors", "feedback"}:
        raise ValueError("handoff.invalid_qa_fields")
    for key in ("run_id", "lesson_version"):
        if chunk[key] != store.identity[key]:
            raise ValueError("handoff.qa_identity_mismatch")

    def mutate(db):
        target, route, step_id = chunk["target_ref"], chunk["route_id"], chunk["step_id"]
        goal = store._goal(db, target)
        if not goal or goal["status"] != "solved" or goal_unavailable(goal):
            raise ValueError("handoff.goal_unavailable")
        task_row = db.execute("SELECT value FROM handoffs WHERE target=? AND route=?", (target, route)).fetchone()
        if not task_row:
            raise ValueError("handoff.missing_task")
        task = json.loads(task_row[0])
        if not task["available"] or task["verified_route_sha256"] != chunk["verified_route_sha256"]:
            raise ValueError("handoff.route_hash_mismatch")
        step = next((value for value in task["math_steps"] if value["step_id"] == step_id), None)
        if step is None or step["math_step_sha256"] != chunk["math_step_sha256"]:
            raise ValueError("handoff.step_hash_mismatch")
        previous = db.execute("SELECT value FROM qa WHERE target=? AND route=? AND step=?", (target, route, step_id)).fetchone()
        if previous:
            if json.loads(previous[0]) != chunk:
                raise ValueError("handoff.immutable_qa")
            return {"qa": deepcopy(chunk)}
        db.execute("INSERT INTO qa VALUES (?,?,?,?)", (target, route, step_id, _dump(chunk)))
        store._append_event(db, commit_id, {"type": "lesson.chunk_ready", "target_ref": target,
            "route_id": route, "payload": {"kind": "step_qa", "step_id": step_id,
                "math_step_sha256": chunk["math_step_sha256"], "verified_route_sha256": chunk["verified_route_sha256"],
                "chunk": chunk}})
        return {"qa": deepcopy(chunk)}

    return store._transaction(commit_id, chunk, mutate, before_commit=before_commit, after_commit=after_commit)


def enrichment_status(store, target_ref, route_id, *, status, commit_id, diagnostic=None):
    if status not in {"pending", "running", "completed", "partial", "failed"}:
        raise ValueError("handoff.invalid_enrichment_status")
    request = {"target_ref": target_ref, "route_id": route_id, "status": status, "diagnostic": diagnostic}

    def mutate(db):
        if goal_unavailable(store._goal(db, target_ref)):
            raise ValueError("handoff.goal_unavailable")
        saved = db.execute("SELECT value FROM handoffs WHERE target=? AND route=?", (target_ref, route_id)).fetchone()
        if not saved:
            raise ValueError("handoff.missing_task")
        task = json.loads(saved[0])
        if status == "completed":
            count = db.execute("SELECT COUNT(*) FROM qa WHERE target=? AND route=?", (target_ref, route_id)).fetchone()[0]
            if count != len(task["math_steps"]):
                raise ValueError("handoff.incomplete_qa")
        task.update(status=status, diagnostic=diagnostic)
        db.execute("UPDATE handoffs SET value=? WHERE target=? AND route=?", (_dump(task), target_ref, route_id))
        store._append_event(db, commit_id, {"type": "lesson.enrichment_status", "target_ref": target_ref,
            "route_id": route_id, "payload": {"status": status, "diagnostic": diagnostic}})
        return {"handoff": task}

    return store._transaction(commit_id, request, mutate)
