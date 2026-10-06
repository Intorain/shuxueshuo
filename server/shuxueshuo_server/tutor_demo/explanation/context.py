"""One problem's explanation context: dialogue turns, threads and verified steps.

The program decides what becomes a step; the interpreter only proposes operations
and extracts what the student said. Everything lives in memory for the pilot.
"""

import json
import re
import time
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from pathlib import Path
from uuid import uuid4

import sympy

from ..contracts import InvalidAction
from .contracts import Clarification, ExplanationProposal, Operation
from .math import D1, D2, MathIssue, MathState
from .board import board_steps, groups, number

ROOT = Path(__file__).parent
REFERENCE_OPERATIONS = {"amgm", "substitute"}
LETTERS = "xyabuvt"
ACKNOWLEDGEMENTS = {"好", "好的", "嗯", "嗯嗯", "对", "是", "是的", "可以", "行", "ok", "继续"}


def normalize(text):
    return re.sub(r"[\s，。,.!！?？、；;：:“”\"'‘’（）()]", "", text).lower()


@dataclass
class Problem:
    id: str
    statement: str
    conditions: list
    target: str
    capabilities: dict
    judgments: dict
    routes: list
    examples: list

    @classmethod
    def load(cls, problem_id="q12"):
        config = json.loads((ROOT / "problems" / f"{problem_id}.json").read_text())
        merged = {"capabilities": {}, "judgments": {}}
        for pack_id in config["capability_packs"]:
            pack = json.loads((ROOT / "packs" / f"{pack_id}.json").read_text())
            for part, values in merged.items():
                values.update(pack[part])
        routes = []
        for route in config["reference_routes"]:
            # Replaying proves the route is executable and yields comparable result keys.
            state, keys = MathState(), []
            for item in route["steps"]:
                keys.append(state.execute(Operation(**item))["key"])
            routes.append({**route, "keys": keys})
        return cls(config["id"], config["statement"], config["conditions"], config["target"],
                   routes=routes, examples=config.get("interpretation_examples", []), **merged)


@dataclass
class Turn:
    id: str
    speaker: str
    text: str
    kind: str
    thread_id: str
    branch_id: str
    selected: list = field(default_factory=list)
    interpretation: dict | None = None
    prompt: str | None = None
    at: float = field(default_factory=time.time)


@dataclass
class Thread:
    id: str
    branch_id: str
    anchor: str | None = None          # None: next step (frontier); otherwise a step id
    revision: int = 0                  # committed steps of the branch when attempts were made
    status: str = "open"               # open | resolved | abandoned
    turn_ids: list = field(default_factory=list)
    attempts: list = field(default_factory=list)
    clarifications: list = field(default_factory=list)
    pending: list = field(default_factory=list)   # unbound judgments, waiting for a unique step
    hinted: bool = False


@dataclass
class Branch:
    id: str
    label: str
    steps: list = field(default_factory=list)
    snapshots: list = field(default_factory=lambda: [MathState()])
    frontier: str | None = None
    focus: str | None = None

    @property
    def state(self):
        return self.snapshots[-1]


