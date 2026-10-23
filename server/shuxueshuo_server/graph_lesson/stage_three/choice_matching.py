"""Match printed choices to an already verified answer using exact mathematics.

Call this optional capability in a bounded worker after mathematical completion.
Printed alternatives are never appended to the problem's conditions, and neither
display strings nor numerical sampling decide which label is correct.
"""

import sympy as sp

from ...problem_understanding.notation_compile import Report, Scope, typecheck
from ...problem_understanding.notation_parser import NotationError, parse
from .choice_source import choice_source
from .context import build_context
from .goals import _answer_value, verify_goal_answer
from .route_constraints import _condition_set, _relation_domain, _RouteArithmetic
from .trajectory import decode_value
from .verification import VerificationGap, _set_mismatch, _supported_set

_SETS = {"real", "empty_set", "interval", "tuple", "set", "set_builder", "∪", "∩"}
_RELATIONS = {"=", "!=", "<", "<=", ">", ">=", "∈", "∉", "and", "or"}


def _domain(ast):
    """Validate set syntax, including unions of the parser's interval domains."""
    kind = ast[0]
    if kind in ("∪", "∩"):
        return [kind, *[_domain(child) for child in ast[1:]]]
    if kind == "tuple":
        ast = ["interval", False, False, *ast[1:]]
    if kind == "set_builder":
        return [kind, ast[1], _domain(ast[2]), _condition(ast[3])]
    if typecheck(ast) not in ("domain", "set"):
        raise NotationError("choice.set_required")
    return ast


def _condition(ast):
    kind = ast[0]
    if kind in ("and", "or"):
        return [kind, *[_condition(child) for child in ast[1:]]]
    if kind == "default_domain":
        ast = ["∈", ast[1], ["real"]]
        kind = "∈"
    if kind in ("∈", "∉"):
        if typecheck(ast[1]) != "scalar":
            raise NotationError("choice.scalar_required")
        return [kind, ast[1], _domain(ast[2])]
    if kind not in _RELATIONS or any(typecheck(part) != "scalar" for part in ast[1:]):
        raise NotationError("choice.parameter_condition_required")
    return ast


def _option_set(expression, parameter_name, goal_kind):
    """Interpret one alternative in a fresh scope containing only the target."""
    ast = parse(expression)
    report = Report()
    scope = Scope(report, "choice")
    symbol = scope.declare(parameter_name, "scalar")
    parameter = ["ref", symbol["ref"], "scalar"]
    algebra = _RouteArithmetic({"goal_ast": {"kind": "find_range", "target": parameter},
                                "symbols": [symbol]})
    if ast[0] in _SETS:
        if goal_kind != "find_range":
            raise NotationError("choice.scalar_answer_required")
        # Open intervals are parsed as tuples. Bind each domain before checking
        # its type, without treating a tuple as an arithmetic expression.
        bound = ["∈", parameter, _domain(scope.bind(ast))]
    elif ast[0] in _RELATIONS:
        bound = _condition(scope.bind(ast))
    elif goal_kind != "find_range":
        value = scope.bind(ast)
        if typecheck(value) != "scalar":
            raise NotationError("choice.scalar_answer_required")
        bound = ["=", parameter, value]
    else:
        raise NotationError("choice.parameter_condition_required")
    result = _condition_set(bound, algebra)
    for divisor in algebra.guards:
        result &= _relation_domain(divisor, "!=", algebra.parameter)
    _supported_set(result)
    if goal_kind != "find_range" and not isinstance(result, sp.FiniteSet):
        raise NotationError("choice.scalar_answer_required")
    if goal_kind != "find_range" and len(result) != 1:
        raise NotationError("choice.scalar_answer_required")
    return result


def match_original_choice(candidate, target_ref, answer, feasible_set_exact=None):
    """Return one certified label, or an explicit unavailable reason (never guess).

    Range answers have a legacy display-only set, so their separately verified
    exact feasible set is required. Unsupported, incomplete, or ambiguous
    alternatives disable only this optional final exercise. Multiple-selection
    questions need a separate statement-verification contract and are deferred.
    """
    source = choice_source(candidate, target_ref)
    if source["status"] == "not_choice":
        return None
    base = {"status": "unavailable", "target_ref": target_ref}
    if source["status"] != "recognized":
        return {**base, "reason": source["reason"]}
    if source["selection_mode"] == "multiple":
        return {**base, "reason": "choice.multiple_selection_unsupported"}
    try:
        context = build_context(candidate, target_ref)
        goal, goal_ast = context["goal"], context["goal_ast"]
        if (goal["kind"] not in ("find_range", "find_minimum", "find_maximum")
                or goal_ast["target"][0] != "ref" or answer.get("kind") != goal["kind"]):
            return {**base, "reason": "choice.unsupported_goal"}
        if feasible_set_exact is not None:
            feasible = decode_value(feasible_set_exact)
            _supported_set(feasible)
            verify_goal_answer(goal, feasible, answer)
        elif goal["kind"] == "find_range":
            return {**base, "reason": "choice.exact_answer_required"}
        if goal["kind"] == "find_range":
            expected = feasible
        elif answer.get("status") == "attained":
            expected = sp.FiniteSet(_answer_value(answer, "value"))
        else:
            return {**base, "reason": "choice.unattained_answer_unsupported"}
        parameter_name = next(symbol["name"] for symbol in context["symbols"]
                              if symbol["ref"] == goal_ast["target"][1])
        option_sets = []
        for option in source["options"]:
            if not isinstance(option["expression"], str):
                return {**base, "reason": "choice.unsupported_option"}
            option_sets.append(_option_set(option["expression"], parameter_name, goal["kind"]))
        matches = [option["label"] for option, value in zip(source["options"], option_sets, strict=True)
                   if _set_mismatch(value, expected) is None]
    except (NotationError, VerificationGap, ValueError, TypeError, KeyError,
            StopIteration, IndexError, RecursionError, ZeroDivisionError):
        return {**base, "reason": "choice.unverifiable_options"}
    if len(matches) != 1:
        return {**base, "reason": "choice.ambiguous_match" if matches else "choice.no_match"}
    return {"status": "matched", "kind": "single_choice", "target_ref": target_ref,
            "options": [{"label": option["label"], "text": option["text"]}
                        for option in source["options"]], "correct_labels": matches}


def dispatch(payload):
    """Independent worker entry; does not share mathematical fault hooks/budget."""
    return match_original_choice(payload["candidate"], payload["target_ref"],
                                 payload["answer"], payload["feasible_set_exact"])
