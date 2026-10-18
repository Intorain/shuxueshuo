"""Fresh Q01 text selection over reverified image extraction, plus offline replay."""

import os
from pathlib import Path
from uuid import uuid4

import pytest

from shuxueshuo_server.graph_lesson.stage_one.runner import replay_batch
from shuxueshuo_server.graph_lesson.stage_two.contracts import ROOT
from shuxueshuo_server.graph_lesson.stage_two.runner import (
    record_run,
    replay_run,
    run_sample,
)
from shuxueshuo_server.graph_lesson.stage_two.selection import live_provider_factory

pytestmark = [pytest.mark.live_llm, pytest.mark.skipif(
    os.getenv("RUN_LLM_INTEGRATION") != "1",
    reason="set RUN_LLM_INTEGRATION=1 for a fresh paid text selection",
)]


def test_live_q01_selection_and_recorded_replay():
    output = Path(os.getenv("GRAPH_STAGE_TWO_RUN_DIR") or (
        ROOT / "internal/solver-runs/graph-guided-stage-two" / f"pytest-live-{uuid4().hex}"))
    output.mkdir(parents=True, exist_ok=False)
    recorded = Path(__file__).parent / "fixtures/graph-guided-stage-one/recorded/live-v2-20261017-02"
    replay_batch(recorded, output / "stage-one", cases=("q01",))
    source = output / "stage-one/q01/sample-01"
    result = run_sample(source / "stage-one-result.json", output / "selection",
                        source_image=source / "source.png", verify=True, provider=live_provider_factory())
    record_run(output / "selection", output / "recording")
    assert result["status"] == "completed", str(output / "selection/index.html")
    goal, = result["goals"]
    assert goal["supported"] == ["type-amgm-quantified", "type-quantified-quadratic"]
    assert goal["primary"] == "type-quantified-quadratic" and goal["primary_source"] == "llm"
    assert result["llm"]["new_semantic_calls"] == 1
    assert 1 <= result["llm"]["new_network_attempts"] <= 2
    replay = replay_run(output / "recording", output / "replay")
    assert replay["status"] == "completed" and replay["goals"][0]["primary"] == goal["primary"]
    assert replay["llm"]["new_semantic_calls"] == replay["llm"]["new_network_attempts"] == 0
