"""Controlled-time WebSocket polling over real authenticated PostgreSQL runs."""

import asyncio
import secrets
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from shuxueshuo_server.auth.api import cookie_name
from shuxueshuo_server.graph_lesson.stage_three.checkpoint import identity_from_seed
from shuxueshuo_server.graph_lesson.stage_three.events import EventStore
from shuxueshuo_server.graph_lesson.stage_three.storage import storage_context
from shuxueshuo_server.problem_understanding.workflow_ledger import save
from shuxueshuo_server.search import dev_api
from tests.search.test_private_api import login
from tests.search.test_private_api import private_app as private_app_fixture
from tests.search.test_repository import repository as repository_fixture
from tests.search.test_repository import submission


@pytest.fixture
def repository(tmp_path):
    yield from repository_fixture.__wrapped__(tmp_path)


@pytest.fixture
def stream(repository, monkeypatch):
    app, auth = private_app_fixture.__wrapped__(repository, monkeypatch)
    with TestClient(app, base_url=auth.config.origin) as client:
        user, token = login(client, auth)
        row, _ = submission(repository, user)
        output = row["path"] / "stage-two-1/stage-three"
        seed = {"run_id": secrets.token_hex(16), "lesson_version": "polling-fixture",
                "stage_one": {"sha256": "a" * 64}, "stage_two": {"sha256": "b" * 64}}
        identity = {**identity_from_seed(seed), "revisions": {"fixture": "c" * 64}}
        save(output / "run.json", seed)
        save(output / "frozen.json", {"implementation": identity["revisions"]})
        with storage_context(repository.db, row["id"], clock=repository.clock):
            store = EventStore(output, identity, create=True)
        endpoint = next(route.endpoint for route in app.routes if route.path.endswith("/{run_id}/ws"))
        yield SimpleNamespace(app=app, auth=auth, token=token, row=row, store=store,
                              output=output, endpoint=endpoint)


class ControlledSocket:
    def __init__(self, stream, *, end=30.0, ping_interval=None, action=None):
        self.app = stream.app
        self.state = SimpleNamespace()
        self.cookies = {cookie_name(stream.auth.config): stream.token}
        self.headers = {"origin": stream.auth.config.origin}
        self.now = 0.0
        self.end = end
        self.ping_interval = ping_interval
        self.action = action
        self.messages = []
        self.received = 0
        self.accepted = False
        self.closed = None

    async def accept(self):
        self.accepted = True

    async def send_json(self, payload):
        self.messages.append((self.now, payload))

    async def close(self, code):
        self.closed = code

    async def receive_text(self):
        self.received += 1
        return "ping"

    async def wait_for(self, receive, *, timeout):
        delay = min(timeout, self.ping_interval) if self.ping_interval else timeout
        self.now = min(self.end, self.now + delay)
        if self.now >= self.end:
            receive.close()
            raise WebSocketDisconnect(1000)
        if self.action:
            self.action(self.now)
        if self.ping_interval and delay < timeout:
            return await receive
        receive.close()
        raise TimeoutError


def run_stream(stream, repository, monkeypatch, socket):
    statements = []

    def record(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append((socket.now, statement))

    sa.event.listen(repository.db, "before_cursor_execute", record)
    monkeypatch.setattr(dev_api, "monotonic", lambda: socket.now)
    monkeypatch.setattr(dev_api, "asyncio", SimpleNamespace(
        get_running_loop=lambda: SimpleNamespace(time=lambda: socket.now), wait_for=socket.wait_for,
    ))
    try:
        asyncio.run(stream.endpoint(socket, stream.row["id"], stream.store.identity["run_id"]))
    finally:
        sa.event.remove(repository.db, "before_cursor_execute", record)
    assert socket.accepted
    return statements


def event_reads(statements):
    return [instant for instant, statement in statements if "SELECT value FROM lesson_events" in statement]


@pytest.mark.parametrize("completed", [False, True])
@pytest.mark.parametrize("ping_interval", [None, 0.01])
def test_idle_and_finished_streams_bound_real_database_reads(stream, repository, monkeypatch, completed, ping_interval):
    if completed:
        save(stream.output / "stage-three-result.json", {"status": "completed", "goals": []})
    socket = ControlledSocket(stream, ping_interval=ping_interval)
    statements = run_stream(stream, repository, monkeypatch, socket)
    reads = event_reads(statements)
    assert reads == pytest.approx([0, 0.3, 0.9, 2.1, 3, 6, 9, 12, 15, 18, 21, 24, 27])
    assert len(statements) < 400
    assert len(socket.messages) == 1
    assert socket.messages[0][1]["events"] == []
    assert socket.closed is None
    if ping_interval:
        assert socket.received > 1000


def test_new_events_reset_fast_polling_then_return_to_idle(stream, repository, monkeypatch):
    published = []

    def publish(now):
        if len(published) < 3 and now >= 6:
            stream.store.commit_events([{
                "type": "lesson.goal_status", "target_ref": "/root/goals/0", "route_id": None,
                "payload": {"status": "running"},
            }], commit_id=f"progress-{len(published)}")
            published.append(now)

    socket = ControlledSocket(stream, end=20, action=publish)
    reads = event_reads(run_stream(stream, repository, monkeypatch, socket))
    assert published == pytest.approx([6, 6.15, 6.3])
    delivered = [(instant, message["last_seq"]) for instant, message in socket.messages if message["events"]]
    assert delivered == [(published[index], index + 1) for index in range(3)]
    assert reads[-4:] == pytest.approx([9.3, 12.3, 15.3, 18.3])
    assert len(reads) < 20


def test_idle_backoff_keeps_revocation_within_authorization_interval(stream, repository, monkeypatch):
    revoked = []

    def revoke(now):
        if now >= 6.1 and not revoked:
            stream.auth.logout(stream.token)
            revoked.append(now)

    socket = ControlledSocket(stream, ping_interval=0.1, action=revoke)
    reads = event_reads(run_stream(stream, repository, monkeypatch, socket))
    assert revoked
    assert socket.closed == 4401
    instant, message = socket.messages[-1]
    assert message == {"error": "search.login_required"}
    assert 0 <= instant - revoked[0] <= dev_api.WS_AUTH_INTERVAL
    assert reads[-1] == pytest.approx(9)
