"""Debug artifacts remain readable offline and never turn source text into markup."""

import json
import re
import socket
from html import escape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest

from shuxueshuo_server.graph_lesson.stage_two.runner import run_result as run_stage_two

RECORDED = Path(__file__).parent / "fixtures/graph-guided-stage-one/recorded/live-v2-20261017-02"


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("stage-three report tests must be offline")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)


def assert_self_contained_report(path):
    root = path.parent.resolve()
    html = path.read_text(encoding="utf-8")

    class OfflineReport(HTMLParser):
        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            assert not any(key.lower().startswith("on") for key in attrs), attrs
            assert tag not in {"iframe", "object", "embed", "base"}, tag
            assert not (tag == "meta" and attrs.get("http-equiv", "").lower() == "refresh")
            for attribute in ("src", "href", "poster", "action", "data", "srcset"):
                if attribute not in attrs:
                    continue
                value = attrs[attribute]
                assert value is not None
                if value.startswith("data:image/"):
                    assert tag == "img" and attribute == "src"
                    continue
                target = urlsplit(value)
                assert not target.scheme and not target.netloc, (tag, attribute, value)
                if not target.path:
                    assert target.fragment, value
                    continue
                destination = (root / unquote(target.path)).resolve()
                assert destination.is_relative_to(root), value
                assert destination.is_file(), value

    OfflineReport().feed(html)
    assert not re.search(r"url\(\s*['\"]?(?:https?:|//)", html, re.IGNORECASE)
    assert "fetch(" not in html and "XMLHttpRequest" not in html and "new WebSocket" not in html
    return html


def test_real_selection_report_contains_scoped_evidence_and_local_artifacts(tmp_path):
    from shuxueshuo_server.graph_lesson.stage_three.runner import run_sample

    value = json.loads((RECORDED / "q10/sample-01/stage-one-result.json").read_text())
    source = tmp_path / "stage-two"
    stage_two = run_stage_two(value, source, unsupported_root=source / "unsupported")
    assert stage_two["status"] == "completed"
    output = tmp_path / "stage-three"
    result = run_sample(source / "stage-two-result.json", output)
    assert result["status"] == "completed"
    html = assert_self_contained_report(output / "index.html")
    assert "D3" in html and "D4" in html
    assert "stage-three-result.json" in html
    for goal in result["goals"]:
        assert goal["target_ref"] in html
    assert "source_ref" in html or "source_refs" in html
    assert "capability_gap" in html or "详细步骤暂不支持" in html


def test_accepted_transcription_is_escaped_in_debug_report(tmp_path):
    from shuxueshuo_server.graph_lesson.stage_three.runner import run_sample

    attack = '<script>alert("source")</script><img src=x onerror="alert(1)">'
    value = json.loads((RECORDED / "q01/sample-01/stage-one-result.json").read_text())
    value["candidate"]["original_text"] += "\n" + attack
    source = tmp_path / "stage-two"
    stage_two = run_stage_two(value, source, unsupported_root=source / "unsupported")
    assert stage_two["status"] == "completed"
    output = tmp_path / "stage-three"
    result = run_sample(source / "stage-two-result.json", output)
    assert result["status"] == "completed"
    html = assert_self_contained_report(output / "index.html")
    assert attack not in html
    assert escape(attack) in html


def test_invalid_json_still_has_an_offline_failure_report(tmp_path):
    from shuxueshuo_server.graph_lesson.stage_three.runner import run_sample

    source = tmp_path / "broken.json"
    source.write_text('{"contract":', encoding="utf-8")
    output = tmp_path / "stage-three"
    result = run_sample(source, output)
    assert result["status"] == "input_error"
    assert not result["input_validation"]["ok"]
    assert result["input_diagnostics"]
    html = assert_self_contained_report(output / "index.html")
    assert "input_error" in html or "输入未通过校验" in html
    assert "stage-three-result.json" in html
