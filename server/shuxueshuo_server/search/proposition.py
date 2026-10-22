"""Present a proposition conversion already proved by stage-two source matching.

No source expression is parsed here. The verified target features supply the
mathematics, and matching fragment metadata supplies the original assertion.
"""

import json
import re
from copy import deepcopy
from hashlib import sha256

from shuxueshuo_server.graph_lesson.stage_two.fragments import _scope_ranges

COMPLEMENT = {"<": ">=", "<=": ">", ">": "<=", ">=": "<"}
REVERSE = {"<": ">", "<=": ">=", ">": "<", ">=": "<="}
QUANTIFIER_COMPLEMENT = {"∀": "∃", "∃": "∀"}
QUANTIFIER_TEX = {"∀": r"\forall", "∃": r"\exists"}


def _validated(fragments, known):
    marked = [f for f in fragments if "reading_transform" in f]
    if not marked:
        return None
    transforms = [f["reading_transform"] for f in marked]
    first = transforms[0]
    if not isinstance(first, dict) or any(value != first for value in transforms):
        raise ValueError("inconsistent_metadata")
    kinds = [f["fragment_kind"] for f in marked]
    if sorted(kinds) != ["quantifier", "relation"]:
        raise ValueError("ambiguous_source_fragments")
    if first.get("kind") != "quantifier_negation":
        raise ValueError("unsupported_kind")
    source_q, target_q = first.get("source_quantifier"), first.get("target_quantifier")
    source_op, target_op = first.get("source_operator"), first.get("target_operator")
    if source_q not in QUANTIFIER_COMPLEMENT or QUANTIFIER_COMPLEMENT[source_q] != target_q:
        raise ValueError("inconsistent_quantifiers")
    if source_op not in COMPLEMENT or target_op not in COMPLEMENT:
        raise ValueError("unsupported_relation")
    # Stage two also proves matches with opposite sides (0 <= f becomes f < 0).
    if target_op not in (COMPLEMENT[source_op], REVERSE[COMPLEMENT[source_op]]):
        raise ValueError("inconsistent_operators")
    relation, domain, goal = known.get("relation"), known.get("domain"), known.get("goal")
    bound = known.get("bound_vars")
    if (not isinstance(relation, dict) or not isinstance(domain, dict) or not isinstance(goal, dict)
            or not isinstance(bound, list) or len(bound) != 1 or not isinstance(bound[0], str) or not bound[0]
            or not all(isinstance(relation.get(key), str) and relation[key] for key in ("lhs", "rhs"))
            or not isinstance(domain.get("expression"), str) or not domain["expression"]
            or goal.get("kind") not in ("find_range", "find_minimum", "find_maximum")
            or not isinstance(goal.get("symbol"), str) or not goal["symbol"] or goal["symbol"] == bound[0]):
        raise ValueError("incomplete_normalized_context")
    if known.get("quantifier") != target_q or relation.get("operator") != target_op:
        raise ValueError("normalized_context_mismatch")
    if "strict" in relation and relation["strict"] is not (target_op in ("<", ">")):
        raise ValueError("normalized_strictness_mismatch")
    return first


def _source_formulas(text, ranges):
    pairs = {"$": "$", "$$": "$$", r"\(": r"\)", r"\[": r"\]"}
    formulas = []
    for left, right in ranges:
        opened = None
        for match in re.finditer(r"(?<!\\)(?:\$+|\\[()[\]])", text[left:right]):
            delimiter, position = match.group(), left + match.start()
            if opened is None and delimiter in pairs:
                opened = (position, delimiter)
            elif opened is not None and delimiter == pairs[opened[1]]:
                formulas.append((opened[0], position, len(opened[1]), len(delimiter)))
                opened = None
            else:
                raise ValueError("source_math_delimiters_ambiguous")
        if opened is not None:
            raise ValueError("source_math_delimiters_ambiguous")
    return formulas


def _source_context(target, fragments, text, candidate, target_math):
    """Keep complete visible source scopes and replace only the verified assertion.

    The scope locator is the same one used to verify stage-two fragments. Math
    delimiter handling changes presentation boundaries, never mathematical meaning.
    """
    if candidate is not None:
        if candidate.get("original_text") != text:
            raise ValueError("source_text_mismatch")
        try:
            ranges = _scope_ranges(candidate, target)
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ValueError("source_scope_ambiguous") from exc
    elif "/children/" in target:
        raise ValueError("source_scope_required")
    else:
        ranges = [(0, len(text))]
    fragment = next(f for f in fragments if f["fragment_kind"] == "quantifier" and f.get("reading_transform"))
    start, end = fragment["start"], fragment["end"]
    if not (0 <= start < end <= len(text)) or text[start:end] != fragment["text"]:
        raise ValueError("source_fragment_mismatch")
    formulas = _source_formulas(text, ranges)
    inside_formula = any(left + opening <= start and end <= right for left, right, opening, _ in formulas)
    if inside_formula:
        replacement = target_math[1:-1]
    else:
        # A verified assertion can start/end inside different formulas.
        # Expand just its partially covered delimiters before inserting one formula.
        for left, right, opening, closing in formulas:
            if left < start < right + closing:
                if start < left + opening or text[left + opening:start].strip():
                    raise ValueError("source_math_boundary_ambiguous")
                start = left
            if left <= end - 1 < right + closing and end < right + closing:
                if end > right or text[end:right].strip():
                    raise ValueError("source_math_boundary_ambiguous")
                end = right + closing
        assertion_suffix = re.match(r"\s*(?:成立|[为是]真(?:命题)?)", text[end:])
        replacement = target_math + ("" if assertion_suffix else "成立")
    containing = [(left, right) for left, right in ranges if left <= start < end <= right]
    if len(containing) != 1:
        raise ValueError("source_assertion_outside_scope")
    source_spans = [{"start": left, "end": right, "text": text[left:right]} for left, right in ranges]
    normalized = [text[left:start] + replacement + text[end:right] if (left, right) == containing[0]
                  else text[left:right] for left, right in ranges]
    source_text = "\n".join(span["text"].strip() for span in source_spans if span["text"].strip())
    normalized_text = "\n".join(part.strip() for part in normalized if part.strip())
    return {"source_spans": source_spans, "source_context": source_text,
            "source_meaning": source_text, "normalized_text": normalized_text}


