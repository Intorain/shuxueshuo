import re
from copy import deepcopy

import pytest

from shuxueshuo_server.graph_lesson.stage_one.features import extract_features
from shuxueshuo_server.graph_lesson.stage_two.fragments import build_d1
from shuxueshuo_server.graph_lesson.stage_two.recognition import derive_knowledge
from shuxueshuo_server.search.lesson import d1_rows, present_lesson, run_stage_two, tex
from shuxueshuo_server.search.walk import walk

TARGET = "/root/goals/0"


def _reading(source_quantifier="∀", source_operator=">", variable="x", parameter="m", domain="[1,4]"):
    target_quantifier = {"∀": "∃", "∃": "∀"}[source_quantifier]
    target_operator = {">": "<=", ">=": "<", "<": ">=", "<=": ">"}[source_operator]
    lhs = f"{variable}^2-{parameter}*{variable}-{parameter}+15"
    formula = f"{lhs}{source_operator}0"
    statement = f"命题 ${source_quantifier}{variable}∈{domain}:{formula}$ 为假命题"
    request = f"求实数 ${parameter}$ 的取值范围"
    text = f"{statement}，{request}。"
    transform = {"kind": "quantifier_negation", "source_quantifier": source_quantifier,
                 "source_operator": source_operator, "target_quantifier": target_quantifier,
                 "target_operator": target_operator}

    def fragment(kind, quote):
        start = text.index(quote)
        return {"id": f"d1:{kind}", "fragment_kind": kind, "start": start, "end": start + len(quote),
                "text": quote, "knowledge_refs": ["knowledge-quantifier"],
                **({"reading_transform": deepcopy(transform)} if kind in ("quantifier", "relation") else {})}

    fragments = [fragment("quantifier", statement), fragment("domain", f"{variable}∈{domain}"),
                 fragment("relation", formula), fragment("goal", request)]
    known = {"bound_vars": [variable], "quantifier": target_quantifier, "domain": {"expression": domain},
             "relation": {"lhs": lhs, "operator": target_operator, "rhs": "0"},
             "goal": {"kind": "find_range", "symbol": parameter},
             "degree_in_bound": {"degree": 2, "degree_kind": "exact"}}
    return text, fragments, known


def _correct(row):
    return next(option["text"] for option in row["options"] if option["correct"])


