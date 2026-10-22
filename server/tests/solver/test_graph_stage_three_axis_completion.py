"""Parameter-linked explorers survive compilation in stems and completed cases."""

from copy import deepcopy

import pytest
import sympy as sp
from jsonschema import ValidationError

from shuxueshuo_server.graph_lesson.stage_three import interaction
from shuxueshuo_server.graph_lesson.stage_three import (
    interaction_graph_contract as contract,
)
from tests.solver.test_graph_stage_three_interactions import _cases, _known, _seed, a, x


@pytest.fixture(scope="module")
def compiled():
    function, domain = x**2-a*x-a+15, sp.Interval(1, 4)
    cases = _cases(function, domain)
    seed = _seed(
        "interval_cases", {"before": [function], "after": [], "cases": cases, "parameter": a},
        {"x": x, "domain": domain, "parameter": a},
        known=_known("∃x∈[1,4]:x^2-a*x-a+15<=0"),
    )
    chunk, diagnostics = interaction.build_chunk([seed], interaction.load_registry(), {"previous": 0})
    assert chunk["status"] == "interactive", diagnostics
    interaction.validate_chunk(chunk)
    return chunk, diagnostics, cases


def test_parameter_dependent_constant_has_stem_and_all_completed_case_graphs(compiled):
    chunk, diagnostics, cases = compiled
    assert not any(row.get("result") == "graph_fallback" for row in diagnostics)
    basis, locations = chunk["parts"]
    assert basis["graph"] == locations["graph"]
    assert basis["graph"]["kind"] == "axis_explorer"
    graphs = locations["completion_graphs"]
    assert len(graphs) == len(cases) == 3
    assert len({tuple(graph["params"]["bounds"]) for graph in graphs}) == 1
    for graph, case in zip(graphs, cases, strict=True):
        contract.validate_graph(graph)
        params = graph["params"]
        assert params["constant"] == 15
        assert params["constant_by_axis"] == {"linear": -2, "quadratic": 0}
        assert params["parameter"] == {"name": "a", "scale": 2, "offset": 0}
        axis = params["axis"]
        # Every slider value belongs to this case, including the initial value;
        # linear parameter mapping and convex case intervals cover the interior.
        for h in (axis["min"], axis["value"], axis["max"]):
            value = 2*sp.Rational(str(h))
            assert case["domain"].contains(value) is sp.true
        assert graph["caption"].startswith("情况")


@pytest.mark.parametrize("field,value", [
    ("constant_by_axis", {"linear": 1}),
    ("constant_by_axis", {"linear": 1, "quadratic": "2"}),
    ("constant_by_axis", {"linear": 1, "quadratic": 2, "expression": "eval()"}),
    ("parameter", {"name": "", "scale": 2, "offset": 0}),
    ("parameter", {"name": "a", "scale": 0, "offset": 0}),
    ("parameter", {"name": "a", "scale": 2}),
    ("parameter", {"name": "a", "scale": 2, "offset": 0, "expression": "eval()"}),
])
def test_new_graph_fields_reject_malformed_payloads(compiled, field, value):
    graph = deepcopy(compiled[0]["parts"][0]["graph"])
    graph["params"][field] = value
    with pytest.raises(ValidationError):
        contract.validate_graph(graph)


@pytest.mark.parametrize("field,key", [("constant_by_axis", "linear"), ("parameter", "offset")])
def test_new_graph_fields_reject_nonfinite_coefficients(compiled, field, key):
    graph = deepcopy(compiled[0]["parts"][0]["graph"])
    graph["params"][field][key] = float("inf")
    with pytest.raises(ValueError, match="interaction.graph_nonfinite"):
        contract.validate_graph(graph)


def test_legacy_constant_only_explorer_remains_valid(compiled):
    graph = deepcopy(compiled[0]["parts"][0]["graph"])
    graph["params"].pop("constant_by_axis")
    graph["params"].pop("parameter")
    assert contract.validate_graph(graph) is graph
