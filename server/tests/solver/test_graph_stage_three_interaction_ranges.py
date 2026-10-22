"""Range questions retain only mathematically different, scoped alternatives."""

import json

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_three import (
    execution_contracts,
    interaction,
    interaction_ranges,
)
from shuxueshuo_server.graph_lesson.stage_three.capabilities import (
    select_quantifier_policy,
    separation_division,
)
from shuxueshuo_server.graph_lesson.stage_three.capabilities.ranges import (
    endpoint_values_extremum,
    reciprocal_range,
)
from shuxueshuo_server.graph_lesson.stage_three.presentation_templates import (
    prepare_values,
    render_highlight,
    render_template,
)
from tests.solver.test_graph_stage_three_interactions import _known, _seed

x, a = sp.symbols("x a", real=True)


@pytest.fixture
def sources():
    return interaction_ranges.register(interaction.EXTENSION_API)["answers"]


@pytest.mark.parametrize("domain,reverse", [(sp.Interval.Lopen(0, 2), False),
                                            (sp.Interval.Ropen(-2, 0), True)])
def test_division_uses_strict_sign_including_open_zero_boundary(sources, domain, reverse):
    data = sources["division_direction"]["facts"]({"divisor": x}, {"x": x, "domain": domain})
    assert data["reverse"] is reverse


@pytest.mark.parametrize("domain", [sp.Interval(0, 2), sp.Interval(-1, 1)])
def test_division_never_asks_same_or_reverse_when_divisor_may_vanish(sources, domain):
    with pytest.raises(interaction.NotInteractive, match="divisor_sign_unknown"):
        sources["division_direction"]["facts"]({"divisor": x}, {"x": x, "domain": domain})


def endpoint_data(sources, function, domain=None, known=sp.S.Reals):
    domain = domain if domain is not None else sp.Interval(-1, 1)
    bound = endpoint_values_extremum(function, x, a, domain, {"bound": "sup"})["outputs"]["range"]
    values = {"function": function, "x": x, "domain": domain, "range": bound}
    context = {"x": x, "domain": domain, "parameter": a}
    source = sources["endpoint_candidates"]
    data = {**source["facts"](values, context), "known": known}
    item, = source["answer"](data)
    candidates = source["generators"]["omit_endpoint"](data, item)
    return source, data, values, context, item, candidates


def test_equal_endpoint_values_do_not_make_omission_a_wrong_answer(sources):
    source, data, values, context, item, candidates = endpoint_data(sources, x**2)
    kept, records, _ = source["validate"](data, values, context, item, candidates)
    assert not kept
    assert all(row[1] == "unproven" for row in records)


def test_endpoint_comparison_uses_parameter_witnesses_within_known_scope(sources):
    args = endpoint_data(sources, x**2+a*x, known=sp.Interval.open(0, sp.oo))
    source, data, values, context, item, candidates = args
    kept, records, _ = source["validate"](data, values, context, item, candidates)
    assert [candidate.value for candidate in kept] == [(-1,)]
    assert records[1][1] == "unproven"  # right endpoint alone is enough when a > 0
    assert records[0][2] in {sp.latex(point) for point in interaction.representatives(values, context, data["known"])
                             if point > 0}


def test_endpoint_attainment_distinguishes_equal_values(sources):
    args = endpoint_data(sources, x**2, domain=sp.Interval.Lopen(-1, 1))
    source, data, values, context, item, candidates = args
    kept, _, _ = source["validate"](data, values, context, item, candidates)
    assert [candidate.value for candidate in kept] == [(-1,)]


def test_endpoint_rule_becomes_readonly_if_every_omission_is_equivalent(sources):
    _, _, values, context, _, _ = endpoint_data(sources, x**2)
    seed = _seed("endpoint_bounds", values, context)
    chunk, records = interaction.build_chunk([seed], interaction.load_registry(), {"previous": 0})
    assert chunk["status"] == "readonly" and chunk["reason"] == "insufficient_options"
    assert not any(row.get("result") == "witness" for row in records)


