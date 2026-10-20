import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {createEventConsumer, mountStageThreeStream} from '../../site/assets/graph-walk/stage-three-stream.mjs';
import {extendStreamBundle, streamStepGraph} from '../../site/assets/graph-walk/walk-state.mjs';

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

function evidence(view, steps) {
  const bundle = extendStreamBundle(base, view, target, graph);
  assert.equal(steps.length, 1);
  return streamStepGraph(bundle, steps[0]);
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
    assert.deepEqual(evidence(compact.view(), [card]), evidence(older.view(), [card]));
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
  for (const card of after.math_steps) assert.deepEqual(evidence(after, [card]), evidence(before, [card]));
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
  const value = evidence(consumer.view(), [card]);
  assert.equal(value.calls.length, 1);
  assert.deepEqual(value.calls[0].rule_edges, [
    'method-interval-extremum|step_rule|rule-interval-skill', 'rule-interval-skill|selects|quadratic-interval-extremum',
  ]);
  assert.equal(value.edges.includes('method-interval-extremum|calls|quadratic-interval-extremum'), false);
  for (const mutation of [
    call => delete call.rule_ref,
    call => delete call.branch,
    call => { call.postconditions = []; },
    call => { call.postconditions = [{passed: 'true'}]; },
    call => { call.case_path = ['other-case']; },
  ]) {
    const invalid = structuredClone(snapshot);
    mutation(invalid.trajectories[0].steps[0].calls[1]);
    assert.equal(evidence(invalid, [card]).calls.length, 0);
  }
});

test('v2 evidence cannot borrow absent boundary proofs from legacy checkpoints', () => {
  const snapshot = publicSnapshot(legacy);
  snapshot.checkpoints = structuredClone(legacy.checkpoints);
  snapshot.trajectories[0].finalization = [];
  const value = evidence(snapshot, [snapshot.math_steps.at(-1)]);
  assert.ok(!value.usedBasis.includes('function-range-extrema#attainability'));
});

test('conflict refresh revokes completion and stops QA forwarding while preserving math data', () => {
  const snapshot = publicSnapshot(legacy), card = snapshot.math_steps[0];
  snapshot.math_steps = [card];
  snapshot.goals = {[target]: {status: 'solved', available: true}};
  snapshot.handoffs = [{...pick(card, ['run_id', 'lesson_version', 'target_ref', 'route_id']),
    status: 'completed', available: true, verified_route_sha256: 'verified-route',
    answer: {kind: 'find_range', status: 'set', set: '[0,1]'}, feasible_set: '[0,1]'}];
  snapshot.qa = [{...pick(card, ['run_id', 'lesson_version', 'target_ref', 'route_id', 'step_id', 'math_step_sha256']),
    verified_route_sha256: 'verified-route', qa: {questions: ['为什么？']}}];
  const received = [], mathematics = [];
  const mounted = mountStageThreeStream(snapshot, {onQA: value => received.push(value), onMathStep: value => mathematics.push(value)});
  mounted.consumer.hydrate(snapshot);
  assert.deepEqual(received.at(-1), snapshot.qa[0]);
  const receivedCount = received.length;
  const conflict = structuredClone(snapshot);
  conflict.last_seq += 1;
  conflict.goals[target] = {status: 'conflict', available: false, reason: 'route_conflict'};
  conflict.handoffs[0].available = false;
  conflict.handoffs[0].status = 'cancelled';
  mounted.consumer.hydrate(conflict);
  assert.equal(mounted.consumer.view().goals[target].available, false);
  assert.ok(mounted.consumer.view().completions.every(value => !value.available));
  assert.equal(received.length, receivedCount);
  assert.deepEqual(mathematics, [card]);
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

for (const status of ['interactive', 'readonly']) for (const count of [1, 2]) {
  test(`consumer output adapts ${count}-card ${status} interactions after early snapshots and on refresh`, () => {
    const identity = pick(legacy, ['run_id', 'lesson_version', 'stream_id']);
    const cards = legacy.math_steps.slice(0, count);
    const snapshot = {...identity, last_seq: 0, math_steps: [], goals: {},
      selection_chunks: legacy.selection_chunks, interaction_protocol: null, interaction_states: [], interactions: []};
    const consumer = createEventConsumer(identity);
    consumer.hydrate(snapshot);
    let bundle = extendStreamBundle(base, consumer.view(), target, graph);
    const send = (seq, payload) => consumer.accept({...identity, seq, event_id: `live-${seq}`,
      target_ref: target, route_id: 'discriminant', type: 'lesson.chunk_ready', payload});
    for (const card of cards) send(card.ordinal, {kind: 'math_step', chunk: card,
      step_id: card.step_id, math_step_sha256: card.math_step_sha256, interaction_status: 'pending'});
    bundle = extendStreamBundle(bundle, consumer.view(), target, graph);
    assert.deepEqual(bundle.routes.discriminant.steps, [], 'pending cards cannot create premature legacy read decisions');
    assert.deepEqual(consumer.view().interaction_states, cards.map(card => ({
      target_ref: target, route_id: card.route_id, step_id: card.step_id,
      ordinal: card.ordinal, math_step_sha256: card.math_step_sha256, status: 'pending'})));
    const chunk = {contract: 'graph-step-interaction/v1', ...identity, target_ref: target, route_id: 'discriminant',
      interaction_id: 'decision-group', interaction_revision: 'frozen-rules', interaction_sha256: 'chunk-hash', status,
      steps: cards.map(card => pick(card, ['step_id', 'math_step_sha256'])),
      parts: status === 'interactive' ? [{id: 'practice-1', title: '判断分类依据', question: '选择依据',
        interaction: {type: 'choice', options: [{value: 'coefficient', label: '二次项系数'}]},
        expected_answer: {one_of: ['coefficient']}}] : [],
      ...(status === 'readonly' ? {reason: 'no_rule'} : {})};
    send(count + 1, {kind: 'step_interaction', chunk, interaction_id: chunk.interaction_id, status});
    const view = consumer.view();
    bundle = extendStreamBundle(bundle, view, target, graph);
    assert.deepEqual(bundle.routes.discriminant.steps.map(value => value.interaction.type),
      status === 'interactive' ? ['choice'] : cards.map(() => 'read'));
    assert.deepEqual(bundle.routes.discriminant.steps.flatMap(value => value.stream_steps), chunk.steps);
    const restored = createEventConsumer(identity);
    restored.hydrate({...snapshot, last_seq: count + 1, math_steps: cards,
      interaction_protocol: view.interaction_protocol, interaction_states: view.interaction_states, interactions: view.interactions});
    assert.deepEqual(extendStreamBundle(base, restored.view(), target, graph).routes.discriminant.steps,
      bundle.routes.discriminant.steps);
  });
}
