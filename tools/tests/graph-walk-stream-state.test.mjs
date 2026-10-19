import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {
  createState, currentDecision, submitAnswer, switchRoute, undo, graphState,
  extendStreamBundle, streamGraphState, replayState, migrateStageTwoState,
} from '../../site/assets/graph-walk/walk-state.mjs';
import {createEventConsumer} from '../../site/assets/graph-walk/stage-three-stream.mjs';

const read = path => JSON.parse(fs.readFileSync(new URL(path, import.meta.url), 'utf8'));
const original = read('../../site/lab/search/demo-lesson-q01.json').goals[0].walk;
const graph = read('../../site/knowledge/graph.json');
const d3 = read('../../site/data/graph-walk/quadratic-always-q01.source.json').intro.find(item => item.id === 'D3');
const d4 = {id: 'D4', title: '解题路线', options: [
  {branch: 'discriminant', route_id: 'discriminant', method: 'method-discriminant', route_plan: 'planned', recommendation: 'preferred'},
  {branch: 'separation', route_id: 'extremum', method: 'method-separation', route_plan: 'planned', recommendation: 'optional'},
]};
const identity = {run_id: 'run-current', lesson_version: 'lesson-current', stream_id: 'run-current'};
const target = '/root/goals/0';
const view = { ...identity, selection_chunks: [{target_ref: target, kind: 'D3', chunk: d3},
  {target_ref: target, kind: 'D4', chunk: d4}], math_steps: []};
const step = (ordinal, basis, source = '/steps/0/calls/0') => ({...identity, target_ref: target, route_id: 'discriminant',
  step_id: `math-${ordinal}`, ordinal, local_check: 'passed', math_step_sha256: `hash-${ordinal}`,
  method_ref: 'method-discriminant#normalize', source_refs: [source], used_basis: [basis], title: `数学步骤 ${ordinal}`});
const first = step(1, 'inequality-properties#addition');
const second = step(2, 'quadratic-function-properties#definition', '/steps/1/calls/0');
const checkpoint = {target_ref: target, route_id: 'discriminant', driver_state: {trajectory: {steps: [
  {seq: 1, method: 'method-discriminant', step: 'normalize', calls: [
    {public_ref: 'skill-inequality-transform', used_basis: ['inequality-properties#addition'], postconditions: [{passed: true}]},
  ]},
  {seq: 2, method: 'method-discriminant', step: 'conditions', calls: [
    {public_ref: 'skill-quadratic-sign', used_basis: ['quadratic-function-properties#definition'], postconditions: [{passed: true}]},
  ]},
]}}};
const withMath = {...view, math_steps: [first, second], checkpoints: [checkpoint]};

function answer(bundle, state, value) {
  const decision = currentDecision(bundle, state);
  return submitAnswer(bundle, state, {decision: decision.id, answer: value ??
    (decision.interaction.type === 'checklist' ? decision.expected_answer.terms : decision.expected_answer.one_of[0])});
}
function selected(bundle, route = 'discriminant') {
  let state = createState(bundle);
  state = answer(bundle, state);
  state = answer(bundle, state);
  const method = currentDecision(bundle, state).interaction.methods.find(item => item.route === route);
  state = answer(bundle, state, [...currentDecision(bundle, state).expected_answer.cell, method.value]);
  return answer(bundle, state, route);
}

test('identity is fixed before selection arrives and D1/D2 answers survive append-only expansion', () => {
  const waiting = extendStreamBundle(original.bundle, identity, target, graph);
  let state = answer(waiting, createState(waiting));
  state = answer(waiting, state);
  assert.equal(currentDecision(waiting, state), null);
  const bundle = extendStreamBundle(waiting, view, target, graph);
  assert.equal(bundle.bundleVersion, waiting.bundleVersion);
  assert.deepEqual(bundle.intro.slice(0, 2), original.bundle.intro);
  assert.equal(currentDecision(bundle, state).id, 'D3');
  const later = extendStreamBundle(bundle, withMath, target, graph);
  assert.equal(later.bundleVersion, bundle.bundleVersion);
  assert.deepEqual(state.introCompleted.map(item => item.decision), ['D1', 'D2']);
  assert.deepEqual(later.routes.discriminant.steps, []);
  assert.equal(later.stream.math_steps.length, 2);
  assert.deepEqual(original.bundle.routes, {});
});

