"""Reports must remain useful for the failure modes that need debugging most."""

import json

import pytest

from shuxueshuo_server.graph_lesson.stage_one import runner
from shuxueshuo_server.graph_lesson.stage_one.report import render_batch


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def sample_batch(tmp_path, *, passed=False, elapsed=None):
    batch = tmp_path / "batch"
    sample = batch / "q06/sample-01"
    sample.mkdir(parents=True)
    row = {"case_id": "q06", "sample_id": "sample-01", "sample_dir": "q06/sample-01", "status": "failed", "passed": passed}
    if elapsed is not None:
        row["elapsed_seconds"] = elapsed
    save(batch / "batch-summary.json", {"results": [row]})
    return batch, sample


def test_invalid_candidate_and_failed_call_still_render_verbatim(tmp_path):
    batch, sample = sample_batch(tmp_path)
    (sample / "candidate.json").write_text('{"original_text":"截断 </script><script>alert(1)</script>')
    call = sample / "workflow/calls/01-extract"
    save(call / "request.json", {"model": "test", "redacted": True})
    (call / "response.json").write_text('upstream timeout <unsafe>')
    save(sample / "workflow/ledger.json", {"calls": [{"number": 1, "stage": "extract", "status": "failed", "directory": "calls/01-extract", "error_code": "provider.timeout"}]})
    output = tmp_path / "report"
    index = render_batch(batch, output)
    html = (output / "sample-001.html").read_text()
    assert index.is_file()
    assert "无效 JSON" in html and "截断" in html
    assert "provider.timeout" in html and "upstream timeout &lt;unsafe&gt;" in html
    assert "</script><script>alert(1)</script>" not in html
    assert "未产出题文" in html
    assert not (sample / "features.json").exists()  # No invented success files.


def test_unicode_transcription_root_and_features_render_offline(tmp_path):
    batch, sample = sample_batch(tmp_path, passed=True, elapsed=4)
    original = '🧮 若 $x<0$，求 $a$。'
    save(sample / "candidate.json", {"original_text": original, "root": {"facts": ["x<0"], "goals": [{"kind": "find_range", "symbol": "a"}]}})
    save(sample / "features.json", {"features": [{"feature_id": "domain", "status": "known", "value": {"expression": "(-∞,0)"}, "source_refs": ["/root/facts/0"]}]})
    render_batch(batch, tmp_path / "report")
    html = (tmp_path / "report/sample-001.html").read_text()
    assert "/root/facts/0" in html and "x&lt;0" in html
    assert "(-∞,0)" in html and "🧮" in html
    assert "data-source-paths" not in html
    assert 'src="http' not in html and "fetch(" not in html
    assert (tmp_path / "report/_assets/katex/katex.min.js").exists()


def test_missing_ledger_discovers_partial_call_materials_and_preserves_inputs(tmp_path):
    batch, sample = sample_batch(tmp_path)
    request = sample / "workflow/calls/01-extract/request.json"
    save(request, {"model": "test", "request_status": "connection_failed"})
    before = {str(path.relative_to(batch)): path.read_bytes() for path in batch.rglob("*") if path.is_file()}
    render_batch(batch, tmp_path / "report")
    after = {str(path.relative_to(batch)): path.read_bytes() for path in batch.rglob("*") if path.is_file()}
    html = (tmp_path / "report/sample-001.html").read_text()
    assert "账本未登记的调用材料" in html and "connection_failed" in html
    assert before == after


def test_summary_timing_ignores_missing_and_path_traversal(tmp_path):
    batch, _ = sample_batch(tmp_path, elapsed=2)
    rows = json.loads((batch / "batch-summary.json").read_text())["results"]
    rows += [
        {"case_id": "q07", "sample_id": "sample-01", "sample_dir": "q07/sample-01", "status": "passed", "passed": True, "elapsed_seconds": 8},
        {"case_id": "q08", "sample_id": "sample-01", "sample_dir": "../private", "status": "missing", "passed": False},
    ]
    save(batch / "batch-summary.json", {"results": rows})
    save(tmp_path / "private/candidate.json", {"original_text": "OUTSIDE_BATCH_MUST_NOT_BE_READ"})
    output = tmp_path / "report"
    index = render_batch(batch, output)
    html = index.read_text()
    assert "5.000s" in html and "8.000s" in html
    assert "2 / 3" in html
    assert "OUTSIDE_BATCH_MUST_NOT_BE_READ" not in (output / "sample-003.html").read_text()


