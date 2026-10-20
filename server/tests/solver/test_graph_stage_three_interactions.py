"""Step interactions compiled from frozen exact seeds.

The Q13 gold runs the real recording offline and compiles the seeds actually
committed with each card; unit cases build seeds from the real capabilities.
"""

from copy import deepcopy

import pytest
import sympy as sp
from jsonschema import ValidationError

from shuxueshuo_server.graph_lesson.stage_three import goals, interaction, runner
from shuxueshuo_server.graph_lesson.stage_three.capabilities import (
    select_quantifier_policy,
)
from shuxueshuo_server.graph_lesson.stage_three.capabilities.parametric import (
    partition_interval_cases,
)
from shuxueshuo_server.graph_lesson.stage_three.context import build_context
from shuxueshuo_server.graph_lesson.stage_three.presentation import (
    append_goal_finalization,
    record_seed,
)
from shuxueshuo_server.graph_lesson.stage_three.trajectory import encode_value
from tests.solver.graph_stage_three_faults import offline_dispatch
from tests.solver.test_graph_stage_three_batch_six import _source
from tests.solver.test_graph_stage_three_execution import store
from tests.solver.test_graph_stage_three_goal_presentation import state_with_boundary
from tests.solver.test_graph_stage_three_recorded import (
    forbid_live_providers_and_network,  # noqa: F401 — shared autouse fixture
)

x, a = sp.Symbol("x", real=True), sp.Symbol("a", real=True)
TARGET = "/root/goals/0"


@pytest.fixture(scope="module")
def registry():
    return interaction.load_registry()


@pytest.fixture(scope="module")
def q13(tmp_path_factory):
    directory = tmp_path_factory.mktemp("interactions") / "q13"
    source, _, _ = _source(directory)
    output = directory / "stage-three"
    result = runner.run_sample(source, output, hooks={"calculation_dispatch": offline_dispatch})
    assert result["status"] == "completed"
    durable = store(output)
    cards = {}
    for card in durable.export()["math_steps"]:
        cards.setdefault(card["route_id"], []).append(card)
    seeds = {route: durable.checkpoint(TARGET, route)["driver_state"]["interaction_seeds"] for route in cards}
    return {"cards": cards, "seeds": seeds}


def _compiled(q13, registry, route):
    results, pending = interaction.compile_route(q13["seeds"][route], registry)
    assert pending == []
    for chunk, _ in results:
        interaction.validate_chunk(chunk)
    return results


def _labels(part):
    return [option["label"] for option in part["interaction"]["options"]]


def _correct(part):
    expected = part["expected_answer"]["one_of"]
    return [option["label"] for option in part["interaction"]["options"] if option["value"] in expected]


def _diagnostic(diagnostics, generator, text=None):
    return [row for row in diagnostics if row.get("generator") == generator
            and (text is None or text in row["label"])]


# --- Rules --------------------------------------------------------------------------

def test_registry_validates_and_rejects_unknown_or_ambiguous_rules(registry):
    assert interaction.registry_revision(registry) == interaction.registry_revision(deepcopy(registry))
    broken = deepcopy(registry)
    broken["templates"]["policy"]["parts"][0]["distractors"].append({"generator": "made_up"})
    with pytest.raises(ValueError, match="generator_not_allowed"):
        interaction.validate_registry(broken)
    broken = deepcopy(registry)
    broken["generators"].append("made_up")
    with pytest.raises(ValueError, match="unimplemented_generator"):
        interaction.validate_registry(broken)
    broken = deepcopy(registry)
    broken["templates"]["policy"]["parts"][0]["distractors"].append({"generator": "drop_piece"})
    with pytest.raises(ValueError, match="generator_not_allowed"):
        interaction.validate_registry(broken)
    broken = deepcopy(registry)
    broken["merges"].append({**deepcopy(broken["merges"][0]), "id": "duplicate"})
    with pytest.raises(ValueError, match="ambiguous_merge"):
        interaction.validate_registry(broken)
    broken = deepcopy(registry)
    broken["templates"]["policy"]["repeat"] = "sometimes"
    with pytest.raises(ValidationError):
        interaction.validate_registry(broken)