test('stage-two answers migrate once into the same base lesson without losing undo or wrong attempts', () => {
  const base = original.bundle, stream = extendStreamBundle(base, view, target, graph);
  let state = submitAnswer(base, createState(base), {decision: 'D1', answer: ['wrong']});
  state = answer(base, state);
  state = answer(base, state);
  const before = structuredClone(state);
  const migrated = migrateStageTwoState(base, stream, JSON.parse(JSON.stringify(state)));
  assert.equal(currentDecision(stream, migrated).id, 'D3');
  assert.deepEqual(migrated.introCompleted, state.introCompleted);
  assert.deepEqual(migrated.events, state.events);
  assert.deepEqual(state, before);
  const oldUndo = undo(base, state), newUndo = undo(stream, migrated);
  assert.deepEqual(newUndo.introCompleted, oldUndo.introCompleted);
  assert.deepEqual(newUndo.events, oldUndo.events);
  assert.equal(currentDecision(stream, newUndo).id, 'D2');
  assert.equal(currentDecision(stream, migrateStageTwoState(base, stream, oldUndo)).id, 'D2');
  const nextRun = extendStreamBundle(base, {...view, run_id: 'new-run'}, target, graph);
  for (const bad of [migrated, {...state, bundleVersion: 'other'}, {...state, run: {...state.run, route: 'discriminant'}},
    {...state, introCompleted: []}, {...state, events: [...state.events, {kind: 'switch_route', route: 'extremum'}]}]) {
    assert.throws(() => migrateStageTwoState(base, nextRun, bad), /invalid_stage_two_progress/);
  }
  assert.throws(() => migrateStageTwoState({...base, problemId: 'different'}, stream, state), /invalid_stage_two_progress/);
});

test('both Q01 methods pass D3 and D4 without pretending mathematics is completed', () => {
  const bundle = extendStreamBundle(original.bundle, view, target, graph);
  for (const route of ['discriminant', 'extremum']) {
    const state = selected(bundle, route);
    assert.equal(state.lastFeedback.status, 'passed');
    assert.equal(state.run.route, route);
    assert.equal(state.done, false);
    assert.equal(currentDecision(bundle, state), null);
    assert.deepEqual(state.introCompleted.map(item => item.decision), ['D1', 'D2', 'D3', 'D4']);
    assert.deepEqual(state.run.completed, []);
    const replay = {...original.replay, bundleVersion: bundle.bundleVersion, routes: [route], status: 'partial',
      actions: state.events.map(event => event.action)};
    assert.deepEqual(replayState(bundle, replay), state);
  }
});

test('a mathematically fit method with a capability gap reaches D4 but cannot start reading', () => {
  const gapView = structuredClone(view);
  gapView.selection_chunks[1].chunk.options[1].route_plan = 'capability_gap';
  gapView.selection_chunks[1].chunk.options[1].message = '详细步骤暂不支持';
  const bundle = extendStreamBundle(original.bundle, gapView, target, graph);
  const state = selected(bundle, 'extremum');
  assert.equal(state.lastFeedback.status, 'uncovered');
  assert.equal(currentDecision(bundle, state).id, 'D4');
  assert.equal(state.introCompleted.length, 3);
  assert.equal(state.done, false);
  assert.equal(streamGraphState(bundle, state, {steps: [first], route: 'extremum'}).calls.length, 0);
  const usable = answer(bundle, state, 'discriminant');
  assert.equal(usable.lastFeedback.status, 'passed');
  assert.equal(usable.run.route, 'discriminant');
  assert.throws(() => switchRoute(bundle, usable, 'extremum'), /暂不支持/);
});

