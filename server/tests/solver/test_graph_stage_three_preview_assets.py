"""Standalone preview serves the complete module graph, including versioned imports."""

import re
from io import BytesIO
from types import SimpleNamespace
from urllib.parse import urljoin

from shuxueshuo_server.graph_lesson.stage_three import preview


def request_handler(monkeypatch, tmp_path):
    # Exercise the actual handler without opening a port or a solver database.
    monkeypatch.setattr(preview, "open_store", lambda directory: object())
    monkeypatch.setattr(preview, "ThreadingHTTPServer", lambda address, handler: handler)
    handler = preview.make_server(tmp_path)

    def get(path):
        status, headers, body = [], {}, BytesIO()
        request = SimpleNamespace(path=path, wfile=body, send_response=status.append,
                                  send_header=lambda name, value: headers.update({name: value}),
                                  end_headers=lambda: None)
        handler.do_GET(request)
        return status[0], headers, body.getvalue().decode()

    return get


def test_standalone_preview_resolves_all_transitive_module_imports(monkeypatch, tmp_path):
    get = request_handler(monkeypatch, tmp_path)
    pending, seen = ["/"], set()
    while pending:
        path = pending.pop()
        if path in seen:
            continue
        seen.add(path)
        status, headers, source = get(path)
        assert status == 200, path
        if path != "/":
            assert headers["Content-Type"].startswith("text/javascript"), path
        imports = re.findall(r"import\s+[^;]*?\s+from\s+['\"]([^'\"]+)['\"]", source)
        pending.extend(urljoin(path, value) for value in imports)
    assert any(path.startswith("/original-choice.mjs?v=") for path in seen)


def test_preview_asset_mount_does_not_expose_unlisted_files(monkeypatch, tmp_path):
    get = request_handler(monkeypatch, tmp_path)
    for path in ["/walk-state.mjs", "/../run.json", "/original-choice.mjs/../walk-state.mjs"]:
        assert get(path)[0] == 404
