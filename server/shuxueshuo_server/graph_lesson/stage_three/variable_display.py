"""Concise affine-case conclusions from the executor's checked values."""

import sympy as sp

from .math_values import BOUND_NAMES, EXTREMUM_NAMES, latex

SIGNS = {"positive": ">", "zero": "=", "negative": "<"}


def slope_view(values):
    cases, slope = values["cases"], values["slope"]
    rows = [{"sign": case["slope_sign"],
             "relation": f"{latex(slope)} {SIGNS[case['slope_sign']]} 0",
             "condition": case["condition"]} for case in cases]
    single = len(cases) == 1
    chain = rows[0]["relation"] if single else ""
    if single and (square := cases[0]["certificate"].get("square")) is not None:
        chain = f"{latex(slope)}={latex(square)} {SIGNS[cases[0]['slope_sign']]} 0"
    return {"slope_rows": rows, "single_sign": single, "slope_chain": chain}


def case_view(values):
    bounds = values["range"]
    key = bounds["bound"]
    row, = bounds["candidates"]
    variable, parameter = values["x"], values["parameter"]
    name = values["function_name"]
    constant = values["slope_sign"] == "zero"
    attained = row["attained"]
    if constant:
        identity = f"{name}({latex(variable)})={latex(row['value'])}"
    elif attained:
        identity = f"{name}({latex(row['point'])})={latex(row['value'])}"
    else:
        direction = "+" if values["endpoint_mode"] == "left_endpoint" else "-"
        identity = (rf"\lim_{{{latex(variable)}\to {latex(row['point'])}^{direction}}}"
                    f"{name}({latex(variable)})={latex(row['value'])}")
    # Conditions are stored as 0 op bound. Reverse only the presentation.
    mirror = {">": "<", "<": ">", ">=": "<=", "<=": ">="}
    conditions = [sp.Rel(item.rhs, item.lhs, mirror[item.rel_op], evaluate=False)
                  if item.lhs == 0 else item for item in values["conditions"]]
    solution = values["after"][-1]
    answer = rf"{latex(parameter)}\in {latex(solution)}"
    region = values["case_domain"]
    raw = values["candidate_set"]
    def grouped(value):
        rendered = latex(value)
        return rf"\left({rendered}\right)" if isinstance(value, sp.Union) else rendered

    chain = answer if region == sp.S.Reals else (
        rf"{latex(parameter)}\in {grouped(raw)}\cap {grouped(region)}={latex(solution)}")
    bound_name = (EXTREMUM_NAMES if attained else BOUND_NAMES)[key]
    return {"bound_identity": identity, "bound_attained": attained, "bound_name": bound_name,
            "case_constant": constant, "case_conditions": conditions,
            "case_answer": answer, "case_chain": chain}


def merge_view(values):
    rows = [{"condition": case["condition"], "solution": solution}
            for case, solution in zip(values["cases"], values["solutions"], strict=True)]
    total = latex(values["after"][-1])
    union = r" \cup ".join(latex(row["solution"]) for row in rows)
    return {"before": [*values["before"], *values["solutions"]], "case_solutions": rows,
            "merge_equation": f"{union}={total}",
            "merge_answer": rf"{latex(values['parameter'])}\in {total}"}