def test_overrides_and_merge_rows_are_checked_as_complete_rules(registry):
    broken = deepcopy(registry)
    broken["overrides"]["method-separation#quantifier"]["policy"]["parts"][0]["title"] = 17
    with pytest.raises(ValidationError):
        interaction.validate_registry(broken)
    broken = deepcopy(registry)
    broken["merges"][0]["parts"][0]["rows"][1]["seed"] = 2
    with pytest.raises(ValueError, match="seed_index_out_of_range"):
        interaction.validate_registry(broken)
    broken = deepcopy(registry)
    broken["templates"]["boundary_only"] = {"repeat": "always", "parts": deepcopy(registry["merges"][0]["parts"])}
    with pytest.raises(ValueError, match="seed_index_out_of_range"):
        interaction.validate_registry(broken)


def test_interaction_code_and_rules_stay_out_of_the_mathematical_fingerprint():
    paths = runner.fingerprint()
    assert not any(path.endswith("stage_three/interaction.py") or "interactions/" in path
                   or "interaction" in path.rsplit("/", 1)[-1] for path in paths)
    assert any(path.endswith("stage_three/presentation.py") for path in paths)
    assert len(interaction.engine_revision()) == 64


def test_override_replaces_fields_for_one_method_step(registry):
    seed = {"template": "policy", "method_ref": "method-separation#quantifier", "display_unit": "policy"}
    rule = interaction.select_rule(registry, [seed])
    names = [row["generator"] for row in rule["parts"][0]["distractors"]]
    assert "flip_direction" in names and "endpoint_only" not in names
    assert rule["parts"][0]["question"] == registry["templates"]["policy"]["parts"][0]["question"]
    default = interaction.select_rule(registry, [{**seed, "method_ref": "method-interval-extremum#quantifier"}])
    assert default == registry["templates"]["policy"]


# --- Q13 gold ---------------------------------------------------------------------

def test_every_card_freezes_a_seed_bound_to_its_final_hash(q13):
    for route, cards in q13["cards"].items():
        seeds = q13["seeds"][route]
        assert [seed["step_id"] for seed in seeds] == [card["step_id"] for card in cards]
        assert [seed["math_step_sha256"] for seed in seeds] == [card["math_step_sha256"] for card in cards]
        assert all(seed["status"] == "ready" and seed["contract"] == "graph-interaction-seed/v1" for seed in seeds)
        assert [seed["display_unit"] for seed in seeds[-2:]] == ["boundary", "goal_finalization"]
        assert seeds[-1]["template"] == "goal_minimum"
        assert all(seed["constraint_context"]["goal_ast"]["kind"] == "find_minimum" for seed in seeds)