@pytest.mark.parametrize("source_quantifier", ["∀", "∃"])
@pytest.mark.parametrize("source_operator", [">", ">=", "<", "<="])
@pytest.mark.parametrize(("variable", "parameter", "domain"), [
    ("x", "m", "[1,4]"), ("t", "k", "(1,5]"), ("u", "b", "ℝ"), ("z", "c", "(-∞,2)"),
    ("x", "m", "[1,1]"),
])
def test_original_reading_is_separate_from_the_joint_quantifier_and_inequality_conversion(
    source_quantifier, source_operator, variable, parameter, domain,
):
    text, fragments, known = _reading(source_quantifier, source_operator, variable, parameter, domain)
    result = d1_rows(TARGET, fragments, known, text)
    assert [row["kind"] for row in result["rows"]] == ["quantifier", "relation", "goal"]
    quantifier, relation, goal = result["rows"]
    conversion = result["transformation"]
    original = conversion["source_relation"]
    expression = f"${tex(original['lhs'])}{tex(original['operator'])}{tex(original['rhs'])}$"
    correct = _correct(quantifier)
    if source_quantifier == "∀":
        assert f"每一个 ${variable}$" in correct or f"所有实数 ${variable}$" in correct
        assert "全称命题为假，说明至少有一个" in conversion["explanation"]
    else:
        assert f"能找到一个 ${variable}$" in correct or f"能找到一个实数 ${variable}$" in correct
        assert "存在命题为假，说明每一个" in conversion["explanation"]
    assert correct.startswith("原命题要求：") and correct.endswith("题目说明这个命题为假")
    assert _correct(relation).startswith(f"原命题中的关系为 {expression}；")
    assert f"关于 ${variable}$ 的一元二次不等式，${parameter}$ 看作常数" in _correct(relation)
    assert _correct(goal) == f"求参数 ${parameter}$ 能取哪些值"
    assert "为假" in result["summary"] and "取反后" not in result["summary"]
    assert conversion["target_math"] not in result["summary"]
    assert conversion["source_quantifier"] == source_quantifier
    assert conversion["source_operator"] == source_operator
    assert conversion["normalized_context"] == known
    assert conversion["normalized_context"] is not known
    assert conversion["normalized_context"]["relation"] is not known["relation"]
    assert conversion["normalized_context"]["goal"] == known["goal"]
    assert _correct(conversion) == conversion["target_math"]
    assert f"\\in {tex(domain)}," in conversion["target_math"]
    assert f"{tex(known['relation']['operator'])}0$" in conversion["target_math"]
    assert r"\Longleftrightarrow" in conversion["equivalence"]
    assert "quantifiers" in conversion["knowledge_refs"]
    assert {o["violates"] for o in conversion["options"] if not o["correct"]} == {
        "quantifier", "relation", "quantifier_and_relation",
    }
    assert len({o["text"] for o in conversion["options"]}) == 4
    for row in result["rows"]:
        assert sum(option["correct"] for option in row["options"]) == 1
        assert all(option["violates"] and option["feedback"] for option in row["options"] if not option["correct"])
    feedback = [option["feedback"] for option in quantifier["options"] if not option["correct"]]
    assert all("为假" in value and "取反" not in value for value in feedback)
    assert all("“任意”“恒成立”" not in value and "“存在”“有解”" not in value for value in feedback)


def test_negation_quote_keeps_the_false_suffix_when_the_domain_is_inside_it():
    text, fragments, known = _reading()
    result = d1_rows(TARGET, fragments, known, text)
    quantifier, relation, _ = result["rows"]
    assert quantifier["quote"] == [{"start": fragments[0]["start"], "end": fragments[0]["end"],
                                    "text": fragments[0]["text"]}]
    assert quantifier["quote"][0]["text"].endswith("为假命题")
    assert quantifier["fragment_ids"] == ["d1:quantifier", "d1:domain"]
    assert relation["quote"][0]["text"] == f"${fragments[2]['text']}$"


def test_negation_metadata_participates_in_the_reading_signature():
    text, fragments, known = _reading()
    negated = d1_rows(TARGET, fragments, known, text)
    plain_fragments = deepcopy(fragments)
    for fragment in plain_fragments:
        fragment.pop("reading_transform", None)
    plain = d1_rows(TARGET, plain_fragments, known, text)
    assert "transformation" not in plain
    assert [row["signature"] for row in negated["rows"][:2]] != [row["signature"] for row in plain["rows"][:2]]
    assert all(a["signature"] != b["signature"] for a, b in zip(negated["rows"][:2], plain["rows"][:2]))
    assert negated["rows"][2] == plain["rows"][2]
    assert _correct(plain["rows"][0]) == "在 $[1,4]$ 里能找到一个 $x$ 满足就行"
    assert _correct(plain["rows"][1]) == "关于 $x$ 的一元二次不等式，$m$ 看作常数"
    reordered = deepcopy(fragments)
    for fragment in reordered:
        if "reading_transform" in fragment:
            fragment["reading_transform"] = dict(reversed(list(fragment["reading_transform"].items())))
    assert d1_rows(TARGET, reordered, known, text) == negated


def test_negated_quantifier_signature_also_binds_the_complement_expression():
    text, fragments, known = _reading()
    original = d1_rows(TARGET, fragments, known, text)
    changed = deepcopy(known)
    changed["relation"]["rhs"] = "2"
    updated = d1_rows(TARGET, fragments, changed, text)
    assert updated["rows"][0]["signature"] != original["rows"][0]["signature"]
    assert updated["rows"][1]["signature"] != original["rows"][1]["signature"]
    assert updated["transformation"]["signature"] != original["transformation"]["signature"]


