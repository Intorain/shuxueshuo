"""Exercise the real loopback port probe without launching PostgreSQL."""

import socket
from types import SimpleNamespace

import pytest

from shuxueshuo_server.product.admin import native
from shuxueshuo_server.product.errors import Conflict


def prepare_start(monkeypatch, tmp_path, port):
    calls = []
    monkeypatch.setattr(native, "init", lambda settings: None)
    monkeypatch.setattr(native, "status", lambda settings: False)
    monkeypatch.setattr(native, "run", lambda *args: calls.append(args))
    return SimpleNamespace(port=port, root=tmp_path, pgdata=tmp_path / "postgres"), calls


def test_restart_allows_closed_connections_in_time_wait(monkeypatch, tmp_path):
    with socket.socket() as listener, socket.socket() as client:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        listener.listen()
        client.settimeout(2)
        client.connect(("127.0.0.1", port))
        connection, _ = listener.accept()
        with connection:
            connection.settimeout(2)
            # The server actively closes, leaving TIME_WAIT on its own port.
            connection.shutdown(socket.SHUT_WR)
            assert client.recv(1) == b""
            client.shutdown(socket.SHUT_WR)
            assert connection.recv(1) == b""

    settings, calls = prepare_start(monkeypatch, tmp_path, port)
    native.start(settings)
    assert len(calls) == 1
    assert calls[0][-1] == "start"


def test_restart_still_rejects_another_listening_server(monkeypatch, tmp_path):
    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        settings, calls = prepare_start(monkeypatch, tmp_path, listener.getsockname()[1])
        with pytest.raises(Conflict, match="postgres.port_in_use"):
            native.start(settings)
        assert not calls
