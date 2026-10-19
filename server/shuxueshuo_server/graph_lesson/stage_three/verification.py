"""Independent, exact critical-cell proofs for the first execution category.

The verifier reads validated original notation, never the method's normalized
expression, features, or intermediate calculations.  Samples cover a proved
sign-invariant partition; sampling a proposed answer alone is not a proof.
"""

import re
from copy import deepcopy
from dataclasses import dataclass
from functools import cmp_to_key, lru_cache, wraps
from itertools import pairwise

import sympy as sp
from sympy.polys.polyerrors import BasePolynomialError

from ...problem_understanding.notation_compile import NotationValidator
from ...problem_understanding.notation_parser import NotationError
from ...problem_understanding.notation_semantics import Canonical, bounded_expand, key


class VerificationGap(ValueError):
    """The supported exact proof category does not cover this input."""


class ContextMismatch(ValueError):
    pass


def math_value(value):
    """Inert exact text and student display; neither field is parsed back."""
    return {"expression": sp.sstr(value), "latex": sp.latex(value)}


def _pointer(path):
    parts = re.sub(r"^r(?=\.|$)", "/root", path)
    parts = re.sub(r"\.c(\d+)", r"/children/\1", parts)
    return re.sub(r"\[(\d+)\]", r"/\1", parts.replace(".", "/"))


def _walk(ast, path=()):
    yield ast, path
    for i, child in enumerate(ast[1:], 1):
        if isinstance(child, list) and child and isinstance(child[0], str):
            yield from _walk(child, (*path, i))


def _source(candidate, path):
    value = candidate
    for part in path.strip("/").split("/"):
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def collect_original(candidate, target_ref):
    """Collect sources by walking original lexical ancestry, independently of context.py."""
    if not re.fullmatch(r"/root(?:/children/\d+)*/goals/\d+", target_ref):
        raise VerificationGap("invalid_target")
    report = NotationValidator().validate_root(candidate["root"])
    if not report.ok:
        raise VerificationGap("invalid_candidate")
    goal_scope, _, goal_index = target_ref.rsplit("/", 2)
    visible = ["/root"]
    semantic = report.semantic
    for index in goal_scope.removeprefix("/root").split("/children/")[1:]:
        visible.append(visible[-1] + "/children/" + index)
        semantic = semantic["children"][int(index)]
    goal = semantic["goals"][int(goal_index)]
    entries = []
    for compiled_scope, facts in report.scope_facts.items():
        scope = _pointer(compiled_scope)
        if scope not in visible:
            continue
        for row in facts:
            source = _pointer(row["path"])
            entries.append({"source_ref": source, "scope": scope,
                            "kind": "definition" if "/definitions/" in source else "fact",
                            "expression": deepcopy(_source(candidate, source)), "ast": deepcopy(row["value"])})
    objects = [o for o in report.objects if _pointer(o["scope"]) in visible]
    default_map = {item["ref"]: item for item in report.defaults}
    symbols = []
    for obj in objects:
        refs = [e["source_ref"] for e in entries
                if any(a[0] == "ref" and a[1] == obj["ref"] for a, _ in _walk(e["ast"]))]
        if any(a[0] == "ref" and a[1] == obj["ref"] for a, _ in _walk(goal["target"])):
            refs.append(target_ref)
        symbols.append({**obj, "scope": _pointer(obj["scope"]), "source_refs": refs,
                        "default_domain": default_map.get(obj["ref"])})
    bound, denominators = [], []
    for entry in entries:
        ast = entry["ast"]
        # Determine enclosing binders by path ancestry, rather than using the
        # driver's recursive collection function.
        binders = []
        for node, path in _walk(ast):
            if node[0] in ("quantifier", "set_builder", "function_definition"):
                function = node[0] == "function_definition"
                i = 2 if node[0] == "quantifier" else 1
                ref = entry["source_ref"] + ("#function_argument" if function
                                               else "#" + "/".join(map(str, (*path, i))))
                record = {"ref": ref, "name": "function_argument" if function else node[i],
                          "kind": "function_argument" if function else "bound",
                          "scope": entry["scope"], "source_ref": entry["source_ref"],
                          "domain": ["real"] if function else deepcopy(node[i + 1]),
                          "binding_path": list(path)}
                bound.append(record)
                binders.append((path, len(node) - 1, record))
        for node, path in _walk(ast):
            if node[0] == "/":
                active = [b[2]["ref"] for b in binders
                          if len(path) > len(b[0]) and path[:len(b[0])] == b[0]
                          and (b[2]["kind"] == "function_argument" or path[len(b[0])] == b[1])]
                denominators.append({"kind": "denominator_nonzero", "source_ref": entry["source_ref"],
                                     "scope": entry["scope"], "ast_path": list(path),
                                     "denominator": deepcopy(node[2]), "binding_refs": active})
    return {"target_ref": target_ref, "scope": goal_scope, "visible_scopes": visible,
            "goal": deepcopy(_source(candidate, target_ref)), "goal_ast": deepcopy(goal),
            "entries": entries, "symbols": symbols, "bound_symbols": bound,
            "default_domains": [default_map[o["ref"]] for o in objects if o["ref"] in default_map],
            "well_definedness": denominators}