def test_q13_interval_route_matches_the_designed_table(q13, registry):
    results = _compiled(q13, registry, "interval")
    chunks = [chunk for chunk, _ in results]
    assert [len(chunk["steps"]) for chunk in chunks] == [1] * 9 + [2]
    assert [chunk["status"] for chunk in chunks] == [
        "interactive", "interactive", "interactive", "interactive", "readonly", "readonly",
        "interactive", "readonly", "interactive", "interactive"]
    assert {chunks[index]["reason"] for index in (4, 5, 7)} == {"repeat"}

    policy, diagnostics = results[0]
    part, = policy["parts"]
    assert part["interaction"]["type"] == "choice" and len(part["interaction"]["options"]) == 3
    assert _correct(part) == [r"$a x + x^{2} + 1$ 在 $\left(0, \frac{1}{2}\right]$ 上的下确界 $\geq 0$"]
    assert any("上确界" in label for label in _labels(part))
    assert any("最小值存在" in label for label in _labels(part))
    assert _diagnostic(diagnostics, "swap_bound")[0]["result"] == "witness"
    assert _diagnostic(diagnostics, "require_attained")[0] == {**_diagnostic(diagnostics, "require_attained")[0],
                                                               "result": "witness", "witness": "1"}
    assert _diagnostic(diagnostics, "swap_quantifier")[0]["result"] == "duplicate"
    assert _diagnostic(diagnostics, "endpoint_only")[0]["result"] == "unproven"
    assert _diagnostic(diagnostics, "flip_strictness")[0]["result"] == "unproven"

    cases, diagnostics = results[1]
    basis, breakpoints = cases["parts"]
    assert "对称轴" in _correct(basis)[0]
    assert {label for label in _labels(basis)} - set(_correct(basis)) == {
        r"判别式 $\Delta=a^{2} - 4$ 的正负", "参数 $a$ 的正负"}
    sign_feedback = next(option["feedback"] for option in basis["interaction"]["options"]
                         if option["label"] == "参数 $a$ 的正负")
    assert "$0$" in sign_feedback and "$-1$" in sign_feedback
    fill = breakpoints["interaction"]
    assert fill["type"] == "fill"
    assert [fill["term_labels"][term] for term in fill["terms"]] == [
        "$-1$", r"$- \frac{1}{2}$", "$0$", r"$\frac{1}{2}$"]
    assert [fill["term_labels"][term] for term in breakpoints["expected_answer"]["terms"]] == ["$-1$", "$0$"]

    first_range = chunks[2]["parts"][0]
    assert _correct(first_range) == [r"在右端点 $x=\frac{1}{2}$ 处取到"]
    assert set(_labels(first_range)) == {r"在右端点 $x=\frac{1}{2}$ 处取到", r"在顶点 $x=- \frac{a}{2}$ 处取到",
                                         r"当 $x\to 0^{+}$ 时趋近，取不到"}
    unattained = chunks[6]["parts"][0]
    assert _correct(unattained) == [r"当 $x\to 0^{+}$ 时趋近，取不到"]
    assert "在左端点 $x=0$ 处取到" in _labels(unattained)

    conditions = chunks[3]["parts"][0]
    assert _correct(conditions) == [r"$\left[- \frac{5}{2}, -1\right]$"]
    assert {r"$\left[- \frac{5}{2}, \infty\right)$", r"$\left(-\infty, -1\right]$",
            r"$\left(- \frac{5}{2}, -1\right]$"} <= set(_labels(conditions))

    merged = chunks[8]["parts"][0]
    assert _correct(merged) == [r"$\left[- \frac{5}{2}, \infty\right)$"]
    assert len(merged["interaction"]["options"]) == 4

    closing = chunks[9]
    assert [step["step_id"] for step in closing["steps"]] == [
        card["step_id"] for card in q13["cards"]["interval"][-2:]]
    checklist = closing["parts"][0]
    assert checklist["interaction"]["type"] == "checklist"
    keep, minimum = checklist["interaction"]["slots"]
    chosen = dict(zip(("keep", "minimum"), checklist["expected_answer"]["terms"], strict=True))
    assert next(o["label"] for o in keep["options"] if o["value"] == chosen["keep"]).startswith("成立，保留")
    assert next(o["label"] for o in minimum["options"] if o["value"] == chosen["minimum"]) == r"$- \frac{5}{2}$"
    assert "不存在" in [option["label"] for option in minimum["options"]]


def test_q13_separation_route_merges_boundary_and_goal(q13, registry):
    chunks = [chunk for chunk, _ in _compiled(q13, registry, "extremum")]
    assert [len(chunk["steps"]) for chunk in chunks] == [1, 1, 1, 1, 2]
    assert chunks[1]["status"] == "interactive"
    assert "上确界" in _correct(chunks[1]["parts"][0])[0]
    assert chunks[-1]["status"] == "interactive"
    assert chunks[-1]["parts"][0]["interaction"]["type"] == "checklist"


def test_first_card_compiles_from_its_own_seed_only(q13, registry):
    seeds = q13["seeds"]["interval"]
    alone, = interaction.compile_route(seeds[:1], registry, final=False)[0]
    route = interaction.compile_route(seeds, registry)[0][0]
    assert alone == route
    values = interaction.decode_value(seeds[0]["values"])
    assert not any(isinstance(value, sp.Set) for value in values.values())


