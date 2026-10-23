"""One checked variable-swap card defines the function used by the next step."""

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_three import driver, interaction
from shuxueshuo_server.graph_lesson.stage_three.math_values import latex
from shuxueshuo_server.graph_lesson.stage_three.trajectory import decode_value
from shuxueshuo_server.problem_understanding.review_contract import pointer
from tests.solver.test_graph_stage_three_batch_five import _finish_swap
from tests.solver.test_graph_stage_three_execution import simple
from tests.solver.test_graph_stage_three_interaction_variable import selected_rows


@pytest.mark.parametrize("variable,parameter,expression", [
    ("m", "x", "m*x^2-m*x+m-6"),
    ("t", "b", "t*b^2-t*b+t-6"),
    ("a", "x", "a*x^2-(a+1)*x+1"),
])
def test_swap_publishes_one_definition_with_both_checked_sources(variable, parameter, expression):
    state = _finish_swap(simple(f"∀{variable}∈[1,3]:{expression}<0", symbol=parameter))
    assert state["status"] == "method_complete"
    seed, = [seed for seed in state["interaction_seeds"] if seed["template"] == "variable_swap"]
    assert not any(seed["template"] in ("variable_roles", "variable_reorder")
                   for seed in state["interaction_seeds"])
    card, = [card for card in state["fragments"] if card["step_id"] == seed["step_id"]]
    assert card["title"] == "更换主元"
    values = decode_value(seed["values"])
    conclusion, = card["highlight"]["items"]
    assert conclusion == {"label": rf"固定 ${parameter}$，${variable}\in \left[1, 3\right]$",
                          "math": f"f({variable})={latex(values['function'])}"}
    assert sp.expand(values["function"] - values["before"][0]) == 0
    assert card["highlight"]["result"] == f"${conclusion['math']}$"
    assert not values["slope"].has(values["x"]) and not values["intercept"].has(values["x"])
    sources = [pointer(state["trajectory"], ref) for ref in card["source_refs"]]
    assert any(row.get("id") == "identify" and row.get("decided_by") == "program" for row in sources)
    assert any(row.get("capability") == "reorder_by_variable" and row.get("outputs") for row in sources)

    chunk, diagnostics = interaction.build_chunk([seed], interaction.load_registry(), {"previous": 0})
    assert chunk["status"] == "interactive", diagnostics
    interaction.validate_chunk(chunk)
    roles, coefficients = chunk["parts"]
    assert [label for _, label in selected_rows(roles)] == [f"${variable}$", f"${parameter}$"]
    assert [label for _, label in selected_rows(coefficients)] == [
        f"${latex(values['slope'])}$", f"${latex(values['intercept'])}$"]
    assert f"f({variable})=A" in coefficients["question"]
    assert f"${latex(values['before'][0])}$" in coefficients["question"]
    assert conclusion["math"] not in coefficients["question"]
    policy = next(card for card in state["fragments"] if card["display_unit"] == "policy")
    assert f"f({variable})" in policy["highlight"]["items"][0]["math"]


def test_swap_does_not_change_the_original_problem_answer():
    state = _finish_swap(simple("∀m∈[1,3]:m*x^2-m*x+m-6<0", symbol="x"))
    values = driver.export_values(state)
    assert values["feasible_set"] == sp.Interval.open((1-sp.sqrt(5))/2, (1+sp.sqrt(5))/2)
