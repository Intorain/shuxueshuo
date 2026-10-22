"""Variable-role, affine envelope and standalone closing interactions."""

from copy import deepcopy

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_three import interaction
from shuxueshuo_server.graph_lesson.stage_three.capabilities import (
    select_quantifier_policy,
)
from shuxueshuo_server.graph_lesson.stage_three.capabilities.variable_swap import (
    parameter_linear_case_range,
    parameter_linear_range,
    variable_case_plan,
)
from shuxueshuo_server.graph_lesson.stage_three.math_values import latex
from tests.solver.test_graph_stage_three_batch_five import _finish_swap
from tests.solver.test_graph_stage_three_execution import simple
from tests.solver.test_graph_stage_three_interactions import _known, _seed

a, t = sp.symbols("a t", real=True)


@pytest.fixture(scope="module")
def registry():
    return interaction.load_registry()


def compile_seed(seed, registry):
    original = deepcopy(seed)
    chunk, diagnostics = interaction.build_chunk([seed], registry, {"previous": 0})
    assert seed == original
    interaction.validate_chunk(chunk)
    return chunk, diagnostics


def selected_rows(part):
    return [(row["label"], next(option["label"] for option in row["options"] if option["value"] == selected))
            for row, selected in zip(part["interaction"]["slots"], part["expected_answer"]["terms"], strict=True)]


def selected_options(part):
    return [option["label"] for option in part["interaction"]["options"]
            if option["value"] in part["expected_answer"]["one_of"]]


def range_seed(slope, domain, *, quantifier="∀", operator="<=", classified=False, sign=None):
    function = slope * t + a + 2
    policy = select_quantifier_policy(quantifier, operator, domain)["outputs"]["policy"]
    case = None
    if classified:
        plan = variable_case_plan(function, t, a, domain, policy)
        case = next(case for case in plan["cases"] if case["slope_sign"] == sign)
        computed = parameter_linear_case_range(function, t, a, domain, policy, case)["outputs"]
    else:
        computed = parameter_linear_range(function, t, a, domain, policy)["outputs"]
    values = {"before": [function], "after": [], "x": t, "parameter": a, "domain": domain,
              "slope": slope, **computed}
    if case:
        values["case"] = case
    return _seed("variable_case_range" if case else "variable_range", values,
                 {"x": t, "parameter": a, "domain": domain, "interval_function": function})


def test_roles_follow_quantifier_and_goal_symbols_instead_of_fixed_letters(registry):
    variable, parameter = sp.symbols("a x", real=True)
    seed = _seed("variable_roles", {"x": variable, "parameter": parameter, "domain": sp.Interval(-1, 1)},
                 {"x": variable, "parameter": parameter})
    chunk, _ = compile_seed(seed, registry)
    assert selected_rows(chunk["parts"][0]) == [("在题设区间内变化的字母", "$a$"),
                                                ("暂时固定、最后要求取值的字母", "$x$")]


def test_coefficient_rows_use_real_expressions_and_drop_equal_candidates(registry):
    seed = _seed("variable_reorder", {"before": [(a + 1) * t + a + 1], "after": [], "x": t,
                                     "slope": a + 1, "intercept": a + 1}, {"x": t, "parameter": a})
    chunk, diagnostics = compile_seed(seed, registry)
    assert [label for _, label in selected_rows(chunk["parts"][0])] == ["$a + 1$", "$a + 1$"]
    assert any(row.get("result") == "unproven" and row.get("label") == "$a + 1$" for row in diagnostics)
    for row in chunk["parts"][0]["interaction"]["slots"]:
        assert len({option["label"] for option in row["options"]}) == len(row["options"])


def test_coefficient_witnesses_respect_visible_conditions(registry):
    seed = _seed("variable_reorder", {"before": [a*t + 1], "after": [], "x": t,
                                     "slope": a, "intercept": sp.S.One}, {"x": t, "parameter": a},
                 known=_known("a=1", "∀x∈ℝ:x^2+a^2+1>=0"))
    _, diagnostics = compile_seed(seed, registry)
    assert any(row.get("label") == "$1$" and row.get("result") == "unproven" for row in diagnostics)
    assert all(row.get("witness") == "1" for row in diagnostics if row.get("result") == "witness")


@pytest.mark.parametrize("slope", [sp.S.One, -sp.S.One, sp.S.Zero, a*a-a])
@pytest.mark.parametrize("quantifier", ["∀", "∃"])
def test_affine_candidates_handle_positive_negative_zero_and_unknown_slopes(registry, slope, quantifier):
    seed = range_seed(slope, sp.Interval(-1, 2), quantifier=quantifier)
    chunk, _ = compile_seed(seed, registry)
    assert chunk["status"] == "interactive"
    attainment = next(part for part in chunk["parts"] if part["title"] == "判断候选值能否取得")
    assert all(label == "能在区间内取得" for _, label in selected_rows(attainment))
    assert attainment["completion_graph"]["kind"] == "linear"
    assert attainment["completion_graph"]["params"]["variable"] == "t"
    assert "固定 $a=" in attainment["completion_graph"]["caption"]


