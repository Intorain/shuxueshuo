"""The offline audit consumes authentic frozen seeds without rewriting inputs."""

import json
from copy import deepcopy

import pytest

from shuxueshuo_server.graph_lesson.stage_three import interaction
from shuxueshuo_server.graph_lesson.stage_three.revision_manifest import math_step_hash
from shuxueshuo_server.problem_understanding.identity import revision
from tools import compile_graph_stage_three_interactions as audit


def _recording(root, *, count=2):
    identity = {"run_id": "recorded-run", "lesson_version": "recorded-lesson",
                "target_ref": "/root/goals/0", "route_id": "interval"}
    cards, seeds = [], []
    for ordinal in range(1, count + 1):
        card = {**identity, "contract": "graph-math-step/v2", "revisions_ref": "a" * 64,
                "step_id": f"card-{ordinal}", "ordinal": ordinal, "method_ref": "method-interval-extremum#select",
                "display_unit": "unknown-test", "case_path": [], "title": "<script>bad()</script>",
                "explanation": "数学说明 $x^2$", "before": [], "after": [], "local_check": "passed",
                "source_refs": [], "used_basis": [], "premise_refs": []}
        card["math_step_sha256"] = math_step_hash(card)
        cards.append(card)
        seeds.append({**{key: card[key] for key in (
            "run_id", "lesson_version", "target_ref", "route_id", "step_id", "ordinal", "method_ref",
            "display_unit", "case_path", "math_step_sha256")},
            "contract": "graph-interaction-seed/v1", "template": "unknown-test", "status": "ready",
            "values": {"own_marker": ordinal}, "context": {}, "constraint_context": {}})
    checkpoint = {**identity, "status": "verified", "driver_state": {
        "method": "method-interval-extremum", "fragments": cards, "interaction_seeds": seeds}}
    snapshot = {**identity, "checkpoints": [checkpoint]}
    root.mkdir(parents=True)
    (root / "checkpoint.json").write_text(json.dumps(snapshot))
    result = {"run_id": identity["run_id"], "lesson_version": identity["lesson_version"], "status": "completed",
              "goals": [{"target_ref": identity["target_ref"], "status": "solved", "routes": [{
                  "route_id": identity["route_id"], "method": "method-interval-extremum", "status": "verified"}]}]}
    (root / "stage-three-result.json").write_text(json.dumps(result))
    return snapshot


def test_real_compiler_reads_frozen_seeds_and_preserves_all_source_bytes(tmp_path):
    source, output = tmp_path / "source", tmp_path / "audit"
    snapshot = _recording(source)
    original = (source / "checkpoint.json").read_bytes()
    result = audit.compile_batch(source, output)
    assert result["completed"] and result["new_llm_calls"] == result["new_mathematical_runs"] == 0
    assert result["totals"]["cards"] == result["totals"]["readonly_cards"] == 2
    assert result["readonly_reasons"] == {"no_rule": 2}
    assert result["templates"]["unknown-test"]["readonly_cards"] == 2
    assert result["declared_template_count"] == 35
    assert len(result["declared_templates"]) == 35
    assert result["seen_templates"] == ["unknown-test"]
    assert result["unseen_templates"] == result["declared_templates"]
    assert result["undeclared_templates"] == ["unknown-test"]
    route = output / "sample-001/route-001"
    seeds = snapshot["checkpoints"][0]["driver_state"]["interaction_seeds"]
    assert json.loads((route / "seeds.json").read_text()) == seeds
    provenance = json.loads((route / "provenance.json").read_text())
    assert provenance["seeds_sha256"] == revision(seeds)
    assert provenance["source"] == str(source / "checkpoint.json")
    assert provenance["result_source"] == str(source / "stage-three-result.json")
    assert len(provenance["result_source_sha256"]) == 64
    assert (source / "checkpoint.json").read_bytes() == original
    page = (route / "index.html").read_text()
    assert "&lt;script&gt;bad()&lt;/script&gt;" in page and "<script>bad()" not in page
    assert (output / "assets/components.js").is_file()
    assert (output / "assets/katex/katex.min.js").is_file()


@pytest.mark.parametrize("damage,reason", [
    ("missing", "missing_frozen_seeds"), ("short", "missing_frozen_seeds"),
    ("hash", "seed_card_mismatch"), ("identity", "seed_card_mismatch"),
    ("card_content", "seed_card_mismatch"), ("order", "card_order"),
])
def test_missing_or_tampered_recordings_fail_before_creating_output(tmp_path, damage, reason):
    source, output = tmp_path / "source", tmp_path / "audit"
    snapshot = _recording(source)
    state = snapshot["checkpoints"][0]["driver_state"]
    if damage == "missing":
        state.pop("interaction_seeds")
    elif damage == "short":
        state["interaction_seeds"].pop()
    elif damage == "hash":
        state["interaction_seeds"][0]["math_step_sha256"] = "b" * 64
    elif damage == "identity":
        state["interaction_seeds"][0]["route_id"] = "another-route"
    elif damage == "card_content":
        state["fragments"][0]["explanation"] = "changed"
    else:
        state["fragments"].reverse()
        state["interaction_seeds"].reverse()
    (source / "checkpoint.json").write_text(json.dumps(snapshot))
    with pytest.raises(ValueError, match=reason):
        audit.compile_batch(source, output)
    assert not output.exists()


