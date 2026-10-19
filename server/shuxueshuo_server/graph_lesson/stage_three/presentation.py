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
    before, after = list(bindings["before"]), list(bindings["after"])
    if unit["template"] == "policy":
        policy = bindings["policy"]
        name = "上确界" if policy["bound"] == "sup" else "下确界"
        quantifier = "对所有" if policy["quantifier"] == "∀" else "至少存在一个"
        explanation = (
            f"{quantifier} ${sp.latex(bindings['x'])}$ 使关系成立，比较式 ${sp.latex(bindings['parameter_expression'])}$ "
            f"需要与函数 ${sp.latex(bindings['function'])}$ 的{name}比较。先确定策略，下一步再计算数值和是否取到。"
        )
    elif unit["template"] == "variable_roles":
        quantifier = "对所有" if bindings["quantifier"] == "∀" else "至少存在一个"
        explanation = (
            f"题目要求{quantifier} ${sp.latex(bindings['x'])}\\in {sp.latex(bindings['domain'])}$ 使关系成立。"
            f"因此以 ${sp.latex(bindings['x'])}$ 为变化的字母，先固定所求的 ${sp.latex(bindings['parameter'])}$，"
            "再由整个区间上的条件求它的取值范围。"
        )
    elif unit["template"] == "variable_reorder":
        explanation = (
            f"按 ${sp.latex(bindings['x'])}$ 合并同类项，一次项系数为 ${sp.latex(bindings['slope'])}$，"
            f"常数项为 ${sp.latex(bindings['intercept'])}$。这两个系数都不含变化的字母。"
        )
    elif unit["template"] == "variable_range":
        sign, bounds = bindings["slope_sign"], bindings["range"]
        slope = sp.latex(bindings["slope"])
        if sign in ("positive", "negative"):
            symbol, direction = (">", "递增") if sign == "positive" else ("<", "递减")
            certificate = bindings["slope_certificate"]
            equality = f"={sp.latex(certificate['square'])}" if "square" in certificate else ""
            explanation = f"一次项系数 ${slope}{equality}{symbol}0$，函数在给定区间上严格{direction}。"
        elif sign == "zero":
            explanation = "一次项系数恒为零，函数为常数，在区间内部也能取得该值。"
        else:
            explanation = (f"一次项系数 ${slope}$ 不能统一判定为严格正或严格负。"
                           "一次函数在闭区间上的确界由两端决定，保留两个端点条件。")
        label = "上确界" if bounds["bound"] == "sup" else "下确界"
        for candidate in bounds["candidates"]:
            after.append(candidate["value"])
            location = f"${sp.latex(bindings['x'])}={sp.latex(candidate['point'])}$"
            attained = "能取得" if candidate["attained"] else "只能趋近、不能取得"
            qualifier = "候选值" if len(bounds["candidates"]) > 1 else ""
            explanation += f"{label}{qualifier}来自 {location}，为 ${sp.latex(candidate['value'])}$，{attained}。"
    elif unit["template"] == "variable_conditions":
        before.extend(bindings["conditions"])
        after = [*bindings["normalized"], *bindings["solutions"], *after]
        logical, operation = ("每个条件都成立", "交集") if bindings["combiner"] == "all" else ("至少一个条件成立", "并集")
        explanation = (f"按确界及其是否取得建立关于 ${sp.latex(bindings['parameter'])}$ 的条件，"
                       "移项并按非零常数作等价变形，分别求解。")
        if len(bindings["conditions"]) > 1:
            explanation += f"原量词要求{logical}，因此各解集取{operation}。"
        explanation += "所得范围随后与其余题设求交，并独立验证边界。"
    elif unit["template"] in ("divided", "negative_divided"):
        negative = unit["template"] == "negative_divided"
        sign, noun, direction = ("<", "负", "反向") if negative else (">", "正", "不变")
        explanation = (
            f"在给定范围内，除数 ${sp.latex(bindings['divisor'])}{sign}0$。"
            f"将参数项移到一边，再两边同除以这个{noun}数，不等号{direction}，得到等价关系。"
        )
    elif unit["template"] in ("numeric_range", "range_evidence", "case_linear_range"):
        bounds = bindings["range"]
        details = []
        for key, label in (("inf", "下确界"), ("sup", "上确界")):
            attained = "能取得" if bounds[key + "_attained"] else "不能取得"
            details.append(f"{label}为 ${sp.latex(bounds[key])}$，{attained}")
        explanation = (
            f"只在题目给定的 ${sp.latex(bindings['domain'])}$ 上求值，"
            "比较端点的值或极限，并检查区间内的转折点。" + "；".join(details) + "。"
        )
        if unit["template"] == "case_linear_range" and bindings["kind"] == "constant":
            explanation = f"代入后函数为常数 ${sp.latex(bounds['inf'])}$，在原区间上处处取得该值。"
        if unit["template"] == "range_evidence":
            for point in bindings["endpoints"]:
                if point["attained"]:
                    explanation += (f"在 ${sp.latex(bindings['x'])}={sp.latex(point['point'])}$ 处，"
                                    f"函数值为 ${sp.latex(point['value'])}$。")
                else:
                    explanation += (f"在定义域内，当 ${sp.latex(bindings['x'])}\\to {sp.latex(point['point'])}$ 时，"
                                    f"函数趋近 ${sp.latex(point['value'])}$。")
            for point in bindings["points"]:
                explanation += (f"区间内转折点为 ${sp.latex(bindings['x'])}={sp.latex(point['point'])}$，"
                                f"函数值 ${sp.latex(point['value'])}$ 可取得。")
    elif unit["template"] == "inverse_range":
        sign = "正" if bindings["sign"] == "positive" else "负"
        explanation = (
            f"分母在所求范围内始终为{sign}且不为零。倒数函数在这个同号范围内递减，"
            "上下端逆序取倒数；无穷端变成不能取得的 0，端点是否取得随对应端点保留。"
        )
    elif unit["template"] == "interval_cases":
        after.extend(case["condition"] for case in bindings["cases"])
        explanation = ("按二次项系数是否为零、开口方向以及对称轴与端点的位置确定以下情况。"
                       "这些情况互不重叠并覆盖全部实数参数，分别求确界后再合并参数范围。")
    elif unit["template"] == "classified_range":
        bounds = bindings["range"]
        key = bounds["bound"]
        value = bounds[key]
        label = "上确界" if key == "sup" else "下确界"
        attained = "能取得" if bounds[key + "_attained"] else "不能取得"
        after.append(value)
        explanation = f"二次项系数为 ${sp.latex(bindings['coefficient'])}$。"
        if bindings["vertex"] is not None:
            explanation += f"对称轴为 ${sp.latex(bindings['x'])}={sp.latex(bindings['vertex'])}$。"
        explanation += (f"结合当前条件与区间 ${sp.latex(bindings['domain'])}$，"
                        f"由端点极限和区间内顶点比较得到{label} ${sp.latex(value)}$，{attained}。")
    elif unit["template"] == "interval_merge":
        before.extend(bindings["solutions"])
        details = [f"${sp.latex(case['condition'])}$ 时得到 ${sp.latex(solution)}$"
                   for case, solution in zip(bindings["cases"], bindings["solutions"], strict=True)]
        explanation = "；".join(details) + "。把各情况的参数集取并集，随后独立验证并检查边界。"
    elif unit["template"] == "endpoint_bounds":
        bounds = bindings["range"]
        label = "上确界" if bounds["bound"] == "sup" else "下确界"
        opening = "向上" if bounds["bound"] == "sup" else "向下"
        details = []
        for candidate in bounds["candidates"]:
            attained = "端点在区间中" if candidate["attained"] else "端点不在区间中，只能趋近"
            details.append(f"${sp.latex(bindings['x'])}={sp.latex(candidate['point'])}$ 时的候选值为 ${sp.latex(candidate['value'])}$，{attained}")
            after.append(candidate["value"])
        explanation = (
            f"二次函数开口{opening}，所需{label}由两个端点候选决定，无需按含参对称轴分类。"
            + "；".join(details) + "。"
        )
    elif unit["template"] == "interval_conditions":
        before.extend(bindings["conditions"])
        after = [*bindings["solutions"], *after]
        if len(bindings["conditions"]) == 1:
            explanation = "将已选量词策略应用到确界及其可达性，得到并解出下面的参数条件。"
        else:
            logical, operation = ("两端条件都要满足", "交集") if bindings["combiner"] == "all" else ("至少一端条件满足", "并集")
            explanation = (
                f"将已选量词策略应用到端点候选及其可达性，{logical}。"
                f"分别解出下列参数条件后取{operation}；开放端点的极限值不当作已取得的最值。"
            )
        if frame.get("case_path"):
            explanation += "再与当前情况的参数范围取交集，保留同时满足的参数。"
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
        before=before,
        after=after,
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
        + read("presentation-registry")["boundary_steps"][updated["method"]],
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


