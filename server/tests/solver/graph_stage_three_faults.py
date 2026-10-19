"""Importable JSON worker dispatchers for actual process-boundary regressions."""

import socket
import time
from contextlib import ExitStack, contextmanager
from unittest.mock import patch


def _forbidden(*args, **kwargs):
    raise AssertionError("offline stage-three worker attempted network or LLM initialization")


@contextmanager
def _offline_worker():
    with ExitStack() as stack:
        for owner, name in (
            (socket, "create_connection"),
            (socket.socket, "connect"),
            (socket.socket, "connect_ex"),
        ):
            stack.enter_context(patch.object(owner, name, _forbidden))
        from shuxueshuo_server.graph_lesson.stage_two import selection
        from shuxueshuo_server.problem_understanding import batch_smoke
        from shuxueshuo_server.solver.extraction import multimodal_provider

        for owner, name in (
            (batch_smoke, "live_provider_factory"),
            (selection, "live_provider_factory"),
            (multimodal_provider, "_default_client_factory"),
        ):
            stack.enter_context(patch.object(owner, name, _forbidden))
        yield


def offline_dispatch(payload):
    with _offline_worker():
        from shuxueshuo_server.graph_lesson.stage_three.calculations import dispatch

        return dispatch(payload)


def _advance_failure(payload, failure):
    with _offline_worker():
        from shuxueshuo_server.graph_lesson.stage_three import (
            calculations,
            capabilities,
        )

        if payload["operation"] != "advance":
            return calculations.dispatch(payload)
        original = capabilities.execute

        def broken(capability, inputs):
            if capability == "quadratic_sign_condition" and inputs["mode"] == "delta":
                if failure == "capability_gap":
                    raise capabilities.CapabilityGap("injected_gap")
                if failure == "execution_error":
                    raise KeyError("injected bug")
                result = original(capability, inputs)
                result["checks"] = [{"kind": "injected_failure", "passed": False}]
                return result
            return original(capability, inputs)

        with patch.object(capabilities, "execute", broken):
            return calculations.dispatch(payload)


def failed_local_check(payload):
    return _advance_failure(payload, "math_failed")


def advance_gap(payload):
    return _advance_failure(payload, "capability_gap")


def advance_error(payload):
    return _advance_failure(payload, "execution_error")


def _later_consistency(payload, decision):
    result = offline_dispatch(payload)
    if payload["operation"] == "finish" and payload["previous"]:
        result["consistency"] = decision
    return result


def later_conflict(payload):
    return _later_consistency(payload, "conflict")


def later_unknown(payload):
    return _later_consistency(payload, "unknown")


def _slow_operation(payload, operation):
    with _offline_worker():
        from shuxueshuo_server.graph_lesson.stage_three.calculations import dispatch

        if payload["operation"] == operation:
            time.sleep(60)
            raise AssertionError("a timed-out worker must never reach this statement")
        return dispatch(payload)


def slow_constraints(payload):
    return _slow_operation(payload, "constraints")


def slow_verify(payload):
    return _slow_operation(payload, "verify")


def slow_endpoints(payload):
    return _slow_operation(payload, "endpoints")


def slow_finish(payload):
    return _slow_operation(payload, "finish")


def _constraints_failure(payload, failure):
    with _offline_worker():
        from shuxueshuo_server.graph_lesson.stage_three import (
            calculations,
            verification,
        )

        if payload["operation"] == "constraints":
            if failure == "capability_gap":
                raise verification.VerificationGap("verification_incomplete:injected_sympy_failure")
            if failure == "math_failed":
                raise verification.ContextMismatch("injected_context_mismatch")
            raise KeyError("local_programming_bug")
        return calculations.dispatch(payload)


def constraints_gap(payload):
    return _constraints_failure(payload, "capability_gap")


def constraints_mismatch(payload):
    return _constraints_failure(payload, "math_failed")


def constraints_error(payload):
    return _constraints_failure(payload, "execution_error")