def test_known_conditions_restrict_witnesses_and_set_comparisons(q13, registry):
    known = _known("∀x∈(0,1/2]:x^2+a*x+1>=0", "a>=0")
    seeds = [{**seed, "constraint_context": known} for seed in q13["seeds"]["interval"]]
    results = interaction.compile_route(seeds, registry)[0]
    diagnostics = results[0][1]
    assert _diagnostic(diagnostics, "swap_bound")[0]["result"] != "witness"
    witnesses = [row["witness"] for row in diagnostics if row.get("result") == "witness"]
    assert witnesses and not any(witness.startswith("-") for witness in witnesses)
    # Case a<=-1 lies outside a>=0: these candidates agree with [-5/2,-1] on every allowed value.
    conditions, records = results[3]
    assert conditions["status"] == "readonly"
    assert {row["result"] for row in records if row.get("generator") in ("case_only", "flip_endpoint")} == {"unproven"}
    assert _diagnostic(records, "skip_intersection")[0]["result"] == "witness"

    unknown = [{**seed, "constraint_context": None} for seed in q13["seeds"]["interval"][:1]]
    chunk, _ = interaction.compile_route(unknown, registry)[0][0]
    assert chunk["status"] == "readonly" and chunk["reason"] == "known_conditions_unknown"


def _policy_seed(function, domain, quantifier, operator):
    policy = select_quantifier_policy(quantifier, operator, domain)["outputs"]["policy"]
    values = {"before": [function], "after": [], "function": function, "parameter_expression": sp.S.Zero,
              "policy": policy, "has_case": False, "x": x}
    return _seed("policy", values, {"x": x, "domain": domain, "parameter": a, "quantifier": quantifier},
                 method="method-interval-extremum#quantifier")


def test_strict_relation_distractors_are_checked_as_displayed(registry):
    # ∀x∈(0,1): ax²>0, i.e. 0 < f with an infimum that is never attained.
    seed = _policy_seed(a * x**2, sp.Interval.open(0, 1), "∀", "<")
    chunk, diagnostics = interaction.build_chunk([seed], registry, {"previous": 0})
    swap, = _diagnostic(diagnostics, "swap_bound")
    assert swap["result"] != "witness"
    assert not any("上确界" in label for part in chunk["parts"] for label in _labels(part))
    strictness, = _diagnostic(diagnostics, "flip_strictness")
    assert strictness == {**strictness, "result": "witness", "witness": "0"}


def test_existential_policy_is_readonly_until_its_wording_exists(registry):
    seed = _policy_seed(x**2 + a, sp.Interval.open(0, 2), "∃", "<=")
    chunk, _ = interaction.build_chunk([seed], registry, {"previous": 0})
    assert chunk["status"] == "readonly" and chunk["reason"] == "quantifier_unsupported"


def test_compilation_is_stable_and_identity_tracks_the_rules(q13, registry):
    first = _compiled(q13, registry, "interval")
    assert first == _compiled(q13, registry, "interval")
    changed = deepcopy(registry)
    changed["templates"]["policy"]["parts"][0]["title"] = "换一个标题"
    revised = interaction.compile_route(q13["seeds"]["interval"], changed)[0]
    assert revised[0][0]["interaction_id"] != first[0][0]["interaction_id"]
    assert revised[1][0]["interaction_revision"] != first[1][0]["interaction_revision"]


# --- Unit cases built from the real capabilities -----------------------------------

POLICY = {"bound": "inf", "strict": False, "quantifier": "∀", "operator": "<="}


def _known(*facts):
    """The route context of a problem with these facts, as frozen in real seeds."""
    candidate = {"original_text": " ".join(facts),
                 "root": {"facts": list(facts), "goals": [{"kind": "find_range", "symbol": "a"}]}}
    return build_context(candidate, TARGET)


FREE = _known("∀x∈ℝ:x^2+a^2+1>=0")


