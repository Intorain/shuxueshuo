"""D1 maps explicit quantified negation, never an arbitrary opposite inequality."""

import pytest
from test_graph_stage_two_fragments import assert_offsets, build, of_kind


def candidate(body="∀x∈[1,4]: x^2-m*x-m+15>0", fact="∃x∈[1,4]: x^2-m*x-m+15<=0", *, original=None):
    return {
        "original_text": original or f"若命题“{body}”为假命题，则实数 $m$ 的取值范围为 ____。",
        "root": {"facts": ["m∈ℝ", fact], "goals": [{"kind": "find_range", "symbol": "m"}]},
    }


@pytest.mark.parametrize("quantifier,target", [("∀", "∃"), ("∃", "∀")])
@pytest.mark.parametrize("source_op,target_op", [("<", ">="), ("<=", ">"), (">", "<="), (">=", "<")])
def test_negation_changes_quantifier_and_complements_all_inequalities(quantifier, target, source_op, target_op):
    item = candidate(f"{quantifier}x∈[1,4]:x^2+m{source_op}0", f"{target}x∈[1,4]:x^2+m{target_op}0")
    result = build(item)
    q, = of_kind(result, "quantifier")
    relation, = of_kind(result, "relation")
    assert "为假命题" in q["text"]
    assert q["reading_transform"] == relation["reading_transform"] == {
        "kind": "quantifier_negation", "source_quantifier": quantifier, "source_operator": source_op,
        "target_quantifier": target, "target_operator": target_op,
    }
    assert {f["fragment_kind"] for f in result["fragments"]} == {"quantifier", "relation", "domain", "goal"}
    assert not result["diagnostics"]
    assert_offsets(item, result)


@pytest.mark.parametrize("original", [
    r'9.[2026 广东深圳高级中学期中]若命题“$\forall x\in\{x|1\le x\le4\}$，不等式 $x^2-mx-m+15>0$ 恒成立”为假命题，则实数 $m$ 的取值范围为 ______.',
    '若命题“∀x∈{x|1≤x≤4}，不等式 x²-mx-m+15>0 恒成立”为假命题，则实数m的取值范围为____。',
    r'已知 $\neg(\forall x\in[1,4]:x^2-mx-m+15>0)$，求实数m的取值范围。',
    r'已知 $\lnot\left(\forall x\in[1,4]:x^2-mx-m+15>0\right)$，求m的取值范围。',
    '已知 ¬∀x∈[1,4]:x²-mx-m+15>0，则实数m的取值范围为____。',
    '若命题「对任意x∈[1,4]，x²-mx-m+15>0成立」是假命题，则实数m的取值范围为____。',
])
def test_uploaded_question_and_display_variants_keep_offsets(original):
    item = candidate(original=original)
    result = build(item)
    assert all(of_kind(result, kind) for kind in ("quantifier", "domain", "relation", "goal")), result
    assert not result["diagnostics"]
    assert_offsets(item, result)


def test_real_domain_prose_and_reversed_sides_are_checked_exactly():
    item = candidate('存在实数t，使得0≤t^2+m', '∀t∈ℝ:t^2+m<0')
    result = build(item)
    relation, = of_kind(result, "relation")
    assert relation["reading_transform"]["source_operator"] == "<="
    assert relation["reading_transform"]["target_operator"] == "<"
    assert_offsets(item, result)


@pytest.mark.parametrize("fact", [
    "∀x∈[1,4]:x^2-m*x-m+15>0",  # unchanged positive body must not bypass the negation matcher
    "∃x∈[1,4]:x^2-m*x-m+15<0",  # strictness
    "∃x∈[1,4]:x^2-m*x-m+15<=1",  # constant
    "∃x∈(1,4]:x^2-m*x-m+15<=0",  # domain
    "∃t∈[1,4]:t^2-m*t-m+15<=0",  # variable
])
def test_mismatched_normalized_facts_cannot_use_positive_body_fragments(fact):
    result = build(candidate(fact=fact))
    assert not of_kind(result, "quantifier")
    assert not of_kind(result, "relation")
    assert any(d["code"] == "d1.negation_not_mapped" for d in result["diagnostics"])
    assert of_kind(result, "goal")


@pytest.mark.parametrize("body", [
    '∀x∈[1,4]:x²-mx-m+15>0且x<4',
    '∀x∈[1,4]:x²-mx-m+15>0或x=4',
    '∀x∈[1,4]:若x²-mx-m+15>0则x<4',
    '∀x∈[1,4]:∃y∈ℝ:x²-mx-m+15>0',
    '¬∀x∈[1,4]:x²-mx-m+15>0',
    r'∀x∈[1,4]:x²-mx-m+15>\unknown{0}',
    '∀x∈[1,4]:(x²-mx-m+15)*x/x>0',
])
def test_compound_nested_and_unsupported_bodies_are_not_partially_negated(body):
    result = build(candidate(body))
    assert not of_kind(result, "relation")
    assert not of_kind(result, "quantifier")


