import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {createEventConsumer, mountStageThreeStream} from '../../site/assets/graph-walk/stage-three-stream.mjs';
import {createState, currentDecision, submitAnswer, extendStreamBundle, streamGraphState} from '../../site/assets/graph-walk/walk-state.mjs';

const read = path => JSON.parse(fs.readFileSync(new URL(path, import.meta.url), 'utf8'));
const legacy = read('./fixtures/graph-stage-three-q03-evidence.json');
const base = read('../../site/lab/search/demo-lesson-q01.json').goals[0].walk.bundle;
const graph = read('../../site/knowledge/graph.json');
const target = '/root/goals/0';
const pick = (value, keys) => Object.fromEntries(keys.filter(key => Object.hasOwn(value, key)).map(key => [key, structuredClone(value[key])]));

function publicSnapshot(value) {
  const source = call => ({...pick(call, ['public_ref', 'rule_ref', 'branch', 'used_basis', 'case_path']),
    ...('postconditions' in call ? {postconditions: call.postconditions.map(check => pick(check, ['passed']))} : {})});
  const result = {...structuredClone(value), contract: 'graph-stage-three-snapshot/v2', revisions_ref: 'a'.repeat(64)};
  delete result.revisions;
  result.trajectories = (value.checkpoints || []).map(checkpoint => ({
    target_ref: checkpoint.target_ref, route_id: checkpoint.route_id,
    steps: (checkpoint.driver_state?.trajectory?.steps || []).map(step => ({
      ...pick(step, ['seq', 'method', 'step', 'case_path']), calls: (step.calls || []).map(source),
    })),
    finalization: (checkpoint.driver_state?.trajectory?.finalization || []).map((record, index) => ({index, record: source(record)})),
  }));
  result.checkpoints = (value.checkpoints || []).map(value => pick(value, ['target_ref', 'route_id', 'status', 'phase', 'commit_id', 'last_seq']));
  return result;
}

function selected(bundle, route = 'discriminant') {
  let state = createState(bundle);
  const answer = value => {
    const decision = currentDecision(bundle, state);
    state = submitAnswer(bundle, state, {decision: decision.id, answer: value ??
      (decision.interaction.type === 'checklist' ? decision.expected_answer.terms : decision.expected_answer.one_of[0])});
  };
  answer(); answer();
  const decision = currentDecision(bundle, state);
  answer([...decision.expected_answer.cell, decision.interaction.methods.find(item => item.route === route).value]);
  answer(route);
  return state;
}

function reached(view, steps, route = 'discriminant') {
  const bundle = extendStreamBundle(base, view, target, graph);
  return streamGraphState(bundle, selected(bundle, route), {steps});
}

test('v2 refresh restores every Q03 source without retaining execution state', () => {
  const older = createEventConsumer(legacy), compact = createEventConsumer(legacy);
  older.hydrate(legacy);
  compact.hydrate(publicSnapshot(legacy));
  assert.deepEqual(compact.view().trajectories, older.view().trajectories);
  assert.deepEqual(compact.view().math_steps, older.view().math_steps);
  for (const consumer of [older, compact]) {
    assert.ok(!JSON.stringify(consumer.view().checkpoints).includes('driver_state'));
    assert.ok(!JSON.stringify(consumer.view().trajectories).includes('outputs'));
  }
  for (const card of legacy.math_steps) {
    assert.deepEqual(reached(compact.view(), [card]), reached(older.view(), [card]));
  }
  assert.deepEqual(compact.view().trajectories[0].finalization.map(value => value.index), [0, 1, 2]);
});

