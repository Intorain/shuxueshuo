"""Deterministic D3/D4 fragments from proven selection premises."""

from copy import deepcopy

import sympy as sp

from ...problem_understanding.notation_parser import NotationError
from .premises import FeatureMath, UnknownPremise, parse_expression


def _bindings(indexed, branch, additional_checks=()):
    values = FeatureMath(indexed)
    bindings = {"bound": sp.latex(values.x), "parameter": sp.latex(values.parameter)}
    for check in [*branch["checks"], *additional_checks]:
        bindings.update(check["display_bindings"])
    # Display the coefficient in the original relation, as in the Demo, while
    # the degeneration proof uses the normalized equivalent relation.
    try:
        relation = values.value("relation")
        expression = parse_expression(relation["lhs"]) - parse_expression(relation["rhs"])
        coefficient = sp.Poly(expression, values.x).nth(2)
        bindings["original_coefficient"] = sp.latex(coefficient)
    except (UnknownPremise, NotationError, sp.PolynomialError):
        bindings["original_coefficient"] = bindings.get("coefficient", "未知")
    return bindings


def _message(entry, branch, bindings, case_split):
    messages = entry["messages"]
    if branch["trigger"] == "not_triggered":
        template = messages["not_triggered"]
    elif branch["applicability"] == "not_applicable":
        failed = next(c for c in branch["checks"] if c["status"] == "fails")
        template = messages["fails"].get(failed["check_id"], "前提检查已证明本方法不适用。")
    elif branch["recommendation"] == "superseded":
        template = messages["superseded"]
    elif entry["branch"] == "discriminant":
        template = messages["degenerate" if bindings["may_be_zero"] else "fit"]
    elif entry["branch"] == "separation":
        template = messages["separated" if bindings["already_separated"] else
                            "no_division" if not bindings["requires_division"] else bindings["sign"]]
    elif entry["branch"] == "interval":
        if case_split["status"] == "unknown":
            template = messages["case_split_unknown"]
        elif case_split["reason"] == "no_parameter_cases":
            template = messages["vertex" if bindings["vertex_extremum"] else "endpoints"]
        else:
            template = messages[case_split["reason"]]
    else:
        template = messages["fit"]
    return template.format(**bindings)


def build_fragments(contract, selection, indexed, primary):
    axes = contract["plane_axes"]
    cell = [axes["x"]["values"][indexed[axes["x"]["feature"]]["value"]],
            "free" if indexed[axes["y"]["feature"]]["value"] else "given"]
    values = FeatureMath(indexed)
    base = {"bound": sp.latex(values.x), "parameter": sp.latex(values.parameter)}
    case_split = next(c for c in selection["recommendation_checks"] if c["check_id"] == "interval_case_split")
    branches = {b["branch"]: b for b in selection["branches"]}
    coverage, verdicts, options = {}, {}, []
    for entry in contract["branches"]:
        branch = branches[entry["branch"]]
        unknown = branch["trigger"] == "unknown" or branch["applicability"] == "unknown"
        fit = branch["recommendation"] in ("preferred", "optional")
        # Other cells describe typical method coverage; this target's cell
        # contains only methods actually supported for the current problem.
        coverage[entry["branch"]] = [list(c) for c in entry["plane"] if c != cell]
        if fit:
            coverage[entry["branch"]].append(cell.copy())
        if unknown:
            continue
        verdict = ("not_triggered" if branch["trigger"] == "not_triggered" else
                   "unfit" if branch["applicability"] == "not_applicable" else
                   "superseded" if branch["recommendation"] == "superseded" else "fit")
        extra_checks = [case_split] if entry["branch"] == "interval" else []
        bindings = _bindings(indexed, branch, extra_checks)
        verdicts[entry["branch"]] = {"value": verdict, "message": _message(entry, branch, bindings, case_split)}
        if fit:
            options.append({"route_id": branch["route_id"], "branch": branch["branch"],
                            "method": branch["target"], "recommendation": branch["recommendation"],
                            "route_plan": branch["route_plan"],
                            "message": "详细步骤暂不支持" if branch["route_plan"] == "capability_gap" else "开始解题"})
    rendered_axes = {}
    for axis in ("x", "y"):
        rendered_axes[axis] = {"label": axes[axis]["label"].format(**base),
                               "options": [{k: v.format(**base) for k, v in option.items()}
                                           for option in axes[axis]["options"]]}
    d3 = {"id": "D3", "title": "选择解题方法", "question": "本题落在哪一格？",
          "query": {"op": "method_rule", "from": primary},
          "interaction": {"type": "plane", "title": "方法坐标图", **rendered_axes, "coverage": coverage},
          "expected_answer": {"cell": cell}, "verdicts": verdicts,
          "feedback": {"x": axes["x"]["feedback"][cell[0]].format(**base),
                       "y": axes["y"]["feedback"][cell[1]].format(**base),
                       "method": "这种方法不在这一格里，请从这一格列出的方法中选一种。"},
          "submit_label": "用这种方法解题"}
    d4 = {"id": "D4", "title": "解题路线", "options": options}
    return deepcopy(d3), d4