def _without_processing(value):
    if isinstance(value, dict):
        return {k: _without_processing(v) for k, v in value.items() if k != "processing"}
    if isinstance(value, list):
        return [_without_processing(v) for v in value]
    return value


def check_context(original, context):
    for field, value in original.items():
        if _without_processing(context.get(field)) != value:
            raise ContextMismatch("constraint_context_mismatch:" + field)


class _Arithmetic(Canonical):
    def __init__(self, symbols, parameter_ref, bound):
        super().__init__()
        self.names = {s["ref"]: s["name"] for s in symbols}
        self.parameter_ref = parameter_ref
        self.parameter = sp.Symbol(self.names[parameter_ref], real=True)
        self.x = sp.Dummy("quantified", real=True)
        self.bound = bound
        self.denominators = []

    def expr(self, ast, depth=0):
        if depth > 40:
            raise VerificationGap("arithmetic_depth")
        if ast[0] == "ref":
            if ast[1] != self.parameter_ref:
                raise VerificationGap("unsupported_constraint:additional_free_variable")
            return self.parameter
        if ast[0] == "bound":
            if ast[1] != self.bound:
                raise VerificationGap("unsupported_constraint:bound_variable")
            return self.x
        if ast[0] == "call" and (ast[1] != "sqrt" or self.expr(ast[2], depth + 1).free_symbols):
            raise VerificationGap("verification_incomplete:symbolic_radical")
        if ast[0] not in ("number", "+", "-", "*", "/", "^", "neg", "call", "function_call"):
            raise VerificationGap("verification_incomplete:arithmetic")
        value = super().expr(ast, depth)
        if ast[0] == "/":
            self.denominators.append(self.expr(ast[2], depth + 1))
        elif ast[0] == "^" and self.expr(ast[2], depth + 1).is_negative:
            self.denominators.append(self.expr(ast[1], depth + 1))
        return value


@dataclass
class OriginalProblem:
    original: dict
    algebra: _Arithmetic
    expression: sp.Expr
    main_ref: str
    constraints: list
    denominators: list
    processing: list

    @property
    def parameter(self):
        return self.algebra.parameter

    @property
    def x(self):
        return self.algebra.x


def _real_domain(ast):
    return ast == ["real"] or (ast[0] == "interval" and ast[3:] == [["infinity", -1], ["infinity", 1]])


def _interval(ast, algebra):
    if ast == ["real"]:
        return sp.S.Reals
    if ast[0] != "interval":
        raise VerificationGap("unsupported_constraint:parameter_domain")
    endpoints = []
    for value in ast[3:]:
        endpoint = value[1] * sp.oo if value[0] == "infinity" else algebra.expr(value)
        if endpoint.free_symbols or endpoint.is_extended_real is not True:
            raise VerificationGap("unsupported_constraint:parameter_domain")
        endpoints.append(endpoint)
    return sp.Interval(*endpoints, left_open=not ast[1], right_open=not ast[2])


def _poly(expression, parameter):
    try:
        result = sp.Poly(expression, parameter, domain=sp.QQ)
    except BasePolynomialError as exc:
        raise VerificationGap("verification_incomplete:rational_polynomial_required") from exc
    if result.degree() > 48:
        raise VerificationGap("verification_incomplete:polynomial_degree_limit")
    return result


def _flatten(ast):
    if ast[0] == "and":
        return [atom for child in ast[1:] for atom in _flatten(child)]
    return [ast]


