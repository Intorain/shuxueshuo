"""Pure JSON entry point for isolated route mathematics.

All symbolic decoding, calculation, rendering and exact-object encoding stay in
the mathematical worker. The parent persists and publishes JSON only.
"""

from . import driver, verification
from .goals import finalize_goal
from .trajectory import decode_value, encode_value


def consistency(feasible, answer, previous):
    for route in previous:
        if route["status"] != "verified":
            continue
        earlier = decode_value(route["feasible_set_exact"])
        try:
            mismatch = verification._set_mismatch(feasible, earlier)
        except verification.VerificationGap:
            return "unknown"
        if mismatch is not None or answer != route["answer"]:
            return "conflict"
    return "consistent"


def dispatch(payload):
    operation = payload["operation"]
    if operation == "initialize":
        return driver.create_state(**payload["arguments"])
    if operation == "advance":
        return driver.advance(payload["state"])
    if operation == "constraints":
        candidate_set = driver.export_values(payload["state"])["feasible_set"]
        feasible, processing = verification.apply_visible_constraints(
            payload["candidate"], payload["target_ref"], payload["context"], candidate_set,
        )
        return {"feasible_set_exact": encode_value(feasible), "processing": processing,
                "feasible_set": verification.math_value(feasible)}
    feasible = decode_value(payload["feasible_set_exact"])
    if operation == "verify":
        return verification.verify(payload["candidate"], payload["target_ref"], payload["context"], feasible)
    if operation == "endpoints":
        evidence = verification.endpoint_check(payload["candidate"], payload["target_ref"], feasible)
        # Boundary rendering calls SymPy too; do not move it back to the parent.
        state = driver.append_endpoint(payload["state"], feasible, evidence)
        return {"state": state, "evidence": evidence}
    if operation == "finish":
        answer = finalize_goal(payload["goal"], feasible)
        return {"answer": answer, "feasible_set": verification.math_value(feasible),
                "consistency": consistency(feasible, answer, payload["previous"])}
    raise ValueError("calculation.unknown_operation:" + operation)