test('route changes preserve the two reading decisions and can be undone after refresh', () => {
  const bundle = extendStreamBundle(original.bundle, withMath, target, graph);
  const prior = selected(bundle);
  const changed = switchRoute(bundle, prior, 'extremum');
  assert.deepEqual(changed.introCompleted.slice(0, 2), prior.introCompleted.slice(0, 2));
  assert.equal(changed.introCompleted[2].answer[2], 'separation');
  assert.equal(changed.introCompleted[3].answer, 'extremum');
  assert.equal(changed.run.route, 'extremum');
  const restored = JSON.parse(JSON.stringify(changed));
  assert.equal(graphState(bundle, restored).nodes['method-separation'], 'confirmed');
  assert.deepEqual(undo(bundle, restored).run, prior.run);
  assert.equal(switchRoute(bundle, restored, 'discriminant').run.route, 'discriminant');
});

test('new calculation data does not illuminate unread skills or future mathematics', () => {
  const bundle = extendStreamBundle(original.bundle, withMath, target, graph);
  const state = selected(bundle);
  const initial = streamGraphState(bundle, state);
  assert.equal(initial.nodes['skill-inequality-transform'], 'idle');
  assert.equal(initial.nodes['skill-quadratic-sign'], 'idle');
  assert.equal(initial.calls.length, 0);
  const reached = streamGraphState(bundle, state, {steps: [first]});
  assert.equal(reached.nodes['skill-inequality-transform'], 'confirmed');
  assert.equal(reached.edges['method-discriminant|calls|skill-inequality-transform'], 'chosen');
  assert.ok(reached.usedBasis.includes('inequality-properties#addition'));
  assert.equal(reached.nodes['skill-quadratic-sign'], 'idle');
  assert.equal(reached.calls.length, 1);
  assert.equal(reached.calls[0].decision, first.step_id);
  assert.equal(reached.calls[0].ref, 'skill-inequality-transform');
  assert.equal(state.events.length, 4); // Reading is not an invented graded answer.
});

test('graph evidence is scoped by run, target, route, step identity and mathematical hash', () => {
  const bundle = extendStreamBundle(original.bundle, withMath, target, graph);
  const state = selected(bundle);
  for (const bad of [{...first, run_id: 'old'}, {...first, target_ref: '/root/children/0/goals/0'},
    {...first, route_id: 'extremum'}, {...first, step_id: 'unknown'}, {...first, math_step_sha256: 'changed'}]) {
    assert.equal(streamGraphState(bundle, state, {steps: [bad]}).calls.length, 0);
  }
  assert.equal(streamGraphState(bundle, state, {steps: [first, first]}).calls.length, 1);
  assert.equal(streamGraphState(bundle, state, {steps: [first], route: 'extremum'}).calls.length, 0);
  const early = answer(bundle, createState(bundle));
  assert.equal(streamGraphState(bundle, early, {steps: [first], route: 'discriminant'}).calls.length, 0);
});

test('snapshot and incremental trajectory evidence produce the same reached graph', () => {
  const incremental = {...withMath, checkpoints: [], trajectories: [{target_ref: target, route_id: 'discriminant',
    steps: checkpoint.driver_state.trajectory.steps}]};
  const a = extendStreamBundle(original.bundle, withMath, target, graph);
  const b = extendStreamBundle(original.bundle, incremental, target, graph);
  assert.deepEqual(streamGraphState(a, selected(a), {steps: [first, second]}),
    streamGraphState(b, selected(b), {steps: [first, second]}));
  const noEvidence = extendStreamBundle(original.bundle, {...withMath, checkpoints: []}, target, graph);
  assert.equal(streamGraphState(noEvidence, selected(noEvidence), {steps: [first]}).calls.length, 0);
});

test('QA and arrival order never rewrite mathematical data or selection identities', () => {
  const bundle = extendStreamBundle(original.bundle, withMath, target, graph);
  assert.deepEqual(extendStreamBundle(bundle, {...withMath, qa: [{qa: {hints: ['提示']}}]}, target, graph), bundle);
  assert.throws(() => extendStreamBundle(bundle, {...view, run_id: 'old'}, target, graph), /identity_mismatch/);
  const changed = structuredClone(withMath);
  changed.math_steps[0].title = '偷偷改正文';
  assert.throws(() => extendStreamBundle(bundle, changed, target, graph), /immutable_math_step/);
  const changedSelection = structuredClone(withMath);
  changedSelection.selection_chunks[0].chunk.title = '改变选法';
  assert.throws(() => extendStreamBundle(bundle, changedSelection, target, graph), /immutable_selection/);
});

