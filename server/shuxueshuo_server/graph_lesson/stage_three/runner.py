"""Admit stage-two artifacts and persist independently inspectable method decisions.

Milestone 1a evaluates methods only. It never claims a route was executed, emits
solver events, or invokes a provider. Later milestones add execution at the
explicit route-plan boundary.
"""

import shutil
import traceback
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from shuxueshuo_server.problem_understanding.identity import revision
from shuxueshuo_server.problem_understanding.workflow_ledger import save

from ..stage_two import runner as stage_two_runner
from ..stage_two.contracts import ROOT, targets
from .context import build_context
from .contracts import (
    INPUT_MANIFEST_CONTRACT,
    RESULT_CONTRACT,
    aggregate_status,
    load_input,
    validate_result,
)
from .selection import evaluate_goal

MILESTONE = "1a"


def fingerprint():
    paths = [
        *Path(__file__).parent.glob("*.py"),
        *Path(__file__).parents[2].joinpath("problem_understanding").glob("notation_*.py"),
        *Path(__file__).parent.parent.joinpath("stage_one").glob("*.py"),
        *Path(__file__).parent.parent.joinpath("stage_two").glob("*.py"),
        *(ROOT / "site/data/knowledge-next/selection").glob("*.json"),
        *(ROOT / "site/data/knowledge-next/nodes").glob("*.json"),
        *(ROOT / "internal/schemas").glob("graph-stage-three-*.json"),
        *(ROOT / "internal/schemas").glob("graph-method-*.json"),
        ROOT / "internal/schemas/graph-math-step-v1.schema.json",
        ROOT / "site/data/graph-walk/quadratic-always-q01.source.json",
    ]
    return {str(path.relative_to(ROOT)): sha256(path.read_bytes()).hexdigest()
            for path in sorted(set(paths)) if path.is_file()}


def zero_calls():
    return {key: 0 for key in ("semantic_calls", "network_attempts", "new_semantic_calls", "new_network_attempts")}


def _provenance(value, reference):
    return {"reference": str(reference) if reference is not None else None,
            "sha256": revision(value) if value is not None else None,
            "run_id": value.get("run_id") if isinstance(value, dict) else None}