@pytest.mark.parametrize("slope", [sp.S.One, -sp.S.One])
def test_open_endpoint_attainment_is_not_claimed(registry, slope):
    chunk, _ = compile_seed(range_seed(slope, sp.Interval.open(-1, 2)), registry)
    attainment = chunk["parts"][-1]
    assert selected_rows(attainment)[0][1] == "只能趋近，不能取得"


@pytest.mark.parametrize("sign", ["negative", "zero", "positive"])
def test_classified_open_interval_uses_its_own_case_and_zero_is_attained(registry, sign):
    seed = range_seed(a, sp.Interval.open(-1, 1), classified=True, sign=sign)
    chunk, diagnostics = compile_seed(seed, registry)
    attainment = chunk["parts"][-1]
    assert selected_rows(attainment)[0][1] == ("能在区间内取得" if sign == "zero" else "只能趋近，不能取得")
    assert attainment["completion_graph"]["kind"] == "linear", diagnostics
    if sign == "zero":
        assert attainment["completion_graph"]["params"]["slope"] == 0


@pytest.mark.parametrize("combiner", ["all", "any"])
def test_condition_sets_respect_universal_intersection_and_existential_union(registry, combiner):
    first, second = sp.Interval.open(-1, 1), sp.Complement(sp.S.Reals, sp.FiniteSet(1))
    result = sp.Intersection(first, second) if combiner == "all" else sp.Union(first, second)
    seed = _seed("variable_conditions", {"after": [result], "conditions": [sp.Gt(1-a*a, 0), sp.Gt((a-1)**2, 0)],
                                        "solutions": [first, second], "combiner": combiner}, {"parameter": a})
    chunk, diagnostics = compile_seed(seed, registry)
    assert selected_options(chunk["parts"][0]) == [interaction._math(result)]
    assert any(row.get("generator") == "swap_combiner" and row.get("result") == "witness" for row in diagnostics)


def test_case_solution_candidates_are_compared_only_where_known_conditions_hold(registry):
    result = sp.Interval.open(-1, 1)
    seed = _seed("variable_case_conditions", {"after": [result], "conditions": [sp.Gt(1-a*a, 0)],
        "solutions": [result], "combiner": "all", "case": {"domain": sp.Interval(-2, 2), "condition": sp.And(a>=-2,a<=2)}},
        {"parameter": a}, known=_known("a=0", "∀x∈ℝ:x^2+a^2+1>=0"))
    chunk, diagnostics = compile_seed(seed, registry)
    assert chunk["status"] == "interactive"
    assert all(row["result"] != "witness" for row in diagnostics if row.get("generator") == "flip_endpoint")


def test_case_solution_does_not_call_an_equivalent_on_case_set_wrong(registry):
    seed = _seed("variable_case_conditions", {"after": [sp.Interval(0, 1)], "conditions": [sp.Le(a, 1)],
        "solutions": [sp.Interval(-sp.oo, 1)], "combiner": "all",
        "case": {"domain": sp.Interval(0, sp.oo), "condition": sp.Ge(a, 0)}}, {"parameter": a})
    chunk, diagnostics = compile_seed(seed, registry)
    assert chunk["status"] == "interactive"
    assert selected_options(chunk["parts"][0]) == [r"$\left[0, 1\right]$"]
    assert all(row["result"] == "unproven" for row in diagnostics if row.get("generator") == "skip_intersection")
    assert not any(option["label"] == r"$\left(-\infty, 1\right]$"
                   for option in chunk["parts"][0]["interaction"]["options"])


def test_variable_constant_cases_use_checked_slope_root_partition(registry):
    domain, function = sp.Interval.open(-1, 1), (a-1)**2*t + 2
    policy = select_quantifier_policy("∀", "<=", domain)["outputs"]["policy"]
    cases = variable_case_plan(function, t, a, domain, policy)["cases"]
    seed = _seed("variable_cases", {"cases": cases, "parameter": a, "slope": (a-1)**2},
                 {"x": t, "parameter": a, "domain": domain})
    chunk, _ = compile_seed(seed, registry)
    assert selected_options(chunk["parts"][0]) == [r"$\left\{1\right\}$"]


@pytest.mark.parametrize("kind", ["find_minimum", "find_maximum"])
@pytest.mark.parametrize("status,bound", [("attained", sp.Rational(3,2)), ("not_attained", sp.Rational(3,2)),
                                         ("empty_feasible_set", None), ("unbounded", None)])
def test_standalone_goals_cover_empty_unbounded_and_finite_closure(registry, kind, status, bound):
    if status == "unbounded":
        status = "unbounded_below" if kind == "find_minimum" else "unbounded_above"
    seed = _seed("goal_minimum" if kind == "find_minimum" else "goal_maximum",
                 {"goal_kind": kind, "status": status, "bound": bound, "feasible_set": sp.S.Reals}, {"parameter": a})
    chunk, _ = compile_seed(seed, registry)
    assert chunk["status"] == "interactive"
    row = chunk["parts"][0]["interaction"]["slots"][0]
    assert len({option["label"] for option in row["options"]}) == len(row["options"])
    label = selected_rows(chunk["parts"][0])[0][1]
    assert "None" not in label and "\\infty" not in label
    if status == "attained":
        assert r"$\frac{3}{2}$" in label and "能够取得" in label