def test_numeric_function_values_are_not_restricted_by_parameter_domain(sources):
    source = sources["certified_range"]
    values = {"range": {"set": sp.Interval(-sp.oo, -1)}, "function": -x**2-1, "after": []}
    context = {"x": x, "parameter": a, "domain": sp.S.Reals}
    data = {**source["facts"](values, context), "known": sp.Interval(0, sp.oo)}
    item, = source["answer"](data)
    candidate = interaction._set_candidate("wrong", sp.Interval.open(-sp.oo, -1))
    kept, records, _ = source["validate"](data, values, context, item, [candidate])
    assert kept == [candidate] and records[0][1] == "witness"


@pytest.mark.parametrize("template", ["range_evidence", "numeric_range"])
def test_range_is_compiled_from_this_card_and_keeps_unattained_endpoint(template):
    seed = _seed(template, {"before": [x], "after": [sp.Interval.open(0, 1)],
                                   "range": {"set": sp.Interval.open(0, 1)}, "function": x},
                 {"x": x, "domain": sp.Interval.open(0, 1), "parameter": a},
                 known=_known("a>0", "∀x∈(0,1):x+a>0"))
    chunk, records = interaction.build_chunk([seed], interaction.load_registry(), {"previous": 0})
    assert chunk["status"] == "interactive", records
    interaction.validate_chunk(chunk)
    part, = chunk["parts"]
    correct = [option for option in part["interaction"]["options"]
               if option["value"] in part["expected_answer"]["one_of"]]
    assert len(correct) == 1 and r"\left(0, 1\right)" in correct[0]["label"]


def separation_seed(relation, domain, fact):
    out = separation_division(relation, a, x, domain)["outputs"]
    template = {"positive_division": "divided", "negative_division": "negative_divided",
                "constant_division": "constant_divided", "move_terms": "moved"}[out["transformation"]]
    bindings = {"before": [relation], "after": [out["separated_relation"]], "moved": out["moved_relation"],
                "separated": out["separated_relation"], "function": out["function"],
                "parameter_expression": out["parameter_expression"], "operator": out["operator"], "x": x,
                "function_name": "h"}
    if template == "moved":
        bindings["relation"] = relation
    else:
        bindings.update(after=[out["moved_relation"], out["separated_relation"]], divisor=out["divisor"])
    if template in ("divided", "negative_divided"):
        bindings["domain"] = domain
    specification = execution_contracts.read("presentation-registry")["templates"][template]
    _, after, text = render_template(specification, bindings)
    values = prepare_values(specification, bindings)
    seed = _seed(template, values, {"x": x, "domain": domain, "parameter": a, "relation": relation},
                 known=_known(fact))
    return seed, after, text


def correct_label(part):
    return next(option["label"] for option in part["interaction"]["options"]
                if option["value"] in part["expected_answer"]["one_of"])


@pytest.mark.parametrize("relation,domain,fact,separated,flip", [
    (sp.Ge(x**2+a*x+1, 0), sp.Interval.Lopen(0, sp.Rational(1, 2)), "∀x∈(0,1/2]:x^2+a*x+1>=0",
     r"a \geq - x - \frac{1}{x}", "保持不变"),
    (sp.Ge(x**2+a*x+2, 0), sp.Interval.open(-sp.oo, 0), "∀x∈(-∞,0):x^2+a*x+2>=0",
     r"a \leq - x - \frac{2}{x}", "反向"),
])
def test_division_card_asks_moving_sign_and_result_in_order(relation, domain, fact, separated, flip):
    seed, after, text = separation_seed(relation, domain, fact)
    constant = 1 if flip == "保持不变" else 2
    moved = rf"a x \geq - x^{{2}} - {constant}"
    assert [sp.latex(value) for value in after] == [moved, separated]
    assert f"移项得 ${moved}$" in text and "记 $h(x)=" in text
    chunk, diagnostics = interaction.build_chunk([seed], interaction.load_registry(), {"previous": 0})
    assert chunk["status"] == "interactive", diagnostics
    interaction.validate_chunk(chunk)
    moving, signs, result = chunk["parts"]
    assert correct_label(moving) == f"${moved}$"
    assert {option["label"] for option in moving["interaction"]["options"]} >= {
        rf"$a x \geq x^{{2}} + {constant}$", rf"$a x \leq - x^{{2}} - {constant}$"}
    assert moved in signs["question"]
    labels = [slot["label"] for slot in signs["interaction"]["slots"]]
    assert labels == ["除数 $x$ 的符号", "不等号方向"]
    expected = [next(option["label"] for option in slot["options"] if option["value"] == term)
                for slot, term in zip(signs["interaction"]["slots"], signs["expected_answer"]["terms"], strict=True)]
    assert expected == ["恒正" if flip == "保持不变" else "恒负", flip]
    assert correct_label(result) == f"${separated}$"
    wrong = {option["label"]: option["feedback"] for option in result["interaction"]["options"]
             if option["value"] not in result["expected_answer"]["one_of"]}
    assert rf"$a {separated.split()[1]} - x - {constant}$" in wrong
    assert any("不等号方向" in message for message in wrong.values())


