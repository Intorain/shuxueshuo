"""Freeze readable mathematical fragments at explicit contract boundaries."""

from copy import deepcopy

import sympy as sp

from ...problem_understanding.identity import revision
from .execution_contracts import read
from .math_values import math_value
from .presentation_templates import render_case_prefix, render_template
from .presentation_templates import validate_registry as _validate_registry
from .revision_manifest import math_step_hash, revision_ref
from .trajectory import decode_value


def validate_registry(registry=None):
    return _validate_registry(read("presentation-registry") if registry is None else registry)


def make_fragment(
    state,
    *,
    unit_id,
    method_ref,
    template,
    before=(),
    after=(),
    source_refs=(),
    used_basis=(),
    explanation=None,
    case_path=(),
    premise_refs=(),
):
    settings = read("presentation-registry")["templates"][template]
    ordinal = len(state["fragments"]) + 1
    target_key = revision(state["target_ref"])[:10]
    value = {
        "contract": "graph-math-step/v2",
        "lesson_version": state["lesson_version"],
        "run_id": state["run_id"],
        "target_ref": state["target_ref"],
        "route_id": state["route_id"],
        "step_id": f"{target_key}-{state['route_id']}-{ordinal:03d}-{unit_id}",
        "ordinal": ordinal,
        "method_ref": method_ref,
        "source_refs": list(source_refs),
        "case_path": list(case_path),
        "title": settings["title"],
        "before": [math_value(v) for v in before],
        "after": [math_value(v) for v in after],
        "explanation": explanation or settings["explanation"],
        "premise_refs": sorted(set(premise_refs)),
        "used_basis": sorted(set(used_basis)),
        "local_check": "passed",
        "revisions_ref": revision_ref(state),
        "display_unit": unit_id,
    }
    value["math_step_sha256"] = math_step_hash(value)
    return value


def render_unit(state, frame, step, unit, bindings, source_refs, used_basis, premise_refs=()):
    registry = read("presentation-registry")
    case_path = frame.get("case_path", [])
    before, after, explanation = render_template(
        registry["templates"][unit["template"]], bindings, has_case=bool(case_path)
    )
    if case_path:
        case = decode_value(frame["bindings"]).get("case")
        if case and isinstance(case.get("condition"), sp.Basic):
            explanation = render_case_prefix(registry, case["condition"]) + explanation
    return make_fragment(
        state, unit_id=unit["id"], method_ref=frame["method"] + "#" + step["id"],
        template=unit["template"], before=before, after=after, source_refs=source_refs,
        used_basis=used_basis, explanation=explanation, case_path=case_path, premise_refs=premise_refs,
    )


def append_boundary(state, evidence, *, feasible_set=None):
    """Add a separate fragment only after the caller's independent boundary checks."""
    updated = deepcopy(state)
    checks = evidence.get(
        "points", evidence.get("checks", evidence.get("boundaries", []))
    )
    if evidence.get("status") not in ("verified", "passed", "ok"):
        raise ValueError("presentation.boundary_unverified")
    operation = {
        "capability": "endpoint_check",
        "public_ref": None,
        "outputs": deepcopy(evidence),
        "operations": ["endpoint_check"],
        "used_basis": ["function-range-extrema#attainability"],
        "postconditions": [{"kind": "independent_boundary", "passed": True}],
    }
    records = updated.setdefault(
        "finalization", deepcopy(updated["trajectory"]["finalization"])
    )
    index = len(records)
    records.append(operation)
    updated["trajectory"]["finalization"] = deepcopy(records)
    _, _, description = render_template(
        read("presentation-registry")["templates"]["boundary"],
        {"before": [], "after": [], "checks": checks},
    )
    fragment = make_fragment(
        updated,
        unit_id="boundary",
        method_ref=updated["method"]
        + "#"
        + read("presentation-registry")["boundary_steps"][updated["method"]],
        template="boundary",
        after=([feasible_set] if feasible_set is not None else []),
        source_refs=[f"/finalization/{index}"],
        used_basis=operation["used_basis"],
        explanation=description,
    )
    updated["fragments"].append(fragment)
    updated["trajectory"]["math_steps"].append(
        {
            "step_id": fragment["step_id"],
            "math_step_sha256": fragment["math_step_sha256"],
            "source_refs": fragment["source_refs"],
            "file": f"math-steps/{updated['route_id']}/{fragment['step_id']}.json",
        }
    )
    return updated


def _goal_math(value, *, set_value=False):
    """Decode an already certified value; do not solve for its bound here."""
    if not isinstance(value, dict) or "exact" not in value:
        raise ValueError("presentation.goal_exact_value_required")
    decoded = decode_value(value["exact"])
    if not isinstance(decoded, sp.Set if set_value else sp.Expr):
        raise TypeError("presentation.goal_math_type")
    if value.get("expression") != sp.sstr(decoded) or value.get("latex") != sp.latex(decoded):
        raise ValueError("presentation.goal_display_mismatch")
    return decoded


