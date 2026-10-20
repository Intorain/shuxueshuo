"""Interactions for affine variable roles and verified closing evidence.

Only the supplied card seeds are read.  ``register`` receives the compiler API
so this interaction-only extension does not import the mathematical driver.
"""

import sympy as sp


def register(api):
    candidate, unavailable, math = api.Candidate, api.NotInteractive, api.math

    def expression(value):
        return candidate("expression:" + sp.srepr(value), math(value), value)

    def scope_facts(values, context):
        case = values.get("case") or {}
        parameter = values.get("parameter", context.get("parameter"))
        return {"parameter": parameter, "case_domain": case.get("domain", sp.S.Reals),
                "display": {"parameter": parameter, "condition": case.get("condition", sp.true)}}

    def expression_check(facts, values, context, item, candidates):
        region = sp.Intersection(facts["known"], facts["case_domain"])
        points = api.representatives(values, context, region)
        parameter = facts["parameter"]

        def difference(left, right, point):
            value = sp.expand(left - right)
            if parameter is not None:
                value = value.subs(parameter, point)
            return api.cmp(value, sp.S.Zero)

        kept, records = [], []
        for option in candidates:
            witness = next((point for point in points
                            if api.attempt(difference, option.value, item["answer"].value, point) in (-1, 1)), None)
            distinct = all(any(api.attempt(difference, option.value, other.value, point) in (-1, 1)
                               for point in points) for other in kept)
            if witness is None or not distinct:
                records.append((option, "unproven" if witness is None else "duplicate", None))
                continue
            kept.append(option)
            records.append((option, "witness", api.latex(witness)))
        return kept, records, []

    def role_facts(values, context):
        variable, parameter = values["x"], values["parameter"]
        if variable == parameter or not all(isinstance(value, sp.Symbol) for value in (variable, parameter)):
            raise unavailable("distinct_symbol_roles_required")
        return {"x": variable, "parameter": parameter, "display": {"domain": values["domain"]}}

    def role_answer(facts):
        return [{"label": label, "answer": candidate("symbol:" + str(symbol), math(symbol), symbol),
                 "other": other}
                for label, symbol, other in (("在题设区间内变化的字母", facts["x"], facts["parameter"]),
                                             ("暂时固定、最后要求取值的字母", facts["parameter"], facts["x"]))]

    def swap_roles(facts, item):
        return [candidate("symbol:" + str(item["other"]), math(item["other"]), item["other"])]

    def coefficient_facts(values, context):
        return {**scope_facts(values, context), "slope": values["slope"], "intercept": values["intercept"],
                "display": {"x": values["x"], "function": values["before"][0]}}

    def coefficient_answer(facts):
        return [{"label": label, "answer": expression(facts[key]), "other": facts[other]}
                for label, key, other in (("一次项系数", "slope", "intercept"),
                                          ("常数项", "intercept", "slope"))]

    def coefficient_errors(facts, item):
        value, other = item["answer"].value, item["other"]
        return [expression(other), expression(-value), expression(value + other)]

    def affine_range_facts(values, context):
        facts = scope_facts(values, context)
        variable, function = values["x"], values["before"][0]
        return {**facts, "x": variable, "function": function, "domain": values["domain"],
                "slope": values["slope"], "rows": values["range"]["candidates"],
                "display": {**facts["display"], "x": variable, "function": function,
                            "domain": values["domain"], "bound_name": api.BOUND_NAMES[values["range"]["bound"]]}}

    def endpoint_answer(facts):
        return [{"label": f"${api.latex(facts['x'])}={api.latex(row['point'])}$ 处的函数值或极限",
                 "answer": expression(row["value"]), "point": row["point"]} for row in facts["rows"]]

    def endpoint_errors(facts, item):
        variable, slope, point = facts["x"], facts["slope"], item["point"]
        intercept = sp.expand(facts["function"] - slope * variable)
        alternatives = [facts["function"].subs(variable, end)
                        for end in (facts["domain"].start, facts["domain"].end)]
        alternatives.extend((slope * point - intercept, -slope * point + intercept,
                             -item["answer"].value))
        return [expression(sp.expand(value)) for value in alternatives]

    def attainment_answer(facts):
        return [{"label": f"候选位置 ${api.latex(facts['x'])}={api.latex(row['point'])}$",
                 "answer": candidate(f"attained:{row['attained']}",
                                     "能在区间内取得" if row["attained"] else "只能趋近，不能取得",
                                     row["attained"])} for row in facts["rows"]]

    def flip_candidate_attainment(facts, item):
        attained = not item["answer"].value
        return [candidate(f"attained:{attained}", "能在区间内取得" if attained else "只能趋近，不能取得", attained)]

    def solution_facts(values, context):
        facts = api.conditions_facts(values, context)
        case = values.get("case") or {}
        facts["display"]["case_note"] = f"在 {math(case['condition'])} 的情况下，" if case else ""
        return facts

    def solution_check(facts, values, context, item, candidates):
        domain = facts.get("case_domain")
        known = facts["known"] if domain is None else sp.Intersection(facts["known"], domain)
        return api.set_check(item["answer"], candidates, known)

    def complement_set(facts, item):
        return [api.set_candidate("set", sp.Complement(sp.S.Reals, item["answer"].value))]

    def swap_combiner(facts, item):
        operation = sp.Union if facts["combiner"] == "all" else sp.Intersection
        value = operation(*facts["solutions"])
        if facts.get("case_domain") is not None:
            value = sp.Intersection(value, facts["case_domain"])
        return [api.set_candidate("set", value)]

    def drop_condition(facts, item):
        if len(facts["solutions"]) < 2:
            return []
        region = facts.get("case_domain")
        region = sp.S.Reals if region is None else region
        return [api.set_candidate("set", sp.Intersection(value, region)) for value in facts["solutions"]]

    def constant_case_facts(values, context):
        parameter = values["parameter"]
        zero = sp.Union(*(case["domain"] for case in values["cases"] if case["slope_sign"] == "zero"))
        return {"answer": zero, "parameter": parameter,
                "display": {"parameter": parameter, "slope": values["slope"]}}

    def all_or_none(facts, item):
        return [api.set_candidate("set", value) for value in (sp.S.Reals, sp.S.EmptySet)]

    def intersect_cases(facts, item):
        return [api.set_candidate("set", sp.Intersection(*facts["solutions"]))]

    def goal_facts(values, context):
        facts = api.goal_facts(values, context)
        if facts["status"] not in ("attained", "not_attained", "empty_feasible_set",
                                   "unbounded_below", "unbounded_above"):
            raise unavailable("goal_status_unknown")
        return facts

    def goal_candidate(facts, status):
        name, bound = facts["display"]["goal_name"], facts["bound"]
        labels = {"empty_feasible_set": "可行集为空，没有满足题设的取值",
                  "unbounded_below": f"可行集向下无界，{name}不存在",
                  "unbounded_above": f"可行集向上无界，{name}不存在",
                  "attained": f"{name}为 {math(bound)}，能够取得",
                  "not_attained": f"{name}不存在，只能趋近 {math(bound)}"}
        return candidate("goal_status:" + status, labels[status], status)

    def goal_answer(facts):
        return [{"label": f"{facts['display']['goal_name']}结论", "answer": goal_candidate(facts, facts["status"])}]

    def goal_errors(facts, item):
        infinity = "unbounded_below" if facts["display"]["goal_name"] == "最小值" else "unbounded_above"
        statuses = ["empty_feasible_set", infinity]
        if api.finite(facts["bound"]):
            statuses.extend(("attained", "not_attained"))
        return [goal_candidate(facts, status) for status in statuses if status != facts["status"]]

    def range_completion(seeds):
        seed = seeds[0]
        values, context = api.decode_value(seed["values"]), api.decode_value(seed["context"])
        facts = affine_range_facts(values, context)
        region = sp.Intersection(facts["case_domain"], api.known_set(seed))
        parameter = facts["parameter"]
        point = (next(iter(region)) if isinstance(region, sp.FiniteSet) and len(region) == 1
                 else api.drawing.representative_parameter(region))
        function = facts["function"].subs(parameter, point)
        actual = api.range_at(function, facts["x"], facts["domain"])
        key = values["range"]["bound"]
        candidates = [{**row, "value": row["value"].subs(parameter, point)} for row in facts["rows"]]
        ordered = [row for row in candidates if api.cmp(row["value"], actual[key]) == 0]
        if not ordered or any(row["attained"] != actual[key + "_attained"] for row in ordered):
            raise api.GraphUnavailable("representative_unverified")
        drawn = api.drawing.family(function, facts["x"])
        marks = api.drawing.drawable(drawn, facts["x"], api.drawing.domain_points(facts["domain"]))
        bounds, ticks = api.drawing.function_frame(drawn, facts["x"], facts["domain"], marks=marks)
        return api.drawing.function_graph(
            drawn, facts["x"], facts["domain"], bounds=bounds, x_ticks=ticks, marks=marks,
            title=f"{parameter}={api.drawing.short_label(point)} 时的一次函数",
            description=f"在给定区间内比较端点及其可达性，{api.BOUND_NAMES[key]}由图中函数确定。",
            caption=f"示意图：固定 ${api.latex(parameter)}={api.latex(point)}$，变化字母为 ${api.latex(facts['x'])}$")

    def boundary_answer(facts):
        rows = api.boundary_answer(facts)
        if not rows:
            raise unavailable("no_finite_boundaries")
        return rows

    answers = {
        "variable_roles": {"kind": "fixed", "facts": role_facts, "answer": role_answer,
                           "generators": {"swap_symbol_roles": swap_roles}},
        "affine_coefficients": {"kind": "expression_rows", "checklist": True, "requires_known": True,
                                "facts": coefficient_facts, "answer": coefficient_answer,
                                "validate": expression_check, "generators": {"coefficient_errors": coefficient_errors}},
        "affine_endpoint_values": {"kind": "expression_rows", "checklist": True, "requires_known": True,
                                   "facts": affine_range_facts, "answer": endpoint_answer,
                                   "validate": expression_check,
                                   "generators": {"endpoint_substitution_errors": endpoint_errors}},
        "affine_attainment": {"kind": "fixed", "facts": affine_range_facts, "answer": attainment_answer,
                              "generators": {"flip_candidate_attainment": flip_candidate_attainment}},
        "variable_solution": {"kind": "set", "facts": solution_facts, "answer": api.case_solution_answer,
                              "validate": solution_check,
                              "generators": {"swap_combiner": swap_combiner, "drop_condition": drop_condition,
                                             "flip_endpoint": api.flip_endpoint, "complement_set": complement_set,
                                             "skip_intersection": api.skip_intersection}},
        "variable_constant_cases": {"kind": "set", "facts": constant_case_facts,
                                    "answer": api.case_solution_answer,
                                    "generators": {"complement_set": complement_set, "all_or_none": all_or_none}},
        "variable_merged_set": {"kind": "set", "facts": api.merge_facts, "answer": api.case_solution_answer,
                                "generators": {"intersect_cases": intersect_cases, "drop_piece": api.drop_piece,
                                               "flip_endpoint": api.flip_endpoint, "complement_set": complement_set}},
        "goal_conclusion": {"kind": "fixed", "facts": goal_facts, "answer": goal_answer,
                            "generators": {"goal_status_errors": goal_errors}},
        "boundary_rows": {"kind": "fixed", "facts": api.boundary_facts, "answer": boundary_answer,
                          "generators": {"flip_keep": api.flip_keep}},
    }
    return {"answers": answers,
            "option_graphs": {"variable_parameter_sets": ({"variable_solution", "variable_merged_set",
                                                           "variable_constant_cases"}, api.set_options)},
            "completion_graphs": {"variable_function": range_completion}}