def test_missing_normalized_relation_omits_the_transformed_rows_instead_of_guessing():
    text, fragments, known = _reading()
    known.pop("relation")
    result = d1_rows(TARGET, fragments, known, text)
    assert [row["kind"] for row in result["rows"]] == ["goal"]
    assert "transformation" not in result
    assert result["diagnostics"] == [{"code": "d1.transformation_invalid", "target_ref": TARGET,
                                      "reason": "incomplete_normalized_context"}]


@pytest.mark.parametrize("change", [
    "mismatched_fragments", "missing_relation_metadata", "duplicate_quantifier", "unchanged_quantifier",
    "wrong_strictness", "different_known_quantifier", "different_known_operator", "unknown_kind", "null_metadata",
])
def test_inconsistent_conversion_metadata_has_a_diagnostic_and_cannot_walk_normalized_type(change):
    text, fragments, known = _reading()
    if change == "mismatched_fragments":
        fragments[2]["reading_transform"]["source_quantifier"] = "∃"
    elif change == "missing_relation_metadata":
        fragments[2].pop("reading_transform")
    elif change == "duplicate_quantifier":
        fragments.append(deepcopy(fragments[0]))
    elif change == "unchanged_quantifier":
        for fragment in (fragments[0], fragments[2]):
            fragment["reading_transform"]["target_quantifier"] = "∀"
    elif change == "wrong_strictness":
        for fragment in (fragments[0], fragments[2]):
            fragment["reading_transform"]["target_operator"] = "<"
    elif change == "different_known_quantifier":
        known["quantifier"] = "∀"
    elif change == "different_known_operator":
        known["relation"]["operator"] = "<"
    elif change == "unknown_kind":
        for fragment in (fragments[0], fragments[2]):
            fragment["reading_transform"]["kind"] = "not_verified"
    else:
        fragments[0]["reading_transform"] = None
    reading = d1_rows(TARGET, fragments, known, text)
    assert "transformation" not in reading
    assert reading["diagnostics"][0]["code"] == "d1.transformation_invalid"
    assert [row["kind"] for row in reading["rows"]] == ["goal"]
    goal = {"status": "resolved", "d1": reading, "d2": [{"type_id": "type-quantified-quadratic"}],
            "primary": "type-quantified-quadratic"}
    assert walk(goal, text, "invalid") is None


@pytest.mark.parametrize("change", ["domain", "goal", "roles", "source"])
def test_transformation_signature_binds_domain_goal_symbol_roles_and_source(change):
    text, fragments, known = _reading()
    before = d1_rows(TARGET, fragments, known, text)["transformation"]
    if change == "domain":
        known["domain"]["expression"] = "(1,4]"
    elif change == "goal":
        known["goal"]["kind"] = "find_minimum"
    elif change == "roles":
        known["free_vars"] = ["m"]
    else:
        text += "另有 $m>20$。"
    after = d1_rows(TARGET, fragments, known, text)["transformation"]
    assert before["signature"] != after["signature"]


@pytest.mark.parametrize(("kind", "noun"), [("find_minimum", "最小值"), ("find_maximum", "最大值")])
def test_conversion_preserves_requested_extremum(kind, noun):
    text, fragments, known = _reading(variable="m", parameter="x", domain="[2,7)")
    known["goal"]["kind"] = kind
    text = text.replace("取值范围", noun)
    fragments[-1]["text"] = fragments[-1]["text"].replace("取值范围", noun)
    fragments[-1]["end"] -= 1
    result = d1_rows(TARGET, fragments, known, text)
    conversion = result["transformation"]
    assert conversion["source_meaning"].endswith(f"求实数 $x$ 的{noun}。")
    assert conversion["normalized_text"].endswith(f"求实数 $x$ 的{noun}。")
    assert conversion["normalized_context"]["bound_vars"] == ["m"]
    assert conversion["normalized_context"]["goal"] == {"kind": kind, "symbol": "x"}
    assert "取值范围" not in conversion["normalized_text"]