def test_standalone_boundary_and_empty_boundary_are_explicit(registry):
    values = {"feasible_set": sp.Interval(0, 1), "checks": [{"point": sp.S.Zero, "holds": True},
                                                           {"point": sp.S.One, "holds": False}]}
    chunk, _ = compile_seed(_seed("boundary", values, {"parameter": a}), registry)
    assert [label for _, label in selected_rows(chunk["parts"][0])] == ["成立，保留 $0$", "不成立，排除 $1$"]
    values["checks"] = []
    chunk, _ = compile_seed(_seed("boundary", values, {"parameter": a}), registry)
    assert chunk["status"] == "readonly" and chunk["reason"] == "no_finite_boundaries"


@pytest.mark.parametrize("fact", [
    "∀m∈[1,3]:m*(x^2-x+1)-6<0",
    "∀a∈[-1,1]:a*x^2-(a+1)*x+1>0",
    "∃a∈[-1,1]:a*x^2-(a+1)*x+1>0",
])
def test_actual_affine_cards_compile_without_future_evidence(registry, fact):
    state = _finish_swap(simple(fact, symbol="x"))
    assert state["status"] == "method_complete"
    seeds = state["interaction_seeds"]
    results, pending = interaction.compile_route(seeds, registry)
    assert pending == []
    for seed, (chunk, diagnostics) in zip(seeds, results, strict=True):
        interaction.validate_chunk(chunk)
        if seed["template"] in ("variable_roles", "variable_reorder", "variable_range", "variable_conditions"):
            assert chunk["status"] == "interactive", (seed["template"], diagnostics)


def test_actual_open_interval_case_merge_unions_isolated_point_and_draws_it(registry):
    state = _finish_swap(simple("∀a∈(-1,1):a*x^2-(a+1)*x+1>0", symbol="x"))
    assert state["status"] == "method_complete"
    seed, = [seed for seed in state["interaction_seeds"] if seed["template"] == "variable_case_merge"]
    # Linear-case seeds deliberately have no quadratic result/axis presentation bindings.
    assert "results" not in interaction.decode_value(seed["values"])
    # The real driver produces [-1,0), {0}, (0,1), and two empty cases.
    # The union includes -1 and the isolated constant-case value 0, but not 1.
    chunk, diagnostics = compile_seed(seed, registry)
    part, = chunk["parts"]
    assert selected_options(part) == [r"$\left[-1, 1\right)$"]
    assert any(row.get("generator") == "intersect_cases" and row["result"] == "witness"
               and row["label"] == r"$\emptyset$" for row in diagnostics)
    assert any(row.get("generator") == "drop_piece" and row["result"] == "witness"
               and row["label"] == r"$\left[-1, 0\right) \cup \left(0, 1\right)$" for row in diagnostics)
    options = {option["label"]: option["graph"] for option in part["interaction"]["options"]}
    assert all(graph["kind"] == "number_line" and graph["params"]["variable"] == "x"
               for graph in options.values())
    assert options[r"$\left[-1, 1\right)$"]["params"]["pieces"] == [
        {"from": -1.0, "to": 1.0, "left_closed": True, "right_closed": False}]
    gap = options[r"$\left[-1, 0\right) \cup \left(0, 1\right)$"]["params"]["pieces"]
    assert gap[0]["to"] == gap[1]["from"] == 0.0
    assert gap[0]["right_closed"] is gap[1]["left_closed"] is False
    assert options[r"$\emptyset$"]["params"]["pieces"] == []


def test_actual_classified_affine_questions_include_their_frozen_case_condition(registry):
    state = _finish_swap(simple("∀a∈(-1,1):a*x^2-(a+1)*x+1>0", symbol="x"))
    assert state["status"] == "method_complete"
    seeds = [seed for seed in state["interaction_seeds"] if seed["template"] == "variable_case_range"]
    assert len(seeds) == 5
    questions = []
    for seed in seeds:
        # Compile each real frozen card by itself: the question must not rely on
        # earlier/later cards, or on the mathematical explanation shown after answering.
        values = interaction.decode_value(seed["values"])
        chunk, diagnostics = compile_seed(seed, registry)
        assert chunk["status"] == "interactive", diagnostics
        condition = f"${latex(values['case']['condition'])}$"
        assert all(condition in part["question"] for part in chunk["parts"])
        questions.extend(part["question"] for part in chunk["parts"])
    assert any("$0 < x < 1$" in question for question in questions)

    first, _ = compile_seed(seeds[0], registry)
    assert [part["title"] for part in first["parts"]] == ["计算候选值", "判断候选值能否取得"]
    assert all("$x < 0$" in part["question"] for part in first["parts"])
    assert selected_rows(first["parts"][1]) == [("候选位置 $a=-1$", "只能趋近，不能取得")]