def read_problem(candidate, target_ref, constraint_context=None):
    original = collect_original(candidate, target_ref)
    if constraint_context is not None:
        check_context(original, constraint_context)
    goal = original["goal_ast"]
    if goal["kind"] not in ("find_range", "find_minimum", "find_maximum") or goal["target"][:1] != ["ref"]:
        raise VerificationGap("verification_incomplete:single_real_parameter")
    atoms = [(entry, atom) for entry in original["entries"] for atom in _flatten(entry["ast"])]
    quantified = [(entry, atom) for entry, atom in atoms if atom[0] == "quantifier"]
    if len(quantified) != 1:
        raise VerificationGap("unsupported_constraint:single_quantifier_required")
    main_entry, main = quantified[0]
    if main[1] != "∀" or not _real_domain(main[3]) or main[4][0] not in (">=", "<="):
        raise VerificationGap("verification_incomplete:universal_full_real_nonstrict")
    algebra = _Arithmetic(original["symbols"], goal["target"][1], main[2])
    processing, constraints, denominator_sources = [], [], []
    for entry, atom in atoms:
        if atom[0] == "function_definition":
            algebra.functions[key(algebra.tree(atom[1]))] = atom[2]
            processing.append({"source_ref": entry["source_ref"], "status": "expanded_definition"})
    # Definitions remain visible constraints even if an algebraic cancellation
    # or an unused function hides their body from the main relation.  Inspect
    # their original arithmetic before any normalization can remove holes.
    for entry, atom in atoms:
        if atom[0] == "function_definition":
            algebra.bound = "function_argument"
            algebra.expr(atom[2])
            denominator_sources.extend((d, entry["source_ref"]) for d in algebra.denominators)
            algebra.denominators.clear()
    algebra.bound = main[2]
    lhs, rhs = (algebra.expr(side) for side in main[4][1:])
    expression = bounded_expand(lhs - rhs if main[4][0] == ">=" else rhs - lhs)
    denominator_sources.extend((d, main_entry["source_ref"]) for d in algebra.denominators)
    algebra.denominators.clear()
    try:
        polynomial = sp.Poly(expression, algebra.x)
    except BasePolynomialError as exc:
        raise VerificationGap("verification_incomplete:quadratic_required") from exc
    if polynomial.degree() != 2 or polynomial.nth(2).is_Rational is not True or polynomial.nth(2) <= 0:
        raise VerificationGap("verification_incomplete:positive_constant_quadratic")
    for coefficient in polynomial.all_coeffs():
        _poly(coefficient, algebra.parameter)
    for entry, atom in atoms:
        source_ref = entry["source_ref"]
        if atom is main:
            processing.append({"source_ref": source_ref, "status": "main_quantifier"})
            continue
        if atom[0] == "function_definition":
            continue
        if atom[0] == "default_domain" and atom[1] == goal["target"] and atom[2] == "real":
            processing.append({"source_ref": source_ref, "status": "redundant_real_domain"})
        elif atom[0] == "∈" and atom[1] == goal["target"]:
            domain = _interval(atom[2], algebra)
            constraints.append({"source_ref": source_ref, "kind": "membership", "set": domain})
            processing.append({"source_ref": source_ref, "status": "parameter_constraint", "set": math_value(domain)})
        elif atom[0] in ("<", "<=", ">", ">=", "=", "!="):
            difference = bounded_expand(algebra.expr(atom[1]) - algebra.expr(atom[2]))
            if _poly(difference, algebra.parameter).degree() > 1:
                raise VerificationGap("unsupported_constraint:nonlinear_parameter_condition")
            constraints.append({"source_ref": source_ref, "kind": "relation", "expression": difference,
                                "operator": atom[0]})
            processing.append({"source_ref": source_ref, "status": "parameter_constraint"})
        else:
            raise VerificationGap("unsupported_constraint:" + source_ref)
        denominator_sources.extend((d, source_ref) for d in algebra.denominators)
        algebra.denominators.clear()
    for denominator, _ in denominator_sources:
        if algebra.x in denominator.free_symbols:
            raise VerificationGap("verification_incomplete:bound_variable_denominator")
        numerator, denominator_part = sp.fraction(sp.cancel(denominator))
        _poly(numerator, algebra.parameter)
        _poly(denominator_part, algebra.parameter)
    return OriginalProblem(original, algebra, expression, main_entry["source_ref"], constraints,
                           denominator_sources, processing)


