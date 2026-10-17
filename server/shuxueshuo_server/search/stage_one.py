"""Run graph-guided stage one on a student's cropped question image (no gold fixture)."""

import json
from hashlib import sha256
from pathlib import Path
from time import perf_counter

from shuxueshuo_server.graph_lesson.stage_one.extraction import GraphStageOneContract, StageOneStorage
from shuxueshuo_server.graph_lesson.stage_one.runner import build_image_request, candidate_features
from shuxueshuo_server.problem_understanding.identity import revision
from shuxueshuo_server.problem_understanding.workflow import run_workflow
from shuxueshuo_server.problem_understanding.workflow_ledger import save
from shuxueshuo_server.solver.extraction.artifacts import ExtractionArtifactStore

RESULT_FILE = "result.json"


def run_question_image(png, output, provider, *, problem_id):
    """Write result.json with the workflow status, candidate, features and image identity.

    ``sent_image_sha256`` comes from the workflow ledger binding, i.e. the image
    actually placed in the model request, so callers can prove the crop reached it.
    """
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    (output / "question.png").write_bytes(png)
    started = perf_counter()
    request = build_image_request(png, ExtractionArtifactStore(output / "inputs"))
    storage = StageOneStorage(output / "workflow")
    workflow = run_workflow(request, provider, storage.directory, [], problem_id=problem_id,
                            storage=storage, contract_adapter=GraphStageOneContract())
    candidate = workflow.get("candidate")
    features = candidate_features(candidate)
    result = {
        "status": workflow.get("status"),
        "source_reviewed": workflow.get("source_reviewed", False),
        "candidate": candidate,
        "features": features["features"],
        "feature_diagnostics": features.get("diagnostics", []),
        "review_findings": _findings(output / "workflow"),
        "confirmation_diagnostics": [d for d in workflow.get("diagnostics", [])
                                     if d.get("action") == "needs_confirmation"],
        # Internal errors are tagged code_gap too, but say nothing about the mathematics.
        "unsupported_diagnostics": [d for d in workflow.get("diagnostics", [])
                                    if d.get("action") == "code_gap" and d.get("stage") != "internal"],
        "question_sha256": sha256(png).hexdigest(),
        "sent_image_sha256": ledger_images(output / "workflow"),
        "elapsed_seconds": round(perf_counter() - started, 3),
    }
    save(output / RESULT_FILE, result)
    return result


def ledger_images(workflow_dir):
    path = Path(workflow_dir) / "ledger.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))["identity"]["binding"]["images"]


def ledger_calls(workflow_dir):
    """(stage, status) of each model call so far, for progress display."""
    path = Path(workflow_dir) / "ledger.json"
    if not path.exists():
        return []
    return [(call["stage"], call["status"]) for call in json.loads(path.read_text(encoding="utf-8"))["calls"]]


def reviewing_candidate(workflow_dir):
    """The candidate a review call is checking, or None.

    A review is only requested for a candidate that passed schema and compile
    checks, so it can be shown before the review answers; ``candidate.json``
    must still be that exact revision (a later repair may have replaced it).
    """
    workflow_dir = Path(workflow_dir)
    ledger, candidate = workflow_dir / "ledger.json", workflow_dir / "candidate.json"
    if not ledger.exists() or not candidate.exists():
        return None
    reviews = [c for c in json.loads(ledger.read_text(encoding="utf-8"))["calls"] if c["stage"] == "review"]
    value = json.loads(candidate.read_text(encoding="utf-8"))
    if not reviews or revision(value) != reviews[-1]["base_revision"]:
        return None
    return value


def _findings(workflow_dir):
    """Review findings of the last completed review call (missing figure, unreadable ...)."""
    workflow_dir = Path(workflow_dir)
    path = workflow_dir / "ledger.json"
    if not path.exists():
        return []
    reviews = [c for c in json.loads(path.read_text(encoding="utf-8"))["calls"]
               if c["stage"] == "review" and c["status"] == "completed" and c.get("response_file")]
    if not reviews:
        return []
    response = json.loads((workflow_dir / reviews[-1]["response_file"]).read_text(encoding="utf-8"))
    try:
        return json.loads(response["text"]).get("findings", [])
    except (KeyError, TypeError, ValueError):
        return []