def test_move_only_card_asks_for_the_moved_relation():
    seed, after, text = separation_seed(sp.Ge(x**2+a+1, 0), sp.S.Reals, "∀x∈ℝ:x^2+a+1>=0")
    assert [sp.latex(value) for value in after] == [r"a \geq - x^{2} - 1"]
    assert "除" not in text
    chunk, diagnostics = interaction.build_chunk([seed], interaction.load_registry(), {"previous": 0})
    assert chunk["status"] == "interactive", diagnostics
    part, = chunk["parts"]
    assert correct_label(part) == r"$a \geq - x^{2} - 1$"
    assert len(part["interaction"]["options"]) == 4


@pytest.mark.parametrize("relation,fact,moved,separated,kind", [
    (sp.Ge(x**2+2*a, 0), "∀x∈ℝ:x^2+2*a>=0", r"2 a \geq - x^{2}", r"a \geq - \frac{x^{2}}{2}", "正数"),
    (sp.Ge(x**2-a+1, 0), "∀x∈ℝ:x^2-a+1>=0", r"- a \geq - x^{2} - 1", r"a \leq x^{2} + 1", "负数"),
])
def test_constant_divisor_card_moves_then_divides_without_a_sign_question(relation, fact, moved, separated, kind):
    seed, after, text = separation_seed(relation, sp.S.Reals, fact)
    assert seed["template"] == "constant_divided"
    assert [sp.latex(value) for value in after] == [moved, separated]
    assert ("不等号变向" in text) is (kind == "负数") and r"\therefore" not in text
    chunk, diagnostics = interaction.build_chunk([seed], interaction.load_registry(), {"previous": 0})
    assert chunk["status"] == "interactive", diagnostics
    moving, result = chunk["parts"]
    assert [moving["title"], result["title"]] == ["移项", "分离参数"]
    assert correct_label(moving) == f"${moved}$"
    assert f"两边同除以{kind}" in result["question"]
    assert correct_label(result) == f"${separated}$"


def test_negative_polynomial_divisor_divides_and_keeps_the_parameter_alone():
    seed, after, text = separation_seed(sp.Ge(a*(1-x)+x**2, 0), sp.Interval.open(1, 2), "∀x∈(1,2):a*(1-x)+x^2>=0")
    assert seed["template"] == "negative_divided"
    separated = after[-1]
    assert separated.lhs == a and separated.rel_op == "<="
    assert sp.simplify(separated.rhs - (x + 1 + 1/(x - 1))) == 0
    assert "两边同除以 $- x + 1$，不等号变向" in text
    chunk, diagnostics = interaction.build_chunk([seed], interaction.load_registry(), {"previous": 0})
    assert chunk["status"] == "interactive", diagnostics
    # h(x) > 4 on (1, 2): the options differ only beyond the grid parameters.
    assert [part["title"] for part in chunk["parts"]] == ["移项", "判断除数符号与不等号方向", "分离参数"]
    assert all(len(part["interaction"].get("options", [])) >= 3 for part in (chunk["parts"][0], chunk["parts"][2]))


