"""Declarative prose rendering and registered, pure mathematical preparation."""

import re
from string import Formatter

import sympy as sp

from .capabilities.ranges import reciprocal_coefficients
from .math_values import (
    BOUND_EXPLANATION,
    BOUND_TEX,
    EXTREMUM_TEX,
    math_value,
    polynomial_extrema_attained,
)
from .presentation_intervals import (
    cases_view,
    classified_view,
    conditions_view,
    linear_view,
    merge_view,
)


def _lookup(values, path):
    result = values
    for part in path.split("."):
        result = result[part]
    return result


class _MathFormatter(Formatter):
    def get_field(self, field_name, args, kwargs):
        value = _lookup(kwargs, field_name)
        return (math_value(value)["latex"] if isinstance(value, sp.Basic) else value), field_name


_FORMATTER = _MathFormatter()


def _render(node, values):
    if isinstance(node, str):
        return _FORMATTER.vformat(node, (), values)
    if isinstance(node, list):
        return "".join(_render(item, values) for item in node)
    if "if" in node:
        return _render(node["then"] if _lookup(values, node["if"]) else node.get("else", ""), values)
    if "select" in node:
        key = str(_lookup(values, node["select"]))
        return _render(node["cases"].get(key, node.get("default", "")), values)
    return node.get("separator", "").join(
        _render(node["body"], {**values, node["as"]: item}) for item in _lookup(values, node["for"])
    )


def _variable_range(values):
    bounds = values["range"]
    return {"after": [*values["after"], *(item["value"] for item in bounds["candidates"])],
            "square": values["slope_certificate"].get("square"),
            "has_square": "square" in values["slope_certificate"],
            "multiple": len(bounds["candidates"]) > 1}


def _variable_conditions(values):
    return {"before": [*values["before"], *values["conditions"]],
            "after": [*values["normalized"], *values["solutions"], *values["after"]],
            "multiple": len(values["conditions"]) > 1}


def _numeric_range(values):
    return {"constant": values.get("kind") == "constant"}


def _interval_cases(values):
    return {"after": [*values["after"], *(case["condition"] for case in values["cases"])]}


def _classified_range(values):
    bounds = values["range"]
    key = bounds["bound"]
    return {"after": [*values["after"], bounds[key]], "bound_value": bounds[key],
            "bound_attained": bounds[key + "_attained"], "has_vertex": values["vertex"] is not None}


def _interval_merge(values):
    return {"before": [*values["before"], *(item for result in values["results"]
                                           for item in result["outputs"]["conditions"])],
            "after": [*values["solutions"], *values["after"]],
            "case_solutions": [{"condition": case["condition"], "solution": solution}
                               for case, solution in zip(values["cases"], values["solutions"], strict=True)]}


def _variable_case_merge(values):
    """The linear case summary only needs the case conditions and solved sets."""
    return {"before": [*values["before"], *values["solutions"]],
            "case_solutions": [{"condition": case["condition"], "solution": solution}
                               for case, solution in zip(values["cases"], values["solutions"], strict=True)]}


def _endpoint_bounds(values):
    return {"after": [*values["after"], *(item["value"] for item in values["range"]["candidates"])]}


def _interval_conditions(values):
    return {"before": [*values["before"], *values["conditions"]],
            "after": [*values["solutions"], *values["after"]], "multiple": len(values["conditions"]) > 1}


def _opening(values):
    opening = values["after"][0]
    return {"opening": opening, "fixed_positive": not opening.free_symbols and (opening.lhs - opening.rhs).is_positive is True,
            "positive_relation": (sp.Gt if values["strict"] else sp.Ge)(values["expression"], 0, evaluate=False)}


def _degenerate_case(values):
    return {"constant": values["linear_coefficient"].is_zero is True}


def _solution_view(values):
    symbols = set().union(*(item.free_symbols for item in values["before"] if isinstance(item, sp.Basic)))
    return {"solution_set": values["after"][-1], "solution_symbol": symbols.pop() if len(symbols) == 1 else None}