class ExplanationContext:
    def __init__(self, problem=None):
        self.problem = problem or Problem.load()
        self.turns, self.threads, self.branches = [], {}, {}
        first = Branch(id=str(uuid4()), label="思路 1")
        self.branches[first.id] = first
        self.active = first.id
        self.focus = self.frontier(first).id

    # ---- structure -------------------------------------------------------
    @property
    def branch(self):
        return self.branches[self.active]

    def frontier(self, branch):
        thread = self.threads.get(branch.frontier)
        if thread is None or thread.status != "open":
            thread = Thread(id=str(uuid4()), branch_id=branch.id, revision=len(branch.steps))
            self.threads[thread.id] = thread
            branch.frontier = thread.id
        return thread

    def focused(self):
        thread = self.threads.get(self.focus)
        if thread is None or thread.status != "open" or thread.branch_id != self.active:
            thread = self.frontier(self.branch)
            self.focus = thread.id
        return thread

    def step_thread(self, step):
        for thread in self.threads.values():
            if thread.anchor == step["id"] and thread.branch_id == self.active and thread.status == "open":
                return thread
        thread = Thread(id=str(uuid4()), branch_id=self.active, anchor=step["id"], revision=len(self.branch.steps))
        self.threads[thread.id] = thread
        return thread

    def turn(self, turn_id):
        return next(t for t in self.turns if t.id == turn_id)

    def add_turn(self, speaker, text, kind, thread, selected=(), interpretation=None, prompt=None):
        turn = Turn(str(uuid4()), speaker, text, kind, thread.id, thread.branch_id, list(selected), interpretation,
                    prompt)
        self.turns.append(turn)
        thread.turn_ids.append(turn.id)
        return turn

    def find_step(self, step_id):
        return next((s for s in self.branch.steps if s["id"] == step_id), None)

    def fork(self, count):
        if len(self.branches) >= 10:
            raise InvalidAction("这次讲解已保留 10 条思路，请重新开始一场讲解。")
        if count > len(self.branch.steps):
            raise InvalidAction("这个步骤位置不存在。")
        if count and count < len(self.branch.steps):
            selection = self.branch.steps[count - 1].get("candidate_id")
            if selection and selection == self.branch.steps[count].get("candidate_id"):
                raise InvalidAction("请从完整操作之后另开思路，不能拆开一次选择。")
        old = self.branch
        old.focus = self.focus
        # The copy holds only evidence bound up to the fork; later judgments stay per branch.
        new = Branch(id=str(uuid4()), label=f"思路 {len(self.branches) + 1}",
                     steps=deepcopy(old.steps[:count]), snapshots=deepcopy(old.snapshots[:count + 1]))
        self.branches[new.id] = new
        self.active = new.id
        self.focus = self.frontier(new).id

    def switch(self, branch_id):
        if branch_id not in self.branches:
            raise InvalidAction("这条思路不存在。")
        self.branch.focus = self.focus
        self.active = branch_id
        saved = self.threads.get(self.branch.focus)
        resumable = saved is not None and saved.status == "open" and saved.branch_id == branch_id \
            and (saved.anchor is None or self.find_step(saved.anchor) is not None)
        self.focus = saved.id if resumable else self.frontier(self.branch).id

    def abandon(self):
        """The student drops the current next-step discussion; it is kept, marked abandoned."""
        thread = self.frontier(self.branch)
        if thread.turn_ids:
            thread.status = "abandoned"
        self.focus = self.frontier(self.branch).id

    def set_focus(self, step_id):
        if step_id is None:
            self.focus = self.frontier(self.branch).id
            return
        step = self.find_step(step_id)
        if step is None:
            raise InvalidAction("这个步骤不在当前思路中。")
        self.focus = self.step_thread(step).id

    # ---- judgments ------------------------------------------------------
    # Reasons are never demanded: a step stands once verified. What the student does say is
    # checked, and only a wrong reason is reported.
    def judge(self, judgment, step):
        """Program verdict on what the student claimed; the model's labelling is not trusted."""
        spec, checks = self.problem.judgments[judgment["key"]], step["checks"]
        if spec.get("check"):
            return bool(checks.get(spec["check"]))
        value = normalize(judgment.get("value", ""))
        if spec.get("expect") and value:
            return value in {normalize(v) for v in spec["expect"]}
        if spec.get("compare") and value and checks.get(spec["compare"]):
            try:
                return MathState().equivalent(judgment["value"], checks[spec["compare"]])
            except MathIssue:
                return True  # a relation stated in words carries no number to compare
        return True

    def bind(self, judgment, anchor, op_steps, new_steps):
        """(target step or None, reason). Never picks between several candidates by key."""
        spec = self.problem.judgments.get(judgment["key"])
        if spec is None or spec.get("implied"):
            return None, "unknown"
        owns = lambda step: step["operation"]["op"] in spec["owners"]
        if judgment.get("operation"):
            target = op_steps.get(judgment["operation"])
            if target is None:
                return None, "pending"
        elif judgment.get("step"):
            steps = self.branch.steps
            if judgment["step"] > len(steps):
                return None, "unknown"
            target = steps[judgment["step"] - 1]
        else:
            candidates = [s for s in new_steps if owns(s)]
            anchored = self.find_step(anchor) if anchor else None
            if not candidates and anchored and owns(anchored):
                candidates = [anchored]
            if len(candidates) > 1:
                return None, "optional"  # an unrequested reason is not worth a question
            if not candidates:
                return None, "pending"
            target = candidates[0]
        if not owns(target):
            return None, "unknown"
        if judgment.get("objects") and target["operation"]["op"] in REFERENCE_OPERATIONS:
            state, operation = self.branch.state, target["operation"]
            try:
                same = all(any(state.equivalent(o, operation[arg]) for arg in ("a", "b") if operation[arg])
                           for o in judgment["objects"])
            except MathIssue:
                same = False
            if not same:
                return target, "objects"
        return target, "bound"

    def implied(self, step, quote, source, turn_id):
        """Judgments the operation itself states (which terms, which equality condition)."""
        for key, spec in self.problem.judgments.items():
            if spec.get("implied") and step["operation"]["op"] in spec["owners"]:
                step["judgments"].append({"key": key, "quote": quote, "value": "", "source": source,
                                          "turn_id": turn_id, "label": spec["label"], "correct": True,
                                          "implied": True})

    # ---- one turn --------------------------------------------------------
    def grounded(self, quote, thread, text):
        needle = normalize(quote)
        said = [text] + [self.turn(t).text for t in thread.turn_ids if self.turn(t).speaker == "student"]
        return bool(needle) and any(needle in normalize(t) and normalize(t) not in ACKNOWLEDGEMENTS for t in said)

    def apply_turn(self, thread, text, selected, kind, proposal: ExplanationProposal, prompt=None):
        origin = thread
        if thread.anchor and proposal.operations:
            # The student moved on: new operations belong to the next-step discussion.
            thread = self.frontier(self.branch)
        branch = self.branch
        if thread.anchor is None and thread.revision != len(branch.steps):
            # The frontier moved since these drafts; their arguments must be restated, not reused.
            thread.attempts, thread.clarifications = [], []
        lower_before, complete_before = branch.state.lower, branch.state.complete
        if kind == "help":
            thread.hinted = True
        source = "prompted" if thread.hinted else "stated"
        student = self.add_turn("student", text or "给点提示", kind, thread, selected, proposal.model_dump(), prompt)
        results, new_steps, notes, op_steps = [], [], [], {}

        for proposed in proposal.operations:
            if len(branch.steps) >= 60:
                results.append({"status": "unsupported", "reply": "这条思路已达到 demo 的 60 步上限。"})
                break
            if kind != "operation" and not self.grounded(proposed.source, thread, text):
                results.append({"status": "clarify", "reply": "请用你自己的话说说接下来准备怎么做。"})
                break
            op = Operation(**proposed.model_dump(exclude={"inferred", "id"}))
            state = branch.state
            try:
                picked = list(selected) + (["+".join(f"({s})" for s in selected)] if len(selected) > 1 else [])
                inferred = [arg for arg in proposed.inferred if arg in ("a", "b") and not any(
                    state.equivalent(p, getattr(op, arg)) for p in picked)]
                # Only arguments that ARE referenced objects must resolve to one; composed
                # expressions ("这两个加起来") are merely flagged as inferred.
                unresolved = [arg for arg in inferred if op.op in REFERENCE_OPERATIONS
                              and not state.matches_object(getattr(op, arg))]
                echo = state.describe(op, inferred)
            except MathIssue as exc:
                results.append({"status": exc.status, "reply": str(exc)})
                break
            if unresolved:
                thread.clarifications = [{"kind": "ambiguous_ref", "question": "你说的是哪一项？在式子上点一下。",
                                          "op": op.op, "known": {}, "missing": unresolved[0],
                                          "candidates": [o["expression"] for o in state.view()["objects"]]}]
                results.append({"status": "clarify", "reply": "我不确定你指的是哪一项。"})
                break
            candidate = deepcopy(state)
            try:
                step = candidate.execute(op)
            except MathIssue as exc:
                thread.attempts.append({"operation": op.model_dump(), "echo": echo, "status": exc.status,
                                        "reply": str(exc), "turn_id": student.id})
                results.append({"status": exc.status, "reply": str(exc), "operation": op.model_dump()})
                break
            if step["key"] is None:
                results.append({"status": "duplicate", "reply": "这一步没有带来新的变化。"})
                continue
            earlier = next((i for i, s in enumerate(branch.steps) if s["key"] == step["key"]), None)
            if earlier is not None:
                branch.steps[earlier]["turn_ids"].append(student.id)
                op_steps[proposed.id or object()] = branch.steps[earlier]
                results.append({"status": "duplicate", "step_id": branch.steps[earlier]["id"],
                                "reply": f"这一点第 {earlier + 1} 步已经得到。"})
                continue
            step.update(id=str(uuid4()), echo=echo, inferred=inferred, origin=kind, source=op.source or text,
                        judgments=[], thread_id=thread.id, turn_ids=list(thread.turn_ids),
                        dependencies=[s["id"] for s in branch.steps])
            self.implied(step, op.source or text, source, student.id)
            branch.steps.append(step)
            branch.snapshots.append(candidate)
            new_steps.append(step)
            op_steps[proposed.id or object()] = step
            results.append({"status": "verified", "step_id": step["id"]})

        touched = {s["id"]: s for s in new_steps}
        said = [{**j.model_dump(), "source": source, "turn_id": student.id}
                for j in proposal.judgments if normalize(j.quote) and normalize(j.quote) in normalize(text)]
        unplaced = []
        for judgment in thread.pending + said:
            target, reason = self.bind(judgment, origin.anchor, op_steps, new_steps)
            if reason == "pending":
                # Kept in the discussion without a target; bound later only if it becomes unique.
                unplaced.append({**judgment, "operation": "", "step": None})
                continue
            if reason == "objects":
                notes.append(f"你说“{judgment['quote']}”，但第 {branch.steps.index(target) + 1} 步用的不是这两项，"
                             "这条理由没有计入。")
                continue
            if target is None or any(j["key"] == judgment["key"] and j["correct"] for j in target["judgments"]):
                continue
            mark = {k: judgment[k] for k in ("key", "quote", "value", "source", "turn_id")}
            mark.update(label=self.problem.judgments[judgment["key"]]["label"], correct=self.judge(judgment, target))
            target["judgments"].append(mark)
            touched[target["id"]] = target
            if judgment["turn_id"] not in target["turn_ids"]:
                target["turn_ids"].append(judgment["turn_id"])
            if not mark["correct"]:
                notes.append(f"你说“{judgment['quote']}”，但验算表明“{mark['label']}”在这里不成立。")
        thread.pending = unplaced[-6:]

        thread.clarifications = thread.clarifications if any(r["status"] == "clarify" for r in results) else []
        for c in proposal.clarifications:
            thread.clarifications.append(self.checked_clarification(c, branch.state))

        failures = [r for r in results if r["status"] not in {"verified", "duplicate"}]
        parts = []
        for r in results:
            if r["status"] == "verified":
                step = next(s for s in branch.steps if s["id"] == r["step_id"])
                parts.append(f"第 {number(branch.steps, branch.steps.index(step))} 步「{step['title']}」已整理到板书。")
            elif r["status"] == "duplicate":
                parts.append(r["reply"])
        if failures:
            parts.append(("前面成立的步骤已保留。" if new_steps else "") + failures[-1]["reply"])
        parts += notes
        if proposal.reply and not proposal.operations:
            parts.append(proposal.reply)
        parts += [c["question"] for c in thread.clarifications if c["question"] not in parts]
        if branch.state.complete and not complete_before:
            parts.append("下界和取等点都已核验，这个最小值可以取到。")
        elif branch.state.lower is not None and lower_before is None:
            parts.append("目前已建立下界，取等是否可达还未确认。")

        reply = " ".join(p for p in parts if p) or "我还没从这句话里找到可以验算的一步。你想对式子做什么？可以说具体的等式、乘数或要用的方法。"
        system = self.add_turn("system", reply, "reply", thread)
        for step in touched.values():
            step["turn_ids"].append(system.id)

        if new_steps and not failures and not thread.clarifications and thread.anchor is None:
            thread.status = "resolved"
            # Carried into the next discussion once; an old reason must not attach to a much later step.
            carried = [{**j, "carried": True} for j in thread.pending if not j.get("carried")]
            if carried:
                self.frontier(branch).pending = carried
            thread.pending = []
        if thread.anchor and (anchored := self.find_step(thread.anchor)) and student.id not in anchored["turn_ids"]:
            # Questions about a step are part of that step's conversation.
            anchored["turn_ids"] += [student.id, system.id]
        thread.revision = len(branch.steps)
        self.focus = thread.id if thread.status == "open" else self.frontier(branch).id

        status = failures[-1]["status"] if failures else "clarify" if thread.clarifications \
            else "verified" if new_steps else "explained" if touched else proposal.intent
        return {"status": status, "reply": reply}, results

    def checked_clarification(self, clarification: Clarification, state):
        item = clarification.model_dump()
        keep = []
        for text in item["candidates"]:
            try:
                match = state.object_for(text)
            except MathIssue:
                continue
            if match is not None and str(match) not in keep:
                keep.append(str(match))
        item["candidates"] = keep
        return item

    # ---- projections -----------------------------------------------------
    def progress(self):
        out = []
        for index, step in enumerate(self.branch.steps, 1):
            words = [self.turn(t).text for t in step["turn_ids"] if self.turn(t).speaker == "student"]
            out.append({"n": index, "op": step["operation"]["op"], "title": step["title"], "result": step["result"],
                        "student_words": words[-4:],
                        "explained": sorted({j["key"] for j in step["judgments"] if j["correct"] and not j.get("implied")})})
        return out[-20:]

    def hint_gap(self, thread):
        keys = {s["key"] for s in self.branch.steps}
        best = max(self.problem.routes, key=lambda r: sum(k in keys for k in r["keys"]))
        for item, key in zip(best["steps"], best["keys"]):
            if key not in keys:
                return {"type": "next_operation", "capability": self.problem.capabilities[item["op"]]["label"]}
        return {"type": "none"}

    def candidates(self):
        """Next operations offered as buttons. Built only from the current expression's structure and
        facts the student has established, so a key construction never appears before its premise."""
        state, steps = self.branch.state, self.branch.steps
        if state.complete:
            return []
        out = []

        def add(op, a="", b="", name="", blank=None):
            operation = Operation(op=op, a=a, b=b or ("0" if blank else ""), name=name)
            echo = state.describe(operation)
            if blank:
                echo = echo[:-1] + [{"blank": True}]
            out.append({"op": op, "a": a, "b": "" if blank else b, "name": name, "blank": blank, "echo": echo})

        def same(x, y):
            # Exact identity, not equality under the constraint: every unit factor equals 1 there.
            return sympy.cancel(state.canonical(state.parse(x) - state.parse(y))) == 0

        def done(op, a, b=""):
            pairs = [(a, b), (b, a)] if b else [(a, "")]
            return any(s["operation"]["op"] == op and same(s["operation"]["a"], x)
                       and (not y or same(s["operation"]["b"], y)) for s in steps for x, y in pairs)

        d1, d2 = state.display(D1), state.display(D2)
        free = iter(l for l in LETTERS if l not in state.aliases)
        for original, shown in ((D1, d1), (D2, d2)):
            if original not in state.aliases.values():
                add("substitute", str(shown), name=next(free))

        # Facts the student established: claims A = c with a constant c.
        facts = []
        for step in steps:
            operation = step["operation"]
            if operation["op"] == "claim":
                value = state.parse(operation["b"])
                if value.is_number and value != 0 and not state.parse(operation["a"]).is_number:
                    facts.append(operation)
        total = state.canonical(D1 + D2)
        if not any(state.equivalent(f["a"], str(total)) or state.equivalent(f["a"], f"({d1})+({d2})") for f in facts):
            add("claim", f"({d1})+({d2})", blank="b")
        for fact in facts:
            factor = f"({fact['a']})/({fact['b']})"
            if not done("multiply", factor):
                add("multiply", factor)

        terms = [t for t in state.terms() if not t.is_number]
        for i, first in enumerate(terms):
            for second in terms[i + 1:]:
                if not done("amgm", str(first), str(second)):
                    add("amgm", str(first), str(second))
        for op in ("combine", "expand"):
            trial = deepcopy(state)
            try:
                if trial.execute(Operation(op=op))["key"] is not None:
                    add(op)
            except MathIssue:
                pass
        if state.lower is not None:
            for first, second in [(d1, d2)] + [(a, b) for i, a in enumerate(terms) for b in terms[i + 1:]]:
                add("attain", str(first), str(second))
        return out

    def project(self, thread, text, selected, request):
        state = self.branch.state.view()
        anchored = self.find_step(thread.anchor) if thread.anchor else None
        data = {
            "problem": {"statement": self.problem.statement, "conditions": self.problem.conditions,
                        "target": self.problem.target},
            "capabilities": {k: v["description"] for k, v in self.problem.capabilities.items()},
            "judgment_keys": {k: {"label": v["label"], "owners": v["owners"], **({"value": v["hint"]} if "hint" in v else {})}
                              for k, v in self.problem.judgments.items() if not v.get("implied")},
            "interpretation_examples": self.problem.examples,
            "progress": self.progress(),
            "current": {"expression": state["expression"], "conditions": state["conditions"],
                        "aliases": state["aliases"], "objects": [o["expression"] for o in state["objects"]]},
            "focus": {
                "about": f"第 {self.branch.steps.index(anchored) + 1} 步" if anchored else "下一步",
                "step": self.branch.steps.index(anchored) + 1 if anchored else None,
                "turns": [{"speaker": self.turn(t).speaker, "text": self.turn(t).text} for t in thread.turn_ids][-12:],
                "failed_attempts": [a["reply"] for a in thread.attempts][-3:],
                "open_clarifications": [c["question"] for c in thread.clarifications],
            },
            "text": text, "selected": selected, "request": request,
        }
        if request == "hint":
            data["hint_gap"] = self.hint_gap(thread)
        return data

    def view(self):
        focus = self.focused()
        anchored = self.find_step(focus.anchor) if focus.anchor else None
        return deepcopy({
            "branch_id": self.active,
            "branches": [{"id": b.id, "label": b.label, "steps": len(groups(b.steps))} for b in self.branches.values()],
            "board_steps": [{k: v for k, v in s.items() if k not in {"checks", "key"}}
                            for s in board_steps(self.branch)],
            "steps": self.branch.steps and [{k: v for k, v in s.items() if k not in {"checks", "key"}}
                                            for s in self.branch.steps],
            "state": self.branch.state.view(),
            "candidates": self.candidates(),
            "turns": [asdict(t) | {"interpretation": None} for t in self.turns][-400:],
            "focus": {"thread_id": focus.id, "step_id": focus.anchor,
                      "step_number": number(self.branch.steps, self.branch.steps.index(anchored)) if anchored else None,
                      "turn_ids": focus.turn_ids,
                      "attempts": focus.attempts, "clarifications": focus.clarifications},
        })
