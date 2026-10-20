"""Declarative prose rendering and registered, pure mathematical preparation."""

import re
from string import Formatter

import sympy as sp

from .math_values import math_value


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


# Preparation functions only select supplied evidence or construct equivalent
# mathematical objects. They contain no prose and never perform solving.
PREPARERS = {
    "variable_range": _variable_range, "variable_conditions": _variable_conditions,
    "numeric_range": _numeric_range, "interval_cases": _interval_cases,
    "classified_range": _classified_range, "interval_merge": _interval_merge,
    "endpoint_bounds": _endpoint_bounds, "interval_conditions": _interval_conditions,
    "opening": _opening, "degenerate_case": _degenerate_case,
}
PREPARED_FIELDS = {
    "variable_range": {"after", "square", "has_square", "multiple"},
    "variable_conditions": {"before", "after", "multiple"},
    "numeric_range": {"constant"}, "interval_cases": {"after"},
    "classified_range": {"after", "bound_value", "bound_attained", "has_vertex"},
    "interval_merge": {"before", "case_solutions"}, "endpoint_bounds": {"after"},
    "interval_conditions": {"before", "after", "multiple"},
    "opening": {"opening", "fixed_positive", "positive_relation"}, "degenerate_case": {"constant"},
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
    _validate_node(registry["case_prefix"], {"condition"})
    return registry


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


def render_case_prefix(registry, condition):
    return _render(registry["case_prefix"], {"condition": condition})
