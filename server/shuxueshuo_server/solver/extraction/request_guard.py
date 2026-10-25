"""Optional request-bound admission checks for outbound model transport."""

from contextlib import contextmanager
from contextvars import ContextVar

_guard = ContextVar('model_request_guard', default=None)


class ModelRequestScopeRequired(RuntimeError):
    pass


@contextmanager
def model_request_scope(guard):
    token = _guard.set(guard)
    try:
        yield
    finally:
        _guard.reset(token)


def require_model_request_scope():
    if _guard.get() is None:
        raise ModelRequestScopeRequired('model.request_scope_required')


def check_model_request():
    guard = _guard.get()
    if guard is not None:
        guard()
