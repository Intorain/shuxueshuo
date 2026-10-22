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
    # KaTeX's parser has a local token-fetch method. Verify the embedded vendor
    # bytes, then inspect our application code for actual network APIs.
    vendor = Path(__file__).parents[3] / "site/assets/practice/vendor/katex-0.18.9/katex.min.js"
    embedded = '<script data-vendor="katex">' + vendor.read_text().replace('</script', '<\\/script') + '</script>'
    assert embedded in html
    application = html.replace(embedded, '')
    assert "fetch(" not in application and "XMLHttpRequest" not in application and "new WebSocket" not in application
    return html


def test_real_selection_report_contains_scoped_evidence_and_local_artifacts(tmp_path):
    from shuxueshuo_server.graph_lesson.stage_three.runner import run_sample

    value = json.loads((RECORDED / "q10/sample-01/stage-one-result.json").read_text())
    source = tmp_path / "stage-two"
    stage_two = run_stage_two(value, source, unsupported_root=source / "unsupported")
    assert stage_two["status"] == "completed"
    output = tmp_path / "stage-three"
    result = run_sample(source / "stage-two-result.json", output, milestone="1a")
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
    result = run_sample(source / "stage-two-result.json", output, milestone="1a")
    assert result["status"] == "completed"
    html = assert_self_contained_report(output / "index.html")
    assert attack not in html
    assert escape(attack) in html


def test_invalid_json_still_has_an_offline_failure_report(tmp_path):
    from shuxueshuo_server.graph_lesson.stage_three.runner import run_sample

    source = tmp_path / "broken.json"
    source.write_text('{"contract":', encoding="utf-8")
    output = tmp_path / "stage-three"
    result = run_sample(source, output, milestone="1a")
    assert result["status"] == "input_error"
    assert not result["input_validation"]["ok"]
    assert result["input_diagnostics"]
    html = assert_self_contained_report(output / "index.html")
    assert "input_error" in html or "输入未通过校验" in html
    assert "stage-three-result.json" in html


@pytest.mark.parametrize("kind,status,field,text", [
    ("find_minimum", "attained", "value", "最小值："),
    ("find_maximum", "attained", "value", "最大值："),
    ("find_minimum", "not_attained", "bound", "最小值不存在；只能趋近"),
    ("find_maximum", "not_attained", "bound", "最大值不存在；只能趋近"),
    ("find_minimum", "unbounded_below", None, "最小值不存在：可行集没有下界。"),
    ("find_maximum", "unbounded_above", None, "最大值不存在：可行集没有上界。"),
    ("find_minimum", "empty_feasible_set", None, "没有满足题设的参数，最小值不存在。"),
    ("find_maximum", "empty_feasible_set", None, "没有满足题设的参数，最大值不存在。"),
])
def test_report_separates_full_feasible_set_from_typed_extremum(kind, status, field, text):
    from shuxueshuo_server.graph_lesson.stage_three.report import _goal_answer

    answer = {"kind": kind, "status": status}
    if field:
        answer[field] = {"expression": "-5/2", "latex": "-\\frac{5}{2}",
                         "exact": {"$math": "Rational", "p": "-5", "q": "2"}}
    html = _goal_answer(answer, {"expression": "Interval(-5/2, oo)", "latex": "[-\\frac{5}{2},+\\infty)"})
    assert "完整可行集：" in html and "[-\\frac{5}{2},+\\infty)" in html
    assert text in html
    assert f'data-answer-status="{status}"' in html
    if field:
        assert '<span class="math">-\\frac{5}{2}</span>' in html


@pytest.mark.parametrize("answer", [
    {"kind": "find_minimum", "status": "unknown", "value": {"latex": "1"}},
    {"kind": "find_minimum", "status": "attained"},
    {"kind": "find_maximum", "status": "not_attained"},
    {"kind": "find_maximum", "status": "unbounded_below"},
])
def test_report_does_not_treat_unknown_or_incomplete_extremum_as_success(answer):
    from shuxueshuo_server.graph_lesson.stage_three.report import _goal_answer

    html = _goal_answer(answer, None)
    assert 'data-answer-status="unknown"' in html
    assert "目标答案尚未确定" in html
    assert "已通过" not in html


def test_report_goal_math_is_escaped_and_range_behavior_is_unchanged():
    from shuxueshuo_server.graph_lesson.stage_three.report import _goal_answer

    attack = '<img src=x onerror="attack()">'
    html = _goal_answer({"kind": "find_minimum", "status": "attained", "value": {"latex": attack}},
                        {"latex": attack})
    assert attack not in html and escape(attack) in html
    assert _goal_answer({"kind": "find_range", "status": "set", "set": {"latex": "[0,1]"}}, None) == ""
