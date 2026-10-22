"""Unified mathematical values, declared prose and precise per-card premises."""

import json
from copy import deepcopy

import pytest
import sympy as sp
from jsonschema import Draft202012Validator, ValidationError

from shuxueshuo_server.graph_lesson.stage_three import (
    driver,
    execution_contracts,
    verification,
)
from shuxueshuo_server.graph_lesson.stage_three.math_values import (
    adapt_legacy_math_values,
    math_value,
)
from shuxueshuo_server.graph_lesson.stage_three.presentation import (
    make_fragment,
    validate_registry,
)
from shuxueshuo_server.graph_lesson.stage_three.presentation_templates import (
    render_template,
)
from shuxueshuo_server.graph_lesson.stage_three.trajectory import (
    encode_value,
    trace_value,
)
from tests.solver.test_graph_stage_three_methods import ROOT, candidate, finish, start


def pointer(value, reference):
    for part in reference.lstrip('/').split('/'):
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


@pytest.mark.parametrize('value', [sp.Symbol('a'), sp.Rational(-5, 2), sp.sqrt(2), sp.Interval.open(0, 1), sp.S.EmptySet, sp.oo])
def test_math_value_representation_is_shared_by_trace_verification_and_card(value):
    assert verification.math_value is math_value
    assert trace_value(value) == {**math_value(value), 'exact': encode_value(value)}
    state = {'fragments': [], 'target_ref': '/root/goals/0', 'route_id': 'r', 'run_id': 'r',
             'lesson_version': 'v', 'revisions': {'presentation': 'a' * 64}}
    card = make_fragment(state, unit_id='one', method_ref='method-discriminant#solve', template='solution', after=[value])
    assert card['after'] == [math_value(value)]
    assert set(card['after'][0]) == {'expression', 'latex'}
    schemas = [json.loads((ROOT / 'internal/schemas' / name).read_text()) for name in
               ('graph-math-step-v2.schema.json', 'graph-stage-three-result-v1.schema.json')]
    assert schemas[0]['$defs']['mathValue'] == schemas[1]['$defs']['mathValue']
    Draft202012Validator(schemas[0]).validate(card)
    invalid = deepcopy(card)
    invalid['after'][0]['display'] = invalid['after'][0].pop('latex')
    with pytest.raises(ValidationError):
        Draft202012Validator(schemas[0]).validate(invalid)


def test_polynomials_in_x_display_from_the_highest_power_down():
    a, x = sp.symbols('a x')
    assert math_value(a * x + x**2 + 1)['latex'] == 'x^{2} + a x + 1'
    assert math_value(sp.Le(0, a * x**2 + a - 2 * x))['latex'] == r'a x^{2} - 2 x + a \geq 0'
    assert math_value(sp.And(-1 < a, a <= 0))['latex'] == r'-1 < a \leq 0'
    assert math_value((a * x + x**2 + 1) / (x + a))['latex'] == r'\frac{x^{2} + a x + 1}{x + a}'
    assert math_value(a + x + 1 / x)['latex'] == sp.latex(a + x + 1 / x)
    assert math_value(a * x)['expression'] == 'a*x'


def test_explicit_legacy_read_adapter_keeps_saved_identity_and_decision_templates():
    saved = {'before': [{'expression': 'a', 'display': 'a'}], 'math_step_sha256': 'old-hash',
             'decision': {'display': '<p>{expression}</p>', 'expression': 'a'}}
    original = deepcopy(saved)
    current = adapt_legacy_math_values(saved)
    assert saved == original
    assert current['before'] == [{'expression': 'a', 'latex': 'a'}]
    assert current['decision'] == saved['decision'] and current['math_step_sha256'] == 'old-hash'


def test_new_declarative_template_renders_without_adding_a_python_branch():
    registry = deepcopy(execution_contracts.read('presentation-registry'))
    spec = {'title': '新增计算说明', 'explanation': '', 'required_bindings': ['before', 'after', 'x', 'value'],
            'render': '代入 ${x}$，得到 ${value}$。'}
    registry['templates']['new_authored_template'] = spec
    validate_registry(registry)
    _, _, explanation = render_template(spec, {'before': [], 'after': [], 'x': sp.Symbol('t'), 'value': sp.sqrt(2)})
    assert explanation == r'代入 $t$，得到 $\sqrt{2}$。'


@pytest.mark.parametrize('change,error', [
    ({'prepare': 'unregistered_function'}, 'unknown_preparer'),
    ({'render': '来自 ${undeclared}$'}, 'unknown_template_binding'),
    ({'render': {'eval': 'anything'}}, 'unknown_template_node'),
    ({'render': '{after.__class__}'}, 'unknown_template_binding'),
])
def test_bad_registered_templates_fail_validation_before_execution(change, error):
    registry = deepcopy(execution_contracts.read('presentation-registry'))
    registry['templates']['normalize'].update(change)
    with pytest.raises(ValueError, match=error):
        validate_registry(registry)


def test_case_cards_depend_on_own_inputs_and_ancestor_cases_not_sibling_judgments():
    state = finish(start(candidate('∀x∈[0,2]:x^2-2*a*x+1>=0'), 'method-interval-extremum'))
    assert state['status'] == 'method_complete', state['diagnostics']
    cards = [card for card in state['fragments'] if card['case_path']]
    assert len({tuple(card['case_path']) for card in cards}) >= 2
    assert any(card['premise_refs'] for card in cards)
    for card in cards:
        for reference in card['premise_refs']:
            judgment = pointer(state['trajectory'], reference)
            assert '/judgments/' in reference
            path = judgment['case_path']
            assert card['case_path'][:len(path)] == path, (card['case_path'], path)
            assert 'source_refs' in judgment
    # The merge really uses every solved case, so its dependency closure must
    # retain those relevant judgments instead of filtering all case judgments.
    merge = next(card for card in state['fragments'] if card['title'] == '求参数范围')
    assert {tuple(pointer(state['trajectory'], ref)['case_path']) for ref in merge['premise_refs']} >= {
        tuple(card['case_path']) for card in cards
    }


def test_unrelated_prior_judgment_does_not_change_later_math_card_or_hash():
    state = start()
    for _ in range(100):
        if state['frames'] and state['frames'][0]['step_index'] >= 2:
            break
        state = driver.advance(state)
    else:
        raise AssertionError('did not reach the later solution step')
    altered = deepcopy(state)
    altered['trajectory']['steps'][0]['judgments'].append({
        'id': 'irrelevant_prior_check', 'selected': 'yes', 'case_path': [], 'source_refs': [],
    })
    altered['premise_refs'] = ['/steps/0/judgments/0']  # ignored old checkpoint field
    original, changed = finish(state), finish(altered)
    assert original['status'] == changed['status'] == 'method_complete'
    assert original['fragments'] == changed['fragments']
