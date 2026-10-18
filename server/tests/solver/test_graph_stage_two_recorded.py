"""The whole retained stage-one batch is reverified and classified without networking."""

import json
import socket
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote

from shuxueshuo_server.graph_lesson.stage_two.runner import (
    replay_run,
    run_recorded_batch,
)


def test_all_22_recordings_produce_scoped_decisions_without_network(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("recorded classification must be offline")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    source = Path(__file__).parent / "fixtures/graph-guided-stage-one/recorded/live-v2-20261017-02"
    output = tmp_path / "batch"
    batch = run_recorded_batch(source, output, provider=forbidden)
    assert batch["completed"] and len(batch["results"]) == 22
    assert batch["llm"]["new_network_attempts"] == batch["llm"]["new_semantic_calls"] == 0
    supported_count = 0
    for row in batch["results"]:
        sample = output / row["sample_dir"]
        result = json.loads((sample / "stage-two-result.json").read_text())
        value = json.loads((sample / "input.json").read_text())
        for goal in result["goals"]:
            is_plain = row["case_id"] == "q11" and goal["target_ref"] == "/root/children/0/goals/0"
            if is_plain:
                assert goal["status"] == "unsupported"
                continue
            supported_count += 1
            assert goal["status"] == "resolved" and goal["primary_source"] == "program"
            assert goal["primary"] == "type-quantified-quadratic"
            relation = [f for f in goal["d1"]["fragments"] if f["fragment_kind"] == "relation"]
            assert relation, (row["sample_dir"], goal["target_ref"], goal["d1"])
            for fragment in goal["d1"]["fragments"]:
                assert fragment["text"] == value["candidate"]["original_text"][fragment["start"]:fragment["end"]]
            assert goal["d2"]
        assert (sample / "index.html").is_file()
    assert supported_count == 24
    assert (output / "index.html").is_file()


def test_real_q01_text_selection_replays_without_network(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("recorded text selection must be offline")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    source = Path(__file__).parent / "fixtures/graph-guided-stage-two/recorded/q01-20261018-02"
    result = replay_run(source, tmp_path / "replay")
    assert result["status"] == "completed"
    assert result["replay_comparison"]["ok"]
    goal, = result["goals"]
    assert goal["primary"] == "type-quantified-quadratic" and goal["primary_source"] == "llm"
    assert set(goal["supported"]) == {"type-quantified-quadratic", "type-amgm-quantified"}
    assert result["llm"]["new_semantic_calls"] == result["llm"]["new_network_attempts"] == 0
    assert result["historical"]["llm"]["new_semantic_calls"] == 1
    assert 1 <= result["historical"]["llm"]["new_network_attempts"] <= 2
    assert goal["llm"]["selection"]["check_ids"]
    assert {o["type_id"]: o["role"] for o in goal["d2"]["options"]} == {
        "type-quantified-quadratic": "primary", "type-amgm-quantified": "alternative",
        "type-parameter-quadratic-solve": "conflict",
    }
    assert (tmp_path / "replay/source.png").is_file()
    html = (tmp_path / "replay/index.html").read_text()
    for required in ("全部题型检查", "D1 · 原文片段", "D2 · 题型选项", "request.json", "response.json",
                     "历史录制结果与调用计数", "<mark>"):
        assert required in html

    class OfflineReport(HTMLParser):
        def handle_starttag(self, tag, attrs):
            assert tag != "script"
            attrs = dict(attrs)
            assert not any(key.startswith("on") for key in attrs)
            if tag == "a":
                target = (tmp_path / "replay" / unquote(attrs["href"])).resolve()
                assert target.is_relative_to((tmp_path / "replay").resolve()) and target.is_file()
            if tag == "img":
                assert attrs["src"].startswith("data:image/png;base64,")

    OfflineReport().feed(html)


def test_pre_extrema_selection_recording_reports_contract_drift(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("historical replay must remain offline")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    source = Path(__file__).parent / "fixtures/graph-guided-stage-two/recorded/q01-20261018-01"
    result = replay_run(source, tmp_path / "historical")
    assert result["status"] == "failed"
    assert not result["replay_comparison"]["ok"]
    goal, = result["goals"]
    assert goal["status"] == "selection_failed"
    assert any(d["code"] == "selection.recording_request_mismatch" for d in goal["diagnostics"])
    assert result["llm"]["new_network_attempts"] == 0