def run_sample(source, output, *, reference_base=None):
    """Read an external stage-two result; invalid input still gets a debug report."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    started = perf_counter()
    loaded = load_input(source, reference_base=reference_base)
    stage_two, stage_one = loaded["stage_two"], loaded["stage_one"]
    frozen = fingerprint()
    run_id = uuid4().hex
    result = {
        "contract": RESULT_CONTRACT, "run_id": run_id, "milestone": MILESTONE,
        "created_at": datetime.now(UTC).isoformat(),
        "lesson_version": revision({"stage_two": stage_two, "stage_one": stage_one, "implementation": frozen}),
        "stage_two": _provenance(stage_two, loaded["source"]),
        "stage_one": _provenance(stage_one, loaded["stage_one_source"]),
        "input_validation": {"ok": loaded["ok"], "diagnostics": loaded["diagnostics"]},
        "input_diagnostics": loaded["diagnostics"],
        "status": "completed" if loaded["ok"] else "input_error", "goals": [],
        "events": {"stream_id": run_id, "last_seq": 0, "snapshot": None},
        "llm": zero_calls(),
        "upstream_llm": stage_two.get("llm") if isinstance(stage_two, dict) else None,
    }
    # Store the actual checked values so reports remain inspectable after moving
    # the output directory or deleting the source run.
    save(output / "stage-two-input.json", stage_two)
    save(output / "stage-one-input.json", stage_one)
    save(output / "input.json", {
        "contract": INPUT_MANIFEST_CONTRACT,
        "stage_two": {**result["stage_two"], "snapshot": "stage-two-input.json"},
        "stage_one": {**result["stage_one"], "snapshot": "stage-one-input.json"},
        "admission": loaded["admission"],
    })
    save(output / "frozen.json", {"milestone": MILESTONE, "implementation": frozen})
    image = Path(source).parent / "source.png"
    if image.is_file():
        shutil.copyfile(image, output / "source.png")
    if loaded["ok"]:
        candidate = stage_one["candidate"]
        original_targets = {row["target_ref"]: row for row in targets(candidate)}
        for number, previous in enumerate(stage_two["goals"], 1):
            ref = previous["target_ref"]
            original = original_targets[ref]
            features = [row for row in stage_one["features"] if row["target_ref"] == ref]
            goal = {
                **original, "stage_two_status": previous["status"],
                "primary": previous["primary"], "primary_source": previous["primary_source"],
                "status": "skipped", "selection": None, "d3": None, "d4": None,
                "routes": [], "route_status": [], "feasible_set": None, "answer": None,
                "diagnostics": [], "constraint_context": None, "features": features,
            }
            if previous["status"] == "resolved":
                phase = "build_context"
                try:
                    goal["constraint_context"] = build_context(candidate, ref)
                    phase = "evaluate_goal"
                    goal.update(evaluate_goal(candidate, ref, features, previous["primary"]))
                except Exception as exc:  # noqa: BLE001 — persist failure at the target isolation boundary
                    # This is the target isolation boundary, not a mathematical
                    # unknown: programming failures stay visible and fail the run.
                    goal.update(status="execution_error", selection=None, d3=None, d4=None)
                    goal["diagnostics"].append({
                        "code": "execution.target_error", "path": ref, "phase": phase,
                        "exception_type": type(exc).__name__, "message": str(exc),
                        "traceback": traceback.format_exc(),
                    })
            else:
                goal["diagnostics"].append({
                    "code": "input.target_skipped", "path": ref,
                    "message": "阶段②未确认本目标，保留其状态，不进行选法。",
                    "stage_two_status": previous["status"],
                })
            result["goals"].append(goal)
            folder = output / "goals" / f"goal-{number:03}"
            for name, value in (("selection", goal["selection"]), ("d3", goal["d3"]),
                                ("d4", goal["d4"]), ("context", goal["constraint_context"]),
                                ("features", features), ("goal", goal)):
                save(folder / f"{name}.json", value)
        result["status"] = aggregate_status(result["goals"])
    result["elapsed_seconds"] = round(perf_counter() - started, 6)
    validate_result(result)
    save(output / "stage-three-result.json", result)
    from .report import render_result

    render_result(output)
    return result


def _no_provider(*args, **kwargs):
    raise RuntimeError("Stage-three offline acceptance cannot construct an LLM provider")


def run_recorded_batch(batch, output, *, cases=None):
    """Reverify all stage-one records, run stage two offline, then admit its files."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    upstream = stage_two_runner.run_recorded_batch(
        batch, output / "stage-two", cases=cases, provider=_no_provider, verify=False,
    )
    rows = []
    for previous in upstream["results"]:
        relative = previous["sample_dir"]
        result = run_sample(output / "stage-two" / relative / "stage-two-result.json", output / relative)
        rows.append({key: previous[key] for key in ("case_id", "sample_id", "sample_dir")} | {
            "status": result["status"], "goals": len(result["goals"]),
            "eligible": sum(goal["stage_two_status"] == "resolved" for goal in result["goals"]),
            "skipped": sum(goal["status"] == "skipped" for goal in result["goals"]),
            "llm": result["llm"],
        })
    summary = {
        "contract": "graph-stage-three-batch/v1", "run_id": output.name, "milestone": MILESTONE,
        "stage_one_recording": str(Path(batch).resolve()), "stage_two_batch": "stage-two/batch-summary.json",
        "completed": bool(rows) and upstream["completed"] and all(row["status"] == "completed" for row in rows),
        "results": rows, "llm": zero_calls(), "upstream_llm": upstream["llm"],
    }
    save(output / "batch-summary.json", summary)
    from .report import render_batch

    render_batch(output)
    return summary
