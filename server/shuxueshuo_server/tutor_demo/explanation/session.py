"""In-memory, owner-isolated pilot sessions around one ExplanationContext."""

import asyncio
import time
from copy import deepcopy
from uuid import uuid4

from starlette.concurrency import run_in_threadpool

from ..contracts import InvalidAction
from ..llm import TutorUnavailable
from ..session import Conflict
from .context import ExplanationContext
from .contracts import ExplanationProposal, ProposedOperation
from .candidates import projection, verify
from .board import board_steps


class ExplanationSession:
    def __init__(self, owner):
        self.id, self.owner = str(uuid4()), owner
        self.context = ExplanationContext()
        self.revision = 0
        self.events = {}
        self.lock = asyncio.Lock()
        self.touched = time.monotonic()
        self.initial_batch = None

    def view(self):
        batch = self.initial_batch if not self.context.branch.steps else None
        return {"session_id": self.id, "revision": self.revision, **self.context.view(),
                "initial_choices": {"status": batch["status"], "candidates": [
                    {"id": c["id"], "echo": c["echo"]} for c in batch["candidates"]]} if batch else None}

    async def generate_initial(self, generator, prompt_version):
        async with self.lock:
            self.touched = time.monotonic()
            if self.context.branch.steps:
                raise InvalidAction("首步选项只在初始状态生成。")
            if self.initial_batch is None:
                data = projection(self.context)
                proposal = await generator.respond(projection=data)
                batch = await run_in_threadpool(verify, self.context, proposal)
                batch.update(prompt_version=prompt_version, projection=data)
                self.initial_batch = batch
            return self.view()

    async def handle(self, event, interpreter):
        async with self.lock:
            self.touched = time.monotonic()
            payload = event.model_dump()
            if event.event_id in self.events:
                old, response = self.events[event.event_id]
                if old != payload:
                    raise Conflict("这次提交标识已用于其他内容，请刷新状态后重新提交。")
                return deepcopy(response)
            if event.revision != self.revision:
                raise Conflict("讲解进度已变化，已同步当前板书，请检查后再提交。")
            if len(self.events) >= 150:
                raise InvalidAction("这次讲解已达到 demo 的轮次上限，请重新开始。")
            context = self.context
            feedback, results = {"status": "info", "reply": ""}, []
            if event.kind in {"fork", "undo"}:
                count = event.step_count if event.step_count is not None else len(context.branch.steps)
                if event.kind == "undo":
                    if not context.branch.steps:
                        raise InvalidAction("还没有可以撤回的步骤。")
                    count = context.branch.steps[-1].get("selection_start", len(context.branch.steps) - 1)
                context.fork(count)
                feedback["reply"] = "已保留原思路，你可以从这里继续讲。"
            elif event.kind == "switch":
                context.switch(event.branch_id)
                feedback["reply"] = "已切换到这条思路。"
            elif event.kind == "focus":
                context.set_focus(event.step_id)
            elif event.kind == "abandon":
                context.abandon()
                feedback["reply"] = "好，这个想法先放下，换个思路接着讲。"
            elif event.kind == "candidate":
                if context.branch.steps or not self.initial_batch:
                    raise Conflict("这个选项所属的数学状态已变化，请回到初始状态重新选择。")
                chosen = next((c for c in self.initial_batch["candidates"] if c["id"] == event.candidate_id), None)
                if chosen is None:
                    raise InvalidAction("这个选项已不可用。")
                # Recheck and commit the entire choice on a private context. Never
                # accept client mathematics or publish a partially executed group.
                trial = deepcopy(context)
                proposal = ExplanationProposal(intent="propose", operations=[
                    ProposedOperation(**op | {"source": chosen["text"]}) for op in chosen["operations"]])
                feedback, results = await run_in_threadpool(
                    trial.apply_turn, trial.focused(), chosen["text"], [], "operation", proposal)
                if len(results) != len(proposal.operations) or any(r["status"] != "verified" for r in results):
                    raise Conflict("这个选项未能完整核验，请重新选择。")
                for step in trial.branch.steps:
                    step.update(via="candidate", candidate_id=chosen["id"],
                                candidate_batch=self.initial_batch["id"], selection_start=0)
                title = board_steps(trial.branch)[-1]["title"]
                feedback["reply"] = f"第 1 步「{title}」已整理到板书。"
                if trial.branch.state.complete:
                    feedback["reply"] += "下界和取等点都已核验，这个最小值可以取到。"
                # The dialogue and feedback describe one student choice too.
                trial.turns[-1].text = feedback["reply"]
                self.context = trial
            else:
                thread = context.focused()
                prompt = None
                if event.kind == "operation":
                    proposal = ExplanationProposal(intent="propose", operations=[
                        ProposedOperation(**event.operation.model_dump() | {"source": event.text})])
                else:
                    known = {o["expression"] for o in context.branch.state.view()["objects"]}
                    if not set(event.selected) <= known:
                        raise Conflict("选中的对象已变化，请重新选择。")
                    request = "hint" if event.kind == "help" else "explain"
                    proposal = await interpreter.respond(
                        projection=context.project(thread, event.text, event.selected, request), request=request)
                    if event.kind == "help" and (proposal.operations or proposal.judgments):
                        raise TutorUnavailable("提示不能推进步骤")
                    prompt = getattr(interpreter, "prompt_version", None)
                feedback, results = await run_in_threadpool(
                    context.apply_turn, thread, event.text, event.selected, event.kind, proposal, prompt)
                for result in results:
                    if event.via and result["status"] == "verified":
                        context.find_step(result["step_id"])["via"] = event.via
            self.revision += 1
            response = {**self.view(), "feedback": feedback, "results": results}
            self.events[event.event_id] = (payload, deepcopy(response))
            return response


class ExplanationSessions:
    def __init__(self):
        self.items = {}

    def create(self, owner):
        now = time.monotonic()
        self.items = {k: v for k, v in self.items.items() if v.lock.locked() or now - v.touched < 7200}
        if len(self.items) >= 256 or sum(s.owner == owner for s in self.items.values()) >= 12:
            raise InvalidAction("暂时不能创建更多讲解，请继续已有讲解或稍后再试。")
        session = ExplanationSession(owner)
        self.items[session.id] = session
        return session

    def get(self, key, owner):
        session = self.items[key]
        if session.owner != owner or time.monotonic() - session.touched >= 7200:
            raise KeyError(key)
        session.touched = time.monotonic()
        return session
