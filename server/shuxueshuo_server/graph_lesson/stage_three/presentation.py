"""Freeze readable mathematical fragments at explicit contract boundaries."""

from copy import deepcopy

import sympy as sp

from ...problem_understanding.identity import revision
from .execution_contracts import read
from .trajectory import decode_value


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
    case_path=(),
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
        "case_path": list(case_path),
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
    elif unit["template"] == "opening":
        opening = bindings["after"][0]
        if not opening.free_symbols and (opening.lhs - opening.rhs).is_positive is True:
            if bindings.get("strict"):
                explanation = "二次项系数确定为正且非零。原式需恒严格大于零，因此图像必须完全位于横轴上方，不能相切。"
        else:
            positive_relation = (sp.Gt if bindings["strict"] else sp.Ge)(bindings["expression"], 0, evaluate=False)
            boundary = "严格不等式不允许图像碰到横轴" if bindings["strict"] else "非严格不等式允许图像与横轴相切"
            explanation = (
                f"按不等号方向把当前关系写成 ${sp.latex(positive_relation)}$。"
                f"在二次项系数不为零的情况下，需要开口条件 ${sp.latex(opening)}$，再与判别式条件联立；{boundary}。"
            )
    elif unit["template"] == "case_basis":
        explanation = (
            f"按原不等号方向移项后，与零比较的差式中二次项系数为 ${sp.latex(bindings['coefficient'])}$。"
            f"先找出使它为零的全部 ${sp.latex(bindings['parameter'])}$ 值，分别检验；"
            "剩余参数对应非退化二次式。这些情况互不重叠并覆盖全部实数参数。"
        )
    elif unit["template"] == "degenerate_case":
        verdict = "满足原题的全称条件，保留这个参数值" if bindings["holds"] else "不满足原题的全称条件，排除这个参数值"
        reason = (
            "一次项系数也为零，只需判断常数关系的真假"
            if bindings["linear_coefficient"].is_zero is True
            else "一次项系数不为零，一次式在全体实数上无上界也无下界，因此不可能始终满足同一方向的不等式"
        )
        explanation = (
            f"把 ${sp.latex(bindings['parameter'])}={sp.latex(bindings['value'])}$ 代回原不等式，"
            f"二次项消失，得到下列一次式或常数关系。{reason}：{verdict}。"
        )
    case_path = frame.get("case_path", [])
    if case_path:
        case = decode_value(frame["bindings"]).get("case")
        if case and isinstance(case.get("condition"), sp.Basic):
            explanation = (
                f"在 ${sp.latex(case['condition'])}$ 的情况下，"
                + (explanation or read("presentation-registry")["templates"][unit["template"]]["explanation"])
            )
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
        case_path=case_path,
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
