"""Offline checks for the standard-library real-sidecar acceptance observer."""

import importlib.util
import json
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError

import pytest


@pytest.fixture
def probe():
    path = Path(__file__).resolve().parents[3] / "deploy/ocr/acceptance_probe.py"
    specification = importlib.util.spec_from_file_location("ocr_acceptance_probe", path)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def case():
    return {"id": "page-r090-auto", "image": "/private/pages/abcdef123456/source.png", "auto_orient": True,
            "expected_rotation": 270, "expected_size": [724, 1600], "expected_status": "corrected"}


def response(*, elapsed=2, status="corrected", rotation=270):
    return {"status": 200, "error": None, "elapsed_seconds": elapsed,
            "body": {"ok": True, "width": 724, "height": 1600,
                     "orientation": {"status": status, "rotation_degrees": rotation}}}


def valid_memory():
    return {"vm_rss_bytes": 1024, "vm_hwm_bytes": 2048,
            "memory_current_bytes": 4096, "memory_peak_bytes": 8192,
            "memory_stat": {"anon": 1024}, "memory_events": {"oom": 0, "oom_kill": 0}}


def test_procfs_and_cgroup_parsing_keep_missing_values_null(probe, tmp_path):
    assert probe.memory_snapshot(tmp_path / "missing", tmp_path) == {
        "vm_rss_bytes": None, "vm_hwm_bytes": None, "memory_current_bytes": None,
        "memory_peak_bytes": None, "memory_stat": None, "memory_events": None,
    }
    status = tmp_path / "status"
    status.write_text("Name:\tpython\nVmRSS:\t123 kB\nVmHWM:\t456 kB\n")
    (tmp_path / "memory.current").write_text("2048\n")
    (tmp_path / "memory.peak").write_text("4096\n")
    (tmp_path / "memory.stat").write_text("anon 1024\nfile 256\ninvalid\n")
    (tmp_path / "memory.events").write_text("oom 0\noom_kill 0\n")
    assert probe.memory_snapshot(status, tmp_path) == {
        "vm_rss_bytes": 123 * 1024, "vm_hwm_bytes": 456 * 1024,
        "memory_current_bytes": 2048, "memory_peak_bytes": 4096,
        "memory_stat": {"anon": 1024, "file": 256}, "memory_events": {"oom": 0, "oom_kill": 0},
    }
    assert probe.parse_counter("max") is None
    assert probe.parse_counter("-1") is None
    assert probe.parse_process_status("VmRSS: nope kB\nVmHWM: 9 bytes") == {
        "vm_rss_bytes": None, "vm_hwm_bytes": None,
    }


def test_phase_peak_is_sample_max_not_a_difference_of_cumulative_peaks(probe, tmp_path, monkeypatch):
    values = iter([10, 20, 15, 12, 13])

    def snapshot():
        value = next(values)
        return {"vm_rss_bytes": value, "vm_hwm_bytes": 1000, "memory_current_bytes": value + 2,
                "memory_peak_bytes": 2000, "memory_stat": {"anon": value}, "memory_events": {"oom": 0}}

    sampler = probe.MemorySampler(tmp_path / "memory.jsonl", snapshot=snapshot)
    monkeypatch.setattr(sampler, "run", lambda: None)
    with sampler:
        with sampler.phase("startup"):
            sampler.sample()
        with sampler.phase("observe_first"):
            pass
    startup, inference = sampler.phases
    assert startup["samples"] == 3
    assert startup["sampled_max"]["vm_rss_bytes"] == 20
    assert startup["sampled_max"]["memory_current_bytes"] == 22
    assert startup["initial"]["memory_peak_bytes"] == startup["final"]["memory_peak_bytes"] == 2000
    assert inference["sampled_max"]["memory_current_bytes"] == 15
    records = [json.loads(line) for line in (tmp_path / "memory.jsonl").read_text().splitlines()]
    assert [record["phase"] for record in records] == ["startup"] * 3 + ["observe_first"] * 2


