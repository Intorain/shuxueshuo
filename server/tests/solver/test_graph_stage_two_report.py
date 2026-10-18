"""Reports expose failed inputs and escape source text without executing it."""

import json

from shuxueshuo_server.graph_lesson.stage_two.report import render_result


def test_failed_input_report_is_offline_and_escapes_transcription(tmp_path):
    attack = '<script>alert("source")</script>'
    (tmp_path / "input.json").write_text(json.dumps({"candidate": {"original_text": attack}}))
    (tmp_path / "stage-two-result.json").write_text(json.dumps({
        "status": "input_error", "goals": [], "input_validation": {"ok": False, "diagnostics": ["bad input"]},
    }))
    page = render_result(tmp_path).read_text()
    assert attack not in page and "&lt;script&gt;" in page
    assert "bad input" in page and "输入未通过校验" in page
    assert "https://" not in page and "fetch(" not in page
