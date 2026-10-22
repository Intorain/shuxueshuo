"""Graphs are optional presentation data; malformed output never blocks text."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
import sympy as sp
from jsonschema import ValidationError

from shuxueshuo_server.graph_lesson.stage_three import interaction
from shuxueshuo_server.graph_lesson.stage_three import (
    interaction_graph_contract as contract,
)
from shuxueshuo_server.graph_lesson.stage_three import interaction_graphs as drawing
from tests.solver.test_graph_stage_three_interaction_commit import _pending
from tests.solver.test_graph_stage_three_interactions import _policy_seed, a, x

DEFAULT_DOMAIN = sp.Interval.Lopen(0, 2)


def function_graph(expression=x**2 + 1, domain=DEFAULT_DOMAIN):
    drawn = drawing.family(expression, x)
    bounds, ticks = drawing.function_frame(drawn, x, domain)
    return drawing.function_graph(
        drawn, x, domain, bounds=bounds, x_ticks=ticks,
        marks=drawing.drawable(drawn, x, drawing.domain_points(domain)),
        title="函数图", description="端点及函数曲线",
    )


def number_line():
    return drawing.number_lines([sp.Interval(-sp.oo, -1) | sp.FiniteSet(2)], a, title="参数范围")[0]


def chunk_with(graph, location="graph"):
    identity = "a" * 24
    part = {
        "id": identity + "#1", "title": "问题", "question": "请选择", "submit_label": "确认",
        "feedback": {"answer": "请重试"}, "expected_answer": {"one_of": ["o1"]},
        "interaction": {"type": "choice", "field": "answer", "options": [
            {"value": "o1", "label": "正确"}, {"value": "o2", "label": "错误"},
        ]},
    }
    if location in ("graph", "completion_graph"):
        part[location] = graph
    elif location == "option":
        part["interaction"]["options"][0]["graph"] = graph
    else:
        part["interaction"] = {"type": "checklist", "title": "检查", "slots": [{
            "label": "边界", "options": [{"value": "o1", "label": "成立", "graph": graph},
                                         {"value": "o2", "label": "不成立"}],
        }]}
        part["expected_answer"] = {"terms": ["o1"]}
    chunk = {
        "contract": interaction.CONTRACT, "run_id": "run", "lesson_version": "lesson",
        "target_ref": "/root/goals/0", "route_id": "interval", "interaction_id": identity,
        "status": "interactive", "steps": [{"step_id": "first", "math_step_sha256": "b" * 64}],
        "interaction_revision": "c" * 64, "parts": [part],
    }
    chunk["interaction_sha256"] = interaction.chunk_sha256(chunk)
    return chunk


@pytest.mark.parametrize("build", [
    function_graph, lambda: function_graph(3 * x + 1), lambda: function_graph(sp.Integer(2)),
    lambda: function_graph(x + 1 / x), lambda: function_graph(x + 1 / x, sp.Interval.Ropen(-2, 0)),
    lambda: function_graph(x**2 + 1, sp.S.Reals), number_line,
    lambda: drawing.number_lines([sp.S.EmptySet], a, title="空集")[0],
    lambda: drawing.number_lines([sp.S.Reals], a, title="实数")[0],
    lambda: drawing.number_lines([sp.FiniteSet(0)], a, title="孤立点")[0],
])
def test_real_builder_shapes_are_accepted(build):
    graph = build()
    assert contract.validate_graph(graph) is graph
    assert interaction.validate_chunk(chunk_with(graph))["status"] == "interactive"


@pytest.mark.parametrize("mutate", [
    lambda p: p.pop("vertex"), lambda p: p.pop("coefficient"),
    lambda p: p.update(coefficient=True), lambda p: p.update(coefficient=0),
    lambda p: p.update(vertex=[1]), lambda p: p.update(vertex=[1, 2, 3]),
    lambda p: p.update(vertex=["1", 2]), lambda p: p.update(bounds=[0, 1]),
    lambda p: p.update(bounds=[0, 1, 0, 1, 2]), lambda p: p.update(bounds=[False, 1, 0, 1]),
    lambda p: p.update(interval=[0]), lambda p: p.update(interval_closed=[True]),
    lambda p: p.update(interval_closed=["false", True]),
    lambda p: p.update(points=[{"x": 0, "open": "true"}]), lambda p: p.update(points=[{"open": True}]),
    lambda p: p.update(xTicks=[[1, "1", 2]]), lambda p: p.update(xTicks=[[1, 1]]),
    lambda p: p.update(slope=1), lambda p: p.update(unknown=True), lambda p: p.update(title=None),
])
def test_shape_and_native_types_reject_malformed_external_graphs(mutate):
    graph = function_graph()
    mutate(graph["params"])
    with pytest.raises(ValidationError):
        interaction.validate_chunk(chunk_with(graph))


@pytest.mark.parametrize("mutate", [
    lambda p: p.update(bounds=[0, 0, 0, 1]), lambda p: p.update(bounds=[1, 0, 0, 1]),
    lambda p: p.update(bounds=[0, 1, 0, 0]), lambda p: p.update(bounds=[-1e308, 1e308, 0, 1]),
    lambda p: p.update(bounds=[0, float("inf"), 0, 1]),
    lambda p: p.update(vertex=[float("nan"), 0]), lambda p: p.update(coefficient=float("-inf")),
    lambda p: p.update(points=[{"x": float("inf")}]), lambda p: p.update(xTicks=[[float("nan"), "0"]]),
    lambda p: p.update(interval=[2, 1]),
    lambda p: p.update(interval=[None, 1], interval_closed=[True, True]),
    lambda p: p.update(coefficient=10**1000),
])
def test_nonfinite_and_invalid_ranges_are_rejected(mutate):
    graph = function_graph()
    mutate(graph["params"])
    with pytest.raises((ValidationError, ValueError)):
        interaction.validate_chunk(chunk_with(graph))


@pytest.mark.parametrize("location", ["graph", "completion_graph", "option", "checklist"])
def test_every_graph_location_checks_semantics(location):
    graph = function_graph()
    graph["params"]["bounds"] = [0, 0, 0, 1]
    with pytest.raises(ValueError, match="interaction.graph_invalid_bounds"):
        interaction.validate_chunk(chunk_with(graph, location))


@pytest.mark.parametrize("invalid", ["shape", "nonfinite", "bounds"])
def test_store_rejects_invalid_graph_without_advancing_pending_state(tmp_path, invalid):
    store, _, chunk = _pending(tmp_path)
    graph = function_graph()
    if invalid == "shape":
        graph["params"].pop("vertex")
    elif invalid == "nonfinite":
        graph["params"]["coefficient"] = float("inf")
    else:
        graph["params"]["bounds"] = [0, 0, 0, 1]
    chunk["parts"][0]["graph"] = graph
    chunk["interaction_sha256"] = interaction.chunk_sha256(chunk)
    before = store.snapshot()
    with pytest.raises((ValidationError, ValueError)):
        store.commit_interaction(chunk)
    assert store.snapshot() == before
    assert store.interaction(chunk["interaction_id"]) is None


@pytest.mark.parametrize(("build", "mutate"), [
    (lambda: function_graph(x + 1 / x), lambda p: p.pop("negative")),
    (lambda: function_graph(x + 1 / x), lambda p: p.update(b=0)),
    (lambda: function_graph(x + 1 / x), lambda p: p.update(a=False)),
    (lambda: function_graph(x), lambda p: p.pop("slope")),
    (lambda: function_graph(x), lambda p: p.update(intercept="0")),
    (number_line, lambda p: p.update(bounds=[0, 1, 0, 1])),
    (number_line, lambda p: p["pieces"][0].pop("left_closed")),
    (number_line, lambda p: p.update(points=[{"x": "0"}])),
    (number_line, lambda p: p.update(ticks=[[0]])),
])
def test_other_kinds_have_distinct_contracts(build, mutate):
    graph = build()
    mutate(graph["params"])
    with pytest.raises(ValidationError):
        contract.validate_graph(graph)


@pytest.mark.parametrize("piece", [
    {"from": 2, "to": 1, "left_closed": True, "right_closed": True},
    {"from": 1, "to": 1, "left_closed": True, "right_closed": True},
    {"from": None, "to": 1, "left_closed": True, "right_closed": True},
    {"from": 1, "to": None, "left_closed": True, "right_closed": True},
])
def test_number_line_piece_endpoints_and_closure_are_checked(piece):
    graph = number_line()
    graph["params"]["pieces"] = [piece]
    with pytest.raises(ValueError):
        contract.validate_graph(graph)


def test_reciprocal_graph_cannot_mark_a_point_at_its_pole():
    graph = function_graph(x + 1 / x)
    graph["params"]["points"] = [{"x": 0, "open": True}]
    with pytest.raises(ValueError, match="interaction.graph_undefined_point"):
        interaction.validate_chunk(chunk_with(graph))


def test_invalid_generated_stem_keeps_identical_text_question(monkeypatch):
    registry = deepcopy(interaction.load_registry())
    registry["templates"]["policy"]["parts"][0]["graphs"] = {"stem": "function_sample"}
    seed = _policy_seed(x*x + a*x + 1, sp.Interval.Lopen(0, sp.Rational(1, 2)), "∀", "<=")
    original, _ = interaction.build_chunk([seed], registry, {"previous": 0})
    assert original["status"] == "interactive" and "graph" in original["parts"][0]
    bad = function_graph()
    bad["params"].pop("vertex")
    monkeypatch.setitem(interaction.STEM_GRAPHS, "function_sample", ({"policy_statement"}, lambda *_: bad))
    actual, diagnostics = interaction.build_chunk([seed], registry, {"previous": 0})
    expected = deepcopy(original)
    del expected["parts"][0]["graph"]
    expected["interaction_sha256"] = interaction.chunk_sha256(expected)
    assert actual == expected
    assert {"part": 1, "result": "graph_fallback", "reason": "invalid_graph"} in diagnostics
    interaction.validate_chunk(actual)


@pytest.mark.parametrize("fault", ["shape", "count", "note"])
def test_bad_option_graph_group_falls_back_as_a_unit(fault):
    good = function_graph()
    bad = deepcopy(good)
    bad["params"]["bounds"] = [0, 0, 0, 1]
    result = {"shape": ([good, bad], None), "count": ([good], None), "note": ([good, good], 42)}[fault]
    diagnostics = []
    assert interaction._picture(lambda: result, diagnostics, 1, option_count=2) is None
    assert diagnostics == [{"part": 1, "result": "graph_fallback", "reason": "invalid_graph"}]


def test_validator_cache_and_engine_revision_track_schema_changes(tmp_path, monkeypatch):
    schema = json.loads(contract.SCHEMA.read_text())
    local = tmp_path / "schema.json"
    local.write_text(json.dumps(schema))
    monkeypatch.setattr(contract, "SCHEMA", local)
    graph = function_graph()
    contract.validate_graph(graph)
    schema["$defs"]["graph"]["properties"]["kind"] = {"const": "linear"}
    local.write_text(json.dumps(schema))
    with pytest.raises(ValidationError):
        contract.validate_graph(graph)
    assert Path(contract.__file__).resolve() in interaction.ENGINE_FILES
    assert interaction.CHUNK_SCHEMA in interaction.ENGINE_FILES