def test_memory_requires_samples_for_every_phase_and_no_sampler_error(probe):
    snapshot = valid_memory()
    phase = {"name": "startup", "samples": 1, "initial": snapshot, "final": snapshot,
             "sampled_max": {metric: snapshot[metric] for metric in probe.MEMORY_GAUGES}}
    assert probe.assess_memory([phase]) == {"passed": True, "failures": []}
    assert probe.assess_memory([phase, {**phase, "name": "observe_first", "samples": 0}])["passed"] is False
    assert probe.assess_memory([phase], "disk full")["passed"] is False
    assert probe.assess_memory([])["passed"] is False


@pytest.mark.parametrize("change,expected", [
    ({}, "passed"),
    ({"elapsed": 121}, "failed"),
    ({"status": "uncertain", "rotation": 0}, "needs_review"),
    ({"rotation": 90}, "failed"),
])
def test_assessment_separates_model_quality_and_client_latency(probe, change, expected):
    result = probe.assess_observation(case(), response(**change))
    assert result["result"] == expected
    assert result["passed"] is (expected == "passed")
    if change.get("elapsed"):
        assert result["inference_pass"] is True
        assert result["latency_budget_pass"] is False
        assert result["failures"] == ["client_latency_budget_exceeded"]
    if change.get("status") == "uncertain":
        assert result["inference_pass"] is False
        assert result["failures"] == ["orientation_uncertain"]
        assert "invalid_response" not in result["failures"]


def test_wait_for_startup_tolerates_connection_refusal_until_ready(probe):
    now = [0]
    replies = iter([
        {"status": None, "body": None, "error": "connection refused"},
        {"status": 503, "body": {"ok": False, "ready": False}, "error": None},
        {"status": 200, "body": {"ok": True, "ready": True}, "error": None},
    ])

    def request(endpoint, *, timeout):
        assert endpoint == "/health" and 0 < timeout <= 5
        return next(replies)

    result = probe.wait_healthy(600, request=request, clock=lambda: now[0], sleeper=lambda value: now.__setitem__(0, now[0] + value))
    assert result["passed"] is True
    assert result["attempts"] == 3
    assert result["elapsed_seconds"] == 0.5


def test_startup_deadline_is_bounded_when_listener_never_appears(probe):
    now = [0]
    result = probe.wait_healthy(
        1, request=lambda *_args, **_kwargs: {"status": None, "body": None, "error": "connection refused"},
        clock=lambda: now[0], sleeper=lambda value: now.__setitem__(0, now[0] + value),
    )
    assert result["passed"] is False
    assert result["elapsed_seconds"] == 1


def test_http_error_body_is_retained_and_proxy_redirects_are_disabled(probe, monkeypatch):
    handlers = []

    def open_request(request, *, timeout):
        assert request.full_url == "http://127.0.0.1:8080/v1/search/observe"
        assert timeout == 900
        assert json.loads(request.data) == {"image": case()["image"], "auto_orient": True}
        raise HTTPError(request.full_url, 503, "unavailable", {}, BytesIO(b'{"ok": false, "error": "ocr.busy"}'))

    def opener(*configured):
        handlers.extend(configured)
        return SimpleNamespace(open=open_request)

    monkeypatch.setattr(probe.urllib.request, "build_opener", opener)
    result = probe.request_json("/v1/search/observe", timeout=900, body={"image": case()["image"], "auto_orient": True})
    assert result["status"] == 503
    assert result["body"] == {"ok": False, "error": "ocr.busy"}
    assert handlers[0].proxies == {}
    assert isinstance(handlers[1], probe.NoRedirect)
    assert handlers[1].redirect_request(None) is None
    with pytest.raises(ValueError, match="local endpoint"):
        probe.request_json("https://example.com", timeout=1)


@pytest.mark.parametrize("change", [
    {"auto_orient": "true"}, {"expected_size": [2652, 1200]}, {"expected_rotation": True},
    {"image": "relative.png"}, {"id": "../escape"},
])
def test_invalid_case_contract_fails_before_http(probe, tmp_path, change):
    path = tmp_path / "cases.json"
    path.write_text(json.dumps([{**case(), **change}]))
    with pytest.raises(ValueError):
        probe.load_cases(path)