def _separation_naming(values):
    return {"named": bool(values["function_name"]) and values["function"].has(values["x"]),
            "operator_tex": {"<=": r"\leq", "<": "<", ">=": r"\geq", ">": ">"}[values["operator"]],
            "divisor_negative": bool(values.get("divisor", sp.S.One).is_negative)}


_OPERATOR_TEX = {"<=": r"\leq", "<": "<", ">=": r"\geq", ">": ">"}
_MIRROR = {"<=": ">=", "<": ">", ">=": "<=", ">": "<"}
_WEAK = {"<": "<=", ">": ">=", "<=": "<=", ">=": ">="}


def _policy_view(values):
    """The quantified relation and the bound comparison it reduces to, as the policy states them.

    Without an attainment proof, a universal strict relation reads as the weak
    bound comparison with an equality caveat. Proven extrema keep strictness.
    A function the method named earlier is referred to by that name.
    """
    policy, function, expression, x = values["policy"], values["function"], values["parameter_expression"], values["x"]
    operator, universal = policy["operator"], policy["quantifier"] == "∀"
    numeric = not expression.free_symbols
    attained = polynomial_extrema_attained(function, x, values["domain"])
    shown = _WEAK[operator] if universal and not attained else operator
    x_tex = math_value(x)["latex"]
    named = bool(values["function_name"]) and function.has(x)
    body = f"{values['function_name']}({x_tex})" if named else math_value(function)["latex"]
    bound_body = rf"\left({body}\right)" if not function.is_Atom and not named else body
    target = math_value(expression)["latex"]

    def compare(left, op):
        return (f"{left} {_OPERATOR_TEX[_MIRROR[op]]} {target}" if numeric
                else f"{target} {_OPERATOR_TEX[op]} {left}")
    extreme = rf"{bound_body}_{{{(EXTREMUM_TEX if attained else BOUND_TEX)[policy['bound']]}}}"
    definition = f"{body}={math_value(function)['latex']}" if named and values["define_name"] else ""
    return {"policy_relation": compare(body, operator), "policy_definition": definition,
            "policy_condition": compare(extreme, shown), "policy_condition_short": compare(extreme, shown),
            "policy_universal": universal, "policy_low": policy["bound"] == "inf", "policy_strict": policy["strict"],
            "policy_attained": attained, "bound_explanation": "" if attained else BOUND_EXPLANATION}


