"""Freeze readable mathematical fragments at explicit contract boundaries."""

from copy import deepcopy

import sympy as sp

from ...problem_understanding.identity import revision
from .execution_contracts import read


def math_step_hash(fragment):
    return revision(
        {
            "content": {
                key: value
                for key, value in fragment.items()
                if key != "math_step_sha256"
            },
            "revisions": fragment["revisions"],
        }
    )


def _math(value):
    if not isinstance(value, sp.Basic):
        raise TypeError("presentation.math_object_required")
    return {"expression": sp.sstr(value), "display": sp.latex(value)}


def make_fragment(
    state,
    *,
    unit_id,
    method_ref,
    template,
    before=(),
    after=(),
    source_refs=(),
    used_basis=(),
    explanation=None,
):
    settings = read("presentation-registry")["templates"][template]
    ordinal = len(state["fragments"]) + 1
    target_key = revision(state["target_ref"])[:10]
    value = {
        "contract": "graph-math-step/v1",
        "lesson_version": state["lesson_version"],
        "run_id": state["run_id"],
        "target_ref": state["target_ref"],
        "route_id": state["route_id"],
        "step_id": f"{target_key}-{state['route_id']}-{ordinal:03d}-{unit_id}",
        "ordinal": ordinal,
        "method_ref": method_ref,
        "source_refs": list(source_refs),
        "case_path": [],
        "title": settings["title"],
        "before": [_math(v) for v in before],
        "after": [_math(v) for v in after],
        "explanation": explanation or settings["explanation"],
        "premise_refs": list(state.get("premise_refs", [])),
        "used_basis": sorted(set(used_basis)),
        "local_check": "passed",
        "revisions": deepcopy(state["revisions"]),
        "display_unit": unit_id,
    }
    value["math_step_sha256"] = math_step_hash(value)
    return value


def render_unit(state, frame, step, unit, bindings, source_refs, used_basis):
    explanation = None
    if unit["template"] == "policy":
        policy = bindings["policy"]
        name = "上确界" if policy["bound"] == "sup" else "下确界"
        explanation = (
            f"对所有 ${sp.latex(bindings['x'])}$ 均成立，参数式 ${sp.latex(bindings['parameter_expression'])}$ "
            f"需要与函数 ${sp.latex(bindings['function'])}$ 的{name}比较。先确定策略，下一步再计算数值和是否取到。"
        )
    elif unit["template"] == "square_range":
        explanation = (
            f"${sp.latex(bindings['function'])}={sp.latex(bindings['square'])}$。平方非负，"
            f"${sp.latex(bindings['x'])}={sp.latex(bindings['vertex'])}$ 在定义域中，"
            f"回代得到取等值 ${sp.latex(bindings['extremum'])}$。"
        )
    elif unit["template"] == "opening" and bindings.get("strict"):
        explanation = "二次项系数确定为正且非零。原式需恒严格大于零，因此图像必须完全位于横轴上方，不能相切。"
    return make_fragment(
        state,
        unit_id=unit["id"],
        method_ref=frame["method"] + "#" + step["id"],
        template=unit["template"],
        before=bindings["before"],
        after=bindings["after"],
        source_refs=source_refs,
        used_basis=used_basis,
        explanation=explanation,
    )


def append_boundary(state, evidence, *, feasible_set=None):
    """Add a separate fragment only after the caller's independent boundary checks."""
    updated = deepcopy(state)
    checks = evidence.get(
        "points", evidence.get("checks", evidence.get("boundaries", []))
    )
    if evidence.get("status") not in ("verified", "passed", "ok"):
        raise ValueError("presentation.boundary_unverified")
    operation = {
        "capability": "endpoint_check",
        "public_ref": None,
        "outputs": deepcopy(evidence),
        "operations": ["endpoint_check"],
        "used_basis": ["function-range-extrema#attainability"],
        "postconditions": [{"kind": "independent_boundary", "passed": True}],
    }
    records = updated.setdefault(
        "finalization", deepcopy(updated["trajectory"]["finalization"])
    )
    index = len(records)
    records.append(operation)
    updated["trajectory"]["finalization"] = deepcopy(records)
    description = read("presentation-registry")["templates"]["boundary"]["explanation"]
    if not checks:
        description += "当前可行集没有有限边界，边界检查为空。"
    else:
        details = []
        for check in checks:
            value = check["point"]["latex"]
            retained = "保留" if check["included"] else "排除"
            outcome = "满足" if check["holds"] else "不满足"
            details.append(f"参数等于 ${value}$ 时{outcome}原题条件，该边界{retained}")
        description += "；".join(details) + "。"
    fragment = make_fragment(
        updated,
        unit_id="boundary",
        method_ref=updated["method"]
        + "#"
        + ("merge" if updated["method"] == "method-discriminant" else "restore"),
        template="boundary",
        after=([feasible_set] if feasible_set is not None else []),
        source_refs=[f"/finalization/{index}"],
        used_basis=operation["used_basis"],
        explanation=description,
    )
    updated["fragments"].append(fragment)
    updated["trajectory"]["math_steps"].append(
        {
            "step_id": fragment["step_id"],
            "math_step_sha256": fragment["math_step_sha256"],
            "source_refs": fragment["source_refs"],
            "file": f"math-steps/{updated['route_id']}/{fragment['step_id']}.json",
        }
    )
    return updated
