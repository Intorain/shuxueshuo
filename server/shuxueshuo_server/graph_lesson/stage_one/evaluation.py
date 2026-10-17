"""Independent benchmark evaluation. This module never builds model requests."""

import json
import re
import unicodedata
from hashlib import sha256
from pathlib import Path

from shuxueshuo_server.problem_understanding.algebra import scalar_expression
from shuxueshuo_server.problem_understanding.notation_parser import parse
from shuxueshuo_server.problem_understanding.notation_semantics import (
    bounded_expand,
    compare_roots,
)

from .extraction import validate_candidate
from .features import conjunct_quantifiers

ACCEPTANCE = "graph-stage-one-acceptance/v4"
FEATURE_EXPECTATIONS = "graph-stage-one-feature-expectations/v2"
FIXTURE_FILES = (
    "problem.md",
    "source.png",
    "source-manifest.json",
    "notation.gold.json",
    "features.gold.json",
    "acceptance.json",
)
GOAL_KEYS = {
    "target_ref",
    "required_goal",
    "required_quantifier",
    "required_bound_variable",
    "required_domain",
    "required_features",
}
_DISPLAY = (
    (r"\left", ""),
    (r"\right", ""),
    (r"\mathbb{R}", "ℝ"),
    (r"\mathbb R", "ℝ"),
    (r"\leq", "≤"),
    (r"\geq", "≥"),
    (r"\le", "≤"),
    (r"\ge", "≥"),
    (r"\forall", "∀"),
    (r"\exists", "∃"),
    (r"\infty", "∞"),
    (r"\in", "∈"),
    (r"\mid", "|"),
    (r"\vert", "|"),
    (r"\quad", ""),
    (r"\,", ""),
    (r"\;", ""),
    (r"\(", ""),
    (r"\)", ""),
    (r"\{", "{"),
    (r"\}", "}"),
    ("²", "^2"),
    ("³", "^3"),
    ("−", "-"),
    ("（", "("),
    ("）", ")"),
)
_FULLWIDTH = str.maketrans("，。；：！？", ",.;:!?")
_PROSE_ONLY = set("、“”‘’「」\"")
_AMBIGUOUS_PUNCTUATION = set(",.;:!?")
_MATH_CHARS = set("()[]{}+-*/^=<>|∞ℝ∈≤≥∀∃_'")


def _math_char(char):
    return (char.isascii() and char.isalnum()) or char in _MATH_CHARS


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def normalized_transcription(text):
    """Compare wording and formulae; layout, TeX spelling and prose punctuation are display only.

    Punctuation between two math characters (1.5, [1,2], ∀x∈ℝ:…) is kept. The
    decision ignores $ delimiters, so plain and delimited transcriptions agree.
    """
    for before, after in _DISPLAY:
        text = text.replace(before, after)
    text = re.sub(r"\\(?:text|mathrm)\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"(?<=\^)\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"\\(?=\s)", "", text)
    text = "".join(
        char
        for char in text.translate(_FULLWIDTH)
        if not char.isspace() and char not in "$*" and char not in _PROSE_ONLY
    )
    kept = [
        char
        for index, char in enumerate(text)
        if char not in _AMBIGUOUS_PUNCTUATION
        or (
            0 < index < len(text) - 1
            and _math_char(text[index - 1])
            and _math_char(text[index + 1])
        )
    ]
    return unicodedata.normalize("NFC", "".join(kept))


def math_equal(expected, actual):
    if expected == actual:
        return True
    if not isinstance(expected, str) or not isinstance(actual, str):
        return False
    names_a = set(re.findall(r"[A-Za-z][A-Za-z0-9_]*", expected)) - {"sqrt"}
    names_b = set(re.findall(r"[A-Za-z][A-Za-z0-9_]*", actual)) - {"sqrt"}
    try:
        obligations_a, obligations_b = [], []
        a = scalar_expression(
            expected, names=sorted(names_a), obligations=obligations_a
        )
        b = scalar_expression(actual, names=sorted(names_b), obligations=obligations_b)
        return obligations_a == obligations_b and bounded_expand(a - b) == 0
    except (ValueError, TypeError, RecursionError):
        return False


def _domain_equal(expected, actual):
    if expected == actual:
        return True
    if not isinstance(expected, str) or not isinstance(actual, str):
        return False
    return compare_roots({"facts": [f"v∈{expected}"]}, {"facts": [f"v∈{actual}"]})["ok"]


def _feature_rows(features):
    """Index feature rows by (goal pointer, feature id)."""
    return {
        (row["target_ref"], row["feature_id"]): {
            key: value
            for key, value in row.items()
            if key not in {"feature_id", "target_ref"}
        }
        for row in features.get("features", [])
    }