@pytest.mark.parametrize("scenario", [
    "passed", "slow", "uncertain", "http_error", "manifest_failed", "startup_failed",
    "memory_all_missing", "memory_partial_missing", "memory_event_missing", "oom", "oom_kill",
])
def test_main_persists_report_and_only_exits_zero_for_complete_acceptance(probe, tmp_path, monkeypatch, capsys, scenario):
    cases = tmp_path / "cases.json"
    cases.write_text(json.dumps([case()]))
    output = tmp_path / "output"
    calls = []
    memory = valid_memory()
    if scenario == "memory_all_missing":
        memory = dict.fromkeys(memory)
    elif scenario == "memory_partial_missing":
        memory["memory_peak_bytes"] = None
    elif scenario == "memory_event_missing":
        del memory["memory_events"]["oom_kill"]
    elif scenario in {"oom", "oom_kill"}:
        memory["memory_events"][scenario] = 1
    monkeypatch.setattr(probe, "memory_snapshot", lambda: memory)

    def request(endpoint, *, timeout, body=None):
        calls.append(endpoint)
        if endpoint == "/health":
            return {"status": 200, "error": None, "elapsed_seconds": 0,
                    "body": {"ok": True, "ready": True}}
        assert timeout == 900
        if endpoint == "/v1/manifests":
            return {"status": 200, "error": None, "elapsed_seconds": 0,
                    "body": {"ok": True, "providers": [] if scenario == "manifest_failed" else [{"id": "real"}]}}
        assert body == {"image": case()["image"], "auto_orient": True}
        if scenario == "http_error":
            return {"status": 500, "error": None, "elapsed_seconds": 0, "body": {"ok": False}}
        return response(elapsed=121 if scenario == "slow" else 2,
                        status="uncertain" if scenario == "uncertain" else "corrected")

    monkeypatch.setattr(probe, "request_json", request)
    if scenario == "startup_failed":
        monkeypatch.setattr(probe, "wait_healthy", lambda *_args, **_kwargs: {"passed": False})
    assert probe.main(["--cases", str(cases), "--output", str(output), "--request-timeout", "900"]) == (0 if scenario == "passed" else 1)
    progress = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert progress[0]["phase"] == "startup"
    assert "body" not in str(progress)
    report = json.loads((output / "report.json").read_text())
    assert report["passed"] is (scenario == "passed")
    assert report["measurement"]["client_latency_budget_seconds"] == 120
    assert report["measurement"]["request_timeout_seconds"] == 900
    assert report["memory"]["phases"][0]["name"] == "startup"
    assert (output / "memory.jsonl").read_text().strip()
    memory_failed = scenario.startswith("memory_") or scenario in {"oom", "oom_kill"}
    assert report["memory"]["passed"] is not memory_failed
    if memory_failed:
        assert report["cases"][0]["passed"] is True
        assert report["memory"]["failures"]
        assert {failure["reason"] for failure in report["memory"]["failures"]} == (
            {"oom_observed"} if scenario in {"oom", "oom_kill"} else {"missing_or_invalid"})
    if scenario == "startup_failed":
        assert calls == []
        assert report["cases"] == []
    else:
        assert calls == ["/health", "/v1/manifests", "/v1/search/observe"]
        assert progress[2]["phase"] == "observe"
        assert progress[2]["case_id"] == case()["id"]
        assert progress[2]["result"] == report["cases"][0]["result"]


def test_probe_refuses_to_overwrite_an_existing_report(probe, tmp_path):
    cases = tmp_path / "cases.json"
    cases.write_text(json.dumps([case()]))
    report = tmp_path / "report.json"
    report.write_text("previous evidence")
    with pytest.raises(SystemExit):
        probe.main(["--cases", str(cases), "--output", str(tmp_path)])
    assert report.read_text() == "previous evidence"