def append_goal_finalization(state, answer, evidence):
    """Append a checked goal conclusion without recomputing extrema.

    Range closure retains its existing record and adds no card. Extremum closure
    requires the independent boundary card first and uses only the supplied exact
    bound, membership evidence and typed answer.
    """
    updated = deepcopy(state)
    records = updated.setdefault("finalization", deepcopy(updated["trajectory"]["finalization"]))
    kind = answer.get("kind")
    if kind == "find_range":
        if answer.get("status") != "set":
            raise ValueError("presentation.goal_answer_invalid")
        records.append({"capability": "finalize_goal", "answer": deepcopy(answer)})
        updated["trajectory"]["finalization"] = deepcopy(records)
        return updated
    if kind not in ("find_minimum", "find_maximum"):
        raise ValueError("presentation.goal_kind_unsupported")
    status = answer.get("status")
    minimum = kind == "find_minimum"
    direction = "lower" if minimum else "upper"
    unbounded = "unbounded_below" if minimum else "unbounded_above"
    checks = evidence.get("checks") if isinstance(evidence, dict) else None
    if (
        not checks or not all(check.get("passed") is True for check in checks)
        or evidence.get("kind") != "goal_closure" or evidence.get("goal_kind") != kind
        or evidence.get("status") != status or evidence.get("direction") != direction
        or status not in ("attained", "not_attained", unbounded, "empty_feasible_set")
    ):
        raise ValueError("presentation.goal_evidence_unverified")
    fragments = updated["fragments"]
    if (not fragments or fragments[-1]["display_unit"] != "boundary"
            or updated.get("verification", {}).get("status") != "verified"):
        raise ValueError("presentation.goal_independent_boundary_required")
    boundary_sources = {f"/finalization/{index}" for index, record in enumerate(records)
                        if record.get("capability") == "endpoint_check"
                        and record.get("postconditions")
                        and all(check.get("passed") is True for check in record["postconditions"])}
    if not boundary_sources.intersection(fragments[-1]["source_refs"]):
        raise ValueError("presentation.goal_independent_boundary_required")
    feasible = _goal_math(evidence.get("feasible_set"), set_value=True)
    if evidence["feasible_set"]["exact"] != updated.get("feasible_set_exact"):
        raise ValueError("presentation.goal_feasible_set_mismatch")
    if any(record.get("capability") == "finalize_goal" for record in records):
        raise ValueError("presentation.goal_already_finalized")
    after, displayed, bound = [], None, None
    if status == "empty_feasible_set":
        valid = (evidence.get("empty") is True and feasible is sp.S.EmptySet
                 and all(evidence.get(key) is None for key in ("bounded", "bound", "member", "attained"))
                 and "value" not in answer and "bound" not in answer)
    elif status == unbounded:
        bound = _goal_math(evidence.get("bound"))
        valid = (evidence.get("empty") is False and evidence.get("bounded") is False
                 and evidence.get("member") is False and evidence.get("attained") is False
                 and bound is (-sp.oo if minimum else sp.oo)
                 and "value" not in answer and "bound" not in answer)
    else:
        attained = status == "attained"
        displayed = answer.get("value" if attained else "bound")
        bound = _goal_math(displayed)
        valid = (evidence.get("empty") is False and evidence.get("bounded") is True
                 and evidence.get("member") is attained and evidence.get("attained") is attained
                 and displayed == evidence.get("bound") and not bound.free_symbols
                 and bound.is_real is True and bound.is_finite is True)
        after.append(bound)
    if not valid:
        raise ValueError("presentation.goal_answer_evidence_mismatch")
    template = "goal_minimum" if minimum else "goal_maximum"
    _, _, explanation = render_template(read("presentation-registry")["templates"][template],
                                        {"before": [feasible], "after": after, "status": status, "bound": bound})
    used_basis = ["function-range-extrema#attainability"]
    operation = {
        "capability": "finalize_goal", "public_ref": None,
        "answer": deepcopy(answer), "outputs": {"answer": deepcopy(answer), "evidence": deepcopy(evidence)},
        "operations": ["goal_finalization"], "used_basis": used_basis,
        "postconditions": [*deepcopy(checks), {"kind": "goal_answer_evidence_match", "passed": True}],
    }
    index = len(records)
    records.append(operation)
    updated["trajectory"]["finalization"] = deepcopy(records)
    fragment = make_fragment(
        updated, unit_id="goal_finalization",
        method_ref=updated["method"] + "#" + read("presentation-registry")["boundary_steps"][updated["method"]],
        template="goal_minimum" if minimum else "goal_maximum", before=[feasible], after=after,
        source_refs=[f"/finalization/{index}"], used_basis=used_basis, explanation=explanation,
    )
    fragment["before"][0]["exact"] = deepcopy(evidence["feasible_set"]["exact"])
    if displayed is not None:
        fragment["after"][0]["exact"] = deepcopy(displayed["exact"])
    fragment["math_step_sha256"] = math_step_hash(fragment)
    fragments.append(fragment)
    updated["trajectory"]["math_steps"].append({
        "step_id": fragment["step_id"], "math_step_sha256": fragment["math_step_sha256"],
        "source_refs": fragment["source_refs"],
        "file": f"math-steps/{updated['route_id']}/{fragment['step_id']}.json",
    })
    return updated
