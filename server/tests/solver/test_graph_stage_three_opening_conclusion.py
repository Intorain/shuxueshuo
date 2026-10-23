"""The prominent opening conclusion preserves quantifier and strictness."""

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_three import execution_contracts
from shuxueshuo_server.graph_lesson.stage_three.math_values import math_value
from shuxueshuo_server.graph_lesson.stage_three.presentation_templates import (
    render_highlight,
)


@pytest.mark.parametrize("quantifier,operator,opening,vertex,sign", [
    ("∀", ">=", "向上", "最小值", r"\geq"),
    ("∀", ">", "向上", "最小值", ">"),
    ("∀", "<=", "向下", "最大值", r"\leq"),
    ("∀", "<", "向下", "最大值", "<"),
    ("∃", ">=", "向下", "最大值", r"\geq"),
    ("∃", ">", "向下", "最大值", ">"),
    ("∃", "<=", "向上", "最小值", r"\leq"),
    ("∃", "<", "向上", "最小值", "<"),
])
def test_parameter_opening_conclusion_is_a_separate_compact_right_cell(quantifier, operator, opening, vertex, sign):
    t, b = sp.symbols("t b", real=True)
    relation = sp.Rel(b*t**2+t-1, 0, operator, evaluate=False)
    coefficient = b if operator in (">", ">=") else -b
    bindings = {"before": [], "after": [sp.Gt(coefficient, 0, evaluate=False)],
                "relation": relation, "quantifier": quantifier}
    specification = execution_contracts.read("presentation-registry")["templates"]["opening"]
    highlight = render_highlight(specification, bindings)
    left, right = highlight["items"]
    assert left == {"label": "研究的关系", "math": math_value(relation)["latex"]}
    assert right["label"] == "图像条件"
    assert f"开口{opening}" in right["math"]
    assert rf"\text{{{vertex}}}{sign}0" in right["math"]
    assert "需要" not in right["math"] and "note" not in right
    if quantifier == "∃":
        automatic = "向上" if opening == "向下" else "向下"
        assert f"开口{automatic}：有解" in right["math"]
    else:
        assert "有解" not in right["math"]
