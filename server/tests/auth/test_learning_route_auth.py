"""Every future graph endpoint must explicitly retain the student boundary."""

import pytest
from fastapi.routing import APIRoute

from shuxueshuo_server.auth.api import require_user
from shuxueshuo_server.learning.api import learning_user
from shuxueshuo_server.learning.graph_api import router


def dependency_calls(dependant):
    return {dependant.call} | set().union(
        *(dependency_calls(child) for child in dependant.dependencies)
    )


@pytest.mark.parametrize('route', [r for r in router.routes if isinstance(r, APIRoute)],
                         ids=lambda route: f'{min(route.methods)} {route.path}')
def test_only_content_metadata_is_public(route):
    calls = dependency_calls(route.dependant)
    if route.path == '/api/learning/content' and route.methods == {'GET'}:
        assert require_user not in calls
    else:
        # Both login and the account-switch/origin checks are required.
        assert {require_user, learning_user} <= calls