def test_no_conversion_is_inferred_without_verified_fragment_metadata():
    text, fragments, known = _reading()
    for fragment in fragments:
        fragment.pop("reading_transform", None)
    result = d1_rows(TARGET, fragments, known, text)
    assert "transformation" not in result and "diagnostics" not in result
    assert len(result["rows"]) == 3


def test_original_reading_uses_the_verified_source_pair_instead_of_an_earlier_plain_fragment():
    text, fragments, known = _reading()
    prefix = "$∃x∈[1,4]$，$x^2-m*x-m+15<=0$。"
    for fragment in fragments:
        fragment["start"] += len(prefix)
        fragment["end"] += len(prefix)
    plain = []
    for kind, quote in (("quantifier", "∃x∈[1,4]"), ("relation", "x^2-m*x-m+15<=0")):
        start = prefix.index(quote)
        plain.append({"id": f"plain:{kind}", "fragment_kind": kind, "start": start, "end": start + len(quote),
                      "text": quote, "knowledge_refs": ["quantifiers"]})
    result = d1_rows(TARGET, plain + fragments, known, prefix + text)
    assert result["rows"][0]["fragment_ids"] == ["d1:quantifier", "d1:domain"]
    assert result["rows"][1]["fragment_ids"] == ["d1:relation"]
    assert "为假命题" in result["rows"][0]["quote"][0]["text"]


def _scoped_reading(candidate, target=TARGET):
    extracted = extract_features(candidate)
    assert extracted["ok"], extracted["diagnostics"]
    features = [feature for feature in extracted["features"] if feature["target_ref"] == target]
    located = build_d1(candidate, target, features, derive_knowledge(features))
    assert not located["diagnostics"], located["diagnostics"]
    known = {feature["feature_id"]: feature["value"] for feature in features if feature["status"] == "known"}
    return d1_rows(target, located["fragments"], known, candidate["original_text"], candidate=candidate)


@pytest.mark.parametrize("statement", [
    "命题“∀x∈[1,4]:x²-mx-m+15>0”为假命题",
    r"$\neg(\forall x\in[1,4]:x^2-mx-m+15>0)$",
    r"命题“$\forall x\in[1,4]$，$x^2-mx-m+15>0$”为假命题",
])
def test_conversion_keeps_extra_conditions_and_replaces_only_verified_assertion(statement):
    text = f"已知 $m>20$，若{statement}，且 $m<30$，求实数 $m$ 的取值范围。"
    candidate = {"original_text": text, "root": {
        "facts": ["m>20", "m<30", "∃x∈[1,4]:x^2-m*x-m+15<=0"],
        "goals": [{"kind": "find_range", "symbol": "m"}],
    }}
    conversion = _scoped_reading(candidate)["transformation"]
    assert conversion["source_meaning"] == text
    assert conversion["source_context"] == text
    assert conversion["source_spans"] == [{"start": 0, "end": len(text), "text": text}]
    normalized = conversion["normalized_text"]
    assert "$m>20$" in normalized and "$m<30$" in normalized
    assert normalized.endswith("求实数 $m$ 的取值范围。")
    assert "为假" not in normalized and r"\neg" not in normalized and "∀" not in normalized
    assert conversion["target_math"] in normalized
    assert len(re.findall(r"(?<!\\)\$", normalized)) % 2 == 0
    assert "$$" not in normalized