def _goal_math(value, *, set_value=False):
    """Decode an already certified value; do not solve for its bound here."""
    if not isinstance(value, dict) or "exact" not in value:
        raise ValueError("presentation.goal_exact_value_required")
    decoded = decode_value(value["exact"])
    if not isinstance(decoded, sp.Set if set_value else sp.Expr):
        raise TypeError("presentation.goal_math_type")
    if value.get("expression") != sp.sstr(decoded) or value.get("latex") != sp.latex(decoded):
        raise ValueError("presentation.goal_display_mismatch")
    return decoded


def append_goal_finalization(state, answer, evidence):
    """Append a checked goal conclusion without recomputing extrema.

    Range closure retains its existing record and adds no card. Extremum closure
    requires the independent boundary card first and uses only the supplied exact
    bound, membership evidence and typed answer.
    """
    updated = deepcopy(state)
    records = updated.setdefault("finalization", deepcopy(updated["trajectory"]["finalization"]))
    kind = answer.get("kind")
    if kind == "find_range":
        if answer.get("status") != "set":
            raise ValueError("presentation.goal_answer_invalid")
        records.append({"capability": "finalize_goal", "answer": deepcopy(answer)})
        updated["trajectory"]["finalization"] = deepcopy(records)
        return updated
    if kind not in ("find_minimum", "find_maximum"):
        raise ValueError("presentation.goal_kind_unsupported")
    status = answer.get("status")
    minimum = kind == "find_minimum"
    direction = "lower" if minimum else "upper"
    unbounded = "unbounded_below" if minimum else "unbounded_above"
    checks = evidence.get("checks") if isinstance(evidence, dict) else None
    if (
        not checks or not all(check.get("passed") is True for check in checks)
        or evidence.get("kind") != "goal_closure" or evidence.get("goal_kind") != kind
        or evidence.get("status") != status or evidence.get("direction") != direction
        or status not in ("attained", "not_attained", unbounded, "empty_feasible_set")
    ):
        raise ValueError("presentation.goal_evidence_unverified")
    fragments = updated["fragments"]
    if (not fragments or fragments[-1]["display_unit"] != "boundary"
            or updated.get("verification", {}).get("status") != "verified"):
        raise ValueError("presentation.goal_independent_boundary_required")
    boundary_sources = {f"/finalization/{index}" for index, record in enumerate(records)
                        if record.get("capability") == "endpoint_check"
                        and record.get("postconditions")
                        and all(check.get("passed") is True for check in record["postconditions"])}
    if not boundary_sources.intersection(fragments[-1]["source_refs"]):
        raise ValueError("presentation.goal_independent_boundary_required")
    feasible = _goal_math(evidence.get("feasible_set"), set_value=True)
    if evidence["feasible_set"]["exact"] != updated.get("feasible_set_exact"):
        raise ValueError("presentation.goal_feasible_set_mismatch")
    if any(record.get("capability") == "finalize_goal" for record in records):
        raise ValueError("presentation.goal_already_finalized")
    name, bound_name = ("最小值", "下确界") if minimum else ("最大值", "上确界")
    after, displayed = [], None
    if status == "empty_feasible_set":
        valid = (evidence.get("empty") is True and feasible is sp.S.EmptySet
                 and all(evidence.get(key) is None for key in ("bounded", "bound", "member", "attained"))
                 and "value" not in answer and "bound" not in answer)
        explanation = f"完整可行集为空，没有满足题设的参数，因此{name}不存在。"
    elif status == unbounded:
        bound = _goal_math(evidence.get("bound"))
        valid = (evidence.get("empty") is False and evidence.get("bounded") is False
                 and evidence.get("member") is False and evidence.get("attained") is False
                 and bound is (-sp.oo if minimum else sp.oo)
                 and "value" not in answer and "bound" not in answer)
        explanation = f"完整可行集已通过独立验证。可行集没有{'下' if minimum else '上'}界，因此{name}不存在。"
    else:
        attained = status == "attained"
        displayed = answer.get("value" if attained else "bound")
        bound = _goal_math(displayed)
        valid = (evidence.get("empty") is False and evidence.get("bounded") is True
                 and evidence.get("member") is attained and evidence.get("attained") is attained
                 and displayed == evidence.get("bound") and not bound.free_symbols
                 and bound.is_real is True and bound.is_finite is True)
        after.append(bound)
        membership = "属于" if attained else "不属于"
        explanation = (f"完整可行集已通过独立验证。{bound_name}为 ${sp.latex(bound)}$，该界{membership}可行集。"
                       + (f"因此{name}为 ${sp.latex(bound)}$，能够取得。" if attained else
                          f"因此{name}不存在，只能趋近该{bound_name}。"))
    if not valid:
        raise ValueError("presentation.goal_answer_evidence_mismatch")
    used_basis = ["function-range-extrema#attainability"]
    operation = {
        "capability": "finalize_goal", "public_ref": None,
        "answer": deepcopy(answer), "outputs": {"answer": deepcopy(answer), "evidence": deepcopy(evidence)},
        "operations": ["goal_finalization"], "used_basis": used_basis,
        "postconditions": [*deepcopy(checks), {"kind": "goal_answer_evidence_match", "passed": True}],
    }
    index = len(records)
    records.append(operation)
    updated["trajectory"]["finalization"] = deepcopy(records)
    fragment = make_fragment(
        updated, unit_id="goal_finalization",
        method_ref=updated["method"] + "#" + read("presentation-registry")["boundary_steps"][updated["method"]],
        template="goal_minimum" if minimum else "goal_maximum", before=[feasible], after=after,
        source_refs=[f"/finalization/{index}"], used_basis=used_basis, explanation=explanation,
    )
    fragment["before"][0]["exact"] = deepcopy(evidence["feasible_set"]["exact"])
    if displayed is not None:
        fragment["after"][0]["exact"] = deepcopy(displayed["exact"])
    fragment["math_step_sha256"] = math_step_hash(fragment)
    fragments.append(fragment)
    updated["trajectory"]["math_steps"].append({
        "step_id": fragment["step_id"], "math_step_sha256": fragment["math_step_sha256"],
        "source_refs": fragment["source_refs"],
        "file": f"math-steps/{updated['route_id']}/{fragment['step_id']}.json",
    })
    return updated
