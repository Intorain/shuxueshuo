"""Printed choices are source metadata, never additional mathematical facts."""

from copy import deepcopy

import pytest

from shuxueshuo_server.graph_lesson.stage_three.choice_source import (
    choice_source,
    option_expression,
)

OPTIONS = "A. $m≤-2$ 或 $m≥2$\nB. $-2≤m≤2$\nC. $m<-2$ 或 $m>2$\nD. $-2<m<2$"


def candidate(text=OPTIONS):
    return {"original_text": "求参数范围（ ）\n" + text,
            "root": {"facts": ["∃x∈ℝ: -x^2+m*x-1≥0"],
                     "goals": [{"kind": "find_range", "symbol": "m"}]}}


def test_reviewed_transcription_provides_choices_without_mutating_premises():
    source = candidate()
    original = deepcopy(source)
    result = choice_source(source, "/root/goals/0")
    assert result["status"] == "recognized"
    assert result["source"] == "transcription"
    assert result["selection_mode"] == "unspecified"
    assert result["target_ref"] == "/root/goals/0"
    assert [item["label"] for item in result["options"]] == list("ABCD")
    assert result["options"][0] == {"label": "A", "text": "$m≤-2$ 或 $m≥2$", "expression": "m≤-2 ∨ m≥2"}
    assert result["options"][1]["expression"] == "-2≤m≤2"
    assert source == original


@pytest.mark.parametrize("labels", ["A. B. C. D.", "Ａ． Ｂ． Ｃ． Ｄ．", "A、 B、 C、 D、", "(A) (B) (C) (D)", "（A） （B） （C） （D）"])
def test_printed_label_formats(labels):
    result = choice_source(candidate(" ".join(label + " $m=1$" for label in labels.split())), "/root/goals/0")
    assert result["status"] == "recognized"
    assert [item["label"] for item in result["options"]] == list("ABCD")


@pytest.mark.parametrize("prefix,mode", [("单选题", "single"), ("单项选择题", "single"), ("多选题", "multiple"), ("多项选择题", "multiple"), ("不定项选择题", "multiple")])
def test_explicit_selection_mode(prefix, mode):
    source = candidate()
    source["original_text"] = prefix + source["original_text"]
    assert choice_source(source, "/root/goals/0")["selection_mode"] == mode


@pytest.mark.parametrize("parent,child,expected", [
    ("多选题", "", "multiple"),
    ("多项选择题", "", "multiple"),
    ("单项选择题", "", "single"),
    ("多选题", "本问单选", "single"),
    ("单选题", "本问多项选择", "multiple"),
    ("", "本问单选或多选", "multiple"),
])
def test_nearest_explicit_choice_format_overrides_ancestor(parent, child, expected):
    source = {"original_text": parent + "（1）" + child + "\n" + OPTIONS,
              "root": {"children": [{"label": "（1）", "goals": [{"kind": "find_range", "symbol": "m"}]}]}}
    result = choice_source(source, "/root/children/0/goals/0")
    assert result["selection_mode"] == expected


def test_choice_mode_never_inherits_a_siblings_heading():
    source = {"original_text": "（1）多选题" + OPTIONS + "（2）" + OPTIONS,
              "root": {"children": [
                  {"label": "（1）", "goals": [{"kind": "find_range", "symbol": "m"}]},
                  {"label": "（2）", "goals": [{"kind": "find_range", "symbol": "m"}]},
              ]}}
    assert choice_source(source, "/root/children/1/goals/0")["selection_mode"] == "unspecified"


def test_prose_in_option_is_not_a_format_heading():
    result = choice_source(candidate("A. 多选 B. 单选 C. $m=1$ D. $m=2$"), "/root/goals/0")
    assert result["selection_mode"] == "unspecified"


@pytest.mark.parametrize("text", ["A. 1 B. 2", "A. 1 B. 2 C. 3", "A. 1 B. 2 D. 4", "A. 1 B. 2 C. 3 D.", "A. 1 B. 2 C. 3 D. [无法辨认]", OPTIONS + " A. 1"])
def test_incomplete_or_repeated_options_are_unavailable(text):
    result = choice_source(candidate(text), "/root/goals/0")
    assert result["status"] == "unavailable"
    assert result["reason"] == "choice.incomplete_options"
    assert "options" not in result


