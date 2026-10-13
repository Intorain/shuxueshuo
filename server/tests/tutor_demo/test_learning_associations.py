"""Shared selector boundaries, independent of PostgreSQL or tutor credentials."""

import json
from pathlib import Path

from shuxueshuo_server.learning.associations import (
    branches,
    matches_ref,
    resolved_refs,
    select,
)

ROOT = Path(__file__).resolve().parents[3]


def test_unsubmitted_partial_choice_hides_all_candidates():
    tree = {'field': 'inequality', 'options': {
        'upper': {'ref': 'amgm-formula#sum'},
        'lower': {'ref': 'amgm-formula#product'},
    }}
    result = select(tree, {}, {'inequality': ['upper', 'lower', 'wrong']})
    assert result == {'actual': [], 'candidates': [], 'withheld': True}
    assert select(tree, {'inequality': 'upper'})['actual'][0]['value']['ref'].endswith('#sum')
    assert not select(tree, {'inequality': 'wrong'})['actual']


def test_nested_selection_keeps_only_observed_path_and_deduplicates_refs():
    tree = {'field': 'first', 'options': {
        'a': {'field': 'second', 'options': {'b': ['skill-a#one', 'skill-a#one'], 'c': ['skill-b']}},
        'd': ['skill-c'],
    }}
    assert len(branches(tree)) == 3
    assert resolved_refs(tree, {'first': 'a'}) == []
    assert resolved_refs(tree, {'first': 'a', 'second': 'b'}) == ['skill-a#one']
    assert resolved_refs(tree, {'first': 'd'}) == ['skill-c']
    assert matches_ref('skill-a#one', 'skill-a')
    assert matches_ref('skill-a#one', 'skill-a', 'one')
    assert not matches_ref('skill-a#one', 'skill-a', 'two')


def test_q30_authored_tip_unblocks_candidates_after_passing_without_inventing_choice():
    topic = json.loads((ROOT / 'site/data/knowledge-next/topics/basic-inequality.json').read_text())
    lesson = json.loads((ROOT / 'server/shuxueshuo_server/tutor_demo/lessons/basic-inequality-q30.json').read_text())
    route = next(iter(topic['problems']['basic-inequality-q30']['routes']))
    teacher_steps = lesson['routes'][route]['nodes']
    options = {n['interaction']['field']: [o['value'] for o in n['interaction']['options']]
               for n in teacher_steps if n['interaction']['type'] == 'choice'}
    step = teacher_steps[4]
    tip = topic['problems']['basic-inequality-q30']['routes'][route]['steps'][step['id']]['tip']
    assert select(tip, {}, options)['withheld']
    assert select(tip, {}, options)['candidates'] == []
    result = select(tip, {}, options, {step['interaction']['field']})
    assert result['actual'] == [] and not result['withheld']
    assert len(result['candidates']) == 2
    correct = step['expected_answer']['one_of'][0]
    chosen = {step['interaction']['field']: correct}
    assert len(select(tip, chosen, options)['actual']) == 1


def test_passing_one_field_does_not_unlock_another_unanswered_field():
    tree = {'field': 'first', 'options': {
        'a': {'field': 'second', 'options': {'b': ['node']}}}}
    options = {'first': ['a', 'wrong'], 'second': ['b', 'wrong']}
    assert select(tree, {}, options, {'first'})['withheld']
    assert select(tree, {}, options, {'second'})['withheld']
    result = select(tree, {}, options, {'first', 'second'})
    assert not result['withheld'] and len(result['candidates']) == 1
    assert result['actual'] == []
    assert resolved_refs(tree, {}) == []