def goal_pointers(root, path="/root"):
    pointers = [f"{path}/goals/{index}" for index in range(len(root.get("goals", [])))]
    for index, child in enumerate(root.get("children", [])):
        pointers.extend(goal_pointers(child, f"{path}/children/{index}"))
    return pointers


def _scope_chain(candidate, target_ref):
    """The goal's scope and its ancestors, root first."""
    parts = target_ref.rsplit("/goals/", 1)[0].lstrip("/").split("/")
    node, chain = candidate, []
    for index, part in enumerate(parts):
        node = node[int(part)] if isinstance(node, list) else node[part]
        if index % 2 == 0:
            chain.append(node)
    return chain


def _relation_equal(expected, actual):
    if not isinstance(actual, dict):
        return False
    try:
        left = f"{expected['lhs']}{expected['operator']}{expected['rhs']}"
        right = f"{actual['lhs']}{actual['operator']}{actual['rhs']}"
        return compare_roots({"facts": [left]}, {"facts": [right]})["ok"]
    except (KeyError, TypeError):
        return False


def subset_diff(expected, actual, path=""):
    if path.endswith("/domain/value/expression") and _domain_equal(expected, actual):
        return []
    if path.endswith("/relation/value") and _relation_equal(expected, actual):
        return subset_diff(
            expected.get("strict"), actual.get("strict"), path + "/strict"
        )
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return [{"path": path, "expected": expected, "actual": actual}]
        return [
            d
            for key, value in expected.items()
            for d in subset_diff(value, actual.get(key), f"{path}/{key}")
        ]
    if isinstance(expected, list):
        if not isinstance(actual, list) or len(expected) != len(actual):
            return [{"path": path, "expected": expected, "actual": actual}]
        return [
            d
            for i, (a, b) in enumerate(zip(expected, actual, strict=True))
            for d in subset_diff(a, b, f"{path}/{i}")
        ]
    equal = (
        math_equal(expected, actual)
        if path.rsplit("/", 1)[-1] in {"expression", "lhs", "rhs"}
        else type(expected) is type(actual) and expected == actual
    )
    return [] if equal else [{"path": path, "expected": expected, "actual": actual}]


def _acceptance_checks(acceptance, candidate, rows):
    """Per-goal checks; a null quantifier means the goal sees no quantifier."""
    diagnostics = []
    for item in acceptance.get("goals", []):
        target_ref = item.get("target_ref")
        diagnostics.extend(
            {**diagnostic, "target_ref": target_ref}
            for diagnostic in _goal_checks(item, candidate, rows, target_ref)
        )
    return {"ok": not diagnostics, "diagnostics": diagnostics}


def _goal_checks(item, candidate, rows, target_ref):
    try:
        chain = _scope_chain(candidate, target_ref)
        goal = chain[-1]["goals"][int(target_ref.rsplit("/", 1)[-1])]
    except (KeyError, IndexError, TypeError, ValueError, AttributeError):
        return [{"code": "acceptance.missing_goal"}]
    diagnostics = []
    if goal != item.get("required_goal"):
        diagnostics.append(
            {"code": "acceptance.required_goal", "expected": item.get("required_goal")}
        )
    quantifiers = []
    for scope in chain:
        for value in [*scope.get("definitions", []), *scope.get("facts", [])]:
            try:
                quantifiers.extend(conjunct_quantifiers(parse(value)))
            except (ValueError, TypeError):
                continue
    expected_quantifier = item.get("required_quantifier")
    expected_variable = item.get("required_bound_variable")
    expected = (
        []
        if expected_quantifier is None
        else [[expected_quantifier, expected_variable]]
    )
    if [tree[1:3] for tree in quantifiers] != expected:
        diagnostics.append(
            {
                "code": "acceptance.quantifier_identity",
                "expected": [expected_quantifier, expected_variable],
            }
        )
    for feature_id in item.get("required_features", []):
        if rows.get((target_ref, feature_id), {}).get("status") != "known":
            diagnostics.append(
                {"code": "acceptance.required_feature", "feature_id": feature_id}
            )
    if item.get("required_domain") is not None:
        domain = (
            (rows.get((target_ref, "domain"), {}).get("value") or {}).get("expression")
        )
        if not _domain_equal(item["required_domain"], domain):
            diagnostics.append(
                {
                    "code": "acceptance.required_domain",
                    "expected": item["required_domain"],
                    "actual": domain,
                }
            )
    return diagnostics