def test_unparsed_option_is_preserved_for_conservative_matcher():
    result = choice_source(candidate("A. $m=1$ B. $m=2$ C. 都正确 D. $m=4$"), "/root/goals/0")
    assert result["status"] == "recognized"
    assert result["options"][2] == {"label": "C", "text": "都正确", "expression": None}


def test_letter_markers_inside_math_are_not_options():
    source = candidate("求四边形 $A.B.C.D.$ 的面积。")
    assert choice_source(source, "/root/goals/0")["status"] == "not_choice"


@pytest.mark.parametrize("stem", [
    "已知 A、B 两点，求参数范围。", "A、B 两点在抛物线上，求参数范围。",
    "过 A、 B、C 三个点，求参数范围。", "过 Ａ、Ｂ 两点，求参数范围。",
    "已知 A、B、C、D 4 点，求参数范围。", "点 A、B 在抛物线上，求参数范围。",
    "交点 A、B，求参数范围。", "交点 A、 B 的横坐标满足题设。",
])
def test_point_names_in_stem_do_not_prevent_complete_choices(stem):
    source = candidate(stem + "\n" + OPTIONS)
    before = deepcopy(source)
    result = choice_source(source, "/root/goals/0")
    assert result["status"] == "recognized"
    assert result["options"] == choice_source(candidate(), "/root/goals/0")["options"]
    assert source == before
    assert choice_source(candidate(stem), "/root/goals/0")["status"] == "not_choice"


@pytest.mark.parametrize("labels", ["A. B. C. D.", "A、 B、 C、 D、", "Ａ． Ｂ． Ｃ． Ｄ．"])
@pytest.mark.parametrize("heading,mode", [("单选题", "single"), ("多选题", "multiple")])
def test_point_names_do_not_hide_later_selection_heading_or_change_label_formats(labels, heading, mode):
    options = " ".join(label + " $m=1$" for label in labels.split())
    result = choice_source(candidate("A、B 两点在曲线上。" + heading + "\n" + options), "/root/goals/0")
    assert result["status"] == "recognized" and result["selection_mode"] == mode
    assert [item["label"] for item in result["options"]] == list("ABCD")


@pytest.mark.parametrize("options", [
    "A. 1 B. 2 C. 3", "A. 1 B. 2 D. 4", "A. 1 A. 2 B. 3 C. 4 D. 5",
    "A、 1 A、 2 B、 3 C、 4 D、 5", OPTIONS + " A. 1", OPTIONS + " D、 5",
])
def test_point_name_filter_never_repairs_missing_or_repeated_choices(options):
    result = choice_source(candidate("过 A、B 两点，求参数范围。\n" + options), "/root/goals/0")
    assert result["status"] == "unavailable" and result["reason"] == "choice.incomplete_options"
    assert "options" not in result


@pytest.mark.parametrize("prefix", ["A、 B、 1", "A、B 三点", "A、A 两点", "点 A、 1"])
def test_ambiguous_letter_prefix_is_not_discarded_to_find_a_complete_suffix(prefix):
    result = choice_source(candidate(prefix + "\n" + OPTIONS), "/root/goals/0")
    assert result["status"] == "unavailable" and result["reason"] == "choice.incomplete_options"


def test_point_enumerations_inside_an_option_preserve_the_option_text():
    source = candidate("A. 点 A、B 在直线上 B. $m=2$ C. $m=3$ D. $m=4$")
    result = choice_source(source, "/root/goals/0")
    assert result["status"] == "recognized"
    assert result["options"][0] == {"label": "A", "text": "点 A、B 在直线上", "expression": None}


def test_sibling_options_do_not_leak_into_current_scope():
    source = {"original_text": "（1）求范围。" + OPTIONS + "（2）求最小值。",
              "root": {"children": [
                  {"label": "（1）", "goals": [{"kind": "find_range", "symbol": "m"}]},
                  {"label": "（2）", "goals": [{"kind": "find_minimum", "expression": "m"}]},
              ]}}
    assert choice_source(source, "/root/children/0/goals/0")["status"] == "recognized"
    assert choice_source(source, "/root/children/1/goals/0")["status"] == "not_choice"


@pytest.mark.parametrize("body", ["", "求范围。"])
def test_parent_options_do_not_leak_into_child_even_if_child_text_empty(body):
    source = {"original_text": OPTIONS + "（1）" + body,
              "root": {"children": [{"label": "（1）", "goals": [{"kind": "find_range", "symbol": "m"}]}]}}
    result = choice_source(source, "/root/children/0/goals/0")
    assert result["status"] in {"not_choice", "unavailable"}
    assert "options" not in result