def _hook_view(values):
    """The hook ``ax+b/x+c`` as a derivation: AM-GM at the turn, the two monotone pieces, the domain's side.

    The turn and the endpoint values come from the capability; this only splits
    the half axis at the turn and writes the equivalent formulas.
    """
    function, x, domain, turn = values["function"], values["x"], values["domain"], values["turn"]
    a, c, b = reciprocal_coefficients(function, x)
    point, minimum = turn["point"], turn["minimum"]
    positive = point.is_positive is True
    half = sp.Interval.open(0, sp.oo) if positive else sp.Interval.open(-sp.oo, 0)
    left = sp.Interval.Lopen(half.start, point) if positive else sp.Interval(half.start, point, True, False)
    right = sp.Interval.Ropen(point, half.end) if positive else sp.Interval(point, half.end, False, True)
    side = ("left" if (domain.sup - point).is_nonpositive
            else "right" if (domain.inf - point).is_nonnegative else "both")
    label = (f"{values['function_name']}({math_value(x)['latex']})" if values["function_name"]
             else math_value(function)["latex"])
    peak_label = label if values["function_name"] else rf"\left({label}\right)"

    def tex(value):
        return {sp.oo: r"+\infty", -sp.oo: r"-\infty"}.get(value, math_value(value)["latex"])

    def call(at):
        if values["function_name"]:
            return rf"{values['function_name']}\left({tex(at)}\right)"
        return rf"\left.{label}\right|_{{{math_value(x)['latex']}={tex(at)}}}"

    # Both terms are positive on the half axis after multiplying by ``sign``, so
    # h = sign·(p + q) + c and AM-GM bounds p + q by 2·sqrt(p·q) with p = q at the turn.
    sign = 1 if (a * point).is_positive else -1
    p, q = sign * a * x, sign * b / x
    shift = "" if c == 0 else ("+" if c.is_positive else "") + math_value(c)["latex"]
    grouped = math_value(p + q)["latex"]
    product = r"\cdot ".join(rf"\left({math_value(t)['latex']}\right)" if t.could_extract_minus_sign()
                             else math_value(t)["latex"] for t in (p, q))
    bound = rf"2\sqrt{{{product}}}"
    amgm = (rf"{label}={grouped}{shift} \geq {bound}{shift}" if sign > 0
            else rf"{label}=-\left({grouped}\right){shift} \leq -{bound}{shift}")
    amgm += f"={tex(turn['value'])}"
    x_tex = math_value(x)["latex"]
    ends = []
    for row in values["endpoints"]:
        at, value = row["point"], row["value"]
        if row["attained"]:
            ends.append({"attained": True, "equation": f"{call(at)}={tex(value)}"})
            continue
        side_mark = "" if at in (sp.oo, -sp.oo) else ("^{+}" if at == domain.inf else "^{-}")
        ends.append({"attained": False, "approach": rf"{x_tex}\to {tex(at)}{side_mark}",
                     "limit": rf"{label}\to {tex(value)}"})
    return {"hook_label": label, "hook_left": left, "hook_right": right, "hook_minimum": minimum,
            "hook_turn": rf"\left({math_value(point)['latex']},\,{math_value(turn['value'])['latex']}\right)",
            "hook_side": side, "hook_relation": f"{x_tex}>0" if positive else f"{x_tex}<0",
            "hook_positive": [math_value(t)["latex"] for t in (p, q) if t != x], "hook_amgm": amgm,
            "hook_equal": math_value(sp.Eq(p, q, evaluate=False))["latex"],
            "hook_peak": f"{peak_label}_{{{EXTREMUM_TEX['inf' if minimum else 'sup']}}}={call(point)}={tex(turn['value'])}",
            "hook_ends": ends}


def _affine_substitution_view(values):
    """Keep the original function's argument while displaying its substituted expression."""
    original = math_value(values["original_expression"])["latex"]
    variable = math_value(values["original_variable"])["latex"]
    label = f"{values['function_name']}({variable})" if values["function_name"] else original
    return {"affine_original": f"{label}={original}" if values["function_name"] else original,
            "affine_identity": f"{label}={math_value(values['expression'])['latex']}"}


def _affine_restore_view(values):
    """Select certified points and attainment; never infer an extremum from the turn alone."""
    points, turn = values["points"], values["turn"]
    rows = [*points, *(row for row in values["endpoints"]
                       if not any(row["point"] == point["point"] for point in points))]
    turn_attained = turn is not None and turn.get(
        "attained", any(row["point"] == turn["point"] and row["attained"] for row in points))
    bounds = values["range"]
    return {"affine_restored_rows": rows, "affine_turn_outside": turn is not None and not turn_attained,
            "affine_bounds": [{"low": key == "inf", "value": bounds[key],
                               "finite": bounds[key] not in (-sp.oo, sp.oo),
                               "attained": bounds[key + "_attained"]} for key in ("inf", "sup")]}


