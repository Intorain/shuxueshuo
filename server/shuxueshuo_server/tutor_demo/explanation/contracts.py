"""Bounded inputs shared by the interpreter, explicit input form and executor."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

OperationName = Literal["claim", "evaluate", "substitute", "multiply", "expand", "combine", "amgm", "attain"]
Argument = Literal["a", "b", "name"]
NO_ARGUMENTS = {"expand", "combine"}


class Operation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    op: OperationName
    a: str = Field(default="", max_length=120)
    b: str = Field(default="", max_length=120)
    name: str = Field(default="", max_length=1)
    source: str = Field(default="", max_length=1200)

    @model_validator(mode="after")
    def required_arguments(self):
        if self.op not in NO_ARGUMENTS and not self.a.strip():
            raise ValueError("缺少数学对象")
        if self.op in {"claim", "amgm", "attain"} and not self.b.strip():
            raise ValueError("缺少第二个数学对象")
        if self.op == "substitute" and (len(self.name) != 1 or self.name not in "xyabuvt"):
            raise ValueError("请选择 x、y、a、b、u、v 或 t 作为新变量")
        return self


class ProposedOperation(Operation):
    id: str = Field(default="", max_length=12)
    # Arguments resolved from a reference ("那两项") rather than said or selected.
    inferred: list[Argument] = Field(default_factory=list, max_length=3)


class ProposedJudgment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(max_length=40)
    quote: str = Field(max_length=400)
    value: str = Field(default="", max_length=120)
    # What the judgment explains: an operation of this turn, or a step number of the progress.
    operation: str = Field(default="", max_length=12)
    step: int | None = Field(default=None, ge=1, le=60)
    objects: list[str] = Field(default_factory=list, max_length=2)

    @model_validator(mode="after")
    def one_target(self):
        if self.operation and self.step is not None:
            raise ValueError("判断只能指向一个操作或一个步骤")
        return self


class Draft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    a: str = Field(default="", max_length=120)
    b: str = Field(default="", max_length=120)
    name: str = Field(default="", max_length=1)


class Clarification(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["ambiguous_ref", "missing_arg", "other"]
    question: str = Field(max_length=400)
    op: OperationName | None = None
    known: Draft = Field(default_factory=Draft)
    missing: Argument | None = None
    candidates: list[str] = Field(default_factory=list, max_length=6)


class ExplanationProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    intent: Literal["propose", "clarify", "question", "unsupported", "other"]
    reply: str = Field(default="", max_length=1800)
    operations: list[ProposedOperation] = Field(default_factory=list, max_length=6)
    judgments: list[ProposedJudgment] = Field(default_factory=list, max_length=6)
    clarifications: list[Clarification] = Field(default_factory=list, max_length=2)

    @model_validator(mode="before")
    @classmethod
    def incomplete_operations_become_questions(cls, data):
        """An operation the student has not finished stating is a question, not a broken turn."""
        if not isinstance(data, dict):
            return data
        kept, dropped, asks = [], set(), list(data.get("clarifications") or [])
        for item in data.get("operations") or []:
            missing = None
            if isinstance(item, dict):
                op = item.get("op")
                missing = "a" if op not in NO_ARGUMENTS and not str(item.get("a", "")).strip() else \
                    "b" if op in {"claim", "amgm", "attain"} and not str(item.get("b", "")).strip() else \
                    "name" if op == "substitute" and not str(item.get("name", "")).strip() else None
            if missing is None:
                kept.append(item)
                continue
            dropped.add(item.get("id") or object())
            if len(asks) < 2 and not any(isinstance(c, dict) and c.get("op") == item.get("op") for c in asks):
                asks.append({"kind": "missing_arg", "question": "这一步还缺一个式子，能具体说说吗？", "op": item.get("op"),
                             "known": {k: str(item.get(k, "")) for k in ("a", "b", "name")}, "missing": missing})
        judgments = [{**j, "operation": ""} if isinstance(j, dict) and j.get("operation") in dropped else j
                     for j in data.get("judgments") or []]
        return {**data, "operations": kept, "judgments": judgments, "clarifications": asks}

    @model_validator(mode="after")
    def no_question_mutations(self):
        ids = [o.id for o in self.operations if o.id]
        if len(ids) != len(set(ids)):
            raise ValueError("操作标识重复")
        if self.intent == "clarify" and (self.operations or self.judgments):
            self.intent = "propose"  # verified parts plus a question about the rest
        if self.intent == "propose" and not (self.operations or self.judgments) and self.clarifications:
            self.intent = "clarify"
        if self.intent != "propose" and (self.operations or self.judgments):
            raise ValueError("提问和提示不能提交数学步骤或判断")
        if self.intent == "propose" and not (self.operations or self.judgments):
            raise ValueError("缺少操作或判断")
        return self


class ExplanationEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: str = Field(min_length=1, max_length=80)
    revision: int = Field(ge=0)
    kind: Literal["text", "operation", "candidate", "undo", "fork", "switch", "help", "focus", "abandon"]
    text: str = Field(default="", max_length=2000)
    operation: Operation | None = None
    selected: list[str] = Field(default_factory=list, max_length=2)
    branch_id: str | None = Field(default=None, max_length=80)
    step_id: str | None = Field(default=None, max_length=80)
    step_count: int | None = Field(default=None, ge=0, le=60)
    candidate_id: str | None = Field(default=None, max_length=80)
    # How a page operation was made: picked from offered candidates, or written in a template.
    via: Literal["candidate", "template"] | None = None

    @model_validator(mode="after")
    def coherent_event(self):
        if self.kind == "text" and not self.text.strip():
            raise ValueError("请先说说你的思路")
        if (self.kind == "operation") != (self.operation is not None):
            raise ValueError("操作与事件类型不匹配")
        if any(len(item) > 120 for item in self.selected):
            raise ValueError("所选表达式过长")
        if self.kind == "switch" and not self.branch_id:
            raise ValueError("缺少分支")
        if (self.kind == "candidate") != (self.candidate_id is not None):
            raise ValueError("候选与事件类型不匹配")
        return self
