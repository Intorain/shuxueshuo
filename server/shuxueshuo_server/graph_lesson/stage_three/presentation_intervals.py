"""Formulas for the interval-extremum cards: axis position, the bound in each case, the case systems.

Like every preparer these return mathematical objects and LaTeX only; the
wording lives in the presentation registry. Nothing here solves anything: the
cases, bounds and solution sets come from certified capability outputs.
"""

import sympy as sp

from .math_values import math_value

_MARKS = "①②③④⑤⑥⑦⑧⑨"
_BOUND_TEX = {"inf": r"\min", "sup": r"\max"}
_LESS = {True: "<", False: r"\leq"}
_GREATER = {True: ">", False: r"\geq"}
_REL_TEX = {">=": r"\geq", ">": ">", "<=": r"\leq", "<": "<", "==": "=", "!=": r"\neq"}


def tex(value):
    return {sp.oo: r"+\infty", -sp.oo: r"-\infty"}.get(value, math_value(value)["latex"])


def in_set(symbol, values):
    """``a`` restricted to ``values`` as one relation: ``-1<a\\leq 0``, ``a\\geq 1``, ``a\\in\\varnothing``."""
    if symbol is None:
        return tex(values)
    name = tex(symbol)
    if isinstance(values, sp.Interval):
        low = "" if values.start is -sp.oo else f"{tex(values.start)} {_LESS[values.left_open]} "
        high = "" if values.end is sp.oo else f" {_LESS[values.right_open]} {tex(values.end)}"
        if low and high:
            return f"{low}{name}{high}"
        if low:
            return f"{name} {_GREATER[values.left_open]} {tex(values.start)}"
        if high:
            return f"{name}{high}"
        return rf"{name} \in \mathbb{{R}}"
    if isinstance(values, sp.FiniteSet) and len(values) == 1:
        return f"{name}={tex(next(iter(values)))}"
    if values is sp.S.EmptySet:
        return rf"{name} \in \varnothing"
    return rf"{name} \in {tex(values)}"


def _parameter_set(condition, parameter):
    if condition is sp.true:
        return sp.S.Reals
    return condition.as_set() if parameter is not None else None


def _sample(values):
    if isinstance(values, sp.FiniteSet):
        return next(iter(values))
    if isinstance(values, sp.Interval):
        low, high = values.start, values.end
        if low is -sp.oo and high is sp.oo:
            return sp.S.Zero
        if low is -sp.oo:
            return high - 1
        if high is sp.oo:
            return low + 1
        return (low + high) / 2
    return None


def _sign(value):
    value = sp.nsimplify(value)
    return 1 if value.is_positive else -1 if value.is_negative else 0


def _axis_image(vertex, parameter, values):
    """Where the axis ``x = vertex`` lies as the parameter runs over ``values``."""
    if vertex is None or not isinstance(values, (sp.Interval, sp.FiniteSet)):
        return None
    if parameter is None or not vertex.free_symbols:
        return sp.FiniteSet(vertex)
    if (vertex.free_symbols != {parameter} or not vertex.is_polynomial(parameter)
            or sp.degree(vertex, parameter) != 1):
        return None
    image = sp.imageset(sp.Lambda(parameter, vertex), values)
    return image if isinstance(image, (sp.Interval, sp.FiniteSet)) else None


def _place(image, domain, compare_ends):
    """The axis relative to the interval; ``compare_ends`` puts the midpoint first (farther end decides)."""
    low, high = domain.start, domain.end
    middle = (low + high) / 2 if low is not -sp.oo and high is not sp.oo else None
    by_middle = [("left_of_middle", sp.Interval(-sp.oo, middle)),
                 ("right_of_middle", sp.Interval(middle, sp.oo))] if middle is not None else []
    by_ends = [("right", sp.Interval(high, sp.oo)) if high is not sp.oo else None,
               ("left", sp.Interval(-sp.oo, low)) if low is not -sp.oo else None,
               ("inside", sp.Interval(low, high))]
    order = [*by_middle, *by_ends] if compare_ends else [*by_ends, *by_middle]
    return next((name for name, region in filter(None, order) if image.is_subset(region)), None)