# Preparation functions only select supplied evidence or construct equivalent
# mathematical objects. They contain no prose and never perform solving.
PREPARERS = {
    "variable_range": _variable_range, "variable_conditions": _variable_conditions,
    "variable_cases": _interval_cases, "variable_case_merge": _variable_case_merge,
    "numeric_range": _numeric_range, "interval_cases": lambda v: {**_interval_cases(v), **cases_view(v)},
    "classified_range": lambda v: {**_classified_range(v), **classified_view(v)},
    "interval_merge": lambda v: {**_interval_merge(v), **merge_view(v)},
    "endpoint_bounds": _endpoint_bounds, "linear_case": lambda v: {**_numeric_range(v), **linear_view(v)},
    "interval_conditions": lambda v: {**_interval_conditions(v), **conditions_view(v)},
    "opening": _opening, "degenerate_case": _degenerate_case, "separation_naming": _separation_naming,
    "policy_view": _policy_view, "hook_view": _hook_view, "solution_view": _solution_view,
    "affine_substitution_view": _affine_substitution_view, "affine_restore_view": _affine_restore_view,
}
PREPARED_FIELDS = {
    "variable_range": {"after", "square", "has_square", "multiple"},
    "variable_conditions": {"before", "after", "multiple"},
    "variable_cases": {"after"}, "variable_case_merge": {"before", "case_solutions"},
    "numeric_range": {"constant"},
    "interval_cases": {"after", "case_rows", "opening", "axis", "function_label", "bound_name"},
    "classified_range": {"after", "bound_value", "bound_attained", "has_vertex", "case_condition", "axis_relation",
                         "leading_relation", "monotone", "function_label", "extreme", "approach", "axis_fixed",
                         "place", "opening"},
    "linear_case": {"constant", "case_condition", "function_label", "trend", "range_set", "case_function"},
    "interval_merge": {"before", "after", "case_solutions", "merge_rows", "merge_total"},
    "endpoint_bounds": {"after"},
    "interval_conditions": {"before", "after", "multiple", "case_condition", "condition_list", "condition_system",
                            "any_condition", "case_answer"},
    "opening": {"opening", "fixed_positive", "positive_relation"}, "degenerate_case": {"constant"},
    "separation_naming": {"named", "operator_tex", "divisor_negative"},
    "policy_view": {"policy_relation", "policy_definition", "policy_condition", "policy_condition_short", "policy_universal",
                    "policy_low", "policy_strict", "policy_attained", "bound_explanation"},
    "solution_view": {"solution_set", "solution_symbol"},
    "hook_view": {"hook_label", "hook_left", "hook_right", "hook_minimum", "hook_turn", "hook_side",
                  "hook_relation", "hook_positive", "hook_amgm", "hook_equal", "hook_peak", "hook_ends"},
    "affine_substitution_view": {"affine_original", "affine_identity"},
    "affine_restore_view": {"affine_restored_rows", "affine_turn_outside", "affine_bounds"},
}


def _validate_path(path, names):
    if (not isinstance(path, str) or not re.fullmatch(r"[A-Za-z][A-Za-z_0-9]*(?:\.[A-Za-z][A-Za-z_0-9]*)*", path)
            or path.split(".")[0] not in names):
        raise ValueError("presentation.unknown_template_binding:" + str(path))


def _validate_node(node, names):
    if isinstance(node, str):
        for _, name, spec, conversion in _FORMATTER.parse(node):
            if name is not None:
                _validate_path(name, names)
                if spec or conversion:
                    raise ValueError("presentation.unsupported_template_format")
        return
    if isinstance(node, list):
        for item in node:
            _validate_node(item, names)
        return
    if not isinstance(node, dict):
        raise TypeError("presentation.invalid_template_node")
    if "if" in node and set(node) <= {"if", "then", "else"} and "then" in node:
        _validate_path(node["if"], names)
        _validate_node(node["then"], names)
        _validate_node(node.get("else", ""), names)
    elif "select" in node and set(node) <= {"select", "cases", "default"} and isinstance(node.get("cases"), dict):
        _validate_path(node["select"], names)
        for value in [*node["cases"].values(), node.get("default", "")]:
            _validate_node(value, names)
    elif "for" in node and set(node) <= {"for", "as", "body", "separator"} and "body" in node:
        _validate_path(node["for"], names)
        if not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", node.get("as", "")) or not isinstance(node.get("separator", ""), str):
            raise ValueError("presentation.invalid_template_loop")
        _validate_node(node["body"], names | {node["as"]})
    else:
        raise ValueError("presentation.unknown_template_node")