@pytest.mark.parametrize("relation,domain,caption,first,last,note", [
    (sp.Ge(x**2+a*x+1, 0), sp.Interval.Lopen(0, sp.Rational(1, 2)), "两边同除以正数",
     ("移项后", r"a x \geq - x^{2} - 1"), ("两边除以 $x$", r"a \geq - x - \frac{1}{x}"), "$x>0$，不等号方向不变"),
    (sp.Ge(x**2+a*x+2, 0), sp.Interval.open(-sp.oo, 0), "两边同除以负数",
     ("移项后", r"a x \geq - x^{2} - 2"), ("两边除以 $x$", r"a \leq - x - \frac{2}{x}"), "$x<0$，不等号方向改变"),
    (sp.Ge(2*a+x**2, 0), sp.S.Reals, "两边同除以正数",
     ("移项后", r"2 a \geq - x^{2}"), ("两边除以 $2$", r"a \geq - \frac{x^{2}}{2}"), "不等号方向不变"),
    (sp.Ge(x**2-a+1, 0), sp.S.Reals, "两边同除以负数",
     ("移项后", r"- a \geq - x^{2} - 1"), ("两边除以 $-1$", r"a \leq x^{2} + 1"), "不等号方向改变"),
    (sp.Ge(x**2+a+1, 0), sp.S.Reals, "移项分离参数",
     ("原不等式", r"x^{2} + a + 1 \geq 0"), ("移项后", r"a \geq - x^{2} - 1"), "只移项，不等号方向不变"),
])
def test_separation_card_highlights_the_conclusion(relation, domain, caption, first, last, note):
    out = separation_division(relation, a, x, domain)["outputs"]
    template = {"positive_division": "divided", "negative_division": "negative_divided",
                "constant_division": "constant_divided", "move_terms": "moved"}[out["transformation"]]
    specification = execution_contracts.read("presentation-registry")["templates"][template]
    bindings = {"before": [relation], "after": [], "relation": relation, "moved": out["moved_relation"],
                "separated": out["separated_relation"], "function": out["function"], "domain": domain,
                "parameter_expression": out["parameter_expression"], "operator": out["operator"], "x": x,
                "divisor": out["divisor"], "function_name": "h"}
    highlight = render_highlight(specification, {key: bindings[key] for key in specification["required_bindings"]})
    assert highlight["caption"] == caption
    assert [(item["label"], item["math"]) for item in highlight["items"]] == [first, last]
    assert "note" not in highlight["items"][0] and highlight["items"][1]["note"] == note
    assert highlight["result"].startswith(rf"$a {last[1].split()[1]} h(x)$，其中 $h(x)=")


@pytest.mark.parametrize("quantifier,operator,expression,function,name,caption,relation_tex,condition,note", [
    ("∀", "<=", a, -x - 2/x, "", "恒成立转化为最值条件", r"a \leq - x - \frac{2}{x}",
     r"a \leq \left(- x - \frac{2}{x}\right)_{\text{下端}}", "从函数值范围的最小一侧判断，并检查等号与能否取到"),
    ("∀", "<=", a, -x - 2/x, "h", "恒成立转化为最值条件", r"a \leq h(x)",
     r"a \leq h(x)_{\text{下端}}", "从函数值范围的最小一侧判断，并检查等号与能否取到"),
    ("∀", ">", sp.S.Zero, x**2 + a*x + 4, "", "恒成立转化为最值条件", r"x^{2} + a x + 4 < 0",
     r"\left(x^{2} + a x + 4\right)_{\text{上端}} \leq 0",
     "从函数值范围的最大一侧判断，并检查等号与能否取到；值域上端取到时不能相等"),
    ("∃", ">=", a, -x - 1/x, "", "能成立转化为最值条件", r"a \geq - x - \frac{1}{x}",
     r"a \geq \left(- x - \frac{1}{x}\right)_{\text{下端}}",
     "从函数值范围的最小一侧判断，并检查等号与能否取到；相等时值域下端必须能取到"),
])
def test_policy_card_highlights_the_bound_condition(quantifier, operator, expression, function, name, caption,
                                                     relation_tex, condition, note):
    domain = sp.Interval.open(0, 1)
    policy = select_quantifier_policy(quantifier, operator, domain)["outputs"]["policy"]
    specification = execution_contracts.read("presentation-registry")["templates"]["policy"]
    bindings = {"before": [], "after": [], "policy": policy, "x": x, "parameter_expression": expression,
                "function": function, "domain": domain, "function_name": name, "define_name": False}
    highlight = render_highlight(specification, bindings)
    assert highlight["caption"] == caption and highlight["connector"] == "⇔"
    left, right = highlight["items"]
    assert left["math"] == relation_tex and right["math"] == condition and right["note"].endswith(note)
    assert "能取到时就是最小值/最大值" in right["note"]
    caveat = "（" + note.split("；", 1)[1] + "）" if "；" in note else ""
    assert highlight["result"] == f"${condition}$" + caveat
    _, _, text = render_template(specification, bindings)
    assert f"$\\iff {condition}$" in text