@pytest.mark.parametrize("original", [
    '若命题“∀x∈[1,4]:x²-mx-m+15>0”不为假命题，则实数m的取值范围为____。',
    '判断命题“∀x∈[1,4]:x²-mx-m+15>0”是否为假命题，求m的取值范围。',
    '命题“∀x∈[1,4]:x²-mx-m+15>0”的否定为假命题，求m的取值范围。',
    '并非命题“∀x∈[1,4]:x²-mx-m+15>0”为假命题，求m的取值范围。',
    '命题p：“∀x∈[1,4]:x²-mx-m+15>0”；命题q为假命题，求m的取值范围。',
    '¬¬(∀x∈[1,4]:x²-mx-m+15>0)，求m的取值范围。',
    '¬(∀x∈[1,4]:x²-mx-m+15>0)为假命题，求m的取值范围。',
    '命题“∀x∈[1,4]:x²-mx-m+15>0”为假命题或m>0，求m的取值范围。',
    '命题“∀x∈[1,4]:x²-mx-m+15>0”为假命题，或者m>0，求m的取值范围。',
    '命题“∀x∈[1,4]:x²-mx-m+15>0”为假命题是否正确，求m的取值范围。',
    '并非¬(∀x∈[1,4]:x²-mx-m+15>0)，求m的取值范围。',
    '并非命题p：“∀x∈[1,4]:x²-mx-m+15>0”为假命题，求m的取值范围。',
    '¬(∀x∈[1,4]:x²-mx-m+15>0]，求m的取值范围。',
])
def test_no_negation_is_inferred_from_unasserted_or_other_statements(original):
    result = build(candidate(original=original))
    assert not any(f.get("reading_transform") for f in result["fragments"])
    assert not of_kind(result, "relation")


def test_function_definitions_and_sibling_scopes_remain_separate():
    item = {
        "original_text": '已知f(t)=t²+m。（1）若命题“∀x∈[0,1]:f(x)>0”为假命题，则实数m的取值范围为____。（2）对任意x∈[0,1]，f(x)>0成立，求m的取值范围。',
        "root": {"definitions": ["f(t)=t^2+m"], "children": [
            {"label": "（1）", "facts": ["∃x∈[0,1]:f(x)<=0"], "goals": [{"kind": "find_range", "symbol": "m"}]},
            {"label": "（2）", "facts": ["∀x∈[0,1]:f(x)>0"], "goals": [{"kind": "find_range", "symbol": "m"}]},
        ]},
    }
    first = build(item, target="/root/children/0/goals/0")
    second = build(item, target="/root/children/1/goals/0")
    assert of_kind(first, "relation")[0]["reading_transform"]["target_operator"] == "<="
    assert not any(f.get("reading_transform") for f in second["fragments"])
    assert of_kind(second, "relation")[0]["text"] == "f(x)>0"
    assert_offsets(item, first)
    assert_offsets(item, second)


def test_later_definition_does_not_retroactively_resolve_a_negated_formula():
    item = candidate('∀x∈[1,4]:f(x)>0', '∃x∈[1,4]:f(x)<=0')
    item['root']['definitions'] = ['f(t)=t^2-m*t-m+15']
    item['original_text'] += '其中f(t)=t²-mt-m+15。'
    assert not of_kind(build(item), "relation")


@pytest.mark.parametrize("spelling", ["m", "$m$", "参数 m", "实数 $ m $", r"实数 \(m\)"])
def test_fill_in_range_goals_do_not_require_qiu(spelling):
    item = candidate(original=f"则{spelling}的取值范围为____。")
    goal, = of_kind(build(item), "goal")
    assert goal["text"] == f"{spelling}的取值范围"


@pytest.mark.parametrize("spelling", ["am", "a m", "m_1", "m₁", "m²", "m+m", "$m+m$", "t"])
def test_fill_in_range_goals_still_require_the_complete_target_symbol(spelling):
    assert not of_kind(build(candidate(original=f"则实数{spelling}的取值范围为____。")), "goal")


def test_given_parameter_domain_is_not_a_range_request():
    assert not of_kind(build(candidate(original="已知实数m的取值范围为[0,1]。")), "goal")


def test_explicit_negation_preserves_half_open_domain_brackets():
    item = candidate(fact="∃x∈(1,4]:x^2-m*x-m+15<=0", original="¬(∀x∈(1,4]:x²-mx-m+15>0)，求m的取值范围。")
    result = build(item)
    assert of_kind(result, "quantifier")[0]["reading_transform"]["target_quantifier"] == "∃"
    assert not result["diagnostics"]
