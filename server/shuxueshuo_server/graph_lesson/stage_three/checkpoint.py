"""JSON checkpoint identities and atomic debug exports.

The SQLite commit in events.py is authoritative. These JSON files are portable
views; a crash while exporting them cannot advance or rewind execution.
"""

import json
import os
import tempfile
from copy import deepcopy
from pathlib import Path

from .contracts import ROOT
from .revision_manifest import manifest_ref, validate_revision_ref
from .storage_validation import validate_schema

IDENTITY_FIELDS = ("run_id", "lesson_version", "input_sha256", "revisions")


def identity_value(value):
    result = {name: deepcopy(value[name]) for name in IDENTITY_FIELDS}
    if not all(isinstance(result[key], str) and result[key] for key in IDENTITY_FIELDS[:-1]):
        raise ValueError("checkpoint.invalid_identity")
    if not isinstance(result["revisions"], dict) or not result["revisions"]:
        raise ValueError("checkpoint.missing_revisions")
    return result


def validate_checkpoint(value, identity):
    version = "v2" if value.get("contract") == "graph-stage-three-checkpoint/v2" else "v1"
    validate_schema(ROOT / f"internal/schemas/graph-stage-three-checkpoint-{version}.schema.json", value)
    expected = identity_value(identity)
    if any(value[key] != expected[key] for key in IDENTITY_FIELDS[:-1]):
        raise ValueError("checkpoint.identity_mismatch")
    try:
        validate_revision_ref(value, expected["revisions"])
        state = value.get("driver_state", {})
        for carrier in (state, state.get("trajectory", {})):
            if "revisions" in carrier or "revisions_ref" in carrier:
                validate_revision_ref(carrier, expected["revisions"])
    except ValueError as exc:
        raise ValueError("checkpoint.identity_mismatch") from exc


def make_checkpoint(identity, target_ref, route_id, *, driver_state, status="running", frames=None,
                    output_refs=None, next_instance=0, compute_seconds=None, phase="method"):
    """Wrap a JSON-safe driver state without interpreting its mathematical data."""
    return {
        "contract": "graph-stage-three-checkpoint/v2",
        **{key: identity[key] for key in IDENTITY_FIELDS[:-1]},
        "revisions_ref": manifest_ref(identity["revisions"]),
        "target_ref": target_ref, "route_id": route_id, "status": status,
        "frames": deepcopy(frames if frames is not None else driver_state.get("frames", [])),
        "output_refs": list(output_refs or []), "math_steps": [], "next_instance": next_instance,
        "compute_seconds": deepcopy(compute_seconds or {"solve": 0, "verification": 0}),
        "driver_state": deepcopy(driver_state), "phase": phase,
        "commit_id": "uncommitted", "last_seq": 0,
    }


def atomic_write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def export_json(path, value):
    atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
