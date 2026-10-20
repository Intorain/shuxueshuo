"""Boundary regressions: portable inputs, complete scopes and honest artifacts."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError

from shuxueshuo_server.graph_lesson.stage_three.context import build_context
from shuxueshuo_server.graph_lesson.stage_three.contracts import (
    ROOT,
    load_input,
    validate_result,
)
from shuxueshuo_server.graph_lesson.stage_two.runner import run_result
from shuxueshuo_server.problem_understanding.identity import revision

FIXTURES = Path(__file__).parent / "fixtures/graph-guided-stage-one"


def accepted(case="q01"):
    return json.loads((FIXTURES / "recorded/live-v2-20261017-02" / case / "sample-01/stage-one-result.json").read_text())


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def upstream(tmp_path, case="q01"):
    folder = tmp_path / "stage-two"
    run_result(accepted(case), folder, input_reference="historical/missing.json", unsupported_root=tmp_path / "unsupported")
    return folder / "stage-two-result.json"


def alter(source, mutate):
    value = json.loads(source.read_text())
    mutate(value)
    write(source, value)


def test_local_copy_wins_and_hash_uses_canonical_json(tmp_path):
    source = upstream(tmp_path)
    input_path = source.parent / "input.json"
    value = json.loads(input_path.read_text())
    input_path.write_text(json.dumps(value, ensure_ascii=True, indent=4) + "\n\n")
    result = load_input(source)
    assert result["ok"] and result["admission"] == "acceptance"
    assert result["stage_one"] == value
    assert result["stage_one_source"] == str(input_path)


@pytest.mark.parametrize("change,code", [
    (lambda v: v.update(contract="graph-stage-two-result/v999"), "input.stage_two"),
    (lambda v: v.update(status="failed"), "input.stage_two"),
    (lambda v: v["stage_one"].update(sha256="0" * 64), "input.stage_one_hash"),
    (lambda v: v["options"].update(admission="unknown"), "input.admission"),
    (lambda v: v["options"].update(admission=[]), "input.admission"),
    (lambda v: v["goals"][0].update(target_ref="/root/goals/9"), "input.target_ref"),
    (lambda v: v["goals"][0].update(goal={"kind": "find_minimum", "expression": "a"}), "input.target_metadata"),
    (lambda v: v["goals"][0].update(scope="/root/children/0"), "input.target_metadata"),
])
def test_reject_corrupt_upstream_fields(tmp_path, change, code):
    source = upstream(tmp_path)
    alter(source, change)
    result = load_input(source)
    assert not result["ok"]
    assert code in {d["code"] for d in result["diagnostics"]}


@pytest.mark.parametrize("mutation", [lambda goals: goals.pop(), lambda goals: goals.reverse()])
def test_complete_target_coverage_and_order_required(tmp_path, mutation):
    source = upstream(tmp_path, "q10")
    alter(source, lambda value: mutation(value["goals"]))
    result = load_input(source)
    assert not result["ok"]
    assert "input.target_coverage" in {d["code"] for d in result["diagnostics"]}


def test_primary_must_agree_with_actual_supported_type_reports(tmp_path):
    source = upstream(tmp_path)

    def corrupt(value):
        goal = value["goals"][0]
        goal["primary"] = "invented-primary"
        goal["supported"].append("invented-primary")

    alter(source, corrupt)
    result = load_input(source)
    assert not result["ok"]
    assert {d["code"] for d in result["diagnostics"]} >= {"input.supported_types", "input.primary"}


def test_stage_one_validation_is_repeated_even_when_hash_matches(tmp_path):
    source = upstream(tmp_path)
    input_path = source.parent / "input.json"
    value = json.loads(input_path.read_text())
    value["statuses"]["passed"] = False
    write(input_path, value)
    alter(source, lambda result: result["stage_one"].update(sha256=revision(value)))
    result = load_input(source)
    assert not result["ok"]
    assert any(d["path"] == "/stage_one/statuses/passed" for d in result["diagnostics"])


@pytest.mark.parametrize("failure", ["input_error", "failed"])
def test_valid_upstream_failure_envelopes_are_not_admitted(tmp_path, failure):
    folder = tmp_path / "rejected"
    if failure == "input_error":
        run_result(None, folder)
    else:
        run_result(accepted(), folder, verify=True)
    result = load_input(folder / "stage-two-result.json")
    assert not result["ok"]
    assert result["diagnostics"][0]["code"] == "input.status"


def test_legacy_missing_admission_defaults_to_acceptance(tmp_path):
    source = upstream(tmp_path)
    alter(source, lambda value: value.pop("options"))
    result = load_input(source)
    assert result["ok"] and result["admission"] == "acceptance"


def test_student_upload_does_not_require_or_invent_gold_acceptance(tmp_path):
    value = accepted()
    value["statuses"].update(admission="student_upload")
    value["statuses"].pop("evaluation")
    value["statuses"].pop("passed")
    folder = tmp_path / "student"
    run_result(value, folder, admission="student_upload")
    result = load_input(folder / "stage-two-result.json")
    assert result["ok"] and result["admission"] == "student_upload"
    assert "evaluation" not in result["stage_one"]["statuses"]
    assert "passed" not in result["stage_one"]["statuses"]


@pytest.mark.parametrize("absolute", [True, False])
def test_reference_fallback_is_explicit_and_not_relative_to_result(tmp_path, absolute):
    source = upstream(tmp_path)
    original = tmp_path / "original"
    original.mkdir()
    destination = original / "stage-one.json"
    (source.parent / "input.json").rename(destination)
    alter(source, lambda result: result["stage_one"].update(reference=str(destination) if absolute else "stage-one.json"))
    result = load_input(source)
    if absolute:
        assert result["ok"]
    else:
        assert not result["ok"]
        assert result["diagnostics"][0]["code"] == "input.reference_base"
        result = load_input(source, reference_base=original)
        assert result["ok"]
    assert Path(result["stage_one_source"]) == destination


def test_present_broken_local_copy_never_falls_back(tmp_path):
    source = upstream(tmp_path)
    backup = tmp_path / "backup.json"
    backup.write_text((source.parent / "input.json").read_text())
    alter(source, lambda result: result["stage_one"].update(reference=str(backup)))
    (source.parent / "input.json").write_text("{")
    result = load_input(source)
    assert not result["ok"]
    assert result["diagnostics"][0]["code"] == "input.read"


@pytest.mark.parametrize("body", ["null", "[]", "{", '{"contract":"x","contract":"y"}'])
def test_bad_json_and_envelopes_are_diagnostics(tmp_path, body):
    source = tmp_path / "bad.json"
    source.write_text(body)
    result = load_input(source)
    assert not result["ok"] and result["diagnostics"]


def test_context_preserves_ancestor_and_own_conditions_but_excludes_sibling():
    candidate = json.loads((FIXTURES / "quadratic-always/q10/notation.gold.json").read_text())
    candidate["root"]["facts"].append("a<1")
    candidate["root"]["children"][0]["facts"].append("a>=0")
    candidate["root"]["children"][1]["facts"].append("b>2")
    original = deepcopy(candidate)
    first = build_context(candidate, "/root/children/0/goals/0")
    second = build_context(candidate, "/root/children/1/goals/0")
    assert candidate == original
    assert {entry["expression"] for entry in first["entries"]} == {
        "f(x)=x^2-2*a*x+3", "a∈ℝ", "a<1", "∀x∈ℝ: f(x) ≥ 0", "a>=0",
    }
    assert "a>=0" not in {entry["expression"] for entry in second["entries"]}
    assert "b" not in {symbol["name"] for symbol in first["symbols"]}
    assert "b" in {symbol["name"] for symbol in second["symbols"]}
    assert "x" not in {symbol["name"] for symbol in first["symbols"]}
    assert first["bound_symbols"] and all(entry["processing"]["status"] == "pending" for entry in first["entries"])
    assert set(first["processing"]["unprocessed_source_refs"]) == {entry["source_ref"] for entry in first["entries"]}
    assert {entry["ref"] for entry in first["bound_symbols"]} != {entry["ref"] for entry in second["bound_symbols"]}


def test_context_retains_minimum_goal_and_uncancelled_denominator_conditions():
    candidate = {"original_text": "测试原分母", "root": {
        "facts": ["a∈ℝ", "∀x∈(0,1]: (x-1)/(x-1)+a>=0"],
        "goals": [{"kind": "find_minimum", "expression": "a"}],
    }}
    result = build_context(candidate, "/root/goals/0")
    assert result["goal"] == candidate["root"]["goals"][0]
    obligation, = result["well_definedness"]
    assert obligation["source_ref"] == "/root/facts/1"
    assert obligation["denominator"] == ["-", ["bound", "quantified_0"], ["number", "1"]]
    assert obligation["binding_refs"] == [result["bound_symbols"][0]["ref"]]
    assert obligation["processing"]["status"] == "pending"


def test_quantified_name_never_reuses_global_symbol_identity():
    candidate = {"original_text": "测试绑定变量", "root": {
        "facts": ["x>0", "∀x∈ℝ:x^2+a>=0"], "goals": [{"kind": "find_range", "symbol": "a"}],
    }}
    result = build_context(candidate, "/root/goals/0")
    global_x = next(symbol for symbol in result["symbols"] if symbol["name"] == "x")
    binder, = result["bound_symbols"]
    assert global_x["ref"] != binder["ref"]
    assert global_x["source_refs"] == ["/root/facts/0"]
    assert binder["source_ref"] == "/root/facts/1"


@pytest.mark.parametrize("ref", ["/root/facts/0", "/root/goals/999", "/root/children/99/goals/0"])
def test_context_rejects_non_goal_pointers(ref):
    with pytest.raises(ValueError, match="context.invalid_target"):
        build_context(accepted()["candidate"], ref)


def test_all_new_schemas_are_valid_and_do_not_require_external_resolution():
    paths = [*ROOT.glob("internal/schemas/graph-stage-three-*.schema.json"),
             *ROOT.glob("internal/schemas/graph-method-*.schema.json"),
             *ROOT.glob("internal/schemas/graph-math-step-*.schema.json")]
    assert len(paths) >= 9
    for path in paths:
        Draft202012Validator.check_schema(json.loads(path.read_text()))


def test_math_event_and_checkpoint_require_full_identity_and_checked_boundaries():
    def validator(name):
        return Draft202012Validator(json.loads((ROOT / f"internal/schemas/{name}-v1.schema.json").read_text()))

    event = {"contract": "graph-stage-three-event/v1", "event_id": "one", "stream_id": "s", "seq": 1,
             "lesson_version": "v", "run_id": "r", "target_ref": "/root/goals/0", "route_id": "discriminant",
             "type": "lesson.chunk_ready", "payload": {"kind": "step_qa", "step_id": "step-1",
                 "math_step_sha256": "a" * 64, "verified_route_sha256": "b" * 64}}
    checker = validator("graph-stage-three-event")
    checker.validate(event)
    for field in ("step_id", "math_step_sha256", "verified_route_sha256"):
        broken = deepcopy(event)
        del broken["payload"][field]
        with pytest.raises(ValidationError):
            checker.validate(broken)
    for field in ("target_ref", "route_id"):
        broken = deepcopy(event)
        broken[field] = None
        with pytest.raises(ValidationError):
            checker.validate(broken)
    with pytest.raises(ValidationError):
        validator("graph-stage-three-checkpoint").validate({"contract": "graph-stage-three-checkpoint/v1"})


def test_result_cannot_claim_nonzero_calls_or_skip_resolved_goal(tmp_path):
    from shuxueshuo_server.graph_lesson.stage_three.runner import run_sample

    source = upstream(tmp_path)
    result = run_sample(source, tmp_path / "stage-three", milestone="1a")
    validate_result(result)
    broken = deepcopy(result)
    broken["llm"]["network_attempts"] = 1
    with pytest.raises(ValidationError):
        validate_result(broken)
    broken = deepcopy(result)
    broken["goals"][0].update(status="skipped", d3=None, d4=None)
    with pytest.raises(ValueError, match="resolved_goal_skipped"):
        validate_result(broken)