def _relation(expression, operator):
    return {"<": sp.Lt, "<=": sp.Le, ">": sp.Gt, ">=": sp.Ge, "=": sp.Eq, "!=": sp.Ne}[operator](expression, 0)


_SYMPY_COMPUTATION_ERRORS = (BasePolynomialError, NotImplementedError, IndexError, ValueError, ZeroDivisionError)


def _sympy_call(operation, function, *args, **kwargs):
    """An explicit library boundary, never a blanket catch around our control flow.

    SymPy sometimes raises IndexError/ValueError while isolating valid algebraic
    inputs.  Those are unproved computations.  The documented undecidable
    relational truth-value TypeError is also a gap; other KeyError/TypeError,
    or an index/value error from our own bookkeeping, remain programming failures.
    """
    try:
        return function(*args, **kwargs)
    except (ContextMismatch, VerificationGap):
        raise
    except _SYMPY_COMPUTATION_ERRORS as exc:
        raise VerificationGap("verification_incomplete:sympy_" + operation) from exc
    except TypeError as exc:
        if not str(exc).startswith("cannot determine truth value of Relational"):
            raise
        raise VerificationGap("verification_incomplete:sympy_" + operation) from exc


def _sympy_traceback(exc):
    """Fallback for SymPy operations performed through Python arithmetic hooks."""
    trace = exc.__traceback__
    while trace is not None:
        if trace.tb_frame.f_globals.get("__name__", "").startswith("sympy."):
            return True
        trace = trace.tb_next
    return False


def _library_exception_details(exc):
    cause = exc.__cause__
    if isinstance(exc, VerificationGap) and cause is not None and (
        str(exc).startswith("verification_incomplete:sympy_") or _sympy_traceback(cause)
    ):
        exc = cause
    elif not _sympy_traceback(exc):
        return {}
    return {"library_exception_type": type(exc).__name__, "library_exception_message": str(exc)}


def _is_sympy_computation_failure(exc):
    return _sympy_traceback(exc) and (
        not isinstance(exc, TypeError) or str(exc).startswith("cannot determine truth value of Relational")
    )