@pytest.mark.parametrize(("opening", "closing"), [("$", "$"), ("$$", "$$"), (r"\(", r"\)"), (r"\[", r"\]")])
def test_conversion_preserves_other_content_inside_the_same_math_delimiters(opening, closing):
    text = "若 " + opening + r"m>20,\neg(\forall x\in[1,4]:x^2-mx-m+15>0)" + closing + "，求实数m的取值范围。"
    candidate = {"original_text": text, "root": {"facts": ["m>20", "∃x∈[1,4]:x^2-m*x-m+15<=0"],
                 "goals": [{"kind": "find_range", "symbol": "m"}]}}
    conversion = _scoped_reading(candidate)["transformation"]
    assert conversion["normalized_text"] == (
        "若 " + opening + "m>20," + conversion["target_math"][1:-1] + closing + "，求实数m的取值范围。"
    )


@pytest.mark.parametrize(("opening", "closing"), [("$", "$"), ("$$", "$$"), (r"\(", r"\)"), (r"\[", r"\]")])
@pytest.mark.parametrize("suffix", ["", "成立", "为真命题"])
def test_conversion_preserves_inline_and_display_delimiters_without_nested_math(opening, closing, suffix):
    statement = opening + r"\neg(\forall x\in[1,4]:x^2-mx-m+15>0)" + closing
    text = f"若 {statement}{suffix}，求实数m的取值范围。"
    candidate = {"original_text": text, "root": {"facts": ["∃x∈[1,4]:x^2-m*x-m+15<=0"],
                 "goals": [{"kind": "find_range", "symbol": "m"}]}}
    conversion = _scoped_reading(candidate)["transformation"]
    assert conversion["normalized_text"] == (
        "若 " + opening + conversion["target_math"][1:-1] + closing + suffix + "，求实数m的取值范围。"
    )


@pytest.mark.parametrize("suffix", ["成立", "为真命题", "是真命题"])
def test_conversion_does_not_duplicate_an_existing_truth_suffix(suffix):
    text = f"若 ¬(∀x∈[1,4]:x^2-mx-m+15>0){suffix}，求实数m的取值范围。"
    candidate = {"original_text": text, "root": {"facts": ["∃x∈[1,4]:x^2-m*x-m+15<=0"],
                 "goals": [{"kind": "find_range", "symbol": "m"}]}}
    conversion = _scoped_reading(candidate)["transformation"]
    assert conversion["normalized_text"] == "若 " + conversion["target_math"] + suffix + "，求实数m的取值范围。"


@pytest.mark.parametrize("side", ["prefix", "suffix"])
def test_cross_formula_replacement_never_swallows_content_outside_the_verified_span(side):
    _, fragments, known = _reading()
    formula = fragments[2]["text"]
    if side == "prefix":
        statement = f"∀x∈[1,4]:{formula}$为假命题"
        text = f"$m>20,{statement}，求实数 $m$ 的取值范围。"
    else:
        statement = f"命题 $∀x∈[1,4]:{formula} 为假"
        text = f"{statement},m<30$，求实数 $m$ 的取值范围。"
    fragments[0]["text"] = statement
    for fragment in fragments:
        fragment["start"] = text.index(fragment["text"])
        fragment["end"] = fragment["start"] + len(fragment["text"])
    reading = d1_rows(TARGET, fragments, known, text)
    assert "transformation" not in reading
    assert reading["diagnostics"][0]["reason"] == "source_math_boundary_ambiguous"


def test_conversion_keeps_ancestor_and_local_conditions_without_sibling_conditions():
    text = ("已知 $m>20$，命题“∀x∈[1,4]:x²-mx-m+15>0”为假命题。"
            "（1）另有 $m<30$，求实数m的取值范围。（2）另有 $m>100$，求实数m的取值范围。")
    candidate = {"original_text": text, "root": {
        "facts": ["m>20", "∃x∈[1,4]:x^2-m*x-m+15<=0"], "children": [
            {"label": "（1）", "facts": ["m<30"], "goals": [{"kind": "find_range", "symbol": "m"}]},
            {"label": "（2）", "facts": ["m>100"], "goals": [{"kind": "find_range", "symbol": "m"}]},
        ],
    }}
    for index, local, sibling in ((0, "$m<30$", "$m>100$"), (1, "$m>100$", "$m<30$")):
        conversion = _scoped_reading(candidate, f"/root/children/{index}/goals/0")["transformation"]
        for key in ("source_meaning", "normalized_text"):
            assert "$m>20$" in conversion[key] and local in conversion[key]
            assert sibling not in conversion[key]
        assert "为假命题" in conversion["source_meaning"]
        assert "为假命题" not in conversion["normalized_text"]
        assert len(conversion["source_spans"]) == 2