def _axis(function, x, parameter, values, vertex, coefficient, domain, bound):
    """The opening, the axis relation and its place, read on one parameter case."""
    sample = _sample(values) if values is not None else None
    leading = coefficient.subs(parameter, sample) if parameter is not None and sample is not None else coefficient
    upward = _sign(leading) > 0 if not leading.free_symbols else None
    image = _axis_image(vertex, parameter, values)
    place = None
    if image is not None and upward is not None:
        place = _place(image, domain, compare_ends=(bound == "sup") == upward)
    relation = in_set(vertex, image) if image is not None and vertex.free_symbols else ""
    return {"upward": upward, "place": place or "", "axis_relation": relation,
            "axis_fixed": tex(vertex) if vertex is not None and not vertex.free_symbols else "",
            "leading_relation": (rf"{tex(coefficient)} {'>' if upward else '<'} 0"
                                 if coefficient.free_symbols and upward is not None else "")}


def _monotone(place, upward):
    if place in ("left", "right"):
        rising = (place == "left") == upward
        return "increasing" if rising else "decreasing"
    if place in ("left_of_middle", "right_of_middle"):
        return "right_far" if place == "left_of_middle" else "left_far"
    return "vertex" if place == "inside" else ""


def _label(values, x):
    name = values.get("function_name")
    return f"{name}({tex(x)})" if name else math_value(values["before"][0])["latex"]


def _extreme(values, x, function, bounds):
    """``g(x)_{min}=g(p)=v`` when attained, ``g(x)>g(p)=v`` when only approached, a limit at infinity."""
    key = bounds["bound"]
    point, value = bounds["candidates"][0]["point"], bounds[key]
    name = values.get("function_name")
    label = _label(values, x)
    if value in (sp.oo, -sp.oo):
        return {"extreme": rf"{label}\to {tex(value)}", "approach": rf"{tex(x)}\to {tex(point)}"}
    call = rf"={name}\left({tex(point)}\right)" if name else ""
    if bounds[key + "_attained"]:
        body = label if name or function.is_Atom else rf"\left({label}\right)"
        return {"extreme": f"{body}_{{{_BOUND_TEX[key]}}}{call}={tex(value)}", "approach": ""}
    relation = ">" if key == "inf" else "<"
    return {"extreme": f"{label} {relation} {call[1:] + '=' if call else ''}{tex(value)}", "approach": ""}


def classified_view(values):
    bounds, condition, x = values["range"], values["condition"], values["x"]
    function = values["before"][0]
    parameter = next(iter(condition.free_symbols), None) if isinstance(condition, sp.Basic) else None
    cases = _parameter_set(condition, parameter)
    axis = _axis(function, x, parameter, cases, values["vertex"], values["coefficient"], values["domain"],
                 bounds["bound"])
    case = in_set(parameter, cases) if parameter is not None else ""
    varying = bool(axis["leading_relation"]) and axis["upward"] is not None
    return {"case_condition": case, "axis_relation": axis["axis_relation"], "axis_fixed": axis["axis_fixed"],
            "place": axis["place"], "opening": ("up" if axis["upward"] else "down") if varying else "",
            "leading_relation": axis["leading_relation"] if axis["leading_relation"] != case else "",
            "monotone": _monotone(axis["place"], axis["upward"]), "function_label": _label(values, x),
            **_extreme(values, x, function, bounds)}


def linear_view(values):
    """A degenerate case: the function after substituting the parameter, its trend and its range."""
    condition, x, function = values["condition"], values["x"], values["before"][0]
    parameter = next(iter(condition.free_symbols), None) if isinstance(condition, sp.Basic) else None
    slope = sp.diff(function, x)
    return {"case_condition": in_set(parameter, condition.as_set()) if parameter is not None else "",
            "function_label": f"{values['function_name']}({tex(x)})" if values.get("function_name") else "y",
            "case_function": function,
            "trend": "" if slope == 0 else "increasing" if _sign(slope) > 0 else "decreasing",
            "range_set": values["after"][-1]}


