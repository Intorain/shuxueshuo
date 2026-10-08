"""Authenticated student data; public content writes only through the publisher."""

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from ..product.db import transaction
from . import drills, practice
from .api import Auth, User, learning_user

router = APIRouter(prefix="/api/learning", dependencies=[Depends(learning_user)])


class StartDrill(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    node_id: str = Field(min_length=1, max_length=100)
    previous_attempt_id: UUID | None = None


class AnswerDrill(BaseModel):
    model_config = ConfigDict(extra="forbid")
    selected: list[str] = Field(max_length=30)


@router.post("/drills")
def start(body: StartDrill, user: User, auth: Auth):
    return drills.start(
        auth.db, UUID(user["id"]), body.node_id, body.id, body.previous_attempt_id
    )


@router.get("/drills/{attempt_id}")
def read(attempt_id: UUID, user: User, auth: Auth):
    with transaction(auth.db) as c:
        return drills.view(c, drills.owned(c, attempt_id, UUID(user["id"])))


@router.post("/drills/{attempt_id}/answers/{position}")
def answer(attempt_id: UUID, position: int, body: AnswerDrill, user: User, auth: Auth):
    return drills.answer(auth.db, UUID(user["id"]), attempt_id, position, body.selected)


@router.get("/nodes")
def nodes(user: User, auth: Auth):
    with transaction(auth.db) as c:
        return {"nodes": drills.statuses(c, UUID(user["id"]))}


class StartPractice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    problem_id: str = Field(max_length=100)
    route_id: str = Field(max_length=100)
    previous_attempt_id: UUID | None = None


class SubmitPractice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    step_id: str = Field(max_length=100)
    answer: dict


@router.post("/practice")
def start_practice(body: StartPractice, user: User, auth: Auth):
    return practice.start(
        auth.db,
        UUID(user["id"]),
        body.problem_id,
        body.route_id,
        body.id,
        body.previous_attempt_id,
    )


@router.post("/practice/{attempt_id}/answers")
def submit_practice(attempt_id: UUID, body: SubmitPractice, user: User, auth: Auth):
    return practice.submit(
        auth.db, UUID(user["id"]), attempt_id, body.id, body.step_id, body.answer
    )


@router.post("/practice/{attempt_id}/displayed/{event_id}")
def displayed(attempt_id: UUID, event_id: UUID, user: User, auth: Auth):
    return practice.acknowledge(auth.db, UUID(user["id"]), attempt_id, event_id)


@router.get("/practice/{attempt_id}")
def read_practice(attempt_id: UUID, user: User, auth: Auth):
    with transaction(auth.db) as c:
        a = practice.owned(c, attempt_id, UUID(user["id"]))
        events = []
        for r in c.execute(
            text(
                "SELECT * FROM student_practice_events WHERE attempt_id=:a ORDER BY sequence"
            ),
            {"a": attempt_id},
        ).mappings():
            row = dict(r)
            if row["event_type"] == "context":
                row["payload"] = {
                    k: v
                    for k, v in row["payload"].items()
                    if k not in ("expected_answer", "criteria")
                }
            events.append(row)
        return practice.result(c, a) | {
            "problem_context": {
                k: v for k, v in a["problem_context"].items() if k != "contract_hash"
            },
            "events": events,
        }


@router.get("/nodes/{node_id}/evidence")
def evidence(node_id: str, user: User, auth: Auth):
    with transaction(auth.db) as c:
        rows = c.execute(
            text("""SELECT a.id AS attempt_id,a.problem_id,a.route_id,a.status,p.label,p.path,s.step_id,s.title,
            r.passed,r.submit_count,r.wrong_count,r.hint_used,r.last_submitted_at
            FROM student_practice_attempts a JOIN practice_step_nodes sn ON sn.problem_id=a.problem_id AND sn.route_id=a.route_id
            JOIN practice_steps s ON s.problem_id=sn.problem_id AND s.route_id=sn.route_id AND s.step_id=sn.step_id
            JOIN student_step_results r ON r.attempt_id=a.id AND r.step_id=s.step_id
            JOIN practice_problems p ON p.id=a.problem_id WHERE a.user_id=:u AND sn.node_id=:n
            ORDER BY r.last_submitted_at DESC,a.id DESC LIMIT 50"""),
            {"u": UUID(user["id"]), "n": node_id},
        ).mappings()
        return {"evidence": [dict(r) for r in rows]}


class ShownReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    step_id: str = Field(max_length=100)
    node_id: str = Field(max_length=100)


@router.post("/practice/{attempt_id}/references")
def reference(attempt_id: UUID, body: ShownReference, user: User, auth: Auth):
    return practice.shown_reference(
        auth.db, UUID(user["id"]), attempt_id, body.id, body.step_id, body.node_id
    )