def test_policy_card_introducing_a_name_defines_it_before_the_bound_condition():
    domain = sp.Interval.Lopen(0, sp.Rational(1, 2))
    policy = select_quantifier_policy("∀", "<=", domain)["outputs"]["policy"]
    specification = execution_contracts.read("presentation-registry")["templates"]["policy"]
    bindings = {"before": [], "after": [], "policy": policy, "x": x, "parameter_expression": sp.S.Zero,
                "function": x**2 + a*x + 1, "domain": domain, "function_name": "g", "define_name": True}
    highlight = render_highlight(specification, bindings)
    assert highlight["items"][0]["math"] == r"g(x) \geq 0"
    assert highlight["result"] == r"$g(x)=x^{2} + a x + 1$，$g(x)_{\text{下端}} \geq 0$"
    _, _, text = render_template(specification, bindings)
    assert text.startswith(r"记 $g(x)=x^{2} + a x + 1$，")


@pytest.mark.parametrize("operator", ["<", "<=", ">", ">="])
@pytest.mark.parametrize("closed", [False, True])
def test_existential_bound_answer_and_display_match_attainment(operator, closed):
    domain = sp.Interval(0, 1) if closed else sp.Interval.open(0, 1)
    policy = select_quantifier_policy("∃", operator, domain)["outputs"]["policy"]
    values = {"function": x, "parameter_expression": a, "policy": policy, "x": x}
    context = {"x": x, "domain": domain, "parameter": a, "quantifier": "∃"}
    data = interaction._policy_facts(values, context)
    item, = interaction._policy_answer(data)
    for parameter in map(sp.Rational, [-1, 0, .5, 1, 2]):
        # A monotone identity on an interval: direct interior/end samples suffice
        # at these exact candidate values, independently of the policy code.
        points = [sp.Rational(1, 4), sp.Rational(1, 2), sp.Rational(3, 4)]
        if closed:
            points += [sp.S.Zero, sp.S.One]
        expected = any(sp.Rel(parameter, point, operator) is sp.true for point in points)
        assert item["answer"].value(parameter) is expected
    assert ("等号成立时" in item["answer"].label) == (operator in ("<=", ">="))


def test_every_presentation_template_has_an_explicit_rule():
    presentation = json.loads((interaction.ROOT / "site/data/knowledge-next/execution/presentation-registry.json")
                              .read_text())
    registry = interaction.load_registry()
    assert set(presentation["templates"]) <= set(registry["templates"])
    assert len(registry["templates"]) == 35


def hook_seed(function, domain, fact):
    out = reciprocal_range(function, x, domain)["outputs"]
    bindings = {"before": [function], "after": [out["range"]["set"]], "range": out["range"], "domain": domain,
                "function": function, "x": x, "turn": out["turning_point"], "endpoints": out["endpoint_values"],
                "function_name": "h"}
    specification = execution_contracts.read("presentation-registry")["templates"]["hook_range"]
    _, _, text = render_template(specification, bindings)
    seed = _seed("hook_range", prepare_values(specification, bindings),
                 {"x": x, "domain": domain, "parameter": a}, known=_known(fact))
    return seed, text, render_highlight(specification, bindings)


def checklist_answers(part):
    expected = set(part["expected_answer"]["terms"])
    return [next(option["label"] for option in slot["options"] if option["value"] in expected)
            for slot in part["interaction"]["slots"]]