def _seed(template, values, context, *, ordinal=1, unit=None, case_path=(), method="method-interval-extremum#select",
          known=FREE):
    return {"contract": "graph-interaction-seed/v1", "run_id": "run", "lesson_version": "lesson",
            "target_ref": TARGET, "route_id": "interval", "step_id": f"step-{ordinal:03d}-{unit or template}",
            "math_step_sha256": f"{ordinal:064x}", "ordinal": ordinal, "display_unit": unit or template,
            "method_ref": method, "case_path": list(case_path), "template": template, "status": "ready",
            "values": encode_value(values), "context": encode_value(context), "constraint_context": known}


def _cases(function, domain):
    return partition_interval_cases(function, x, a, domain, POLICY)["outputs"]["cases"]


def test_discriminant_is_not_called_wrong_when_it_is_a_sufficient_basis(registry):
    function, domain = (x + a)**2 - a, sp.Interval(0, sp.oo)
    cases = _cases(function, domain)
    seed = _seed("interval_cases", {"before": [function], "after": [], "cases": cases, "parameter": a},
                 {"x": x, "domain": domain, "parameter": a})
    chunk, diagnostics = interaction.build_chunk([seed], registry, {"previous": 0})
    discriminant, = _diagnostic(diagnostics, "case_basis_alternatives", "判别式")
    assert discriminant["result"] == "unproven"
    assert not any("判别式" in label for part in chunk["parts"] for label in _labels(part)
                   if part["interaction"]["type"] == "choice")


def _tie_seed():
    function, domain = -x**2 + x + a, sp.Interval(0, 1)
    case, = _cases(function, domain)
    assert case["range"]["candidates"][0]["location"] == "left_endpoint"
    values = {"before": [function], "after": [], "range": case["range"], "condition": case["condition"],
              "vertex": case["vertex"], "coefficient": case["coefficient"], "x": x, "domain": domain,
              "bound_value": case["range"]["inf"], "bound_attained": True, "case": case}
    return _seed("classified_range", values, {"x": x, "domain": domain, "parameter": a})


def test_tied_bound_positions_never_offer_a_correct_position_as_wrong(registry):
    seed = _tie_seed()
    chunk, diagnostics = interaction.build_chunk([seed], registry, {"previous": 0})
    right, = _diagnostic(diagnostics, "location_alternatives", "右端点")
    assert right["result"] == "also_correct"
    vertex, = _diagnostic(diagnostics, "location_alternatives", "顶点")
    assert vertex["result"] == "witness"
    assert not any("右端点" in label for part in chunk["parts"] for label in _labels(part))

    rule = deepcopy(registry["templates"]["classified_range"])
    rule["parts"][0]["component"] = "multi"
    compiled = interaction.compile_interaction([seed], rule, {"previous": 0}, interaction_id="0" * 24)
    part, = compiled["parts"]
    options = {option["value"]: option["label"] for option in part["interaction"]["options"]}
    required = {options[value] for value in part["expected_answer"]["required"]}
    assert required == {"在左端点 $x=0$ 处取到", "在右端点 $x=1$ 处取到"}


def test_insufficient_options_and_repeat_fall_back_to_readonly(registry):
    seed = _tie_seed()
    chunk, _ = interaction.build_chunk([seed], registry, {"previous": 0})
    assert chunk["status"] == "readonly" and chunk["reason"] == "insufficient_options" and chunk["parts"] == []
    chunk, _ = interaction.build_chunk([seed], registry, {"previous": 1})
    assert chunk["reason"] == "repeat"
    missing = {**seed, "status": "missing", "reason": "seed_encode_failed"}
    chunk, _ = interaction.build_chunk([missing], registry, {"previous": 0})
    assert chunk["reason"] == "seed_encode_failed"
    chunk, _ = interaction.build_chunk([{**seed, "template": "unknown"}], registry, {"previous": 0})
    assert chunk["reason"] == "no_rule"
    for result in (chunk,):
        interaction.validate_chunk(result)


