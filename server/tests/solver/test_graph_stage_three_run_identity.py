"""All run entry points derive the same immutable identity from the saved seed."""

from copy import deepcopy
from pathlib import Path

import pytest
from sqlalchemy import text

from shuxueshuo_server.graph_lesson.stage_three import preview, runner
from shuxueshuo_server.graph_lesson.stage_three.checkpoint import identity_from_seed
from shuxueshuo_server.graph_lesson.stage_three.storage import RunNotFound
from shuxueshuo_server.problem_understanding.workflow_ledger import save
from shuxueshuo_server.search import stage_three

SEED = {"run_id": "a" * 32, "lesson_version": "lesson-01",
        "stage_one": {"sha256": "b" * 64}, "stage_two": {"sha256": "c" * 64}}
EXPECTED = {"run_id": SEED["run_id"], "lesson_version": SEED["lesson_version"],
            "input_sha256": "6794acf893633639d41fc663838f375e51269a5a9874b9e107469b926150554b"}
FROZEN = {"implementation.py": "d" * 64}


def create_run(directory):
    store = runner._open_store(directory, SEED, FROZEN, create=True)
    save(directory / "run.json", SEED)
    save(directory / "frozen.json", {"implementation": FROZEN})
    with store.transaction(write=True) as db:
        db.execute(text("""INSERT INTO lesson_interaction_states
            (run_id,target,route,step,ordinal,hash,status,interaction_id)
            VALUES (:run_id,:target,:route,:step,:ordinal,:hash,:status,NULL)"""),
                   {"run_id": store.identity["run_id"], "target": "/root/goals/0", "route": "interval",
                    "step": "step-1", "ordinal": 1, "hash": "e" * 64, "status": "pending"})
    return store


def test_seed_identity_preserves_the_existing_canonical_hash_without_io_or_mutation(monkeypatch):
    seed = {**deepcopy(SEED), "goals": [{"changed": "ignored"}], "revisions": {"unrelated": "ignored"}}
    original = deepcopy(seed)

    def forbidden(*args, **kwargs):
        raise AssertionError("seed identity must not read files")

    monkeypatch.setattr(Path, "read_text", forbidden)
    assert identity_from_seed(seed) == EXPECTED
    assert seed == original
    first = identity_from_seed(seed)
    first["run_id"] = "mutated"
    assert identity_from_seed(seed) == EXPECTED


@pytest.mark.parametrize("field", ["run_id", "lesson_version", "stage_one", "stage_two"])
def test_seed_identity_binds_each_run_and_input_field(field):
    changed = deepcopy(SEED)
    if field.startswith("stage_"):
        changed[field]["sha256"] = "f" * 64
        assert identity_from_seed(changed)["input_sha256"] != EXPECTED["input_sha256"]
    else:
        changed[field] = "different"
        assert identity_from_seed(changed) == {**EXPECTED, field: "different"}


def test_runner_preview_and_status_share_identity_while_status_skips_the_frozen_manifest(tmp_path, monkeypatch):
    store = create_run(tmp_path)
    assert store.identity == {**EXPECTED, "revisions": FROZEN}
    assert preview.open_store(tmp_path).identity == store.identity
    # A polling read does not need the large frozen implementation file at all.
    (tmp_path / "frozen.json").write_text("not even valid JSON")
    original = stage_three.read
    reads = []

    def read_seed_only(path):
        reads.append(path.name)
        assert path.name == "run.json"
        return original(path)

    def forbidden(*args, **kwargs):
        raise AssertionError("polling must not open or migrate EventStore")

    monkeypatch.setattr(stage_three, "read", read_seed_only)
    monkeypatch.setattr(stage_three, "open_store", forbidden)
    assert stage_three.has_pending_interactions(tmp_path) is True
    assert reads == ["run.json"]


@pytest.mark.parametrize("seed", [
    None, [], {},
    {**SEED, "run_id": ""}, {**SEED, "run_id": 42},
    {**SEED, "lesson_version": None}, {**SEED, "lesson_version": ""},
    {**SEED, "stage_one": None}, {**SEED, "stage_one": []},
    {**SEED, "stage_one": {}}, {**SEED, "stage_two": {}},
    {**SEED, "stage_one": {"sha256": ""}}, {**SEED, "stage_two": {"sha256": None}},
    {**SEED, "stage_two": {"sha256": 42}},
])
def test_invalid_seed_is_rejected_consistently_without_hiding_query_errors(tmp_path, caplog, seed):
    create_run(tmp_path)
    save(tmp_path / "run.json", seed)
    error_type = ValueError if isinstance(seed, dict) else TypeError
    with pytest.raises(error_type, match="checkpoint.invalid_identity"):
        identity_from_seed(seed)
    with pytest.raises(error_type, match="checkpoint.invalid_identity"):
        runner._open_store(tmp_path, seed, FROZEN, create=False)
    with pytest.raises(error_type, match="checkpoint.invalid_identity"):
        preview.open_store(tmp_path)
    assert stage_three.has_pending_interactions(tmp_path) is False
    assert len(caplog.records) == 1
    assert "Could not read pending interaction status" in caplog.records[0].message
    assert caplog.records[0].exc_info is not None


@pytest.mark.parametrize("field", ["run_id", "lesson_version", "stage_one", "stage_two"])
def test_all_entry_points_reject_seed_identity_different_from_stored_run(tmp_path, caplog, field):
    create_run(tmp_path)
    changed = deepcopy(SEED)
    if field.startswith("stage_"):
        changed[field]["sha256"] = "f" * 64
    else:
        changed[field] = "different"
    save(tmp_path / "run.json", changed)
    error_type = RunNotFound if field == "run_id" else ValueError
    code = "events.run_not_found" if field == "run_id" else "checkpoint.identity_mismatch"
    with pytest.raises(error_type, match=code):
        runner._open_store(tmp_path, changed, FROZEN, create=False)
    with pytest.raises(error_type, match=code):
        preview.open_store(tmp_path)
    assert stage_three.has_pending_interactions(tmp_path) is False
    assert len(caplog.records) == (0 if field == "run_id" else 1)


def test_runner_and_preview_still_validate_the_frozen_implementation(tmp_path):
    create_run(tmp_path)
    changed = {"implementation.py": "f" * 64}
    save(tmp_path / "frozen.json", {"implementation": changed})
    with pytest.raises(ValueError, match="checkpoint.identity_mismatch"):
        runner._open_store(tmp_path, SEED, changed, create=False)
    with pytest.raises(ValueError, match="checkpoint.identity_mismatch"):
        preview.open_store(tmp_path)
    # Status only describes existing committed work; resume checks implementation.
    assert stage_three.has_pending_interactions(tmp_path) is True


def test_stream_descriptor_still_accepts_an_early_seed_with_only_stream_identity(tmp_path):
    create_run(tmp_path)
    save(tmp_path / "run.json", {key: SEED[key] for key in ("run_id", "lesson_version")})
    descriptor = stage_three.stream_descriptor("search-id", tmp_path)
    assert descriptor["run_id"] == SEED["run_id"]
    assert descriptor["lesson_version"] == SEED["lesson_version"]
