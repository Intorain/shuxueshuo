"""Authenticated pilot endpoints, included under the existing teaching router."""

from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from ...auth.api import service
from ..limits import BudgetedTutor, BudgetUnavailable, CallBudget, DialogueLimited
from ..llm import TutorUnavailable
from ..session import Conflict, InvalidAction
from .generated_contracts import GeneratedEvent
from .generated_llm import ExplanationGenerator
from .generated_session import GeneratedSessions


class Start(BaseModel):
    model_config = ConfigDict(extra="forbid")
    problem_id: str = Field(default="q12", pattern=r"^[a-zA-Z0-9_-]{1,60}$")


def create_explanation_router(user_dependency, interpreter=None, budget=None):
    User = Annotated[dict, Depends(user_dependency)]
    interpreter = interpreter or ExplanationGenerator()
    sessions = GeneratedSessions()

    @asynccontextmanager
    async def lifespan(app):
        try:
            yield
        finally:
            if hasattr(interpreter, "close"):
                await interpreter.close()

    router = APIRouter(prefix="/explanation", lifespan=lifespan)

    @router.post("/sessions", status_code=201)
    async def start(body: Start, user: User):
        try:
            return sessions.create(user["id"], body.problem_id).view()
        except KeyError:
            raise HTTPException(404, "没有找到这道题。") from None
        except InvalidAction as exc:
            raise HTTPException(429, str(exc)) from None

    @router.get("/sessions/{session_id}")
    async def read(session_id: str, user: User):
        try:
            return sessions.get(session_id, user["id"]).view()
        except KeyError:
            raise HTTPException(404, "讲解已过期或不可访问，请重新开始。") from None

    @router.post("/sessions/{session_id}/candidates")
    async def initial_candidates(session_id: str, user: User, request: Request):
        try:
            session = sessions.get(session_id, user["id"])
            if session.lock.locked():
                raise DialogueLimited("session_busy", "正在生成推导和选项，请稍后再试。", 2)
            ledger = budget if budget is not None else CallBudget(service(request).db)
            generator = BudgetedTutor(interpreter, ledger, session_id, user_id=user["id"])
            return await session.generate_initial(generator)
        except KeyError:
            raise HTTPException(404, "讲解已过期或不可访问，请重新开始。") from None
        except InvalidAction as exc:
            raise HTTPException(422, str(exc)) from None
        except DialogueLimited as exc:
            raise HTTPException(429, "暂时无法调用讲解模型，请稍后重试；仍可回看、撤回或切换思路。", headers={"Retry-After": str(exc.retry_after or 2)}) from None
        except (BudgetUnavailable, TutorUnavailable):
            raise HTTPException(503, "暂时无法生成选项，请稍后重试。") from None

    @router.post("/sessions/{session_id}/events")
    async def event(session_id: str, body: GeneratedEvent, user: User, request: Request):
        try:
            session = sessions.get(session_id, user["id"])
            if session.lock.locked():
                raise DialogueLimited("session_busy", "正在生成推导和选项，请稍后再试。", 2)
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
            raise HTTPException(429, "暂时无法调用讲解模型，请稍后重试；仍可回看、撤回或切换思路。", headers={"Retry-After": str(exc.retry_after or 2)}) from None
        except BudgetUnavailable:
            raise HTTPException(503, "讲解服务额度暂不可用。已有板书可以回看、撤回或切换思路。") from None
        except TutorUnavailable:
            raise HTTPException(503, "暂时未能生成完整推导和选项，当前进度与输入已保留，请重试。") from None

    return router
