"""Independent type/knowledge expectations; no network or model calls."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from shuxueshuo_server.graph_lesson.stage_one.features import extract_features
from shuxueshuo_server.graph_lesson.stage_two.recognition import (
    DATA,
    build_d2,
    derive_knowledge,
    evaluate_types,
    load_contracts,
    load_nodes,
)

FIXTURES = Path(__file__).parent / "fixtures"
CORPUS = FIXTURES / "graph-guided-stage-one/quadratic-always"
RECORDED = FIXTURES / "graph-guided-stage-one/recorded/live-v2-20261017-02"
GOLD = json.loads((FIXTURES / "graph-guided-stage-two/recognition.gold.json").read_text())["cases"]
QUADRATIC = "type-quantified-quadratic"
PARAMETER = "type-parameter-quadratic-solve"
AMGM = "type-amgm-quantified"


def features(case="q01"):
    return extract_features(json.loads((CORPUS / case / "notation.gold.json").read_text()))["features"]


def assert_expected(candidate, expected):
    all_features = extract_features(candidate)["features"]
    for goal in expected:
        selected = [f for f in all_features if f["target_ref"] == goal["target_ref"]]
        reports = evaluate_types(selected)
        indexed = {r["type_id"]: r for r in reports}
        assert [r["type_id"] for r in reports if r["status"] == "supported"] == goal["supported"]
        assert indexed[PARAMETER]["status"] == goal["parameter_status"]
        assert indexed[AMGM]["status"] == "unknown"
        assert {i["ref"] for i in derive_knowledge(selected)["items"]} == set(goal["knowledge"])
        passed = [b["branch_id"] for b in indexed[QUADRATIC]["branches"] if b["status"] == "supported"]
        assert passed == ([goal["quadratic_branch"]] if goal["quadratic_branch"] else [])
        identifiers = [c["check_id"] for r in reports for b in r["branches"] for c in b["checks"]]
        assert len(identifiers) == len(set(identifiers))


@pytest.mark.parametrize("case", list(GOLD))
def test_authored_problem_expectations(case):
    assert_expected(json.loads((CORPUS / case / "notation.gold.json").read_text()), GOLD[case])


@pytest.mark.parametrize("case,sample", [(q, s) for q in GOLD for s in ("sample-01", "sample-02")])
def test_recorded_candidate_math_has_same_recognition(case, sample):
    # Internal deterministic unit test only. Public input tests separately replay
    # and validate these recordings; no source-review status is fabricated here.
    assert_expected(json.loads((RECORDED / case / sample / "candidate.json").read_text()), GOLD[case])


def test_contract_and_rule_references_exist():
    nodes = load_nodes()
    for contract in load_contracts():
        node = nodes[contract["type_id"]]
        for branch in contract["branches"]:
            for check in branch["checks"]:
                assert node["features"][check["student_cue"]]["cue"]
        assert all(entry["ref"] in nodes for entry in node.get("confuse", []))
    rules = json.loads((DATA / "recognition/feature-knowledge.json").read_text())["rules"]
    assert len({r["rule_id"] for r in rules}) == len(rules)
    for rule in rules:
        node, entry = rule["ref"].split("#")
        assert entry in {x["id"] for x in nodes[node]["entries"]}


@pytest.mark.parametrize("state", ["unknown", "conditional"])
def test_unknown_or_conditional_inputs_never_confirm_or_refute(state):
    rows = features()
    for row in rows:
        row["status"] = state
    reports = evaluate_types(rows)
    assert all(r["status"] == "unknown" for r in reports)
    assert all(c["status"] == "unknown" for r in reports for b in r["branches"] for c in b["checks"])
    assert derive_knowledge(rows)["items"] == []


@pytest.mark.parametrize("fact", ["∀x∈ℝ:a*x+1>=0", "∀x∈ℝ:a*x>=0", "∃x∈ℝ:x^2=a", "∃x∈ℝ:x^2!=a"])
def test_nonquadratic_and_noninequality_counterexamples(fact):
    candidate = {"original_text": fact, "root": {"facts": [fact], "goals": [{"kind": "find_range", "symbol": "a"}]}}
    report = next(r for r in evaluate_types(extract_features(candidate)["features"]) if r["type_id"] == QUADRATIC)
    assert report["status"] == "conflict"
    assert all(b["status"] == "conflict" for b in report["branches"])


@pytest.mark.parametrize("operator,lights", [("=", False), ("!=", False), ("<", True), ("<=", True), (">", True), (">=", True)])
def test_quadratic_knowledge_requires_inequality(operator, lights):
    candidate = {"original_text": "求 a", "root": {"facts": [f"∃x∈ℝ:x^2{operator}a"], "goals": [{"kind": "find_range", "symbol": "a"}]}}
    knowledge = derive_knowledge(extract_features(candidate)["features"])
    refs = {item["ref"] for item in knowledge["items"]}
    assert ("quadratic-inequality#definition" in refs) is lights
    assert "quadratic-function-properties#definition" in refs


def test_knowledge_does_not_depend_on_primary_and_never_lights_method():
    rows = features()
    plain = derive_knowledge(rows)
    chosen = derive_knowledge(rows, QUADRATIC)
    assert plain["items"] == chosen["items"]
    assert {link["from"] for link in chosen["links"]} == {"quantifiers", "quadratic-inequality", "quadratic-function-properties"}
    assert not any(i["ref"].startswith("function-range-extrema") for i in plain["items"])
    roles = next(i for i in plain["items"] if i["ref"] == "quantifiers#roles")
    assert roles["matched_any"] == ["bound_vars", "goal"]
    assert next(i for i in plain["items"] if i["ref"] == "quadratic-inequality#definition")["fragment_kinds"] == ["relation"]


def test_relation_unknown_only_hides_relation_knowledge():
    rows = features()
    next(r for r in rows if r["feature_id"] == "relation")["status"] = "unknown"
    refs = {i["ref"] for i in derive_knowledge(rows)["items"]}
    assert "quadratic-inequality#definition" not in refs
    assert "quadratic-function-properties#definition" in refs


def test_d2_unknown_is_omitted_and_verified_alternative_is_not_wrong():
    rows = features()
    before = build_d2(evaluate_types(rows), QUADRATIC)["options"]
    assert {o["type_id"] for o in before} == {QUADRATIC, PARAMETER}
    assert next(o for o in before if o["type_id"] == PARAMETER)["role"] == "conflict"
    assert next(o for o in before if o["type_id"] == PARAMETER)["check_ids"]
    after = build_d2(evaluate_types(rows, {"status": "supported"}), QUADRATIC)["options"]
    assert next(o for o in after if o["type_id"] == AMGM)["role"] == "alternative"


def test_d2_supported_evidence_only_comes_from_supported_branches():
    reports = evaluate_types(features(), {"status": "supported"})
    for report in reports:
        if report["status"] != "supported":
            continue
        for state in ("conflict", "unknown"):
            report["branches"].append({"branch_id": f"unpassed-{state}", "status": state,
                                       "checks": [{"check_id": f"{report['type_id']}/{state}/partial",
                                                   "status": "supported"}]})
    options = build_d2(reports, QUADRATIC)["options"]
    for report in reports:
        if report["status"] != "supported":
            continue
        option = next(o for o in options if o["type_id"] == report["type_id"])
        expected = [check["check_id"] for branch in report["branches"] if branch["status"] == "supported"
                    for check in branch["checks"] if check["status"] == "supported"]
        assert option["check_ids"] == expected
        assert expected


def test_d2_conflict_evidence_keeps_each_conflicting_branch():
    reports = evaluate_types(features())
    report = next(r for r in reports if r["type_id"] == PARAMETER)
    report["branches"].append({"branch_id": "other-conflict", "status": "conflict", "checks": [
        {"check_id": "other-conflict/rejected", "status": "conflict"},
        {"check_id": "other-conflict/partial", "status": "supported"},
    ]})
    option = next(o for o in build_d2(reports, QUADRATIC)["options"] if o["type_id"] == PARAMETER)
    expected = [check["check_id"] for branch in report["branches"] for check in branch["checks"]
                if check["status"] == "conflict"]
    assert option["check_ids"] == expected
    assert "other-conflict/rejected" in option["check_ids"]
    assert "other-conflict/partial" not in option["check_ids"]


def test_d2_unknown_filter_is_not_a_q01_exception():
    reports = [{"type_id": AMGM, "status": "supported", "branches": []},
               {"type_id": QUADRATIC, "status": "unknown", "branches": []}]
    assert [o["type_id"] for o in build_d2(reports, AMGM)["options"]] == [AMGM]
    reports[1]["status"] = "conflict"
    assert [o["type_id"] for o in build_d2(reports, AMGM)["options"]] == [AMGM, QUADRATIC]


def test_target_groups_cannot_be_mixed_and_checks_cannot_collide():
    with pytest.raises(ValueError, match="multiple_targets"):
        evaluate_types(features("q10"))
    contracts = load_contracts()
    with pytest.raises(ValueError, match="duplicate_check_id"):
        evaluate_types(features(), contracts=[contracts[0], deepcopy(contracts[0])])
    with pytest.raises(ValueError, match="primary_not_supported"):
        build_d2(evaluate_types(features()), AMGM)