def test_outputs_cannot_overwrite_or_be_created_inside_the_source(tmp_path):
    source = tmp_path / "source"
    _recording(source)
    for output in (source, source / "nested"):
        with pytest.raises(ValueError, match="output_inside_source"):
            audit.compile_batch(source, output)
    with pytest.raises(FileExistsError):
        audit.compile_batch(source, tmp_path)


def test_compile_route_is_the_only_compilation_entry_and_passes_only_current_group(tmp_path, monkeypatch):
    source, output = tmp_path / "source", tmp_path / "audit"
    snapshot = _recording(source)
    all_seeds = snapshot["checkpoints"][0]["driver_state"]["interaction_seeds"]
    observed = []
    original = interaction.build_chunk

    def capture(group, registry, context, **kwargs):
        observed.append(deepcopy(group))
        assert len(group) == 1
        assert group[0]["values"] == {"own_marker": len(observed)}
        return original(group, registry, context, **kwargs)

    monkeypatch.setattr(interaction, "build_chunk", capture)
    audit.compile_batch(source, output)
    assert observed == [[seed] for seed in all_seeds]


def test_batch_routes_and_templates_are_counted_without_double_counting_merges(tmp_path, monkeypatch):
    source, output = tmp_path / "source", tmp_path / "audit"
    _recording(source / "q01/sample-01")
    _recording(source / "q01/sample-02")
    # A valid final result can cover two mathematics cards as one question.
    def merged(seeds, registry, *, final, revision):
        chunk = interaction.readonly_chunk(seeds, revision, "no_rule")
        chunk.update(status="interactive", parts=[{
            "id": chunk["interaction_id"] + "#1", "title": "选择", "question": "<img src=x onerror=bad()> $x$",
            "graph": {"kind": "linear", "params": {
                "slope": 1, "intercept": 0, "bounds": [-1, 1, -1, 1], "title": "直线", "description": "直线",
                "variable": "x", "interval": [None, None], "interval_closed": [False, False],
                "points": [], "xTicks": []}},
            "interaction": {"type": "choice", "field": "p", "options": [
                {"value": "o1", "label": "$x=1$"},
                {"value": "o2", "label": "<script>bad()</script>"}]},
            "expected_answer": {"one_of": ["o1"]}, "feedback": {"answer": "反馈"}, "submit_label": "确认"}])
        chunk.pop("reason")
        chunk["interaction_sha256"] = interaction.chunk_sha256(chunk)
        return [(chunk, [])], []

    monkeypatch.setattr(interaction, "compile_route", merged)
    result = audit.compile_batch(source, output)
    assert len(result["recordings"]) == 2
    assert result["totals"]["interactive_cards"] == 4
    assert result["totals"]["interactive_groups"] == result["totals"]["questions"] == 2
    assert result["templates"]["unknown-test"]["questions"] == 2
    page = (output / "sample-001/route-001/index.html").read_text()
    assert "&lt;img src=x onerror=bad()&gt;" in page
    assert "<img src=x" not in page and "<script>bad()" not in page
    assert "data-graph=" in page and "正确：" in page


def test_compile_error_marks_the_report_unsuccessful(tmp_path, monkeypatch):
    source, output = tmp_path / "source", tmp_path / "audit"
    _recording(source)

    def fail(seeds, registry, context, **kwargs):
        return interaction.readonly_chunk(seeds, kwargs["revision"], "compile_error"), [{"result": "compile_error"}]

    monkeypatch.setattr(interaction, "build_chunk", fail)
    result = audit.compile_batch(source, output)
    assert not result["completed"]
    assert result["totals"]["compile_errors"] == 2
    assert (output / "index.html").is_file()


def test_dropped_compiler_group_cannot_be_reported_as_complete(tmp_path, monkeypatch):
    source, output = tmp_path / "source", tmp_path / "audit"
    _recording(source)
    monkeypatch.setattr(interaction, "compile_route", lambda *args, **kwargs: ([], []))
    with pytest.raises(ValueError, match="incomplete_or_reordered_groups"):
        audit.compile_batch(source, output)


@pytest.mark.parametrize("damage", ["missing_route", "status", "method", "identity"])
def test_result_and_snapshot_route_manifest_must_match(tmp_path, damage):
    source, output = tmp_path / "source", tmp_path / "audit"
    _recording(source)
    result_path = source / "stage-three-result.json"
    result = json.loads(result_path.read_text())
    if damage == "missing_route":
        result["goals"][0]["routes"].append({"route_id": "lost-route", "method": "method-separation", "status": "verified"})
    elif damage in {"status", "method"}:
        result["goals"][0]["routes"][0][damage] = "different"
    else:
        result["run_id"] = "other-recording"
    result_path.write_text(json.dumps(result))
    with pytest.raises(ValueError, match="result_(routes|identity)_mismatch"):
        audit.compile_batch(source, output)
    assert not output.exists()
