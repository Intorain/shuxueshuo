"""Root-only compilation shares the old mathematical contract, not its envelope."""

from copy import deepcopy

import pytest

from shuxueshuo_server.problem_understanding.notation_compile import (
    NotationValidator,
    typecheck,
)
from shuxueshuo_server.problem_understanding.notation_parser import parse
from shuxueshuo_server.problem_understanding.notation_semantics import (
    Canonical,
    compare_roots,
)


def test_root_compiler_does_not_need_or_insert_family_fields():
    root = {
        "facts": ["∀x∈ℝ: x^2+a>=0"],
        "goals": [{"kind": "find_range", "symbol": "a"}],
    }
    frozen = deepcopy(root)
    validator = NotationValidator()
    direct = validator.validate_root(root)
    assert direct.ok, direct.issues
    assert root == frozen
    assert set(direct.normalized) == {"root"}
    assert not validator.validate({"root": root}).ok
    legacy = validator.validate(
        {
            "root": root,
            "match_status": "unmatched",
            "family_id": None,
            "match_reason": "synthetic",
        }
    )
    assert legacy.ok
    assert legacy.semantic == direct.semantic
    assert legacy.semantic_normalization == direct.semantic_normalization


@pytest.mark.parametrize(
    "root", [None, [], {"facts": "x>0"}, {"goals": [{"kind": "find_range"}]}]
)
def test_root_compiler_validates_the_shared_scope_schema(root):
    report = NotationValidator().validate_root(root)
    assert not report.ok
    assert all(
        issue["code"] == "schema.invalid" and issue["path"].startswith("/root")
        for issue in report.issues
    )


@pytest.mark.parametrize("domain", ["(-∞,0)", "(0,+∞)", "(-∞,+∞)", "[0,∞)", "(-∞,0]"])
def test_infinite_endpoints_compile_and_compare(domain):
    left = {
        "facts": [f"∀t∈{domain}: t^2+a*t+2>=0"],
        "goals": [{"kind": "find_range", "symbol": "a"}],
    }
    right = {"facts": [f"∀t∈{domain}: 0<=2+t*a+t^2"], "goals": left["goals"]}
    assert compare_roots(left, right)["ok"]
    assert NotationValidator().validate_root({"facts": [f"t∈{domain}"]}).ok


@pytest.mark.parametrize(
    "fact",
    [
        "∀x∈[-∞,0):x>0",
        "∀x∈(0,∞]:x>0",
        "∀x∈(∞,0):x>0",
        "∀x∈(0,-∞):x>0",
        "x=∞",
        "∞=∞",
        "∞>0",
        "x+∞>0",
        "sqrt(∞)>0",
        "x∈(0,1+∞)",
        "P=(0,∞)",
    ],
)
def test_infinity_is_never_a_real_scalar_or_included_endpoint(fact):
    report = NotationValidator().validate_root({"facts": [fact]})
    assert not report.ok, fact


def test_infinity_is_never_an_atom_in_algebra():
    ast = parse("-∞")
    assert typecheck(ast) == "infinite_endpoint"
    with pytest.raises(ValueError, match="semantic.infinity_outside_interval"):
        Canonical().expr(ast)


@pytest.mark.parametrize(
    "replacement",
    [
        "∃x∈(-∞,0):x^2+a>=0",
        "∀x∈(-∞,0]:x^2+a>=0",
        "∀x∈(-∞,0):x^2+a>0",
        "∀x∈(0,∞):x^2+a>=0",
    ],
)
def test_root_comparison_preserves_quantifier_endpoint_and_strictness(replacement):
    expected = {
        "facts": ["∀x∈(-∞,0):x^2+a>=0"],
        "goals": [{"kind": "find_range", "symbol": "a"}],
    }
    actual = {**expected, "facts": [replacement]}
    assert not compare_roots(expected, actual)["ok"]
