"""LLM proposals for the initial board; isolated exact checks before offering a choice.

No problem-specific candidate enumeration. The existing mathematics kernel is
still the Q12 pilot; later-state generation and a general kernel are separate work.
"""

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..llm import DeepSeekTutor
from .contracts import Operation
from .math import MathIssue

PROMPT = Path(__file__).parent / "prompts/candidates.jinja"
CAPABILITIES = {
    "substitute": "用新变量 name 定义表达式 a，当前核验器支持对目标分母整体换元。多个相关对象可连续定义。",
    "evaluate": "根据已知条件计算表达式 a 的常数值；只给 a，结果由代码计算。",
    "claim": "核验等式 a=b 是否由已知条件恒成立。",
    "multiply": "给整个目标表达式乘 a；a 必须恒等于 1，程序随后展开。",
    "expand": "展开当前目标式，无参数。",
    "combine": "合并当前目标式中同分母的项，无参数。",
    "amgm": "对两个正表达式 a,b 应用基本不等式；不要求立即得到常数下界。",
    "attain": "检验取等关系 a=b；没有已证下界时只能核验候选点。",
}


class CandidateProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Validate each candidate separately so one malformed choice cannot discard the rest.
    candidates: list[dict] = Field(default_factory=list, max_length=8)


class CandidateSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operations: list[Operation] = Field(min_length=1, max_length=3)


class CandidateGenerator(DeepSeekTutor):
    proposal_type = CandidateProposal
    max_tokens = 2200

    @property
    def prompt_version(self):
        return "candidates:" + hashlib.sha256(PROMPT.read_bytes()).hexdigest()[:10]

    def prompts(self, projection):
        return [{"role": "system", "content": PROMPT.read_text()},
                {"role": "user", "content": json.dumps(projection, ensure_ascii=False)}]


def projection(context):
    return {
        "problem": {"statement": context.problem.statement, "conditions": context.problem.conditions,
                    "target": context.problem.target},
        "state": context.branch.state.view(),
        "verified_steps": [{"operation": s["operation"], "lines": s["lines"]} for s in context.branch.steps],
        "capabilities": CAPABILITIES,
    }


def verify(context, proposal):
    accepted, rejected, seen = [], [], set()
    for raw in proposal.candidates:
        try:
            spec = CandidateSpec.model_validate(raw)
            trial = deepcopy(context.branch.state)
            keys, echo, operations = [], [], []
            for op in spec.operations:
                if echo:
                    echo.append({"text": "，"})
                if op.op == "claim":
                    echo.append({"text": "核对 "})
                echo.extend(trial.describe(op))
                result = trial.execute(op)
                if result["key"] is None or result["key"] in keys:
                    raise MathIssue("这一步没有带来新的变化。")
                keys.append(result["key"])
                operations.append(op.model_copy(update={"source": ""}))
            key = tuple(keys)
            if key in seen:
                raise MathIssue("候选重复。")
            seen.add(key)
            label = "".join(s.get("text", s.get("math", "")) for s in echo)
            accepted.append({"id": str(uuid4()), "echo": echo, "text": label, "keys": keys,
                             "operations": [op.model_dump() for op in operations]})
        except (MathIssue, ValidationError, ValueError, TypeError) as exc:
            rejected.append({"proposal": raw, "reason": str(exc)})
    # Prefer one complete related substitution over separate buttons for its parts.
    groups = [set(c["keys"]) for c in accepted if len(c["operations"]) > 1
              and all(op["op"] == "substitute" for op in c["operations"])]
    accepted = [c for c in accepted if not (len(c["operations"]) == 1
                and c["operations"][0]["op"] == "substitute"
                and any(set(c["keys"]) < group for group in groups))]
    return {"id": str(uuid4()), "status": "ready" if accepted else "empty",
            "candidates": accepted, "rejected": rejected, "raw": proposal.model_dump()}