const q03Evidence = read('./fixtures/graph-stage-three-q03-evidence.json');
const q03Bundle = snapshot => extendStreamBundle(original.bundle, snapshot, target, graph);
const q03Reached = (snapshot, steps) => {
  const bundle = q03Bundle(snapshot);
  return streamGraphState(bundle, selected(bundle), {steps});
};

test('Q03 checked internal operations light their bases only after their own card is read', () => {
  const bundle = q03Bundle(q03Evidence), state = selected(bundle);
  const [classification, negativeCase, positiveCase, , , , solution, merge, boundary] = q03Evidence.math_steps;
  const unread = streamGraphState(bundle, state);
  assert.equal(unread.nodes['linear-interval-extremum'], 'idle');
  assert.ok(!unread.usedBasis.includes('method-discriminant#merge'));
  const classified = streamGraphState(bundle, state, {steps: [classification]});
  assert.equal(classified.nodes['linear-interval-extremum'], 'idle');
  for (const card of [negativeCase, positiveCase]) {
    const reached = streamGraphState(bundle, state, {steps: [card]});
    assert.equal(reached.nodes['linear-interval-extremum'], 'confirmed');
    assert.ok(reached.usedBasis.includes('method-discriminant#degree'));
    assert.ok(reached.usedBasis.includes('quadratic-function-properties#definition'));
    assert.ok(!reached.usedBasis.includes('method-discriminant#merge'));
    assert.equal(reached.calls.length, 0); // No synthetic public call for an internal operation.
  }
  const solved = streamGraphState(bundle, state, {steps: [solution]});
  assert.ok(solved.usedBasis.includes('method-discriminant#solve'));
  assert.equal(solved.nodes['skill-solve-quadratic'], 'confirmed');
  assert.ok(!solved.usedBasis.includes('method-discriminant#merge'));
  const merged = streamGraphState(bundle, state, {steps: [merge]});
  assert.ok(merged.usedBasis.includes('method-discriminant#merge'));
  assert.equal(merged.nodes['linear-interval-extremum'], 'idle'); // No scan of earlier cases.
  assert.equal(merged.calls.length, 0);
  assert.ok(streamGraphState(bundle, state, {steps: [boundary]}).usedBasis.includes('function-range-extrema#attainability'));
});

test('Q03 card basis claims cannot bypass source, branch and nonempty local-check validation', () => {
  const caseIndex = 1;
  const base = structuredClone(q03Evidence);
  base.math_steps[caseIndex].used_basis.push('inequality-properties#addition', 'invented-basis');
  const reached = q03Reached(base, [base.math_steps[caseIndex]]);
  assert.ok(!reached.usedBasis.includes('inequality-properties#addition'));
  assert.ok(!reached.usedBasis.includes('invented-basis'));
  assert.equal(reached.nodes['invented-basis'], undefined);
  const invalid = [
    value => value.checkpoints[0].driver_state.trajectory.steps[1].calls[0].postconditions = [],
    value => delete value.checkpoints[0].driver_state.trajectory.steps[1].calls[0].postconditions,
    value => value.checkpoints[0].driver_state.trajectory.steps[1].calls[0].postconditions[0].passed = false,
    value => value.checkpoints[0].driver_state.trajectory.steps[1].calls[0].postconditions[0].passed = 'true',
    value => value.checkpoints[0].driver_state.trajectory.steps[1].case_path = ['degenerate-1'],
    value => value.checkpoints[0].driver_state.trajectory.steps[1].calls[0].case_path = ['degenerate-1'],
    value => value.checkpoints[0].route_id = 'extremum',
    value => value.checkpoints[0].target_ref = '/root/children/0/goals/0',
    value => value.math_steps[caseIndex].source_refs = ['/steps/8/skipped_calls/0'],
    value => value.math_steps[caseIndex].source_refs = ['/steps/0/judgments/0'],
    value => value.math_steps[caseIndex].source_refs = ['/steps/999/calls/0'],
  ];
  for (const mutate of invalid) {
    const snapshot = structuredClone(base);
    mutate(snapshot);
    const result = q03Reached(snapshot, [snapshot.math_steps[caseIndex]]);
    assert.ok(!result.usedBasis.includes('linear-interval-extremum'));
    assert.ok(!result.usedBasis.includes('method-discriminant#degree'));
    assert.equal(result.calls.length, 0);
  }
  const unverifiedBoundary = structuredClone(base);
  unverifiedBoundary.checkpoints[0].driver_state.trajectory.finalization[2].postconditions = [];
  assert.ok(!q03Reached(unverifiedBoundary, [unverifiedBoundary.math_steps.at(-1)]).usedBasis.includes('function-range-extrema#attainability'));
});