def test_corrupt_summary_falls_back_to_saved_samples(tmp_path):
    batch, sample = sample_batch(tmp_path)
    (batch / "batch-summary.json").write_text('{"results":')
    save(sample / "validation.json", {"ok": False, "diagnostics": ["truncated_response"]})
    output = tmp_path / "report"
    assert render_batch(batch, output).exists()
    assert "未完成：样本中断" in (output / "index.html").read_text()
    assert "truncated_response" in (output / "sample-001.html").read_text()


def test_fixture_gold_and_offline_history_are_visible(tmp_path):
    batch, sample = sample_batch(tmp_path, passed=True)
    save(sample / "fixture/notation.gold.json", {"original_text": "独立金标题文"})
    save(sample / "fixture/source-manifest.json", {"source_kind": "synthetic-rendered"})
    summary = json.loads((batch / "batch-summary.json").read_text())
    summary["mode"] = "offline_replay"
    summary["results"][0].update(mode="offline_replay", historical_live={"passed": False, "status": "historical_failure"})
    save(batch / "batch-summary.json", summary)
    output = tmp_path / "report"
    render_batch(batch, output)
    sample_html = (output / "sample-001.html").read_text()
    assert "独立金标题文" in sample_html
    assert "历史 live 结论（保持原样）" in sample_html and "historical_failure" in sample_html
    assert "新网络调用 0 次" in sample_html
    assert "当前离线重评" in (output / "index.html").read_text()


def test_partially_summarized_batch_still_shows_and_records_interrupted_samples(tmp_path):
    batch, finished = sample_batch(tmp_path)
    save(finished / "failure.json", {"error_type": "PreflightError"})
    summary = json.loads((batch / "batch-summary.json").read_text())
    summary["results"][0]["sample_id"] = 1
    save(batch / "batch-summary.json", {**summary, "requested_cases": ["q06", "q07"], "samples_per_case": 1})
    interrupted = batch / "q07/sample-01"
    save(interrupted / "workflow/calls/01-extract/request.json", {"model": "test"})
    save(interrupted / "workflow/calls/01-extract/response.json", {"text": "INTERRUPTED_RESPONSE"})
    save(interrupted / "workflow/ledger.json", {"calls": [{"number": 1, "stage": "extract", "status": "reserved", "directory": "calls/01-extract"}]})
    output = tmp_path / "report"
    index = render_batch(batch, output).read_text()
    assert "0 / 2" in index and "未完成：样本中断" in index
    assert "INTERRUPTED_RESPONSE" in (output / "sample-002.html").read_text()

    recorded = runner.record_batch(batch, tmp_path / "recorded")
    summary = json.loads((recorded / "batch-summary.json").read_text())
    assert summary["unrecorded_samples"] == ["q07/sample-01"]
    assert len(summary["results"]) == 1
    assert "INTERRUPTED_RESPONSE" in (recorded / "q07/sample-01/workflow/calls/01-extract/response.json").read_text()
    render_batch(recorded, tmp_path / "recorded-report")
    assert "未完成：样本中断" in (tmp_path / "recorded-report/index.html").read_text()

    replayed = runner.replay_batch(recorded, tmp_path / "replayed", cases=("q06", "q07"))
    assert [(row["case_id"], row.get("incomplete", False)) for row in replayed["results"]] == [
        ("q06", False), ("q07", True)
    ]
    assert not replayed["passed"] and not replayed["formal_passed"]
    assert "INTERRUPTED_RESPONSE" in (tmp_path / "replayed/q07/sample-01/workflow/calls/01-extract/response.json").read_text()


@pytest.mark.parametrize("corrupt_summary", [False, True])
def test_interrupted_pytest_session_discovers_nested_samples(tmp_path, corrupt_summary):
    batch = tmp_path / "interrupted-session"
    sample = batch / "q01/q01/sample-01"
    save(sample / "summary.json", {"case_id": "q01", "sample_id": 1, "passed": False, "status": "runner.failed"})
    save(sample / "failure.json", {"error_type": "SAVED_FAILURE_MUST_REMAIN_VISIBLE"})
    if corrupt_summary:
        (batch / "batch-summary.json").write_text('{"results":')
    output = tmp_path / "report"
    index = render_batch(batch, output)
    assert "0 / 1" in index.read_text()
    assert "runner.failed" in index.read_text()
    html = (output / "sample-001.html").read_text()
    assert "SAVED_FAILURE_MUST_REMAIN_VISIBLE" in html
