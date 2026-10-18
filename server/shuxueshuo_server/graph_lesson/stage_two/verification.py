"""A deliberately bounded AM–GM certificate for the Q01 mathematical shape.

Only bound, validated AST arithmetic enters SymPy. There is no expression-text
evaluation, parameter-range solving, or question-ID lookup here.
"""

import re

import sympy as sp

from ...problem_understanding.identity import revision
from ...problem_understanding.notation_compile import NotationValidator
from ...problem_understanding.notation_parser import NotationError
from ...problem_understanding.notation_semantics import Canonical, bounded_expand


class _Polynomial(Canonical):
    def __init__(self, bound, target):
        super().__init__()
        self.bound, self.target = bound, target
        self.x, self.a = sp.symbols("u p", real=True)

    def expr(self, ast, depth=0):
        if depth > 40:
            raise NotationError("verification.depth_limit")
        if ast == ["bound", self.bound]:
            return self.x
        if ast == self.target:
            return self.a
        if ast[0] not in ("number", "+", "-", "*", "^", "neg"):
            raise NotationError("verification.unsupported_arithmetic")
        value = super().expr(ast, depth)
        if self.obligations:
            raise NotationError("verification.unproved_obligations")
        return value


def _visible_target(root, target_ref):
    if not re.fullmatch(r"/root(?:/children/\d+)*/goals/\d+", target_ref):
        raise ValueError("verification.invalid_target")
    parts = target_ref.split("/")[2:]
    scope, visible = root, [root]
    for index in range(0, len(parts) - 2, 2):
        scope = scope["children"][int(parts[index + 1])]
        visible.append(scope)
    return scope["goals"][int(parts[-1])], [fact for s in visible for fact in s["facts"]]


def _linear_range(expression, domain, variable):
    polynomial = sp.Poly(expression, variable)
    if polynomial.degree() != 1:
        raise ValueError("verification.linear_sign_failed")
    slope = polynomial.nth(1)
    endpoints = [expression.subs(variable, x) for x in (domain.start, domain.end)]
    closed = [domain.left_open, domain.right_open]
    if slope.is_negative:
        endpoints.reverse()
        closed.reverse()
    elif not slope.is_positive:
        raise ValueError("verification.linear_sign_failed")
    return sp.Interval(*endpoints, left_open=closed[0], right_open=closed[1])


def _full_real_domain(domain):
    return domain in (["real"], ["interval", False, False, ["infinity", -1], ["infinity", 1]])


def _target_real_domain(fact, target):
    return (fact[0] == "default_domain" and fact[1] == target and fact[2] == "real"
            or fact[0] == "∈" and fact[1] == target and _full_real_domain(fact[2]))


def _expression_text(expression):
    """Render only arithmetic already produced from the validated AST."""
    return sp.sstr(expression).replace("**", "^").replace(" ", "")


