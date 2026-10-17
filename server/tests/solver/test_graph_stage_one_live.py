"""Nine independent image-only LLM integration cases; every invocation buys fresh calls."""

import os
from pathlib import Path

import pytest

from shuxueshuo_server.graph_lesson.stage_one.extraction import REPO
from shuxueshuo_server.graph_lesson.stage_one.report import render_batch
from shuxueshuo_server.graph_lesson.stage_one.runner import (
    CASES,
    collect_case_batches,
    reserve_live_session,
    run_batch,
)
from shuxueshuo_server.problem_understanding.batch_smoke import live_provider_factory

pytestmark = [pytest.mark.live_llm, pytest.mark.skipif(
    os.getenv("RUN_LLM_INTEGRATION") != "1", reason="set RUN_LLM_INTEGRATION=1 for fresh paid image extraction and review",
)]
SAMPLES = 2


@pytest.fixture(scope="session")
def live_run_directory(testrun_uid):
    configured = os.getenv("GRAPH_STAGE_ONE_RUN_DIR")
    directory = Path(configured) if configured else REPO / "internal/solver-runs/graph-guided-stage-one" / (
        "pytest-" + testrun_uid)
    reserve_live_session(directory, testrun_uid, cases=CASES, samples=SAMPLES)
    yield directory.resolve()
    collect_case_batches(directory)
    render_batch(directory, directory)


@pytest.mark.parametrize("case_id", CASES, ids=lambda case: case.upper())
def test_live_stage_one_case(case_id, live_run_directory):
    # Missing credentials, invalid fixtures, or existing sample dirs fail after explicit opt-in.
    output = live_run_directory / case_id
    try:
        result = run_batch(output, live_provider_factory("deepseek"), cases=(case_id,), samples=SAMPLES, workers=1)
    finally:
        # The session summary must not depend on reaching teardown.
        collect_case_batches(live_run_directory)
    report = render_batch(output, output)
    assert len(result["results"]) == SAMPLES
    assert all(row.get("semantic_calls", 0) >= 2 for row in result["results"]), str(report)
    assert result["passed"], f"{case_id}: inspect {report} and every sample evaluation.json"
