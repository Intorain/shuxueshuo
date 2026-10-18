"""D1 acceptance checks use independent original-text excerpts, not snapshots."""

import json
from pathlib import Path

import pytest

from shuxueshuo_server.graph_lesson.stage_one.features import extract_features
from shuxueshuo_server.graph_lesson.stage_two.fragments import build_d1
from shuxueshuo_server.graph_lesson.stage_two.recognition import derive_knowledge
from shuxueshuo_server.graph_lesson.stage_two.surface_math import (
    PolynomialReader,
    normalize_surface,
)

FIXTURES = Path(__file__).parent / "fixtures"
GOLD = json.loads((FIXTURES / "graph-guided-stage-two/d1-relations.gold.json").read_text())
RECORDED = FIXTURES / "graph-guided-stage-one/recorded" / GOLD["batch"]
TARGET = "/root/goals/0"


def recorded(question, sample="sample-01"):
    directory = RECORDED / question / sample
    candidate = json.loads((directory / "workflow/candidate.json").read_text())
    features = json.loads((directory / "features.json").read_text())["features"]
    return candidate, features


def build(candidate, features=None, target=TARGET):
    if features is None:
        result = extract_features(candidate)
        assert result["ok"], result["diagnostics"]
        features = result["features"]
    current = [item for item in features if item["target_ref"] == target]
    return build_d1(candidate, target, features, derive_knowledge(current))


def of_kind(output, kind):
    return [item for item in output["fragments"] if item["fragment_kind"] == kind]


def assert_offsets(candidate, output):
    original = candidate["original_text"]
    for fragment in output["fragments"]:
        assert 0 <= fragment["start"] < fragment["end"] <= len(original)
        assert fragment["text"] == original[fragment["start"]:fragment["end"]]


@pytest.mark.parametrize("case", GOLD["cases"], ids=lambda c: f"{c['question']}-{c['sample']}-{c['target_ref']}")
def test_recorded_relations_match_independent_gold(case):
    candidate, features = recorded(case["question"], case["sample"])
    output = build(candidate, features, case["target_ref"])
    relations = of_kind(output, "relation")
    assert [item["text"] for item in relations] == [case["text"]]
    assert relations[0]["matched_feature_ids"] == ["relation"]
    expected = {"quadratic-inequality#definition"}
    if case["question"] not in ("q08", "q09"):
        expected.add("quadratic-function-properties#definition")
    assert set(relations[0]["knowledge_refs"]) == expected
    assert_offsets(candidate, output)


def test_gold_covers_every_recorded_known_relationship():
    actual = set()
    samples = set()
    for path in RECORDED.glob("q*/sample-*/features.json"):
        features = json.loads(path.read_text())["features"]
        samples.add((path.parent.parent.name, path.parent.name))
        actual.update((path.parent.parent.name, path.parent.name, item["target_ref"])
                      for item in features if item["feature_id"] == "relation" and item["status"] == "known")
    expected = {(case["question"], case["sample"], case["target_ref"]) for case in GOLD["cases"]}
    assert len(samples) == 22
    assert len(expected) == 24
    assert actual == expected


def semantic_signature(output):
    return [(item["fragment_kind"], item["matched_feature_ids"], item["knowledge_rule_ids"], item["knowledge_refs"])
            for item in output["fragments"]]


def test_tex_bare_tex_unicode_and_internal_spaces_have_identical_meanings():
    candidate, features = recorded("q01", "sample-02")
    reference = build(candidate, features)
    variants = [candidate["original_text"].replace("$", ""),
                candidate["original_text"].replace(r"\le", "≤").replace("$", ""),
                candidate["original_text"].replace(r"-x^2+2x+3 \le a^2-3a", r"- x^{2} + 2 x + 3 \leq a^{2} - 3 a")]
    for text in variants:
        changed = {**candidate, "original_text": "🧮" + text}
        output = build(changed, features)
        assert semantic_signature(output) == semantic_signature(reference)
        assert_offsets(changed, output)


@pytest.mark.parametrize("formula", [
    r"-x^2+2x+3 ≤ a^2-3\mathrm{a}",
    r"\mathrm{-x^2}+2x+3 ≤ a^2-3a",
    r"\mathrm{ -x^2 }+2x+3 ≤ a^2-3\text{ a }",
])
def test_formula_edge_wrappers_keep_their_complete_original_spelling(formula):
    candidate, features = recorded("q01")
    original = "-x^2+2x+3 ≤ a^2-3a"
    candidate["original_text"] = candidate["original_text"].replace(original, formula)
    result = build(candidate, features)
    relation, = of_kind(result, "relation")
    assert relation["text"] == formula
    assert_offsets(candidate, result)


