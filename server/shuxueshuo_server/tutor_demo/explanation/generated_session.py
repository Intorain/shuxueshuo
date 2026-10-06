"""Model-authored steps with atomic snapshots, owner isolation and branch replay.

Reference solutions and family guidance are separate from student progress.
This module never imports the historical Q12 mathematical executor.
"""

import asyncio
import json
import time
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from ..contracts import InvalidAction
from ..llm import TutorUnavailable
from ..session import Conflict
from .generated_contracts import GeneratedTurn, ProblemSpec
from .references import load_references


def uid():
    return str(uuid4())


def load_problem(problem_id):
    path = Path(__file__).parent / "problems" / f"{problem_id}.json"
    if not path.is_file():
        raise KeyError(problem_id)
    raw = json.loads(path.read_text())
    # Public problem data only; private reference context is loaded separately.
    return ProblemSpec.model_validate({k: raw[k] for k in ProblemSpec.model_fields})


def snapshot(state=None, candidates=()):
    choices, seen = [], set()
    for candidate in candidates:
        if candidate.label in seen:
            continue
        seen.add(candidate.label)
        choices.append({"id": uid(), "label": candidate.label})
    return {"id": uid(), "state": state.model_dump() if state else None,
            "choices": {"status": "ready" if choices else "empty", "candidates": choices} if state else None}


def branch(steps=None, snapshots=None):
    return {"id": uid(), "steps": steps or [], "snapshots": snapshots or [snapshot()],
            "focus": None, "discussions": {}}