def test_compiler_errors_become_readonly_results(registry):
    seed = _tie_seed()
    broken = {**seed, "values": encode_value({"before": [x]})}
    chunk, diagnostics = interaction.build_chunk([broken], registry, {"previous": 0})
    assert chunk["status"] == "readonly" and chunk["reason"] == "compile_error"
    assert diagnostics[0]["result"] == "compile_error"


def test_representatives_use_only_seed_data_and_include_set_endpoints():
    values = {"after": [sp.Interval(-sp.Rational(5, 2), sp.oo)], "x": x}
    points = interaction.representatives(values, {"domain": sp.Interval.Lopen(0, sp.Rational(1, 2))})
    assert -sp.Rational(5, 2) in points and len(points) <= interaction.MAX_REPRESENTATIVES
    restricted = interaction.representatives(values, {}, sp.Interval(-sp.oo, -1))
    assert all(point <= -1 for point in restricted)


# --- Merge planning ---------------------------------------------------------------

def _closing_pair():
    boundary = _seed("boundary", {"feasible_set": sp.Interval(-1, sp.oo),
                                  "checks": [{"point": sp.Integer(-1), "included": True, "holds": True}]},
                     {"parameter": a}, ordinal=4)
    goal = _seed("goal_minimum", {"goal_kind": "find_minimum", "status": "attained", "bound": sp.Integer(-1),
                                  "feasible_set": sp.Interval(-1, sp.oo), "attained": True},
                 {"parameter": a}, ordinal=5, unit="goal_finalization")
    return boundary, goal


def test_merge_prefix_waits_for_its_follower_until_the_route_ends(registry):
    boundary, goal = _closing_pair()
    groups, pending = interaction.plan_groups([boundary], registry, final=False)
    assert groups == [] and pending == [boundary]
    groups, pending = interaction.plan_groups([boundary], registry, final=True)
    assert groups == [[boundary]] and pending == []
    groups, _ = interaction.plan_groups([boundary, goal], registry, final=False)
    assert groups == [[boundary, goal]]
    other_case = {**goal, "case_path": ["case-1"]}
    assert interaction.plan_groups([boundary, other_case], registry, final=True)[0] == [[boundary], [other_case]]
    readonly_follower = {**goal, "status": "missing", "reason": "seed_encode_failed"}
    assert interaction.plan_groups([boundary, readonly_follower], registry, final=True)[0] == [
        [boundary], [readonly_follower]]
    chunk, _ = interaction.build_chunk([boundary, goal], registry, {"previous": 0})
    assert chunk["status"] == "interactive"
    assert [step["step_id"] for step in chunk["steps"]] == [boundary["step_id"], goal["step_id"]]


# --- Seed entry points -------------------------------------------------------------

def test_goal_seed_is_frozen_after_exact_values_change_the_hash():
    feasible = sp.Interval(-sp.Rational(5, 2), sp.oo)
    state = state_with_boundary(feasible)
    boundary_seed, = state["interaction_seeds"]
    assert boundary_seed["display_unit"] == "boundary"
    assert boundary_seed["math_step_sha256"] == state["fragments"][-1]["math_step_sha256"]
    answer = goals.finalize_goal({"kind": "find_minimum"}, feasible)
    evidence = goals.verify_goal_answer({"kind": "find_minimum"}, feasible, answer)
    updated = append_goal_finalization(state, answer, evidence)
    seed = updated["interaction_seeds"][-1]
    assert seed["display_unit"] == "goal_finalization" and seed["template"] == "goal_minimum"
    assert seed["math_step_sha256"] == updated["fragments"][-1]["math_step_sha256"]
    assert interaction.decode_value(seed["values"])["bound"] == -sp.Rational(5, 2)


def test_unencodable_seed_is_recorded_missing_without_touching_the_card():
    state = state_with_boundary(sp.Interval(0, 1))
    card = deepcopy(state["fragments"][-1])
    seed = record_seed(state, card, template="boundary", values={"value": sp.Lambda(x, x)})
    assert seed["status"] == "missing" and seed["reason"] == "seed_encode_failed"
    assert "values" not in seed and state["fragments"][-1] == card