def test_partial_word_inside_a_prose_wrapper_does_not_take_the_whole_wrapper():
    text = r"\text{任意实数 x}"
    surface = normalize_surface(text)
    start, end = surface.original_span(0, 2)
    assert text[start:end] == "任意"


def test_q06_delimited_and_bare_forms_agree():
    first, first_features = recorded("q06", "sample-01")
    second, second_features = recorded("q06", "sample-02")
    assert semantic_signature(build(first, first_features)) == semantic_signature(build(second, second_features))
    for candidate, features in [(first, first_features), (second, second_features)]:
        result = build(candidate, features)
        assert [item["text"] for item in of_kind(result, "domain")] == ["x<0"]


@pytest.mark.parametrize(("spelling", "expected"), [
    ("实数 x ", "实数 x"),
    ("实数 x\t ", "实数 x"),
    ("实数 $x$ ", "实数 $x$"),
    ("实数 $ x $ ", "实数 $ x $"),
    (r"实数 \(x\) ", r"实数 \(x\)"),
])
def test_real_domain_ends_at_variable_or_closing_delimiter(spelling, expected):
    candidate, features = recorded("q01")
    candidate["original_text"] = "🧮对任意" + spelling + "恒成立，求实数 a 的取值范围。"
    output = build(candidate, features)
    domain, = of_kind(output, "domain")
    assert domain["text"] == expected
    assert_offsets(candidate, output)


def test_one_fact_does_not_spread_knowledge_between_fragments():
    candidate, features = recorded("q01")
    output = build(candidate, features)
    quantifier = next(item for item in output["fragments"] if item["text"] == "任意")
    domain = of_kind(output, "domain")[0]
    relation = of_kind(output, "relation")[0]
    goal = of_kind(output, "goal")[0]
    assert quantifier["knowledge_refs"] == ["quantifiers#universal"]
    assert quantifier["knowledge_rule_ids"] == ["quantifier-universal"]
    assert domain["matched_feature_ids"] == ["bound_vars", "domain"]
    assert set(domain["knowledge_refs"]) == {"quantifiers#domain", "quantifiers#roles"}
    assert relation["knowledge_rule_ids"] == ["quadratic-function", "quadratic-relation"]
    assert goal["matched_feature_ids"] == ["goal"]
    assert goal["knowledge_refs"] == ["quantifiers#roles"]
    assert set(quantifier["source_refs"]) & set(relation["source_refs"])


@pytest.mark.parametrize(("kind", "noun"), [("find_minimum", "最小值"), ("find_maximum", "最大值")])
@pytest.mark.parametrize("spelling", ["实数 $a$ 的", "参数 $ a $ 的", "求实数 a 的", "求 $a$ 的", "a的", r"实数 \(a\) 的"])
def test_extremum_goal_locates_whole_symbol_with_or_without_request_verb(kind, noun, spelling):
    candidate, features = recorded("q01")
    next(item for item in features if item["feature_id"] == "goal")["value"] = {"kind": kind, "symbol": "a"}
    candidate["original_text"] = "🧮若不等式恒成立，则" + spelling + noun + "为 ______。"
    output = build(candidate, features)
    fragment, = of_kind(output, "goal")
    assert fragment["text"] == spelling + noun
    assert fragment["matched_feature_ids"] == ["goal"]
    assert_offsets(candidate, output)


@pytest.mark.parametrize(("kind", "noun"), [("find_minimum", "最小值"), ("find_maximum", "最大值")])
@pytest.mark.parametrize("spelling", ["b", "$b$", "ba", "b a", "a+a", "a + a", "$a+a$", "a_1", "a₁", "$a^2$"])
def test_extremum_goal_does_not_match_a_different_symbol_or_expression(kind, noun, spelling):
    candidate, features = recorded("q01")
    next(item for item in features if item["feature_id"] == "goal")["value"] = {"kind": kind, "symbol": "a"}
    candidate["original_text"] = "则实数 " + spelling + " 的" + noun + "为 ______。"
    assert not of_kind(build(candidate, features), "goal")


@pytest.mark.parametrize(("kind", "opposite"), [("find_minimum", "最大值"), ("find_maximum", "最小值")])
def test_extremum_goal_does_not_match_the_opposite_requested_extremum(kind, opposite):
    candidate, features = recorded("q01")
    next(item for item in features if item["feature_id"] == "goal")["value"] = {"kind": kind, "symbol": "a"}
    candidate["original_text"] = f"求实数 $a$ 的{opposite}。"
    assert not of_kind(build(candidate, features), "goal")