@pytest.mark.parametrize(("change", "reason"), [
    ("text", "source_text_mismatch"), ("missing_label", "source_scope_ambiguous"),
    ("missing_candidate", "source_scope_required"), ("fragment", "source_fragment_mismatch"),
    ("dollar", "source_math_delimiters_ambiguous"),
])
def test_unsafe_source_scope_does_not_fall_back_to_incomplete_normalization(change, reason):
    text, fragments, known = _reading()
    candidate = {"original_text": text, "root": {"goals": [{"kind": "find_range", "symbol": "m"}]}}
    target = TARGET
    if change == "text":
        candidate["original_text"] = "不同版本。" + text
    elif change == "missing_label":
        candidate["root"] = {"children": [{"label": "（1）", "goals": [{"kind": "find_range", "symbol": "m"}]}]}
        target = "/root/children/0/goals/0"
    elif change == "missing_candidate":
        target, candidate = "/root/children/0/goals/0", None
    elif change == "fragment":
        fragments[0]["text"] += "。"
    else:
        text += "$"
        candidate["original_text"] = text
    result = d1_rows(target, fragments, known, text, candidate=candidate)
    assert "transformation" not in result
    assert result["diagnostics"][0]["reason"] == reason


@pytest.mark.parametrize(("original", "fact", "parameter", "explanation", "marker"), [
    ("若命题“∀x∈{x|1≤x≤4}:x²-mx-m+15>0”为假命题，则实数 m 的取值范围是____。",
     "∃x∈[1,4]:x^2-m*x-m+15<=0", "m", "全称命题为假，说明至少有一个", "为假命题"),
    ("命题“∃t∈[1,4]:t²-kt-k+15≤0”为假命题，求参数 k 的取值范围。",
     "∀t∈[1,4]:t^2-k*t-k+15>0", "k", "存在命题为假，说明每一个 $t$ 都不满足原关系", "为假命题"),
    ("若 ¬(∀u∈ℝ:u²-bu-b+15≥0)，求实数 b 的取值范围。",
     "∃u∈ℝ:u^2-b*u-b+15<0", "b", "全称命题为假，说明至少有一个", "¬"),
    (r"若 $\neg(\exists z\in\mathbb R:z^2-cz-c+15<0)$，求实数 c 的取值范围。",
     "∀z∈ℝ:z^2-c*z-c+15>=0", "c", "存在命题为假，说明每一个 $z$ 都不满足原关系", r"\neg"),
    ("命题“存在实数t，使得0≤t^2+m”为假命题，求实数m的取值范围。",
     "∀t∈ℝ:t^2+m<0", "m", "存在命题为假，说明每一个 $t$ 都不满足原关系", "为假命题"),
])
def test_stage_two_negation_fragments_become_source_reading_and_verified_conversion(
    original, fact, parameter, explanation, marker,
):
    candidate = {"original_text": original,
                 "root": {"facts": [fact], "goals": [{"kind": "find_range", "symbol": parameter}]}}
    extracted = extract_features(candidate)
    assert extracted["ok"], extracted["diagnostics"]
    features = extracted["features"]
    located = build_d1(candidate, TARGET, features, derive_knowledge(features))
    assert not located["diagnostics"], located["diagnostics"]
    known = {feature["feature_id"]: feature["value"] for feature in features if feature["status"] == "known"}
    reading = d1_rows(TARGET, located["fragments"], known, original)
    assert [row["kind"] for row in reading["rows"]] == ["quantifier", "relation", "goal"]
    assert explanation in reading["transformation"]["explanation"]
    assert marker in reading["rows"][0]["quote"][0]["text"]
    assert _correct(reading["rows"][1]).startswith("原命题中的关系为 ")
    assert marker in reading["summary"] and "取反后" not in reading["summary"]
    assert reading["transformation"]["normalized_context"] == known
    if "0≤" in original:
        assert reading["transformation"]["source_relation"] == {
            "lhs": known["relation"]["rhs"], "rhs": known["relation"]["lhs"], "operator": "<=",
        }
        assert "交换不等式两边" in reading["transformation"]["explanation"]