def transformation(target, fragments, known, render, *, text, candidate=None):
    """Return verified teaching data, or an explicit diagnostic on bad metadata."""
    try:
        metadata = _validated(fragments, known)
    except (ValueError, TypeError) as exc:
        return None, [{"code": "d1.transformation_invalid", "target_ref": target, "reason": str(exc)}]
    if metadata is None:
        return None, []
    context = deepcopy(known)
    variable, domain = context["bound_vars"][0], context["domain"]["expression"]
    relation = context["relation"]
    source_q, target_q = metadata["source_quantifier"], metadata["target_quantifier"]
    source_op, target_op = metadata["source_operator"], metadata["target_operator"]
    source_relation = {"lhs": relation["lhs"], "operator": source_op, "rhs": relation["rhs"]}
    if target_op != COMPLEMENT[source_op]:
        source_relation.update(lhs=relation["rhs"], rhs=relation["lhs"])

    def quantified(quantifier, body):
        return (rf"{QUANTIFIER_TEX[quantifier]} {render(variable)}\in {render(domain)},\quad "
                f"{render(body['lhs'])}{render(body['operator'])}{render(body['rhs'])}")

    original = quantified(source_q, source_relation)
    source = rf"\neg\left({original}\right)"
    normalized = quantified(target_q, relation)
    try:
        source_context = _source_context(target, fragments, text, candidate, f"${normalized}$")
    except (ValueError, TypeError) as exc:
        return None, [{"code": "d1.transformation_invalid", "target_ref": target, "reason": str(exc)}]
    source_name, target_name = ("全称", "存在") if source_q == "∀" else ("存在", "全称")
    quantifier_reason = (f"全称命题为假，说明至少有一个 ${render(variable)}$ 不满足原关系"
                         if source_q == "∀" else
                         f"存在命题为假，说明每一个 ${render(variable)}$ 都不满足原关系")
    explanation = (f"{quantifier_reason}；量词由{source_name}变为{target_name}，"
                   f"关系 ${render(source_op)}$ 取反为 ${render(COMPLEMENT[source_op])}$，"
                   "变量的取值范围和所求保持不变。")
    if target_op != COMPLEMENT[source_op]:
        explanation += "交换不等式两边后，不等号方向随之改变。"
    # Distractors isolate changing neither component, only the operator, and
    # only the quantifier, always in the target expression's orientation.
    original_relation = {**relation, "operator": COMPLEMENT[target_op]}
    options = [
        {"id": "converted", "text": f"${normalized}$", "correct": True, "violates": None, "feedback": ""},
        {"id": "quantifier_only", "text": f"${quantified(target_q, original_relation)}$", "correct": False,
         "violates": "relation", "feedback": f"量词已经交换，但不等号还没有取反。{explanation}"},
        {"id": "relation_only", "text": f"${quantified(source_q, relation)}$", "correct": False,
         "violates": "quantifier", "feedback": f"不等号已经取反，但量词还没有交换。{explanation}"},
        {"id": "unchanged", "text": f"${quantified(source_q, original_relation)}$", "correct": False,
         "violates": "quantifier_and_relation", "feedback": f"这仍是原命题，题目给出的却是原命题为假。{explanation}"},
    ]
    options.sort(key=lambda option: sha256((target + option["text"]).encode()).hexdigest())
    refs = list(dict.fromkeys(["quantifiers"] + [ref for f in fragments if f.get("reading_transform")
                                                for ref in f["knowledge_refs"]]))
    value = {**metadata, "source_relation": source_relation, "source_proposition_math": f"${original}$",
             "source_math": f"${source}$", "target_math": f"${normalized}$",
             "equivalence": f"${source} \\Longleftrightarrow {normalized}$",
             **source_context, "normalized_context": context,
             "explanation": explanation, "options": options, "knowledge_refs": refs}
    evidence = [{key: f.get(key) for key in ("id", "fragment_kind", "start", "end", "text", "reading_transform")}
                for f in fragments]
    value["signature"] = sha256(json.dumps([value, evidence], ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]
    return value, []