test('full incremental evidence and projected refresh share immutable finalization identity', () => {
  const consumer = createEventConsumer(legacy);
  const trajectory = legacy.checkpoints[0].driver_state.trajectory;
  consumer.accept({...legacy, seq: 1, event_id: 'source-1', type: 'solver.step_completed',
    target_ref: target, route_id: 'discriminant', payload: {trajectory: trajectory.steps,
      finalization: [{index: 2, record: trajectory.finalization[2]}]}});
  const snapshot = publicSnapshot(legacy);
  snapshot.last_seq = Math.max(snapshot.last_seq || 0, 2);
  assert.doesNotThrow(() => consumer.hydrate(snapshot));
  const altered = structuredClone(snapshot);
  altered.last_seq += 1;
  altered.trajectories[0].finalization[2].record.used_basis = ['invented'];
  assert.throws(() => consumer.hydrate(altered), /immutable_finalization_source/);
});

test('full trace updates after a public snapshot extend the same step without duplicating cards', () => {
  const snapshot = publicSnapshot(legacy), consumer = createEventConsumer(legacy);
  snapshot.last_seq = 100;
  consumer.hydrate(snapshot);
  const before = consumer.view();
  const row = structuredClone(legacy.checkpoints[0].driver_state.trajectory.steps.find(step => step.calls.length));
  row.calls.push({public_ref: null, used_basis: [], inputs: {internal: 'not retained'},
    outputs: {internal: 'not retained'}, postconditions: [{kind: 'checked', passed: true}]});
  consumer.accept({...legacy, seq: 101, event_id: 'continued-step', type: 'solver.step_completed',
    target_ref: target, route_id: 'discriminant', payload: {trajectory: [row]}});
  const after = consumer.view();
  assert.deepEqual(after.math_steps, before.math_steps);
  assert.equal(after.trajectories[0].steps.find(step => step.seq === row.seq).calls.length, row.calls.length);
  assert.ok(!JSON.stringify(after.trajectories).includes('not retained'));
  for (const card of after.math_steps) assert.deepEqual(reached(after, [card]), reached(before, [card]));
  assert.doesNotThrow(() => consumer.hydrate({...snapshot, last_seq: 101,
    trajectories: [{...snapshot.trajectories[0], steps: after.trajectories[0].steps}]}));
  assert.deepEqual(consumer.view().math_steps, before.math_steps);
});

test('public evidence keeps unchecked call slots and the actual method-rule-skill path', () => {
  const d3 = read('../../site/data/graph-walk/quadratic-always-q01.source.json').intro.find(item => item.id === 'D3');
  d3.expected_answer.cell = ['interval', 'free'];
  const card = {...structuredClone(legacy.math_steps[0]), route_id: 'interval', method_ref: 'method-interval-extremum#select',
    source_refs: ['/steps/1/calls/1'], case_path: [], used_basis: ['quadratic-interval-extremum']};
  const snapshot = {...publicSnapshot(legacy), math_steps: [card], checkpoints: [], handoffs: [], qa: [], goals: {},
    selection_chunks: [{target_ref: target, kind: 'D3', chunk: d3}, {target_ref: target, kind: 'D4', chunk: {
      id: 'D4', title: '解题路线', options: [{branch: 'interval', route_id: 'interval', method: 'method-interval-extremum',
        route_plan: 'planned', recommendation: 'preferred'}],
    }}], trajectories: [{target_ref: target, route_id: 'interval', finalization: [], steps: [{
      seq: 2, method: 'method-interval-extremum', step: 'select', case_path: [], calls: [
        {public_ref: null, postconditions: []},
        {public_ref: 'quadratic-interval-extremum', rule_ref: 'rule-interval-skill', branch: 'quadratic',
          case_path: [], used_basis: ['quadratic-interval-extremum'], postconditions: [{passed: true}]},
      ],
    }]}]};
  const consumer = createEventConsumer(legacy);
  consumer.hydrate(snapshot);
  const value = reached(consumer.view(), [card], 'interval');
  assert.equal(value.calls.length, 1);
  assert.deepEqual(value.calls[0].rule_edges, [
    'method-interval-extremum|step_rule|rule-interval-skill', 'rule-interval-skill|selects|quadratic-interval-extremum',
  ]);
  assert.equal(value.edges['method-interval-extremum|calls|quadratic-interval-extremum'], undefined);
  for (const mutation of [
    call => delete call.rule_ref,
    call => delete call.branch,
    call => { call.postconditions = []; },
    call => { call.postconditions = [{passed: 'true'}]; },
    call => { call.case_path = ['other-case']; },
  ]) {
    const invalid = structuredClone(snapshot);
    mutation(invalid.trajectories[0].steps[0].calls[1]);
    assert.equal(reached(invalid, [card], 'interval').calls.length, 0);
  }
});