def test_unlabelled_subquestion_is_not_guessed():
    source = {"original_text": OPTIONS, "root": {"children": [{"goals": [{"kind": "find_range", "symbol": "m"}]}]}}
    assert choice_source(source, "/root/children/0/goals/0")["reason"] == "choice.ambiguous_scope"


@pytest.mark.parametrize("body,recognized", [(OPTIONS, True), ("", False)])
def test_nested_question_uses_only_its_own_options(body, recognized):
    source = {"original_text": "第一问" + OPTIONS + "子问" + body,
              "root": {"children": [{"label": "第一问", "children": [
                  {"label": "子问", "goals": [{"kind": "find_range", "symbol": "m"}]},
              ]}]}}
    result = choice_source(source, "/root/children/0/children/0/goals/0")
    assert (result["status"] == "recognized") is recognized


def test_parent_goal_ignores_child_option_block():
    source = candidate()
    source["original_text"] = "求范围。" + OPTIONS + "（1）" + OPTIONS.replace("m", "x")
    source["root"]["children"] = [{"label": "（1）", "goals": [{"kind": "find_range", "symbol": "x"}]}]
    result = choice_source(source, "/root/goals/0")
    assert result["status"] == "recognized"
    assert result["options"][0]["expression"] == "m≤-2 ∨ m≥2"


def test_multiple_goals_are_not_assigned_one_option_block():
    source = candidate()
    source["root"]["goals"].append({"kind": "find_range", "symbol": "x"})
    assert choice_source(source, "/root/goals/0")["reason"] == "choice.ambiguous_scope"


@pytest.mark.parametrize("target", ["/root/goals/1", "/root/facts/0", "/root/goals/-1", "/root/children/9/goals/0", None])
def test_bad_target_is_unavailable(target):
    assert choice_source(candidate(), target)["status"] == "unavailable"


@pytest.mark.parametrize("text", [None, {}, "", 42, "x" * 32769])
def test_missing_or_oversize_text_is_unavailable(text):
    source = candidate()
    source["original_text"] = text
    assert choice_source(source, "/root/goals/0")["reason"] == "choice.missing_text"


@pytest.mark.parametrize("text,expected", [
    (r"$m\leqslant-2$ 或 $m\geqslant2$", "m≤-2 ∨ m≥2"),
    (r"$m\in(-\infty,-2]\cup[2,\infty)$", "m∈(-∞,-2]∪[2,∞)"),
    (r"$\frac{1-\sqrt{5}}{2}$", "((1-sqrt(5))/(2))"),
    (r"$m^{2}\ge 4$", "m^(2)≥ 4"),
    (r"$m>0\wedge m\ne1$", "m>0∧ m≠1"),
    (r"$\{-1,1\}$", "{-1,1}"),
    ("$m∈∅$", "m∈∅"),
    (r"$\mathbb{R}$", "ℝ"),
])
def test_option_notation_conversion_is_inert(text, expected):
    assert option_expression(text) == expected


@pytest.mark.parametrize("text,expected", [
    (r"$\{k \mid k<-4\}$", "{k∈ℝ| k<-4}"),
    (r"$\{k \mid k<-4 \text{ 或 } k>0\}$", "{k∈ℝ| k<-4  ∨  k>0}"),
    ("{k: -4<k<0}", "{k∈ℝ: -4<k<0}"),
    ("{k∈[0,1]|k>0}", "{k∈[0,1]|k>0}"),
])
def test_set_builder_shorthand_uses_only_the_range_goals_real_parameter(text, expected):
    assert option_expression(text, real_parameter="k") == expected


@pytest.mark.parametrize("text", ["{k|k>0}", "{k:k>0}"])
def test_set_builder_shorthand_needs_parameter_context(text):
    assert option_expression(text) is None
    assert option_expression(text, real_parameter="m") is None


@pytest.mark.parametrize("text", ["{m|m>0}", "{k^2|k>0}", "{k|}", "{k|k>0", "k|k>0}"])
def test_set_builder_shorthand_does_not_infer_foreign_or_incomplete_sets(text):
    assert option_expression(text, real_parameter="k") is None


@pytest.mark.parametrize("text", ["所有选项都正确", "[无法辨认]", "$m<2", r"$\foo{2}$", "__import__('os').system('x')", r"$\frac{1}{$", "x" * 2049])
def test_unrecognized_math_is_not_guessed(text):
    assert option_expression(text) is None