class GeneratedSession:
    def __init__(self, owner, problem, references=None):
        self.id, self.owner, self.problem = uid(), owner, problem
        self.references = deepcopy(references or {"reference_solutions": [], "family_guidance": None})
        self.revision, self.events = 0, {}
        first = branch()
        self.branches, self.active = {first["id"]: first}, first["id"]
        self.turns, self.audit = [], []
        self.lock = asyncio.Lock()
        self.touched = time.monotonic()

    @property
    def branch(self):
        return self.branches[self.active]

    @property
    def current(self):
        return self.branch["snapshots"][-1]

    def thread_key(self):
        return self.branch["focus"] or self.current["id"]

    def project(self, request):
        ids = self.branch["discussions"].get(self.thread_key(), [])[-12:]
        return {"problem": self.problem.model_dump(), **deepcopy(self.references),
                "state": deepcopy(self.current["state"]),
                "steps": [{"title": s["title"], "highlight": s["highlight"], "change": s["change"],
                           "lines": s["lines"], "student_action": s["action"]}
                          for s in self.branch["steps"]],
                "discussion": [{"speaker": t["speaker"], "text": t["text"]} for t in self.turns if t["id"] in ids],
                "focused_step": next((i + 1 for i, s in enumerate(self.branch["steps"])
                                      if s["id"] == self.branch["focus"]), None),
                "request": request}

    def view(self):
        math = self.current["state"]
        # Adapter for the shared page composer. No problem-specific mathematics.
        state = {"marked": math["expression"] if math else "", "conditions": math["facts"] if math else [],
                 "definitions": math["definitions"] if math else [],
                 "objects": [dict(o, id=i) for i, o in enumerate(math["objects"])] if math else [],
                 "symbols": math["symbols"] if math else [], "aliases": {}, "lower": None,
                 "complete": math["complete"] if math else False}
        focus = self.branch["focus"]
        focused = next((i + 1 for i, s in enumerate(self.branch["steps"]) if s["id"] == focus), None)
        return deepcopy({"session_id": self.id, "revision": self.revision, "engine": "llm",
                         "problem": self.problem.model_dump(), "snapshot_id": self.current["id"],
                         "state": state, "steps": self.branch["steps"], "board_steps": self.branch["steps"],
                         "choices": self.current["choices"], "turns": self.turns,
                         "branch_id": self.active,
                         "branches": [{"id": b["id"], "label": f"思路 {i + 1}", "steps": len(b["steps"])}
                                      for i, b in enumerate(self.branches.values())],
                         "focus": {"step_id": focus, "step_number": focused, "thread_id": self.thread_key(),
                                   "turn_ids": self.branch["discussions"].get(self.thread_key(), []),
                                   "attempts": [], "clarifications": []}})

    async def ask(self, generator, request):
        projection = self.project(request)
        raw = await generator.respond(projection=projection)
        try:
            result = GeneratedTurn.model_validate(raw.model_dump() if hasattr(raw, "model_dump") else raw)
            kind = request["kind"]
            if kind in {"initial", "refresh"}:
                if result.outcome != "initial":
                    raise ValueError("候选生成不能推进板书")
                if kind == "initial" and result.state.complete:
                    raise ValueError("初始题目不能直接判为完成")
                if kind == "refresh" and result.state.model_dump() != self.current["state"]:
                    raise ValueError("重新生成选项不能修改状态")
            elif kind in {"help", "discuss"}:
                if result.outcome != "feedback":
                    raise ValueError("提示和追问不能推进板书")
            elif result.outcome == "initial":
                raise ValueError("执行操作必须给出推导或反馈")
        except (ValueError, ValidationError) as exc:
            raise TutorUnavailable("模型返回的步骤结构不完整，请重试。") from exc
        return result, {"projection": projection, "response": result.model_dump(),
                        "prompt_version": getattr(getattr(generator, "tutor", generator), "prompt_version", "test")}

    async def generate_initial(self, generator):
        async with self.lock:
            self.touched = time.monotonic()
            if self.current["choices"] is None:
                result, audit = await self.ask(generator, {"kind": "initial"})
                self.branch["snapshots"][-1] = snapshot(result.state, result.candidates)
                self.audit.append(audit)
            return self.view()

    def fork(self, count):
        if count < 0 or count > len(self.branch["steps"]):
            raise InvalidAction("请选择已有步骤。")
        if len(self.branches) >= 40:
            raise InvalidAction("本次讲解的分支已达上限，请切换已有思路。")
        new = branch(deepcopy(self.branch["steps"][:count]), deepcopy(self.branch["snapshots"][:count + 1]))
        new["discussions"] = {s["id"]: deepcopy(self.branch["discussions"].get(s["id"], s["turn_ids"]))
                              for s in new["steps"]}
        self.branches[new["id"]], self.active = new, new["id"]

    async def handle(self, event, generator):
        async with self.lock:
            self.touched = time.monotonic()
            payload = event.model_dump()
            if event.event_id in self.events:
                old, response = self.events[event.event_id]
                if payload != old:
                    raise Conflict("这次提交标识已用于其他内容。")
                return deepcopy(response)
            if event.revision != self.revision:
                raise Conflict("进度已变化，请按当前板书重新选择。")
            if len(self.events) >= 150:
                raise InvalidAction("本次讲解已达到轮次上限，请重新开始。")
            reply = ""
            if event.kind in {"undo", "fork"}:
                count = event.step_count if event.step_count is not None else len(self.branch["steps"])
                if event.kind == "undo":
                    if not count:
                        raise InvalidAction("还没有可以撤回的步骤。")
                    count = len(self.branch["steps"]) - 1
                self.fork(count)
                reply = "已保留原思路，并恢复这里的数学状态和选项。"
            elif event.kind == "switch":
                if event.branch_id not in self.branches:
                    raise InvalidAction("这条思路不存在。")
                self.active = event.branch_id
                reply = "已切换到这条思路。"
            elif event.kind == "focus":
                if event.step_id and not any(s["id"] == event.step_id for s in self.branch["steps"]):
                    raise InvalidAction("这一步不在当前思路中。")
                self.branch["focus"] = event.step_id
            elif event.kind == "abandon":
                self.branch["focus"] = None
                self.branch["discussions"][self.current["id"]] = []
            else:
                if len(self.branch["steps"]) >= 60 and event.kind not in {"help", "refresh"}:
                    raise InvalidAction("本次板书已达步骤上限，可以回退或重新开始。")
                known = {o["expression"] for o in self.view()["state"]["objects"]}
                if not set(event.selected) <= known:
                    raise Conflict("选中的对象已变化，请重新选择。")
                action = event.text
                request = {"kind": event.kind, "text": event.text, "selected": event.selected}
                if event.kind == "candidate":
                    choices = (self.current["choices"] or {}).get("candidates", [])
                    chosen = next((c for c in choices if c["id"] == event.candidate_id), None)
                    if chosen is None:
                        raise Conflict("这个选项已不属于当前状态，请重新选择。")
                    action = chosen["label"]
                    request = {"kind": "candidate", "action": action}
                elif event.kind == "operation":
                    request["operation"] = event.operation.model_dump()
                    action = action or json.dumps(request["operation"], ensure_ascii=False)
                elif event.kind == "text" and self.branch["focus"]:
                    request["kind"] = "discuss"
                elif event.kind == "refresh":
                    request["kind"] = "refresh" if self.current["state"] else "initial"
                # Nothing is published until the entire response passes structural checks.
                result, audit = await self.ask(generator, request)
                reply = result.reply
                if result.outcome == "initial":
                    discussion = self.branch["discussions"].get(self.current["id"], [])
                    self.branch["snapshots"][-1] = snapshot(result.state, result.candidates)
                    self.branch["discussions"][self.current["id"]] = discussion
                else:
                    student = {"id": uid(), "speaker": "student", "text": action or "给点提示"}
                    pair = [student]
                    if reply:
                        pair.append({"id": uid(), "speaker": "system", "text": reply})
                    ids = self.branch["discussions"].get(self.thread_key(), []) + [t["id"] for t in pair]
                    self.turns.extend(pair)
                    if result.outcome == "step":
                        step = {"id": uid(), "title": result.step.title, "lines": result.step.lines,
                                "change": result.step.change.model_dump(),
                                "highlight": result.step.highlight.model_dump(),
                                "derivation": [{"lead": "", "math": line} for line in result.step.lines],
                                "result": result.step.lines[-1], "turn_ids": ids, "judgments": [], "inferred": [],
                                "action": action, "via": event.via or event.kind, "provenance": "llm_generated",
                                "step_count": len(self.branch["steps"]) + 1}
                        self.branch["steps"].append(step)
                        self.branch["discussions"][step["id"]] = ids
                        self.branch["snapshots"].append(snapshot(result.state, result.candidates))
                        self.branch["focus"] = None
                    else:
                        self.branch["discussions"][self.thread_key()] = ids
                self.audit.append(audit)
            self.revision += 1
            response = {**self.view(), "feedback": {"status": "info", "reply": reply}, "results": []}
            self.events[event.event_id] = (payload, deepcopy(response))
            return response


class GeneratedSessions:
    def __init__(self):
        self.items = {}

    def create(self, owner, problem_id="q12"):
        now = time.monotonic()
        self.items = {k: v for k, v in self.items.items() if v.lock.locked() or now - v.touched < 7200}
        if len(self.items) >= 256 or sum(s.owner == owner for s in self.items.values()) >= 12:
            raise InvalidAction("暂时不能创建更多讲解，请继续已有讲解或稍后再试。")
        session = GeneratedSession(owner, load_problem(problem_id), load_references(problem_id))
        self.items[session.id] = session
        return session

    def get(self, key, owner):
        session = self.items[key]
        if session.owner != owner or time.monotonic() - session.touched >= 7200:
            raise KeyError(key)
        session.touched = time.monotonic()
        return session
