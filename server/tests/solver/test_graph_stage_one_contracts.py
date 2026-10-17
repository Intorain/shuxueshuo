"""The independent extraction contract cannot silently fall back to families."""

import copy

import pytest
from jsonschema import Draft202012Validator

from shuxueshuo_server.graph_lesson.stage_one import contracts


@pytest.fixture
def candidate():
    return {
        "original_text": "对任意实数t，t²+c>0，求c的范围。",
        "root": {
            "facts": ["∀t∈ℝ: t^2+c>0"],
            "goals": [{"kind": "find_range", "symbol": "c"}],
        },
    }


def test_family_free_contract_is_valid_and_scopes_nest(candidate):
    validator = Draft202012Validator(contracts.schema())
    validator.validate(candidate)
    for field in (
        "family_id",
        "match_status",
        "match_reason",
        "features",
        "answer",
        "source_annotations",
        "conventions",
    ):
        invalid = {**candidate, field: None}
        assert not validator.is_valid(invalid), field
    nested = copy.deepcopy(candidate)
    part = nested["root"]
    nested["root"] = {"definitions": ["f(t)=t^2+c"], "children": [{"label": "（1）", **part}]}
    validator.validate(nested)
    nested["root"]["children"][0]["features"] = []
    assert not validator.is_valid(nested)
    for field in ("original_text", "root"):
        assert not validator.is_valid(
            {k: v for k, v in candidate.items() if k != field}
        )


def test_versioned_catalog_overrides_default_policy_without_changing_base():
    catalog = contracts.expression_catalog()
    domain = next(
        item for item in catalog["expressions"] if item["id"] == "domain_and_interval"
    )
    assert "∞" in domain["syntax"]
    assert "量词域取 ℝ" in domain["meaning"]
    assert "convention_rules" not in catalog
    assert (
        "不要补写题面未给出的默认实数域" in contracts.BASE_EXPRESSIONS_PATH.read_text()
    )


def test_review_contract_requires_findings_for_nonconfirmation():
    validator = Draft202012Validator(contracts.review_schema())
    validator.validate({"status": "confirmed", "findings": []})
    assert not validator.is_valid({"status": "uncertain", "findings": []})
    finding = {
        "path": "/root/facts/0",
        "kind": "wrong_expression",
        "source_excerpt": "原图关系",
        "message": "原图为非严格不等式",
    }
    validator.validate({"status": "correction_required", "findings": [finding]})
    assert not validator.is_valid({"status": "confirmed", "findings": [finding]})
    assert not validator.is_valid(
        {
            "status": "correction_required",
            "findings": [{**finding, "kind": "source_mapping"}],
        }
    )