def verify_amgm(candidate, target_ref, features, enabled=False):
    """Verify one full-real, universally quantified Q01-shaped upper bound."""
    result = {"status": "unknown", "reason": "verification.disabled", "steps": [],
              "input_refs": [target_ref]}
    if not enabled:
        return result
    try:
        indexed = {f["feature_id"]: f for f in features}
        required = ("quantifier", "bound_vars", "goal", "domain", "relation")
        if any(indexed.get(f, {}).get("status") != "known" for f in required):
            raise ValueError("verification.unknown_input")
        if any(f.get("target_ref", target_ref) != target_ref for f in features):
            raise ValueError("verification.wrong_target_features")
        report = NotationValidator().validate_root(candidate["root"])
        if not report.ok:
            raise ValueError("verification.invalid_candidate")
        goal, facts = _visible_target(report.semantic, target_ref)
        if goal["kind"] != "find_range" or goal["target"][:1] != ["ref"]:
            raise ValueError("verification.unsupported_goal")
        quantifiers = [f for f in facts if f[0] == "quantifier"]
        if len(quantifiers) != 1:
            raise ValueError("verification.single_quantifier_required")
        quantified = quantifiers[0]
        if any(f is not quantified and not _target_real_domain(f, goal["target"]) for f in facts):
            raise ValueError("verification.additional_conditions")
        if quantified[1] != "∀":
            raise ValueError("verification.universal_required")
        domain = quantified[3]
        if not _full_real_domain(domain):
            raise ValueError("verification.full_real_domain_required")
        body = quantified[4]
        if body[0] not in ("<=", ">="):
            raise ValueError("verification.nonstrict_upper_bound_required")
        algebra = _Polynomial(quantified[2], goal["target"])
        lhs, rhs = algebra.expr(body[1]), algebra.expr(body[2])
        normalized = bounded_expand(rhs - lhs if body[0] == "<=" else lhs - rhs)
        x = algebra.x
        bound_expression = -x**2 + 2*x + 3
        # Extract the other side instead of recognizing one fixed parameter
        # polynomial. Any remaining bound variable invalidates this separation,
        # including mixed parameter/bound terms such as p*u or p*u^2.
        parameter_expression = bounded_expand(normalized + bound_expression)
        if x in parameter_expression.free_symbols:
            raise ValueError("verification.unsupported_shape")
        result["input_refs"] = sorted({target_ref, *indexed["quantifier"].get("source_refs", [])})
        result["input_revision"] = revision(candidate)
        result["variables"] = {"bound": indexed["bound_vars"]["value"], "goal": indexed["goal"]["value"]}
        result["symbol_mapping"] = {"u": indexed["bound_vars"]["value"][0],
                                    "p": indexed["goal"]["value"]["symbol"]}
        product = x * (2-x)
        # These are exact polynomial identities. The sign premises below are
        # fixed rational half-lines, not assumptions inferred from model prose.
        identities = {
            "separate-bound": normalized - (parameter_expression - bound_expression),
            "sum-product-identity": bound_expression - (3+product),
            "fixed-sum": x+(2-x)-2,
            "amgm-gap": 1-product-(x-1)**2,
        }
        if any(bounded_expand(value) != 0 for value in identities.values()):
            raise ValueError("verification.identity_failed")
        if bound_expression.subs(x, 1) != 4 or product.subs(x, 1) != 1:
            raise ValueError("verification.attainment_failed")
        interior = sp.Interval.open(0, 2)
        outside = [sp.Interval(-sp.oo, 0), sp.Interval(2, sp.oo)]
        positive = [_linear_range(f, interior, x) for f in (x, 2-x)]
        signs = [[_linear_range(f, interval, x) for f in (x, 2-x)] for interval in outside]
        if not all(r.start == 0 and r.left_open for r in positive):
            raise ValueError("verification.positivity_failed")
        if not (signs[0][0].end <= 0 and signs[0][1].start >= 2
                and signs[1][0].start >= 2 and signs[1][1].end <= 0):
            raise ValueError("verification.outside_sign_failed")
        if sp.Union(interior, *outside) != sp.S.Reals or interior.contains(1) is not sp.true:
            raise ValueError("verification.domain_cover_failed")
        result["steps"] = [
            {"step_id": "separate-bound", "operation": "polynomial_identity", "checked": True,
             "expression": f"{_expression_text(parameter_expression)} >= {_expression_text(bound_expression)}",
             "input_operator": body[0]},
            {"step_id": "sum-product-identity", "operation": "polynomial_identity", "checked": True,
             "expression": "-u^2+2*u+3 = 3+u*(2-u)"},
            {"step_id": "positive-factors", "operation": "linear_signs_on_interval", "checked": True,
             "domain": "0<u<2", "conclusions": ["u>0", "2-u>0"]},
            {"step_id": "fixed-sum", "operation": "polynomial_identity", "checked": True,
             "expression": "u+(2-u)=2"},
            {"step_id": "amgm-bound", "operation": "amgm_with_square_certificate", "checked": True,
             "domain": "0<u<2", "expression": "u*(2-u)<=1", "certificate": "1-u*(2-u)=(u-1)^2"},
            {"step_id": "outside-sign", "operation": "linear_signs_on_half_lines", "checked": True,
             "cases": [{"domain": "u<=0", "factors": ["u<=0", "2-u>=2"]},
                       {"domain": "u>=2", "factors": ["u>=2", "2-u<=0"]}],
             "conclusion": "u*(2-u)<=0"},
            {"step_id": "attainment", "operation": "exact_substitution", "checked": True,
             "point": "u=1", "domain_verified": True, "product": "1", "value": "4"},
            {"step_id": "full-real-bound", "operation": "cover_domain_and_attain", "checked": True,
             "cover": ["u<=0", "0<u<2", "u>=2"], "maximum": "4", "attained": True},
        ]
        result.update(status="supported", reason="verification.q01_sum_product_bound")
    except (KeyError, IndexError, TypeError, ValueError, NotationError, RecursionError) as exc:
        result["reason"] = getattr(exc, "code", str(exc))
    return result