def validate_fixture(fixture):
    """Check gold self-consistency and frozen input identity before paid calls.

    No provider is imported or created here. The independent gold is never used
    as extraction feedback; a failure is a corpus/configuration failure.
    """
    fixture = Path(fixture)
    diagnostics, hashes = [], {}
    try:
        for name in FIXTURE_FILES:
            hashes[name] = sha256((fixture / name).read_bytes()).hexdigest()
        expected = read_json(fixture / "notation.gold.json")
        expected_features = read_json(fixture / "features.gold.json")
        acceptance = read_json(fixture / "acceptance.json")
        manifest = read_json(fixture / "source-manifest.json")
        if acceptance.get("schema_version") != ACCEPTANCE:
            diagnostics.append({"code": "fixture.unsupported_acceptance"})
        if expected_features.get("schema_version") != FEATURE_EXPECTATIONS:
            diagnostics.append({"code": "fixture.unsupported_feature_expectations"})
        for item in acceptance.get("goals", []):
            if not GOAL_KEYS <= set(item):
                diagnostics.append(
                    {
                        "code": "fixture.incomplete_acceptance",
                        "target_ref": item.get("target_ref"),
                        "missing": sorted(GOAL_KEYS - set(item)),
                    }
                )
        goals = goal_pointers(expected["root"])
        if [item.get("target_ref") for item in acceptance.get("goals", [])] != goals:
            diagnostics.append(
                {"code": "fixture.acceptance_goal_coverage", "expected": goals}
            )
        uncovered = sorted(
            {target for target, _ in _feature_rows(expected_features)} - set(goals)
        )
        if uncovered:
            diagnostics.append(
                {"code": "fixture.feature_goal_unknown", "target_refs": uncovered}
            )
        for name, key in (("source.png", "source_sha256"), ("problem.md", "problem_sha256")):
            if hashes[name] != manifest.get(key):
                diagnostics.append({"code": "fixture.hash_mismatch", "path": name})
        problem = (fixture / "problem.md").read_text(encoding="utf-8")
        if normalized_transcription(problem) != normalized_transcription(
            expected["original_text"]
        ):
            diagnostics.append(
                {
                    "code": "fixture.transcription_mismatch",
                    "path": "notation.gold.json/original_text",
                }
            )
        validation = validate_candidate(expected)
        if not validation["contract_valid"]:
            diagnostics.append(
                {"code": "fixture.invalid_candidate", "validation": validation}
            )
        checks = _acceptance_checks(
            acceptance, expected, _feature_rows(expected_features)
        )
        if not checks["ok"]:
            diagnostics.append(
                {"code": "fixture.inconsistent_acceptance", "details": checks}
            )
    except (OSError, ValueError, TypeError, KeyError, IndexError) as error:
        diagnostics.append({"code": "fixture.invalid", "message": str(error)})
    return {"ok": not diagnostics, "diagnostics": diagnostics, "hashes": hashes}


def evaluate(
    fixture, candidate, features, *, source_reviewed=False, require_source_review=True
):
    fixture = Path(fixture)
    fixture_validation = validate_fixture(fixture)
    base = {
        "source_reviewed": source_reviewed,
        "source_review_required": require_source_review,
        "fixture_validation": fixture_validation,
    }
    if not fixture_validation["ok"]:
        return {"ok": False, "diagnostics": [{"code": "evaluation.invalid_fixture"}], **base}
    if not isinstance(candidate, dict):
        return {"ok": False, "diagnostics": [{"code": "evaluation.no_candidate"}], **base}
    validation = validate_candidate(candidate)
    if not validation["contract_valid"]:
        return {"ok": False, "contract_valid": False, "validation": validation, **base}
    expected = read_json(fixture / "notation.gold.json")
    semantics = compare_roots(expected["root"], candidate.get("root", {}))
    transcription = {
        "ok": normalized_transcription(expected["original_text"])
        == normalized_transcription(candidate.get("original_text", "")),
        "expected": expected["original_text"],
        "actual": candidate.get("original_text"),
    }
    # Golden files contain independently authored required value subsets.
    rows = _feature_rows(read_json(fixture / "features.gold.json"))
    actual = _feature_rows(features)
    feature_diffs = [
        diff
        for (target_ref, feature_id), expected_row in rows.items()
        for diff in subset_diff(
            expected_row,
            actual.get((target_ref, feature_id)),
            f"/features{target_ref}/{feature_id}",
        )
    ]
    checks = _acceptance_checks(read_json(fixture / "acceptance.json"), candidate, actual)
    return {
        "ok": bool(
            semantics["ok"]
            and transcription["ok"]
            and features.get("ok")
            and not feature_diffs
            and (source_reviewed or not require_source_review)
            and checks["ok"]
        ),
        "contract_valid": True,
        "semantics": semantics,
        "transcription": transcription,
        "acceptance": checks,
        "features": {
            "ok": not feature_diffs and bool(features.get("ok")),
            "differences": feature_diffs,
        },
        **base,
    }