def test_unknown_features_never_attach_knowledge_even_if_source_refs_match():
    candidate, features = recorded("q01")
    for item in features:
        if item["feature_id"] in {"relation", "domain", "bound_vars"}:
            item["status"], item["value"] = "unknown", None
    output = build(candidate, features)
    assert not of_kind(output, "relation")
    assert not of_kind(output, "domain")
    assert all("quantifiers#roles" not in item["knowledge_refs"] for item in output["fragments"])


def test_same_relationship_in_siblings_uses_only_its_own_scope_and_shared_function():
    candidate = {
        "original_text": "已知 $f(x)=x^2-a$。\n（1）对任意实数 $x$，$f(x)≥0$，求 $a$ 的取值范围。\n（2）存在实数 $x$，$f(x)≥0$，求 $a$ 的取值范围。",
        "root": {"definitions": ["f(x)=x^2-a"], "children": [
            {"label": "（1）", "facts": ["∀x∈ℝ: f(x)≥0"], "goals": [{"kind": "find_range", "symbol": "a"}]},
            {"label": "（2）", "facts": ["∃x∈ℝ: f(x)≥0"], "goals": [{"kind": "find_range", "symbol": "a"}]},
        ]},
    }
    dividing = candidate["original_text"].index("（2）")
    first = build(candidate, target="/root/children/0/goals/0")
    second = build(candidate, target="/root/children/1/goals/0")
    assert len(of_kind(first, "relation")) == len(of_kind(second, "relation")) == 1
    assert all(item["end"] <= dividing for item in first["fragments"])
    assert all(item["start"] > dividing for item in second["fragments"])
    assert of_kind(first, "quantifier")[0]["knowledge_refs"] == ["quantifiers#universal"]
    assert of_kind(second, "quantifier")[0]["knowledge_refs"] == ["quantifiers#existential"]


def test_sibling_definition_is_not_visible_and_ambiguous_labels_are_omitted():
    candidate, features = recorded("q10")
    candidate["original_text"] = candidate["original_text"].replace("已知函数 $f(x)=x^2-2ax+3$。", "").replace("（1）", "（1）已知函数 $f(x)=x^2-2ax+3$。")
    output = build(candidate, features, "/root/children/1/goals/0")
    assert not of_kind(output, "relation")
    candidate["original_text"] = candidate["original_text"].replace("（2）", "（1）")
    output = build(candidate, features, "/root/children/1/goals/0")
    assert not output["fragments"]
    assert output["diagnostics"][0]["code"] == "d1.scope_or_features_ambiguous"


@pytest.mark.parametrize("function", [
    "f(1)", "f ( 1 )", "f（1）", "f\t(1)", "φ(1)", "f₁(1)",
    "φ（1）", "f1（1）", "f₁（1）", "f²（1）", "f_1 （1）",
])
@pytest.mark.parametrize("labels", [("（1）", "（2）"), ("(1)", "(2)")])
def test_bare_function_call_is_not_a_subquestion_heading(function, labels):
    candidate, features = recorded("q10")
    candidate["original_text"] = function + " 有意义。" + candidate["original_text"]
    candidate["original_text"] = candidate["original_text"].replace("（1）若", labels[0] + "若").replace("（2）若", labels[1] + "若")
    dividing = candidate["original_text"].index(labels[1])
    for index in (0, 1):
        output = build(candidate, features, f"/root/children/{index}/goals/0")
        assert len(of_kind(output, "relation")) == 1
        assert not output["diagnostics"]
        assert_offsets(candidate, output)
        if index == 0:
            assert all(item["end"] <= dividing for item in output["fragments"])
        else:
            assert all(item["start"] > dividing for item in output["fragments"])


@pytest.mark.parametrize("separator", ["", " ", "\t"])
def test_full_width_heading_follows_bare_formula_on_the_same_line(separator):
    candidate, features = recorded("q10")
    candidate["original_text"] = candidate["original_text"].replace(
        "已知函数 $f(x)=x^2-2ax+3$。\n（1）",
        "已知函数 f(x)=x^2-2ax+3" + separator + "（1）",
    )
    dividing = candidate["original_text"].index("（2）")
    for index, expected in [(0, r"f(x)\ge 0"), (1, "f(x)<0")]:
        output = build(candidate, features, f"/root/children/{index}/goals/0")
        relation, = of_kind(output, "relation")
        assert relation["text"] == expected
        assert not output["diagnostics"]
        assert_offsets(candidate, output)
        if index == 0:
            assert all(item["end"] <= dividing for item in output["fragments"])
        else:
            assert all(item["start"] > dividing for item in output["fragments"])


