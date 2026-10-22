"""Affine range cards keep the new variable separate from original problem scope."""

from copy import deepcopy

import pytest
import sympy as sp
from jsonschema import ValidationError

from shuxueshuo_server.graph_lesson.stage_three import execution_contracts, interaction
from shuxueshuo_server.graph_lesson.stage_three.capabilities.ranges import (
    reciprocal_range,
)
from shuxueshuo_server.graph_lesson.stage_three.presentation import record_seed
from shuxueshuo_server.graph_lesson.stage_three.presentation_templates import (
    prepare_values,
)
from shuxueshuo_server.graph_lesson.stage_three.trajectory import (
    decode_value,
    encode_value,
)
from tests.solver.test_graph_stage_three_interactions import _known, _seed

x, t, a = sp.symbols("x t a", real=True)


@pytest.mark.parametrize("domain,answer,side", [
    (sp.Interval(3, 5), sp.Interval(sp.Rational(16, 3), sp.Rational(34, 5)), "右侧"),
    (sp.Interval(-3, -1), sp.Interval(-4, -3), "两侧都有"),
])
def test_affine_hook_seed_keeps_original_scope_but_uses_new_variable(domain, answer, side):
    function = t + 4 / t + 1
    outputs = reciprocal_range(function, t, domain)["outputs"]
    assert outputs["range"]["set"] == answer
    specification = execution_contracts.read("presentation-registry")["templates"]["hook_range"]
    values = prepare_values(specification, {
        "before": [function], "after": [answer], "range": outputs["range"],
        "domain": domain, "function": function, "x": t,
        "turn": outputs["turning_point"], "endpoints": outputs["endpoint_values"],
        "function_name": "",
    })
    original = {"x": x, "domain": sp.Interval(0, 1), "parameter": a}
    constraints = _known("a>=0", "∀x∈[0,1]:(x+1)*a>=x^2+4")
    source = _seed("hook_range", values, original, known=constraints,
                   method="method-separation#range")
    state = {key: source[key] for key in ("run_id", "lesson_version", "target_ref", "route_id")}
    state.update(input_values=encode_value(original), trajectory={"constraint_context": constraints})
    seed = record_seed(state, source, template="hook_range", values=values)
    assert decode_value(seed["context"]) == original
    assert seed["constraint_context"] == constraints
    assert decode_value(seed["values"])["x"] == t
    assert interaction.known_set(seed) == sp.Interval(0, sp.oo)

    chunk, diagnostics = interaction.build_chunk([seed], interaction.load_registry(), {"previous": 0})
    assert chunk["status"] == "interactive", diagnostics
    interaction.validate_chunk(chunk)
    shape, placement = chunk["parts"]
    assert "t" in shape["question"] and "h(" not in shape["question"]
    assert "$t=" in placement["question"] and "$x=" not in placement["question"]
    expected = set(placement["expected_answer"]["terms"])
    answers = [next(option["label"] for option in slot["options"] if option["value"] in expected)
               for slot in placement["interaction"]["slots"]]
    assert answers == [side, "$" + sp.latex(answer) + "$"]
    for graph in (shape["graph"], placement["graph"], placement["completion_graph"]):
        assert graph["kind"] == "reciprocal_sum"
        assert graph["params"]["variable"] == "t"
    assert placement["graph"]["params"]["interval"] == [float(domain.start), float(domain.end)]
    assert not any(row.get("result") in {"graph_fallback", "compile_error", "readonly"} for row in diagnostics)


@pytest.mark.parametrize("template", ["affine_substitution", "affine_restore"])
def test_affine_transition_templates_are_explicit_readonly(template):
    registry = interaction.load_registry()
    assert registry["templates"][template] == {"repeat": "never", "parts": []}
    seed = _seed(template, {}, {"x": x, "domain": sp.Interval(0, 1), "parameter": a},
                 method="method-separation#range")
    chunk, diagnostics = interaction.build_chunk([seed], registry, {"previous": 0})
    assert chunk["status"] == "readonly" and chunk["reason"] == "repeat"
    assert chunk["parts"] == [] and diagnostics == []
    interaction.validate_chunk(chunk)


@pytest.mark.parametrize("repeat", ["first", "always", {"first_or": {"binding": "mode", "equals": "all"}}])
def test_active_rules_still_require_at_least_one_part(repeat):
    registry = deepcopy(interaction.load_registry())
    registry["templates"]["affine_substitution"]["repeat"] = repeat
    with pytest.raises(ValidationError):
        interaction.validate_registry(registry)