@pytest.mark.parametrize("function,domain,fact,turn,side,answer", [
    (-x - 1/x, sp.Interval.Lopen(0, sp.Rational(1, 2)), "∀x∈(0,1/2]:x^2+a*x+1>=0",
     r"最高点 $\left(1,\,-2\right)$", "左侧", r"$\left(-\infty, - \frac{5}{2}\right]$"),
    (x + 1 + 4/x, sp.Interval(1, 3), "∀x∈[1,3]:x^2+x+4-a*x>=0",
     r"最低点 $\left(2,\,5\right)$", "两侧都有", r"$\left[5, 6\right]$"),
])
def test_hook_card_finds_the_turn_then_the_side_then_the_range(function, domain, fact, turn, side, answer):
    seed, text, highlight = hook_seed(function, domain, fact)
    assert "由对勾函数的性质" in text and "当且仅当" in text and "\n$\\therefore\\ h(x) \\in " in text
    assert highlight["result"].startswith("$h(x) \\in ")
    chunk, diagnostics = interaction.build_chunk([seed], interaction.load_registry(), {"previous": 0})
    assert chunk["status"] == "interactive", diagnostics
    interaction.validate_chunk(chunk)
    shape, placement = chunk["parts"]
    assert shape["question"].startswith("$h(x)=") and "的图像如图" in shape["question"]
    assert "ax+" not in shape["question"] and correct_label(shape) == turn
    assert len(shape["interaction"]["options"]) == 4
    assert shape["graph"]["kind"] == "reciprocal_sum" and not shape["graph"]["params"]["points"]
    assert checklist_answers(placement) == [side, answer]
    assert any("label" in point for point in placement["graph"]["params"]["points"])
    assert placement["completion_graph"]["kind"] == "reciprocal_sum"
    assert not [row for row in diagnostics if row.get("result") == "graph_fallback"]


@pytest.mark.parametrize("function,domain,fact,answer", [
    (x - 1/x, sp.Interval(1, 2), "∀x∈[1,2]:x^2-a*x-1>=0", r"$\left[0, \frac{3}{2}\right]$"),
    (-x - 1/x, sp.Interval(2, 3), "∀x∈[2,3]:x^2+a*x+1>=0", r"$\left[- \frac{10}{3}, - \frac{5}{2}\right]$"),
])
def test_reciprocal_range_routes_hooks_and_monotone_sums_to_their_own_cards(function, domain, fact, answer):
    out = reciprocal_range(function, x, domain)["outputs"]
    hook = function == -x - 1/x
    assert out["shape"] == ("hook" if hook else "monotone")
    assert (out["turning_point"] is None) is not hook
    units = {unit["id"]: unit for step in execution_contracts.read("method-separation")["steps"]
             for unit in step["display_units"]}
    selected = [name for name in ("reciprocal_range", "reciprocal_monotone_range")
                if {"ref": "reciprocal_shape", "equals": out["shape"]} in units[name]["guard"]["all"]]
    assert selected == ["reciprocal_range" if hook else "reciprocal_monotone_range"]
    if hook:
        return
    bindings = {"before": [function], "after": [out["range"]["set"]], "range": out["range"], "domain": domain,
                "function": function, "x": x, "points": out["critical_points"],
                "endpoints": out["endpoint_values"], "function_name": "h"}
    specification = execution_contracts.read("presentation-registry")["templates"]["range_evidence"]
    _, _, text = render_template(specification, bindings)
    assert "对勾" not in text and "$h(x)$ 的最小值为 $0$，能取得" in text
    seed = _seed("range_evidence", prepare_values(specification, bindings),
                 {"x": x, "domain": domain, "parameter": a}, known=_known(fact))
    chunk, diagnostics = interaction.build_chunk([seed], interaction.load_registry(), {"previous": 0})
    assert chunk["status"] == "interactive", diagnostics
    interaction.validate_chunk(chunk)
    part, = chunk["parts"]
    assert part["question"] == r"$h(x)$ 在 $\left[1, 2\right]$ 上的值域是？"
    assert correct_label(part) == answer
