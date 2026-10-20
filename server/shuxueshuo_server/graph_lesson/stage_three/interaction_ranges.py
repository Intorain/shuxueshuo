"""Questions about separation and certified ranges, using only this card's seed."""

import sympy as sp


def register(api):
    """Explicit compiler dependency; no math-driver or persistent-state access."""
    def division_facts(values, context):
        divisor, variable, domain = values["divisor"], context["x"], context["domain"]
        bounds = api.range_at(divisor, variable, domain)
        positive = api.cmp(bounds["inf"], 0) > 0 or (
            api.cmp(bounds["inf"], 0) == 0 and not bounds["inf_attained"])
        negative = api.cmp(bounds["sup"], 0) < 0 or (
            api.cmp(bounds["sup"], 0) == 0 and not bounds["sup_attained"])
        if not (positive or negative):
            raise api.NotInteractive("divisor_sign_unknown")
        return {"reverse": negative, "display": {"divisor": divisor, "domain": domain, "x": variable}}

    def division_answer(facts):
        reverse = facts["reverse"]
        return [{"label": "不等号方向", "answer": api.Candidate(
            f"direction:{reverse}", "反向" if reverse else "保持不变", reverse)}]

    def direction_error(facts, item):
        reverse = not item["answer"].value
        return [api.Candidate(f"direction:{reverse}", "反向" if reverse else "保持不变", reverse)]

    def move_facts(values, context):
        return {"reverse": False, "display": {"before": values["before"][0]}}

    def range_facts(values, context):
        bound = values.get("range", {})
        answer = bound.get("set")
        if answer is None:
            answer = next((value for value in reversed(values["after"]) if isinstance(value, sp.Set)), None)
        if not isinstance(answer, sp.Set) or answer.free_symbols:
            raise api.NotInteractive("numeric_range_missing")
        function = values.get("function")
        if function is None and values.get("before") and isinstance(values["before"][0], sp.Expr):
            function = values["before"][0]
        return {"answer": answer, "function": function, "parameter": context.get("parameter"),
                "x": values.get("x", context["x"]), "domain": values.get("domain", context["domain"]),
                "case_domain": values.get("case", {}).get("domain", sp.S.Reals),
                "display": {"function": function if function is not None else "该函数",
                            "domain": values.get("domain", context["domain"])}}

    def answer_set(facts):
        return [{"answer": api.set_candidate("range", facts["answer"])}]

    def range_errors(facts, item):
        answer = item["answer"].value
        values = [*api.flip_endpoint(facts, item)]
        values.append(api.set_candidate("range", sp.Complement(sp.S.Reals, answer)))
        pieces = list(answer.args) if isinstance(answer, sp.Union) else [answer]
        for piece in pieces:
            if isinstance(piece, sp.Interval):
                for end in (piece.start, piece.end):
                    if api.finite(end):
                        values.append(api.set_candidate("range", sp.FiniteSet(end)))
                if api.finite(piece.start) and api.finite(piece.end):
                    values.append(api.set_candidate("range", sp.Interval(piece.start, sp.oo,
                                                                              left_open=piece.left_open)))
            elif isinstance(piece, sp.FiniteSet):
                values.extend(api.set_candidate("range", sp.Interval(v, sp.oo)) for v in piece)
        return values

    def validate_range(facts, values, context, item, candidates):
        # These are FUNCTION VALUES, not parameter values: never intersect them
        # with the known parameter set (e.g. a >= 0 does not mean f(x) >= 0).
        return api.set_check(item["answer"], candidates, sp.S.Reals)

    def range_graph(facts, values, context):
        if facts["function"] is None:
            raise api.GraphUnavailable("function_missing")
        return api.function_stem({**facts, "known": sp.Intersection(facts["known"], facts["case_domain"])},
                                   values, context)

    def range_options(facts, values, context, candidates):
        return api.drawing.number_lines([candidate.value for candidate, _ in candidates], sp.Symbol("y"),
                                         title="函数值的范围"), None

    def endpoint_facts(values, context):
        candidates = values["range"]["candidates"]
        points = tuple(dict.fromkeys(row["point"] for row in candidates))
        if not points:
            raise api.NotInteractive("endpoint_candidates_missing")
        return {"points": points, "candidates": candidates, "bound": values["range"]["bound"],
                "parameter": context.get("parameter"), "case_domain": values.get("case", {}).get("domain", sp.S.Reals),
                "x": values["x"], "domain": values["domain"],
                "display": {"function": values["function"], "domain": values["domain"],
                            "bound_name": api.BOUND_NAMES[values["range"]["bound"]]}}

    def endpoint_label(facts, points):
        return "、".join(f"${api.latex(facts['x'])}={api.latex(point)}$" for point in points)

    def endpoint_answer(facts):
        return [{"label": "比较候选位置（开放端点取极限）", "answer": api.Candidate(
            "ends:" + str(facts["points"]), endpoint_label(facts, facts["points"]), facts["points"])}]

    def endpoint_errors(facts, item):
        points = facts["points"]
        candidates = [(point,) for point in points] if len(points) > 1 else []
        return [api.Candidate("ends:" + str(other), endpoint_label(facts, other), other)
                for other in candidates if other != points]

    def endpoint_check(facts, values, context, item, candidates):
        # Omitting a candidate is wrong only when it changes the extremum or
        # its attainment. Equal-valued/redundant endpoints are not distractors.
        region = sp.Intersection(facts["known"], facts["case_domain"])
        points = api.representatives(values, context, region)

        def summary(selected, parameter_value):
            best, attained = None, False
            for row in facts["candidates"]:
                if row["point"] not in selected:
                    continue
                value = row["value"]
                if facts["parameter"] is not None:
                    value = value.subs(facts["parameter"], parameter_value)
                comparison = api.cmp(value, best) if best is not None else None
                better = comparison is None or (comparison < 0 if facts["bound"] == "inf" else comparison > 0)
                if better:
                    best, attained = value, bool(row["attained"])
                elif comparison == 0:
                    attained = attained or bool(row["attained"])
            if best is None:
                raise api.NotInteractive("endpoint_candidates_missing")
            return best, attained

        def differs(candidate, point):
            full, other = summary(facts["points"], point), summary(candidate.value, point)
            return api.cmp(full[0], other[0]) != 0 or full[1] != other[1]

        kept, records = [], []
        for candidate in candidates:
            witness = next((point for point in points if api.attempt(differs, candidate, point) is True), None)
            if witness is None:
                records.append((candidate, "unproven", None))
                continue
            kept.append(candidate)
            records.append((candidate, "witness", api.latex(witness)))
        return kept, records, []

    def completion(seeds):
        values, context = api.decode_value(seeds[0]["values"]), api.decode_value(seeds[0]["context"])
        function = values.get("function")
        if function is None:
            raise api.GraphUnavailable("function_missing")
        return api.function_stem({"function": function, "x": values["x"], "domain": values["domain"],
                                    "parameter": context.get("parameter"), "known": api.known_set(seeds[0])},
                                   values, context)

    return {"answers": {
        "division_direction": {"kind": "fixed", "facts": division_facts, "answer": division_answer,
                               "generators": {"reverse_division": direction_error}},
        "movement_direction": {"kind": "fixed", "facts": move_facts, "answer": division_answer,
                               "generators": {"reverse_division": direction_error}},
        "certified_range": {"kind": "validated", "requires_known": True, "facts": range_facts,
                            "answer": answer_set, "validate": validate_range,
                            "generators": {"range_alternatives": range_errors}},
        "endpoint_candidates": {"kind": "validated", "checklist": True, "requires_known": True,
                                "facts": endpoint_facts, "answer": endpoint_answer,
                                "validate": endpoint_check, "generators": {"omit_endpoint": endpoint_errors}},
    }, "stem_graphs": {"range_function": ({"certified_range"}, range_graph)},
        "option_graphs": {"range_sets": ({"certified_range"}, range_options)},
        "completion_graphs": {"range_evidence_function": completion}}
