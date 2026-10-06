"""Generic model-authored mathematics; validation here is structural, not a proof."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Text = Annotated[str, Field(min_length=1, max_length=2000)]
Formula = Annotated[str, Field(min_length=1, max_length=2000)]
MAX_CANDIDATES = 3


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ModelRecord(Record):
    # Providers sometimes echo input metadata. Discard unknown fields; only the
    # typed mathematical contract can reach state or the UI. Missing/bad required
    # fields still reject the whole turn. User events remain strictly validated.
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


class ProblemSpec(Record):
    id: str
    statement: Text
    conditions: list[Text] = Field(max_length=30)
    target: Text


class MathObject(ModelRecord):
    expression: str = Field(min_length=1, max_length=120)
    latex: Formula


class GeneratedState(ModelRecord):
    expression: Formula
    facts: list[Formula] = Field(max_length=40)
    definitions: list[Formula] = Field(default_factory=list, max_length=20)
    symbols: list[Annotated[str, Field(min_length=1, max_length=16)]] = Field(max_length=20)
    objects: list[MathObject] = Field(max_length=24)
    complete: bool = False


class Choice(ModelRecord):
    # The displayed full action IS the selected action. No hidden solution plan.
    label: str = Field(min_length=1, max_length=1000)


class StepHighlight(ModelRecord):
    kind: Literal["problem", "conclusion"]
    content: str = Field(min_length=1, max_length=1200,
                         description="本步后的等价问题或新增结论，中文配 $...$ 数学；不能提前使用参考解法的未来结果")


class StepChange(ModelRecord):
    before: Formula = Field(description="本次操作涉及的原式或已知关系，只取关键部分，不带数学定界符")
    after: Formula = Field(description="仅执行所选动作得到的式子或关系，不提前执行后续策略")


class Derivation(ModelRecord):
    title: str = Field(min_length=1, max_length=80)
    change: StepChange
    highlight: StepHighlight
    lines: list[Formula] = Field(min_length=1, max_length=16)


class GeneratedTurn(ModelRecord):
    outcome: Literal["initial", "step", "feedback"]
    reply: str = Field(default="", max_length=2000)
    step: Derivation | None = None
    state: GeneratedState | None = None
    candidates: list[Choice] = Field(default_factory=list, json_schema_extra={"maxItems": MAX_CANDIDATES})

    @field_validator("candidates")
    @classmethod
    def limit_choices(cls, candidates):
        # The model ranks actions by suitability. Tolerate overproduction without
        # losing a valid derivation; validate items, deduplicate, then keep the top 3.
        seen, choices = set(), []
        for candidate in candidates:
            if candidate.label not in seen:
                seen.add(candidate.label)
                choices.append(candidate)
        return choices[:MAX_CANDIDATES]

    @model_validator(mode="after")
    def consistent(self):
        if self.outcome == "feedback":
            if self.step is not None or self.state is not None or self.candidates:
                raise ValueError("讨论或错误反馈不能改写数学状态")
            if not self.reply:
                raise ValueError("反馈不能为空")
        else:
            if self.state is None or (self.outcome == "step") != (self.step is not None):
                raise ValueError("推导和数学状态必须完整返回")
            if self.state.complete and self.candidates:
                raise ValueError("完成后不再提供下一步操作")
            if not self.state.complete and not self.candidates and not self.reply:
                raise ValueError("没有候选时需要说明暂未找到下一步")
        return self


class InputOperation(Record):
    # Compatibility with the manual operation composer, not an executor whitelist.
    op: str = Field(min_length=1, max_length=80)
    a: str = Field(default="", max_length=120)
    b: str = Field(default="", max_length=120)
    name: str = Field(default="", max_length=16)
    source: str = Field(default="", max_length=1200)


class GeneratedEvent(Record):
    event_id: str = Field(min_length=1, max_length=80)
    revision: int = Field(ge=0)
    kind: Literal["text", "operation", "candidate", "undo", "fork", "switch", "help", "focus", "abandon", "refresh"]
    text: str = Field(default="", max_length=2000)
    selected: list[Annotated[str, Field(max_length=120)]] = Field(default_factory=list, max_length=2)
    operation: InputOperation | None = None
    branch_id: str | None = Field(default=None, max_length=80)
    step_id: str | None = Field(default=None, max_length=80)
    step_count: int | None = Field(default=None, ge=0, le=60)
    candidate_id: str | None = Field(default=None, max_length=80)
    via: Literal["candidate", "template"] | None = None

    @model_validator(mode="after")
    def coherent(self):
        if self.kind == "text" and not self.text:
            raise ValueError("请先说说你的思路")
        if (self.kind == "operation") != (self.operation is not None):
            raise ValueError("操作与事件不匹配")
        if (self.kind == "candidate") != (self.candidate_id is not None):
            raise ValueError("候选与事件不匹配")
        if self.kind == "switch" and not self.branch_id:
            raise ValueError("缺少分支")
        return self
