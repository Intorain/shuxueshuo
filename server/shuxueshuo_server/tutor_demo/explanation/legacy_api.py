"""Authenticated pilot endpoints, included under the existing teaching router."""

from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from ...auth.api import service
from ..limits import BudgetedTutor, BudgetUnavailable, CallBudget, DialogueLimited
from ..llm import TutorUnavailable
from ..session import Conflict, InvalidAction
from .contracts import ExplanationEvent
from .llm import ExplanationInterpreter
from .session import ExplanationSessions
from .candidates import CandidateGenerator


def create_explanation_router(user_dependency, interpreter=None, budget=None, candidate_generator=None):
    User = Annotated[dict, Depends(user_dependency)]
    interpreter = interpreter or ExplanationInterpreter()
    sessions = ExplanationSessions()
    candidate_generator = candidate_generator or CandidateGenerator()

    @asynccontextmanager
    async def lifespan(app):
        try:
            yield
        finally:
            if hasattr(interpreter, "close"):
                await interpreter.close()
            if hasattr(candidate_generator, "close"):
                await candidate_generator.close()

    router = APIRouter(prefix="/explanation", lifespan=lifespan)

    @router.post("/sessions", status_code=201)
    async def start(user: User):
        try:
            return sessions.create(user["id"]).view()
        except InvalidAction as exc:
            raise HTTPException(429, str(exc)) from None

    @router.get("/sessions/{session_id}")
    async def read(session_id: str, user: User):
        try:
            return sessions.get(session_id, user["id"]).view()
        except KeyError:
            raise HTTPException(404, "讲解已过期或不可访问，请重新开始。") from None

    @router.post("/sessions/{session_id}/initial-candidates")
    async def initial_candidates(session_id: str, user: User, request: Request):
        try:
            session = sessions.get(session_id, user["id"])
            if session.lock.locked():
                raise DialogueLimited("session_busy", "正在生成或验算，请稍后再试。", 2)
            ledger = budget if budget is not None else CallBudget(service(request).db)
            generator = BudgetedTutor(candidate_generator, ledger, session_id, user_id=user["id"])
            return await session.generate_initial(generator, getattr(candidate_generator, "prompt_version", "test"))
        except KeyError:
            raise HTTPException(404, "讲解已过期或不可访问，请重新开始。") from None
        except InvalidAction as exc:
            raise HTTPException(422, str(exc)) from None
        except DialogueLimited as exc:
            raise HTTPException(429, str(exc), headers={"Retry-After": str(exc.retry_after or 2)}) from None
        except (BudgetUnavailable, TutorUnavailable):
            raise HTTPException(503, "暂时无法生成选项，可以稍后重试或自己写一步。") from None

    @router.post("/sessions/{session_id}/events")
    async def event(session_id: str, body: ExplanationEvent, user: User, request: Request):
        try:
            session = sessions.get(session_id, user["id"])
            if session.lock.locked():
                raise DialogueLimited("session_busy", "正在验算，请稍后再试。", 2)
            ledger = budget if budget is not None else CallBudget(service(request).db)
            tutor = BudgetedTutor(interpreter, ledger, session_id, user_id=user["id"])
            return await session.handle(body, tutor)
        except KeyError:
            raise HTTPException(404, "讲解已过期或不可访问，请重新开始。") from None
        except Conflict as exc:
            return JSONResponse(status_code=409, content={"detail": str(exc), "snapshot": session.view()})
        except InvalidAction as exc:
            raise HTTPException(422, str(exc)) from None
        except DialogueLimited as exc:
            raise HTTPException(429, str(exc), headers={"Retry-After": str(exc.retry_after or 2)}) from None
        except BudgetUnavailable:
            raise HTTPException(503, "讲解服务额度暂不可用。仍可使用数学操作栏提交验算。") from None
        except TutorUnavailable:
            raise HTTPException(503, "暂时没有听懂这段讲解，输入已保留，可以重试或用数学操作栏明确表达。") from None

    return router