def validate_registry(registry):
    for specification in registry["templates"].values():
        preparation = specification.get("prepare")
        if preparation is not None and preparation not in PREPARERS:
            raise ValueError("presentation.unknown_preparer:" + str(preparation))
        names = set(specification["required_bindings"]) | PREPARED_FIELDS.get(preparation, set()) | {"has_case"}
        for name, node in specification.get("variables", {}).items():
            _validate_node(node, names)
            names.add(name)
        _validate_node(specification.get("render", specification["explanation"]), names)
        if "highlight" in specification:
            _validate_highlight(specification["highlight"], names)
    _validate_node(registry["case_prefix"], {"condition"})
    return registry


def _validate_highlight(highlight, names):
    if (not isinstance(highlight, dict)
            or not {"caption", "items"} <= set(highlight)
            <= {"caption", "items", "connector", "result", "conclusion_only", "layout"}
            or not isinstance(highlight.get("connector", ""), str)
            or highlight.get("layout", "merge") != "merge"
            or (highlight.get("layout") and "result" not in highlight)
            or not isinstance(highlight.get("conclusion_only", False), bool)):
        raise ValueError("presentation.invalid_highlight")
    _validate_node(highlight["caption"], names)
    _validate_node(highlight.get("result", ""), names)
    items = highlight["items"]
    if not isinstance(items, list) or not items:
        raise ValueError("presentation.invalid_highlight")
    for item in items:
        if not isinstance(item, dict) or not {"label", "math"} <= set(item) <= {"label", "math", "note", "for", "as"}:
            raise ValueError("presentation.invalid_highlight")
        scope = names
        if "for" in item:
            _validate_path(item["for"], names)
            if not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", item.get("as", "")):
                raise ValueError("presentation.invalid_highlight")
            scope = names | {item["as"]}
        for key, node in item.items():
            if key not in ("for", "as"):
                _validate_node(node, scope)


def prepare_values(specification, bindings, *, has_case=False):
    values = {**bindings, "has_case": has_case}
    for key in ("before", "after"):
        values[key] = list(values.get(key, []))
    if specification.get("prepare"):
        values.update(PREPARERS[specification["prepare"]](values))
    return values


def render_template(specification, bindings, *, has_case=False):
    values = prepare_values(specification, bindings, has_case=has_case)
    for name, node in specification.get("variables", {}).items():
        values[name] = _render(node, values)
    return values["before"], values["after"], _render(specification.get("render", specification["explanation"]), values)


def render_highlight(specification, bindings, *, has_case=False):
    """The card's emphasised conclusion: a caption over labelled formulas, read left to right.

    ``result`` is the one line the next step starts from.
    """
    if "highlight" not in specification:
        return None
    values = prepare_values(specification, bindings, has_case=has_case)
    for name, node in specification.get("variables", {}).items():
        values[name] = _render(node, values)
    highlight = specification["highlight"]
    items = []
    for item in highlight["items"]:
        fields = {key: node for key, node in item.items() if key not in ("for", "as")}
        scopes = ([{**values, item["as"]: entry} for entry in _lookup(values, item["for"])] if "for" in item
                  else [values])
        items.extend({key: text for key, text in ((key, _render(node, scope)) for key, node in fields.items()) if text}
                     for scope in scopes)
    rendered = {"caption": _render(highlight["caption"], values), "items": items}
    for key in ("connector", "layout"):
        if key in highlight:
            rendered[key] = highlight[key]
    if result := _render(highlight.get("result", ""), values):
        rendered["result"] = result
    if highlight.get("conclusion_only"):
        rendered["conclusion_only"] = True
    return rendered


def render_case_prefix(registry, condition):
    return _render(registry["case_prefix"], {"condition": condition})