def cases_view(values):
    cases, parameter, x, domain = values["cases"], values["parameter"], values["x"], values["domain"]
    function = values["before"][0]
    rows, upward = [], None
    for index, case in enumerate(cases):
        axis = (_axis(function, x, parameter, case["domain"], case["vertex"], case["coefficient"], domain,
                      case["range"]["bound"])
                if case.get("kind") == "quadratic" and case.get("vertex") is not None else
                {"upward": None, "place": "", "axis_relation": ""})
        upward = axis["upward"] if upward is None else upward
        bounds = case["range"]
        if case.get("kind") == "constant":
            extreme, attained = f"{_label(values, x)}={tex(case['expression'])}", True
        else:
            extreme, attained = _extreme(values, x, function, bounds)["extreme"], bounds[bounds["bound"] + "_attained"]
        rows.append({"mark": _MARKS[index] if index < len(_MARKS) else f"({index + 1})",
                     "condition": in_set(parameter, case["domain"]), "axis_relation": axis["axis_relation"],
                     "place": axis["place"] or case.get("kind", ""), "extreme": extreme, "attained": attained})
    vertex = next((case["vertex"] for case in cases if case.get("vertex") is not None), None)
    fixed = not cases[0]["coefficient"].free_symbols and upward is not None
    return {"case_rows": rows, "opening": ("up" if upward else "down") if fixed else "",
            "axis": tex(vertex) if vertex is not None else "", "function_label": _label(values, x),
            "bound_name": {"inf": "最小值", "sup": "最大值"}[cases[0]["range"]["bound"]]}


def conditions_view(values):
    condition, conditions, solution = values["condition"], values["conditions"], values["after"][-1]
    symbols = set().union(*(item.free_symbols for item in conditions if isinstance(item, sp.Basic)))
    parameter = next(iter(condition.free_symbols), None) if isinstance(condition, sp.Basic) else None
    parameter = parameter or next(iter(symbols), None)
    case = in_set(parameter, condition.as_set()) if condition is not sp.true and parameter is not None else ""
    listed = [math_value(item)["latex"] for item in conditions]
    rows = ([case] if case else []) + listed
    joined = r",\\ ".join(rows)
    return {"case_condition": case, "condition_list": listed,
            "condition_system": rf"\begin{{cases}}{joined}\end{{cases}}" if len(rows) > 1 else rows[0],
            "any_condition": values["combiner"] == "any" and len(conditions) > 1,
            "case_answer": in_set(parameter, solution) if parameter is not None else tex(solution)}


def merge_view(values):
    """Each case's conditions and their solution inside the case, then the union."""
    cases, solutions, results = values["cases"], values["solutions"], values["results"]
    parameter = next((symbol for case in cases for symbol in case["condition"].free_symbols), None)
    total, x, function = values["after"][-1], values["x"], values["before"][0]
    rows = []
    for index, (case, solution, result) in enumerate(zip(cases, solutions, results, strict=True)):
        outputs = result["outputs"]
        either = outputs.get("combiner") == "any"
        listed = [math_value(item)["latex"] for item in outputs["conditions"]]
        condition = in_set(parameter, case["domain"])
        joined = (r"\ \text{或}\ " if either else r",\\ ").join(listed)
        empty = solution == sp.S.EmptySet
        rows.append({"mark": _MARKS[index] if index < len(_MARKS) else f"({index + 1})",
                     "condition": condition, "set": solution, "empty": empty,
                     "conditions": (r"\ \text{或}\ " if either else r",\ ").join(listed),
                     "system": rf"\begin{{cases}}{condition},\\ {joined}\end{{cases}}",
                     "answer": in_set(parameter, solution),
                     "value": r"\text{无解}" if empty else in_set(parameter, solution),
                     "requirement": _requirement(values, x, function, case, outputs["conditions"])})
    return {"merge_rows": rows, "merge_total": in_set(parameter, total)}


def oriented(relation):
    """``0 \\leq v`` read as ``v \\geq 0``, the way the cards print it."""
    if isinstance(relation, sp.Rel) and relation.lhs == 0 and relation.rhs != 0:
        return relation.reversed
    return relation


def _requirement(values, x, function, case, conditions):
    """``g(x)_{min}=g(p)=v \\geq 0``: the case's extreme carrying its one condition, else the conditions."""
    relations = [oriented(item) for item in conditions if isinstance(item, sp.Rel)]
    if len(relations) != 1 or len(conditions) != 1:
        return r",\ ".join(math_value(item)["latex"] for item in conditions)
    relation = relations[0]
    if case.get("kind") == "constant":
        extreme = f"{_label(values, x)}={tex(case['expression'])}"
    else:
        extreme = _extreme(values, x, function, case["range"])["extreme"]
    if not extreme.endswith(tex(relation.lhs)):
        return math_value(relation)["latex"]
    return f"{extreme} {_REL_TEX[relation.rel_op]} {tex(relation.rhs)}"
