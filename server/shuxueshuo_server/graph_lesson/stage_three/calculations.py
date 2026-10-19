"""Pure JSON entry point for isolated route mathematics.

All symbolic decoding, calculation, rendering and exact-object encoding stay in
the mathematical worker. The parent persists and publishes JSON only.
"""

from functools import lru_cache

from . import driver, execution_contracts, verification
from .goals import finalize_goal
from .trajectory import decode_value, encode_value


@lru_cache(maxsize=1)
def _session_contracts(revision_key):
    """Validate once in this worker; a new process or revision loads afresh.

    Only immutable configuration is shared. Capability and judgment dispatch
    stay live; neither this cache nor its key is persisted in checkpoints.
    """
    expected = dict(revision_key)
    read_revisions = execution_contracts.revisions
    current = read_revisions()
    if expected.keys() != current.keys():
        # Recorded runs freeze the entire pipeline under relative file paths;
        # direct driver sessions use the named execution-only revision map.
        # Preserve either complete identity, rather than reducing to a subset.
        from .runner import fingerprint

        read_revisions = fingerprint
        current = read_revisions()
    if current != expected:
        raise ValueError("execution.contract_revisions_changed")
    contracts = execution_contracts.load_contracts()
    # Validation reads several files. Refuse a snapshot changed during those
    # reads instead of publishing it under the checkpoint's earlier revision.
    if read_revisions() != expected:
        raise ValueError("execution.contract_revisions_changed")
    return contracts


def _contracts(revisions):
    return _session_contracts(tuple(sorted(revisions.items())))


def consistency(feasible, answer, previous):
    for route in previous:
        if route["status"] != "verified":
            continue
        earlier = decode_value(route["feasible_set_exact"])
        try:
            mismatch = verification._set_mismatch(feasible, earlier)
        except verification.VerificationGap:
            return "unknown"
        earlier_answer = route["answer"]
        if mismatch is not None:
            return "conflict"
        if answer.get("kind") == "find_range" and answer.get("status") == "set":
            # The proved feasible sets ARE the range answers. Their expression
            # and LaTeX strings may differ, e.g. Reals vs Interval(-oo, oo).
            if {key: value for key, value in answer.items() if key != "set"} != {
                key: value for key, value in earlier_answer.items() if key != "set"
            }:
                return "conflict"
        elif answer != earlier_answer:
            return "conflict"
    return "consistent"


def dispatch(payload):
    operation = payload["operation"]
    if operation == "initialize":
        arguments = payload["arguments"]
        revisions = arguments.get("revisions") or execution_contracts.revisions()
        return driver.create_state(contracts=_contracts(revisions), **arguments)
    if operation == "advance":
        return driver.advance(payload["state"], contracts=_contracts(payload["state"]["revisions"]))
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