@pytest.mark.parametrize("duplicate", ["（1）", "(1)"])
def test_repeated_real_headings_are_still_ambiguous(duplicate):
    candidate, features = recorded("q10")
    candidate["original_text"] = duplicate + "补充说明。\n" + candidate["original_text"]
    for index in (0, 1):
        output = build(candidate, features, f"/root/children/{index}/goals/0")
        assert not output["fragments"]
        assert output["diagnostics"][0]["code"] == "d1.scope_or_features_ambiguous"


@pytest.mark.parametrize("replacement", [
    r"-x^2+2x+3 \untrusted a^2-3a",
    "-z^2+2z+3 ≤ a^2-3a",
    "-x^2+2x+3 ≤ a^2-3a < 10",
    "-x^2+2x+3。≤ a^2-3a",
    "g(x)≤a^2-3a",
    "(-x^2+2x+3)*a/a≤a^2-3a",
])
def test_unsupported_math_is_omitted_without_losing_other_clues(replacement):
    candidate, features = recorded("q01")
    candidate["original_text"] = candidate["original_text"].replace("-x^2+2x+3 ≤ a^2-3a", replacement)
    output = build(candidate, features)
    assert not of_kind(output, "relation")
    assert of_kind(output, "quantifier")
    assert of_kind(output, "goal")
    assert_offsets(candidate, output)


def test_relation_direction_preserves_strictness_and_can_reverse_sides():
    candidate, features = recorded("q01")
    original = candidate["original_text"]
    candidate["original_text"] = original.replace("-x^2+2x+3 ≤ a^2-3a", "a^2-3a≥3+2x-x^2")
    assert of_kind(build(candidate, features), "relation")
    candidate["original_text"] = original.replace("≤", "<")
    assert not of_kind(build(candidate, features), "relation")


@pytest.mark.parametrize("formula", [
    "__import__('os').system('touch sentinel')", "sqrt(x)", "x/0", "x/x", "x^100000", "x^(-1)",
])
def test_reader_rejects_code_and_unsupported_math(formula):
    with pytest.raises(ValueError):
        PolynomialReader({"x"}).parse(formula)


def test_shared_function_can_use_a_different_formal_parameter():
    candidate, features = recorded("q10")
    candidate["original_text"] = candidate["original_text"].replace("f(x)=x^2-2ax+3", "f(t)=t^2-2at+3")
    assert [item["text"] for item in of_kind(build(candidate, features, "/root/children/0/goals/0"), "relation")] == [r"f(x)\ge 0"]


def test_nested_scope_inherits_only_ancestor_introductions():
    candidate = {
        "original_text": "已知 $f(t)=t^2-a$。\n（1）已知 $g(t)=f(t)+1$。\n（3）对任意实数 $x$，$g(x)≥0$，求 $a$ 的取值范围。\n（4）存在实数 $x$，$g(x)<0$，求 $a$ 的取值范围。\n（2）其他小问。",
        "root": {"definitions": ["f(t)=t^2-a"], "children": [
            {"label": "（1）", "definitions": ["g(t)=f(t)+1"], "children": [
                {"label": "（3）", "facts": ["∀x∈ℝ: g(x)≥0"], "goals": [{"kind": "find_range", "symbol": "a"}]},
                {"label": "（4）", "facts": ["∃x∈ℝ: g(x)<0"], "goals": [{"kind": "find_range", "symbol": "a"}]},
            ]},
            {"label": "（2）", "facts": ["a=1"]},
        ]},
    }
    output = build(candidate, target="/root/children/0/children/0/goals/0")
    assert [item["text"] for item in of_kind(output, "relation")] == ["g(x)≥0"]
    assert all(item["end"] <= candidate["original_text"].index("（4）") for item in output["fragments"])


def test_repeated_alias_definitions_remain_ambiguous():
    candidate, features = recorded("q08")
    candidate["original_text"] = candidate["original_text"].replace(
        "$y=mx^2-mx-6+m$", "$y=0$，$y=mx^2-mx-6+m$，$y=mx^2-mx-6+m$"
    )
    assert not of_kind(build(candidate, features), "relation")


@pytest.mark.parametrize("formula", [
    "((((999999999999999999999999^8)^8)^8)^8)",
    "((((x^8)^8)^8)^8)",
    "(" * 30 + "x" + ")" * 30,
    "+".join(["x"] * 300),
])
def test_reader_has_resource_limits_before_expansion(formula):
    with pytest.raises(ValueError):
        PolynomialReader({"x"}).parse(formula)