test('unchecked public calls cannot light a skill or inherit a card basis claim', () => {
  for (const postconditions of [undefined, [], [{passed: false}], [{passed: true}, {passed: false}]]) {
    const changed = structuredClone(withMath);
    changed.checkpoints[0].driver_state.trajectory.steps[0].calls[0].postconditions = postconditions;
    const bundle = extendStreamBundle(original.bundle, changed, target, graph);
    const reached = streamGraphState(bundle, selected(bundle), {steps: [first]});
    assert.equal(reached.calls.length, 0);
    assert.notEqual(reached.nodes['skill-inequality-transform'], 'confirmed');
    assert.ok(!reached.usedBasis.includes('inequality-properties#addition'));
  }
});

test('Q03 snapshot and committed events give identical internal, public and boundary graph evidence', () => {
  const snapshotConsumer = createEventConsumer(q03Evidence);
  snapshotConsumer.hydrate(q03Evidence);
  const eventConsumer = createEventConsumer(q03Evidence);
  let seq = 0;
  const emit = (type, payload, route = null) => eventConsumer.accept({
    run_id: q03Evidence.run_id, lesson_version: q03Evidence.lesson_version, stream_id: q03Evidence.stream_id,
    event_id: `event-${++seq}`, seq, type, target_ref: target, route_id: route, payload,
  });
  for (const {kind, chunk} of q03Evidence.selection_chunks) emit('lesson.chunk_ready', {kind, chunk});
  const trajectory = q03Evidence.checkpoints[0].driver_state.trajectory;
  emit('solver.step_completed', {trajectory: trajectory.steps}, 'discriminant');
  for (const card of q03Evidence.math_steps) {
    if (card.source_refs[0].startsWith('/finalization/')) {
      // The sparse event carries the original index, never a compacted array.
      emit('solver.step_completed', {trajectory: [], operation: 'endpoint_check',
        finalization: [{index: 2, record: trajectory.finalization[2]}]}, 'discriminant');
    }
    emit('lesson.chunk_ready', {kind: 'math_step', step_id: card.step_id,
      math_step_sha256: card.math_step_sha256, chunk: card}, 'discriminant');
    const snapshotGraph = q03Reached({...snapshotConsumer.view(),
      math_steps: q03Evidence.math_steps.filter(step => step.ordinal <= card.ordinal)}, [card]);
    const eventGraph = q03Reached(eventConsumer.view(), [card]);
    assert.deepEqual(eventGraph, snapshotGraph);
  }
  const finalView = eventConsumer.view();
  assert.deepEqual(finalView.trajectories[0].finalization.map(item => item.index), [2]);
  assert.ok(q03Reached(finalView, [q03Evidence.math_steps.at(-1)]).usedBasis.includes('function-range-extrema#attainability'));
  assert.throws(() => emit('solver.step_completed', {trajectory: [], finalization: [{index: 2,
    record: {...trajectory.finalization[2], used_basis: ['invented-basis']}}]}, 'discriminant'), /immutable_finalization_source/);
});
