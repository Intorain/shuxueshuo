"""Separate, evidence-bound parameter questions for the two opening directions."""

import sympy as sp

from .discriminant_display import constant_true_condition, displayed_delta_condition


def register(api):
    def certificate(values, context):
        proof = values["opening_certificate"]
        relation, variable = proof["relation"], context["x"]
        try:
            positive = relation.rel_op in (">", ">=")
            if (proof["quantifier"] != context["quantifier"] or proof["variable"] != variable
                    or proof["parameter"] != context["parameter"] or relation.rhs != 0
                    or (relation.rel_op in ("<", ">")) != (context["relation"].rel_op in ("<", ">"))
                    or sp.expand((1 if positive else -1) * relation.lhs - context["expression"]) != 0
                    or displayed_delta_condition(proof["delta"], relation, variable, proof["quantifier"],
                                                 proof["delta_condition"]) != proof["delta_condition"]):
                raise ValueError("opening_certificate_context")
            rows = [*proof["branches"], *proof["excluded"]]
            if (len({row["id"] for row in rows}) != len(rows)
                    or not api.exact_set_equal(sp.Union(*(row["domain"] for row in rows)), proof["case_domain"])
                    or not api.exact_set_equal(sp.Union(*(row["solution"] for row in proof["branches"])),
                                              proof["solution"])):
                raise ValueError("opening_certificate_coverage")
            coefficient = sp.Poly(relation.lhs, variable).nth(2)
            for row in rows:
                upward = row["upward"]
                sign = (sp.Gt if upward else sp.Lt)(coefficient, 0, evaluate=False)
                viable = proof["quantifier"] == "∃" or upward == positive
                automatic = proof["quantifier"] == "∃" and upward == positive
                expected = row["domain"] if automatic else sp.Intersection(row["domain"], proof["delta_solution"]) if viable else sp.S.EmptySet
                if (row["condition"] != sign or row["direction"] != ("向上" if upward else "向下")
                        or row["id"] != ("opening-up" if upward else "opening-down")
                        or row["automatic"] != automatic or row["viable"] != viable
                        or row["delta_condition"] != proof["delta_condition"]
                        or not api.exact_set_equal(row["delta_solution"], proof["delta_solution"])
                        or not api.exact_set_equal(row["solution"], expected)):
                    raise ValueError("opening_certificate_branch")
        except (KeyError, TypeError, ValueError, sp.PolynomialError) as exc:
            raise api.NotInteractive("opening_certificate_unverified") from exc
        return proof

    def branch_facts(values, context):
        branch = values["branch"]
        proof = certificate(values, context)
        relation, variable = values["relation"], context["x"]
        try:
            if (values["quantifier"] != context["quantifier"]
                    or values["parameter"] != context["parameter"]
                    or relation.rhs != 0
                    or (relation.rel_op in ("<", ">")) != (context["relation"].rel_op in ("<", ">"))):
                raise ValueError("branch_context")
            positive = relation.rel_op in (">", ">=")
            residual = (1 if positive else -1) * (relation.lhs - relation.rhs)
            if sp.expand(residual - context["expression"]) != 0:
                raise ValueError("branch_relation")
            coefficient = sp.Poly(relation.lhs - relation.rhs, variable).nth(2)
            upward = branch["upward"]
            sign = (sp.Gt if upward else sp.Lt)(coefficient, 0, evaluate=False)
            existential = context["quantifier"] == "∃"
            automatic = existential and upward == positive
            viable = existential or upward == positive
            raw = displayed_delta_condition(values["delta"], relation, variable,
                                            context["quantifier"], branch["delta_condition"])
            before = [] if constant_true_condition(sign) else [sign]
            if not automatic:
                before.append(raw)
            if (branch["condition"] != sign or raw != branch["delta_condition"]
                    or branch["direction"] != ("向上" if upward else "向下")
                    or branch["id"] != ("opening-up" if upward else "opening-down")
                    or branch["automatic"] != automatic or branch["viable"] != viable
                    or values["before"] != before
                    or values["case"]["condition"] != sign
                    or not api.exact_set_equal(values["case"]["domain"], branch["domain"])
                    or branch not in proof["branches"]):
                raise ValueError("branch_display")
        except (KeyError, TypeError, ValueError, sp.PolynomialError) as exc:
            raise api.NotInteractive("opening_branch_display_unverified") from exc
        answer = values["after"][-1]
        expected = branch["domain"] if branch["automatic"] else sp.Intersection(
            branch["domain"], branch["delta_solution"])
        if (not branch["viable"] or not api.exact_set_equal(expected, answer)
                or not api.exact_set_equal(branch["solution"], answer)):
            raise api.NotInteractive("opening_branch_unverified")
        fixed_opening = constant_true_condition(branch["condition"])
        conditions = [] if fixed_opening else [branch["condition"]]
        if not branch["automatic"]:
            conditions.append(branch["delta_condition"])
        condition_text = " 且 ".join(api.math(value) for value in conditions)
        return {"answer": answer, "parameter": context["parameter"],
                "solutions": list(answer.args) if isinstance(answer, sp.Union) else [answer],
                "display": {"direction": branch["direction"], "parameter": context["parameter"],
                            "conditions": condition_text,
                            "condition_prompt": f"由 {condition_text}，" if conditions else "",
                            "branch_feedback": ("此开口下必有实数解，保留本情况的全部参数。" if automatic and fixed_opening else
                                                "只需解判别式条件，得到参数范围。" if fixed_opening else
                                                "无需限制判别式，保留满足开口条件的参数。" if automatic else
                                                "开口条件和判别式条件同时成立，取交集。"),
                            "automatic_note": "此时必有实数解，无需限制判别式。" if branch["automatic"] else ""}}

    def merge_facts(values, context):
        proof = certificate(values, context)
        solutions = [branch["solution"] for branch in values["branches"]]
        answer = values["after"][-1]
        if (values["branches"] != proof["branches"] or not api.exact_set_equal(answer, proof["solution"])
                or not api.exact_set_equal(sp.Union(*solutions), answer)):
            raise api.NotInteractive("opening_union_unverified")
        return {"answer": answer, "parameter": context["parameter"], "solutions": solutions,
                "display": {"parameter": context["parameter"],
                            "pieces": "；".join("开口" + branch["direction"] + "：" + api.math(branch["solution"])
                                              for branch in values["branches"])}}

    def validate(facts, values, context, item, candidates):
        # Test the whole proposed parameter range. Restricting witnesses to the
        # answer's branch domain would incorrectly accept extra parameters.
        return api.set_check(item["answer"], candidates, facts["known"])

    def complement(facts, item):
        return [api.set_candidate("set", sp.Complement(sp.S.Reals, item["answer"].value))]

    source = {"kind": "set", "answer": api.case_solution_answer, "validate": validate,
              "generators": {"flip_endpoint": api.flip_endpoint, "set_complement": complement,
                             "drop_piece": api.drop_piece}}
    return {"answers": {"opening_branch_set": {**source, "facts": branch_facts},
                        "opening_union_set": {**source, "facts": merge_facts}},
            "option_graphs": {"opening_branch_sets": ({"opening_branch_set", "opening_union_set"}, api.set_options)}}