def test_false_proposition_search_lesson_starts_with_reading_without_an_llm(tmp_path):
    candidate = {
        "original_text": "若命题“∀x∈{x|1≤x≤4}:x²-mx-m+15>0”为假命题，则实数 m 的取值范围是____。",
        "root": {"facts": ["∃x∈[1,4]:x^2-m*x-m+15<=0"], "goals": [{"kind": "find_range", "symbol": "m"}]},
    }
    extracted = extract_features(candidate)
    assert extracted["ok"], extracted["diagnostics"]
    stage_one = {"status": "reviewed_candidate", "source_reviewed": True, "candidate": candidate,
                 "features": extracted["features"], "features_ok": True}
    snapshot = deepcopy(stage_one)

    def no_llm():
        raise AssertionError("this uniquely supported type does not need an LLM")

    directory = tmp_path / "problem"
    directory.mkdir()
    stage_two = run_stage_two(directory, stage_one, provider=no_llm, unsupported_root=tmp_path / "unsupported")
    (goal,) = present_lesson(stage_two, extracted["features"], candidate["original_text"], candidate=candidate)["goals"]
    assert goal["status"] == "resolved"
    bundle, replay = goal["walk"]["bundle"], goal["walk"]["replay"]
    intro = bundle["intro"]
    assert [step["id"] for step in intro] == ["D1", "D1-transform", "D2"]
    assert len(intro[0]["interaction"]["slots"]) == 3
    assert len(intro[0]["expected_answer"]["terms"]) == 3
    assert "题目说明这个命题为假" in replay["actions"][0]["reason"]
    transformation = goal["d1"]["transformation"]
    step = intro[1]
    assert step["title"] == "命题转化" and step["interaction"]["type"] == "choice"
    # In a singleton domain, changing only the relation may happen to be
    # equivalent too. This question grades the general negation rule itself.
    assert "按量词命题的否定规则，量词和关系应怎样同时改写" in step["question"]
    assert "等价条件是哪一个" not in step["question"]
    assert step["expected_answer"] == {"one_of": ["converted"]}
    assert len(step["interaction"]["options"]) == 4
    assert all(o.get("feedback") for o in step["interaction"]["options"] if o["value"] != "converted")
    assert step["effects"]["nodes"] == ["quantifiers"]
    assert transformation["equivalence"] in step["effects"]["results"]
    assert [action["decision"] for action in replay["actions"]] == ["D1", "D1-transform", "D2"]
    assert replay["actions"][1]["answer"] == "converted"
    assert transformation["equivalence"] in replay["actions"][1]["reason"]
    assert bundle["problem"]["text"] == bundle["problem"]["source_text"] == candidate["original_text"]
    assert bundle["problem"]["normalization_decision"] == "D1-transform"
    assert bundle["problem"]["source_meaning"] == transformation["source_meaning"]
    assert bundle["problem"]["normalized_text"] == transformation["normalized_text"]
    assert intro[2]["question"].startswith(f"已转化为：{transformation['normalized_text']}")
    assert replay["bundleVersion"] == bundle["bundleVersion"]
    assert stage_one == snapshot