def _sympy_gap_boundary(function):
    """Protect non-verdict operations while leaving local bugs and mismatches visible."""
    @wraps(function)
    def guarded(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except (ContextMismatch, VerificationGap):
            raise
        except (*_SYMPY_COMPUTATION_ERRORS, TypeError) as exc:
            if not _is_sympy_computation_failure(exc):
                raise
            raise VerificationGap("verification_incomplete:sympy_" + function.__name__) from exc

    return guarded


@lru_cache(maxsize=512)
def _algebraic_value(value):
    """Prove zero/rational values from the minimal polynomial of the whole value.

    Expression equality/is_zero alone is insufficient for r**3-r-1 when r is
    a RootOf.  Its minimal polynomial is z, so its exact value is zero.  A
    degree-one minimal polynomial similarly gives the unique rational value.
    Higher-degree values retain their original real embedding for certified
    interval signs; the polynomial's constant term alone is not a sign test.

    Do not compose a field from every nested radical atom: sqrt(1+sqrt(2)) and
    sqrt(2) are redundant generators, and that route can make SymPy's primitive
    element construction expensive or fail internally.
    """
    if value.is_Rational:
        return value
    if value.free_symbols or value.has(sp.Float, sp.nan, sp.zoo, sp.oo, -sp.oo):
        raise VerificationGap("verification_incomplete:exact_algebraic_value_required")
    algebraic_atoms = value.atoms(sp.CRootOf) | {
        power for power in value.atoms(sp.Pow) if power.exp.is_Rational and not power.exp.is_Integer
    }
    if not algebraic_atoms:
        raise VerificationGap("verification_incomplete:algebraic_value_unsupported")
    variable = sp.Dummy("algebraic_value")
    expression = _sympy_call("minimal_polynomial", sp.minpoly, value, variable)
    polynomial = _sympy_call("minimal_polynomial_domain", sp.Poly, expression, variable, domain=sp.QQ)
    if polynomial.degree() == 1:
        return -polynomial.nth(0) / polynomial.nth(1)
    if polynomial.degree() < 1 or polynomial.nth(0) == 0:
        raise VerificationGap("verification_incomplete:invalid_minimal_polynomial")
    return value


def _interval_product(left, right):
    products = [a*b for a in left for b in right]
    return min(products), max(products)


def _integer_power(bounds, exponent):
    if exponent == 0:
        return sp.S.One, sp.S.One
    if exponent < 0:
        if bounds[0] <= 0 <= bounds[1]:
            return None
        bounds = (1 / bounds[1], 1 / bounds[0])
        exponent = -exponent
    values = [value**exponent for value in bounds]
    if exponent % 2 == 0 and bounds[0] <= 0 <= bounds[1]:
        values.append(sp.S.Zero)
    return min(values), max(values)


def _rational_root_bound(value, degree, precision):
    """Certified dyadic enclosure using integer nth roots, without evalf."""
    scale = 2**precision
    floor_power = int(sp.floor(value * scale**degree))
    lower, _exact = sp.integer_nthroot(floor_power, degree)
    lower = sp.Rational(lower, scale)
    upper = lower if lower**degree == value else lower + sp.Rational(1, scale)
    return lower, upper


def _algebraic_interval(value, roots, precision):
    """Outward rational arithmetic over real-root isolating intervals."""
    if value.is_Rational:
        return value, value
    if isinstance(value, sp.CRootOf):
        if value.is_real is not True:
            raise VerificationGap("verification_incomplete:nonreal_algebraic_value")
        interval = roots[value]
        return sp.Rational(interval.a), sp.Rational(interval.b)
    if value.is_Add or value.is_Mul:
        result = (sp.S.Zero, sp.S.Zero) if value.is_Add else (sp.S.One, sp.S.One)
        for argument in value.args:
            bound = _algebraic_interval(argument, roots, precision)
            if bound is None:
                return None
            result = ((result[0] + bound[0], result[1] + bound[1]) if value.is_Add
                      else _interval_product(result, bound))
        return result
    if value.is_Pow and value.exp.is_Rational:
        bound = _algebraic_interval(value.base, roots, precision)
        if bound is None:
            return None
        if value.exp.is_Integer:
            return _integer_power(bound, int(value.exp))
        if bound[0] < 0:
            return None
        degree = int(value.exp.q)
        if degree > 48:
            raise VerificationGap("verification_incomplete:radical_degree_limit")
        lower = _rational_root_bound(bound[0], degree, precision)[0]
        upper = _rational_root_bound(bound[1], degree, precision)[1]
        return _integer_power((lower, upper), int(value.exp.p))
    raise VerificationGap("verification_incomplete:algebraic_interval_unsupported")


@lru_cache(maxsize=512)
def _algebraic_sign(value):
    """Return -1/0/+1 only with exact evidence; undecidable means a gap."""
    value = _algebraic_value(value)
    if value.is_Rational:
        return 0 if value == 0 else 1 if value > 0 else -1
    roots = {root: _sympy_call("root_interval", root._get_interval) for root in value.atoms(sp.CRootOf)}
    for precision in range(4, 260):
        bounds = _algebraic_interval(value, roots, precision)
        if bounds is not None:
            if bounds[0] > 0:
                return 1
            if bounds[1] < 0:
                return -1
        roots = {root: _sympy_call("root_refinement", interval.refine) for root, interval in roots.items()}
    raise VerificationGap("verification_incomplete:algebraic_sign_unproved")


def _relation_holds(expression, operator):
    sign = _algebraic_sign(expression)
    return {"<": sign < 0, "<=": sign <= 0, ">": sign > 0,
            ">=": sign >= 0, "=": sign == 0, "!=": sign != 0}[operator]


def _contains_exact(domain, value):
    if domain == sp.S.Reals:
        return True
    if domain == sp.S.EmptySet:
        return False
    if isinstance(domain, sp.Interval):
        left = 1 if domain.start is -sp.oo else _algebraic_sign(value - domain.start)
        right = -1 if domain.end is sp.oo else _algebraic_sign(value - domain.end)
        return (left > 0 or left == 0 and not domain.left_open) and (right < 0 or right == 0 and not domain.right_open)
    if isinstance(domain, sp.FiniteSet):
        return any(_algebraic_sign(value - member) == 0 for member in domain)
    if isinstance(domain, sp.Union):
        return any(_contains_exact(member, value) for member in domain.args)
    raise VerificationGap("verification_incomplete:set_membership")


def _constraint_set(constraint, parameter):
    if constraint["kind"] == "membership":
        return constraint["set"]
    relation = _relation(constraint["expression"], constraint["operator"])
    if relation is sp.true:
        return sp.S.Reals
    if relation is sp.false:
        return sp.S.EmptySet
    return sp.solve_univariate_inequality(relation, parameter, relational=False)


@_sympy_gap_boundary
def apply_visible_constraints(candidate, target_ref, constraint_context, feasible_set):
    """Intersect every supported visible restriction and retain discharge records."""
    problem = read_problem(candidate, target_ref, constraint_context)
    result = feasible_set
    processing = deepcopy(problem.processing)
    for constraint in problem.constraints:
        domain = _constraint_set(constraint, problem.parameter)
        result = result.intersect(domain)
        processing.append({"source_ref": constraint["source_ref"], "status": "intersected",
                           "constraint_set": math_value(domain), "result": math_value(result)})
    for expression, source in problem.denominators:
        zeros = sp.solveset(expression, problem.parameter, domain=sp.S.Reals)
        if zeros.has(sp.ConditionSet):
            raise VerificationGap("verification_incomplete:denominator_zeros")
        result = result - zeros
        processing.append({"source_ref": source, "status": "original_denominator_nonzero",
                           "denominator": math_value(expression), "excluded": math_value(zeros)})
    return result, processing


def _point(problem, value):
    evidence = []
    for expression, source in problem.denominators:
        evaluated = sp.cancel(expression.subs(problem.parameter, value))
        holds = evaluated not in (sp.nan, sp.zoo) and _algebraic_sign(evaluated) != 0
        evidence.append({"source_ref": source, "kind": "definedness", "holds": holds,
                         "value": math_value(evaluated)})
        if not holds:
            return False, evidence
    for constraint in problem.constraints:
        holds = (_contains_exact(constraint["set"], value) if constraint["kind"] == "membership"
                 else _relation_holds(constraint["expression"].subs(problem.parameter, value), constraint["operator"]))
        evidence.append({"source_ref": constraint["source_ref"], "kind": "parameter_constraint", "holds": holds})
        if not holds:
            return False, evidence
    # Prove the original predicate directly at this exact parameter.  A set
    # returned by solve_univariate_inequality may retain unsimplified RootOf
    # endpoints, so structural inequality with Reals must never mean False.
    # This independently constructed square identity uses no method outputs.
    polynomial = sp.Poly(problem.expression.subs(problem.parameter, value), problem.x)
    a, b, c = (_algebraic_value(polynomial.nth(i)) for i in (2, 1, 0))
    if polynomial.degree() != 2 or _algebraic_sign(a) != 1:
        raise VerificationGap("verification_incomplete:point_quadratic_category")
    vertex = _algebraic_value(-b / (2*a))
    minimum = _algebraic_value(c - b**2 / (4*a))
    identity = sp.Poly(bounded_expand(polynomial.as_expr() - a*(problem.x-vertex)**2-minimum), problem.x)
    if any(_algebraic_sign(coefficient) != 0 for coefficient in identity.all_coeffs()):
        raise VerificationGap("verification_incomplete:point_square_identity")
    sign = _algebraic_sign(minimum)
    holds = sign >= 0
    evidence.append({"source_ref": problem.main_ref, "kind": "quantified_predicate", "holds": holds,
                     "certificate": {"kind": "positive_quadratic_minimum", "identity_verified": True,
                                     "leading_coefficient": math_value(a), "vertex": math_value(vertex),
                                     "minimum": math_value(minimum), "minimum_sign": sign}})
    if not holds:
        evidence[-1]["counterexample"] = {"bound_variable": math_value(vertex), "value": math_value(minimum)}
    return holds, evidence


def _compare(a, b):
    return _algebraic_sign(a - b)


def _rational_between(left, right):
    if left is -sp.oo and right is sp.oo:
        return sp.S.Zero
    if left is -sp.oo:
        return sp.floor(right) - 1
    if right is sp.oo:
        return sp.ceiling(left) + 1
    scale = 1
    for _ in range(256):
        sample = (sp.floor(left * scale) + 1) / scale
        if _compare(left, sample) < 0 and _compare(sample, right) < 0:
            return sample
        scale *= 2
    raise VerificationGap("verification_incomplete:rational_isolation")


def _critical(problem):
    parameter, x = problem.parameter, problem.x
    polynomial = sp.Poly(problem.expression, x)
    sources = [(c, problem.main_ref, "coefficient") for c in polynomial.all_coeffs()]
    sources.append((sp.discriminant(polynomial.as_expr(), x), problem.main_ref, "discriminant"))
    for c in problem.constraints:
        if c["kind"] == "relation":
            sources.append((c["expression"], c["source_ref"], "parameter_condition"))
        elif isinstance(c["set"], sp.Interval):
            for boundary in (c["set"].start, c["set"].end):
                if boundary not in (-sp.oo, sp.oo):
                    # Algebraic endpoints have a rational minimal polynomial.
                    expression = _sympy_call("boundary_minimal_polynomial", sp.minpoly, boundary, parameter)
                    sources.append((expression, c["source_ref"], "parameter_domain_boundary"))
    sources.extend((d, ref, "original_denominator") for d, ref in problem.denominators)
    records, roots = [], []
    for expression, source, kind in sources:
        numerator, denominator = sp.fraction(sp.cancel(expression))
        for part, value in (("numerator", numerator), ("denominator", denominator)):
            poly = _poly(value, parameter)
            real_roots = [] if poly.is_zero or poly.degree() == 0 else _sympy_call("real_roots", poly.real_roots)
            isolation = [] if not real_roots else [
                {"lower": math_value(bounds[0]), "upper": math_value(bounds[1]), "multiplicity": multiplicity}
                for bounds, multiplicity in _sympy_call("root_isolation", poly.intervals)
            ]
            record = {"source_ref": source, "kind": kind, "part": part, "polynomial": math_value(value),
                      "identically_zero": bool(poly.is_zero), "roots": [math_value(r) for r in real_roots],
                      "isolating_intervals": isolation}
            records.append(record)
            roots.extend(real_roots)
    ordered = sorted(roots, key=cmp_to_key(_compare))
    unique = []
    for root in ordered:
        if not unique or _compare(root, unique[-1]):
            unique.append(root)
    return unique, records


def _supported_set(value):
    if value in (sp.S.EmptySet, sp.S.Reals):
        return
    if isinstance(value, sp.Union):
        for part in value.args:
            _supported_set(part)
        return
    if not isinstance(value, (sp.Interval, sp.FiniteSet)):
        raise VerificationGap("verification_incomplete:candidate_set")
    endpoints = value.args[:2] if isinstance(value, sp.Interval) else value.args
    if any(e not in (-sp.oo, sp.oo) and (e.is_real is not True or e.is_algebraic is not True) for e in endpoints):
        raise VerificationGap("verification_incomplete:candidate_endpoint")


def _set_boundaries(value):
    if value in (sp.S.EmptySet, sp.S.Reals):
        return []
    if isinstance(value, sp.FiniteSet):
        return list(value)
    if isinstance(value, sp.Union):
        return [point for part in value.args for point in _set_boundaries(part)]
    if isinstance(value, sp.Interval):
        return [point for point in (value.start, value.end) if point not in (-sp.oo, sp.oo)]
    raise VerificationGap("verification_incomplete:set_comparison")


def _set_mismatch(left, right):
    """Exact equality for supported finite unions, independent of set simplification.

    RootOf and nested-radical spellings can denote the same endpoint without
    SymPy normalizing their symmetric difference.  On the common, exactly
    ordered endpoint partition each set's membership is constant on every open
    cell.  Comparing all cells and singleton endpoints is a complete equality
    proof, after the independent original-predicate proof has been built.
    """
    points = []
    for point in sorted([*_set_boundaries(left), *_set_boundaries(right)], key=cmp_to_key(_compare)):
        if not points or _compare(point, points[-1]) != 0:
            points.append(point)
    for index, (lower, upper) in enumerate(pairwise([-sp.oo, *points, sp.oo])):
        sample = _rational_between(lower, upper)
        if _contains_exact(left, sample) != _contains_exact(right, sample):
            return sample
        if index < len(points) and _contains_exact(left, points[index]) != _contains_exact(right, points[index]):
            return points[index]
    return None


def verify(candidate, target_ref, constraint_context, feasible_set):
    """Prove the entire proposed set by an original-input critical partition."""
    result = {"status": "capability_gap", "proof": {}, "diagnostics": []}
    try:
        problem = read_problem(candidate, target_ref, constraint_context)
        _supported_set(feasible_set)
        points, critical = _critical(problem)
        boundaries = [-sp.oo, *points, sp.oo]
        cells, accepted = [], []
        for i, (left, right) in enumerate(pairwise(boundaries)):
            interval = sp.Interval.open(left, right)
            sample = _rational_between(left, right)
            holds, evidence = _point(problem, sample)
            cells.append({"kind": "open_interval", "domain": math_value(interval), "sample": math_value(sample),
                          "holds": holds, "evidence": evidence})
            if holds:
                accepted.append(interval)
            if i < len(points):
                point = points[i]
                holds, evidence = _point(problem, point)
                cells.append({"kind": "critical_point", "domain": math_value(sp.FiniteSet(point)),
                              "sample": math_value(point), "holds": holds, "evidence": evidence})
                if holds:
                    accepted.append(sp.FiniteSet(point))
        reconstructed = sp.Union(*accepted)
        result["proof"] = {
            "category": "positive-rational-leading-universal-real-quadratic/v1",
            "source_refs": [e["source_ref"] for e in problem.original["entries"]],
            "critical_polynomials": critical,
            "critical_points": [{**math_value(p), "sources": [
                {"source_ref": item["source_ref"], "kind": item["kind"], "part": item["part"]}
                for item in critical if math_value(p) in item["roots"]
            ]} for p in points],
            "invariance": {"proved": True, "reason": "Positive constant degree-two leading coefficient; all coefficient, discriminant, condition and original-denominator signs are fixed between their complete exact real roots."},
            "cells": cells, "reconstructed_set": math_value(reconstructed), "candidate_set": math_value(feasible_set),
        }
        sample = _set_mismatch(reconstructed, feasible_set)
        if sample is None:
            result["status"] = "verified"
        else:
            holds, evidence = _point(problem, sample)
            included = _contains_exact(feasible_set, sample)
            if holds == included:
                raise VerificationGap("verification_incomplete:set_equivalence")
            result.update(status="math_failed", counterexample={"parameter": math_value(sample),
                          "original_holds": holds, "candidate_includes": included,
                          "reason": "missing_feasible_point" if holds else "extraneous_point", "evidence": evidence})
            result["diagnostics"].append({"code": "verification.set_mismatch", "path": target_ref})
    except ContextMismatch as exc:
        result.update(status="math_failed", diagnostics=[{"code": "constraint_context_mismatch", "message": str(exc), "path": target_ref}])
    except (VerificationGap, NotationError, BasePolynomialError, NotImplementedError) as exc:
        result.update(status="capability_gap", diagnostics=[{
            "code": "verification_incomplete", "message": str(exc), "path": target_ref,
            **_library_exception_details(exc),
        }])
    except (IndexError, ValueError, ZeroDivisionError, TypeError) as exc:
        # Arithmetic overloads can enter library code without an explicit call
        # above. Only a traceback actually crossing SymPy is a computation gap;
        # an error in our own source/partition bookkeeping must not disappear.
        if not _is_sympy_computation_failure(exc):
            raise
        result.update(status="capability_gap", diagnostics=[{
            "code": "verification_incomplete", "message": "sympy_computation_failed:" + type(exc).__name__,
            "path": target_ref, **_library_exception_details(exc),
        }])
    return result


@_sympy_gap_boundary
def endpoint_check(candidate, target_ref, feasible_set):
    """Independent exact boundary evidence, including excluded candidate ends."""
    problem = read_problem(candidate, target_ref)
    _supported_set(feasible_set)
    boundaries = feasible_set.boundary
    if not isinstance(boundaries, sp.FiniteSet) and boundaries != sp.S.EmptySet:
        raise VerificationGap("verification_incomplete:boundary_set")
    rows = []
    for point in sorted(boundaries, key=cmp_to_key(_compare)):
        holds, evidence = _point(problem, point)
        included = _contains_exact(feasible_set, point)
        rows.append({"point": math_value(point), "included": included, "holds": holds,
                     "passed": included == holds, "evidence": evidence})
    return {"status": "passed" if all(r["passed"] for r in rows) else "failed", "points": rows}