test('v2 evidence cannot borrow absent boundary proofs from legacy checkpoints', () => {
  const snapshot = publicSnapshot(legacy);
  snapshot.checkpoints = structuredClone(legacy.checkpoints);
  snapshot.trajectories[0].finalization = [];
  const value = reached(snapshot, [snapshot.math_steps.at(-1)]);
  assert.ok(!value.usedBasis.includes('function-range-extrema#attainability'));
});

function documentFixture() {
  const document = {createElement(tag) { return new Element(tag); }};
  class Element {
    constructor(tag) { this.tagName = tag; this.ownerDocument = document; this.children = []; this.dataset = {}; this.hidden = false; this.textContent = ''; }
    append(...children) { this.children.push(...children); }
    replaceChildren(...children) { this.children = [...children]; }
    set innerHTML(value) { throw new Error(`unexpected HTML: ${value}`); }
  }
  const container = new Element('main');
  const find = (name, parent = container) => [
    ...(parent.className === name ? [parent] : []), ...parent.children.flatMap(child => find(name, child)),
  ];
  return {container, find};
}

test('conflict refresh hides completion and QA without replacing mathematics DOM', () => {
  const snapshot = publicSnapshot(legacy), card = snapshot.math_steps[0];
  snapshot.math_steps = [card];
  snapshot.goals = {[target]: {status: 'solved', available: true}};
  snapshot.handoffs = [{...pick(card, ['run_id', 'lesson_version', 'target_ref', 'route_id']),
    status: 'completed', available: true, verified_route_sha256: 'verified-route',
    answer: {kind: 'find_range', status: 'set', set: '[0,1]'}, feasible_set: '[0,1]'}];
  snapshot.qa = [{...pick(card, ['run_id', 'lesson_version', 'target_ref', 'route_id', 'step_id', 'math_step_sha256']),
    verified_route_sha256: 'verified-route', qa: {questions: ['为什么？']}}];
  const {container, find} = documentFixture();
  const mounted = mountStageThreeStream(container, snapshot);
  mounted.consumer.hydrate(snapshot);
  const node = find('stage-three-math-step')[0];
  assert.equal(find('stage-three-qa')[0].hidden, false);
  const conflict = structuredClone(snapshot);
  conflict.last_seq += 1;
  conflict.goals[target] = {status: 'conflict', available: false, reason: 'route_conflict'};
  conflict.handoffs[0].available = false;
  conflict.handoffs[0].status = 'cancelled';
  mounted.consumer.hydrate(conflict);
  assert.equal(find('stage-three-math-step')[0], node);
  assert.equal(find('stage-three-completion')[0].hidden, true);
  assert.equal(find('stage-three-qa')[0].hidden, true);
});

test('v2 resnapshot retains its waterline and ignores pruned event redelivery', () => {
  const snapshot = publicSnapshot(legacy);
  snapshot.last_seq = 100;
  snapshot.minimum_seq = 90;
  const consumer = createEventConsumer(legacy);
  consumer.hydrate(snapshot);
  const before = consumer.view();
  assert.deepEqual(consumer.accept({...legacy, seq: 80, event_id: 'pruned', type: 'solver.step_completed',
    target_ref: target, route_id: 'discriminant', payload: {trajectory: []}}), {ignored: 'duplicate', last_seq: 100});
  assert.deepEqual(consumer.view(), before);
});
