"""Rule provenance and public-call guards on interval execution contracts."""

import json

import pytest

from shuxueshuo_server.graph_lesson.stage_three import execution_contracts


def test_interval_rule_public_calls_have_explicit_branch_sources():
    contract = execution_contracts.read("method-interval-extremum")
    execution_contracts.validate_contract(contract)
    select = contract["steps"][1]
    targets = {row["id"]: row["target"] for row in
               execution_contracts.load_nodes()["rule-interval-skill"]["branches"]}
    assert {call["branch"] for call in select["calls"]} == set(targets)
    for call in select["calls"]:
        assert call["rule_ref"] == "rule-interval-skill"
        assert call["public_ref"] == targets[call["branch"]]


@pytest.mark.parametrize("mutation", ["missing_rule", "wrong_rule", "wrong_branch",
                                     "no_guard", "wrong_guard", "missing_option"])
def test_interval_rule_rejects_unproven_or_invented_public_calls(mutation):
    contract = execution_contracts.read("method-interval-extremum")
    select = contract["steps"][1]
    call = select["calls"][0]
    if mutation == "missing_rule":
        del call["rule_ref"]
    elif mutation == "wrong_rule":
        call["rule_ref"] = "rule-quadratic-method"
    elif mutation == "wrong_branch":
        call["branch"] = "linear"
    elif mutation == "no_guard":
        del call["guard"]
    elif mutation == "wrong_guard":
        call["guard"] = {"ref": "parametric", "equals": True}
    else:
        select["judgments"][0]["options"].pop()
    with pytest.raises(ValueError, match="execution\\."):
        execution_contracts.validate_contract(contract)


def test_boundary_locations_come_from_valid_graph_steps():
    registry = execution_contracts.read("presentation-registry")["boundary_steps"]
    assert registry["method-interval-extremum"] == "verify"
    nodes = execution_contracts.load_nodes()
    assert all(execution_contracts.valid_ref(method + "#" + step, nodes)
               for method, step in registry.items())


@pytest.mark.parametrize("method", sorted(execution_contracts.route_methods()))
def test_loading_rejects_a_missing_boundary_for_every_top_level_route(monkeypatch, method):
    original_read = execution_contracts.read

    def read(name):
        value = original_read(name)
        if name == "presentation-registry":
            del value["boundary_steps"][method]
        return value

    monkeypatch.setattr(execution_contracts, "read", read)
    with pytest.raises(ValueError, match="execution\\.missing_boundary_step:" + method):
        execution_contracts.load_contracts()


def test_loading_rejects_a_missing_boundary_registry(monkeypatch):
    original_read = execution_contracts.read

    def read(name):
        value = original_read(name)
        if name == "presentation-registry":
            del value["boundary_steps"]
        return value

    monkeypatch.setattr(execution_contracts, "read", read)
    with pytest.raises(ValueError, match="execution\\.missing_boundary_step:"):
        execution_contracts.load_contracts()


def test_new_selection_route_requires_a_boundary_without_another_method_list(monkeypatch, tmp_path):
    selection = tmp_path / "selection"
    selection.mkdir()
    (selection / "new-rule.json").write_text(json.dumps({
        "schema_version": "graph-method-selection/v1",
        "branches": [{"target": "quadratic-inequality-solve"}],
    }))
    monkeypatch.setattr(execution_contracts, "DATA", tmp_path)
    with pytest.raises(ValueError, match="execution\\.missing_boundary_step:quadratic-inequality-solve"):
        execution_contracts.load_contracts()
