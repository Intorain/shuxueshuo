"""Optional original-exam answer matching, after mathematical verification.

The independent allowance and lease keep choice parsing out of mathematical
budgets and fault-injection hooks. Durable receipts prevent a resumed run from
repeatedly spending the allowance on an unsupported or expensive option.
"""

import logging
from copy import deepcopy

from . import choice_matching
from .choice_source import choice_source
from .handoff import validate_original_choice
from .route_calculations import DurableCalculations, InteractionUnavailable

_LOG = logging.getLogger(__name__)
MATCH_SECONDS = 5.0


def normalize_original_choice(choice, target_ref):
    """Freeze only valid optional evidence; malformed results have one identity."""
    try:
        validate_original_choice(choice, target_ref)
    except ValueError:
        # Neither worker diagnostics nor malformed payload fields may enter the
        # route hash: retries must produce the same optional unavailable value.
        return {"status": "unavailable", "target_ref": target_ref, "reason": "choice.invalid_result"}
    return deepcopy(choice)


def resolve_original_choice(store, candidate, target_ref, route_id, answer, feasible_set_exact):
    """Return optional choice evidence; a failure never changes a verified answer."""
    try:
        source = choice_source(candidate, target_ref)
        if source["status"] == "not_choice":
            return None
        if source["status"] != "recognized":
            return {"status": "unavailable", "target_ref": target_ref,
                    "reason": source.get("reason", "choice.incomplete_options")}
        with DurableCalculations(
            store, target_ref, route_id + "#original-choice",
            limits={"interaction": MATCH_SECONDS}, dispatch=choice_matching.dispatch,
        ) as calculator:
            return calculator.call("match_original_choice", {
                "candidate": candidate, "target_ref": target_ref,
                "answer": answer, "feasible_set_exact": feasible_set_exact,
            }, bucket="interaction")
    except InteractionUnavailable as exc:
        return {"status": "unavailable", "target_ref": target_ref,
                "reason": "choice." + exc.reason}
    except Exception:  # noqa: BLE001 -- optional matching cannot revoke verified mathematics.
        _LOG.exception("Original choice matching failed for %s %s", target_ref, route_id)
        return {"status": "unavailable", "target_ref": target_ref, "reason": "choice.matching_error"}
