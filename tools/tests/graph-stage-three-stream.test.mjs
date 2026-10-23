import test from 'node:test';
import assert from 'node:assert/strict';
import {createEventConsumer, mountStageThreeStream, connectStageThreeStream} from '../../site/assets/graph-walk/stage-three-stream.mjs';

const identity = {run_id: 'run-01', lesson_version: 'lesson-01', stream_id: 'run-01'};
const target = '/root/goals/0';
const route = 'discriminant';
const step = (ordinal = 1, targetRef = target) => ({
  contract: 'graph-math-step/v1', ...identity, target_ref: targetRef, route_id: route,
  step_id: `step-${ordinal}`, ordinal, math_step_sha256: `${targetRef}-${ordinal}-hash`, local_check: 'passed',
  title: ordinal === 1 ? '计算判别式' : '求参数范围',
  before: [{expression: 'x^2+a', latex: 'x^2+a'}], after: [{expression: 'a>=0', latex: 'a≥0'}],
  explanation: '根据二次函数性质计算。', premise_refs: ['/root/facts/0'], used_basis: ['skill-quadratic-sign'],
});
const event = (seq, type, payload, targetRef = target) => ({
  contract: 'graph-stage-three-event/v1', ...identity, seq, event_id: `event-${seq}`,
  target_ref: targetRef, route_id: type === 'lesson.goal_status' ? null : route, type, payload,
});
const mathEvent = (seq, value = step()) => event(seq, 'lesson.chunk_ready', {
  kind: 'math_step', step_id: value.step_id, math_step_sha256: value.math_step_sha256, chunk: value,
}, value.target_ref);
const doneEvent = seq => event(seq, 'lesson.chunk_ready', {kind: 'route_completion', status: 'verified',
  answer: {kind: 'find_range', status: 'set', set: '[0,+∞)'}, feasible_set: '[0,+∞)', verified_route_sha256: 'route-hash'});
const qa = (value = step()) => ({...identity, target_ref: value.target_ref, route_id: value.route_id,
  step_id: value.step_id, math_step_sha256: value.math_step_sha256, verified_route_sha256: 'route-hash',
  qa: {questions: ['为什么判别式不大于零？'], feedback: '函数在实数范围恒非负。'}});
const qaEvent = (seq, chunk = qa()) => event(seq, 'lesson.chunk_ready', {kind: 'step_qa', step_id: chunk.step_id,
  math_step_sha256: chunk.math_step_sha256, verified_route_sha256: chunk.verified_route_sha256, chunk}, chunk.target_ref);

test('snapshot recovery retains the same original-choice answer as the live completion event', () => {
  const original_choice = {status: 'matched', kind: 'single_choice', target_ref: target,
    options: [{label: 'A', text: '$a\\ge0$'}, {label: 'B', text: '$a<0$'}], correct_labels: ['A']};
  const live = createEventConsumer(identity), completion = doneEvent(1);
  completion.payload.original_choice = original_choice;
  live.accept(completion);
  const refreshed = createEventConsumer(identity);
  refreshed.hydrate({...identity, last_seq: 1, math_steps: [], goals: {}, handoffs: [{
    target_ref: target, route_id: route, available: true, status: 'pending',
    answer: completion.payload.answer, feasible_set: completion.payload.feasible_set,
    verified_route_sha256: completion.payload.verified_route_sha256, original_choice}]});
  assert.deepEqual(refreshed.view().completions[0].original_choice, live.view().completions[0].original_choice);
  assert.deepEqual(refreshed.view().completions[0].answer, live.view().completions[0].answer);
});

test('frozen case conditions survive live delivery and snapshot recovery and cannot be rewritten', () => {
  const value = {...step(), contract: 'graph-math-step/v2', case_path: ['quadratic'],
    case_condition: {expression: 'Ne(c, 1/3)', latex: 'c\\ne\\frac{1}{3}'}};
  const live = createEventConsumer(identity), refreshed = createEventConsumer(identity);
  live.accept(mathEvent(1, value));
  refreshed.hydrate({...identity, last_seq: 1, math_steps: [value], goals: {}});
  for (const consumer of [live, refreshed]) {
    assert.deepEqual(consumer.view().math_steps[0].case_condition, value.case_condition);
    assert.deepEqual(consumer.view().math_steps[0].case_path, value.case_path);
    const changed = {...value, case_condition: {...value.case_condition, latex: 'c=0'}};
    assert.throws(() => consumer.accept(mathEvent(2, changed)), /stream.immutable_math_step/);
    assert.deepEqual(consumer.view().math_steps[0].case_condition, value.case_condition);
  }
});

for (const delivery of ['live', 'snapshot']) test(`opening branch metadata is frozen separately from the execution path after ${delivery} delivery`, () => {
  const value = {...step(), contract: 'graph-math-step/v2', case_path: ['nondegenerate'],
    case_condition: {expression: 'Ne(k, 0)', latex: 'k\\ne0'}, branch_id: 'opening-up',
    branch_condition: {expression: 'Gt(k, 0)', latex: 'k>0'}};
  const snapshot = math => ({...identity, last_seq: 1, math_steps: [math], goals: {}});
  for (const field of ['branch_id', 'branch_condition']) {
    const consumer = createEventConsumer(identity);
    if (delivery === 'live') consumer.accept(mathEvent(1, value));
    else consumer.hydrate(snapshot(value));
    assert.deepEqual(consumer.view().math_steps[0], value);
    const changed = {...value, [field]: field === 'branch_id' ? 'opening-down'
      : {expression: 'Lt(k, 0)', latex: 'k<0'}};
    assert.throws(() => consumer.accept(mathEvent(2, changed)), /stream.immutable_math_step/);
    assert.throws(() => consumer.hydrate(snapshot(changed)), /stream.snapshot_math_changed/);
    assert.deepEqual(consumer.view().math_steps[0], value);
  }
});

test('subscription forwards committed data without creating DOM or reading progress', () => {
  const seen = [];
  const view = mountStageThreeStream(identity, {
    onMathStep: value => seen.push(['math', value.step_id]),
    onRouteStatus: (targetRef, routeId, value) => seen.push(['status', targetRef, routeId, value.status]),
  });
  view.consumer.accept(event(1, 'lesson.route_status', {status: 'running'}));
  view.consumer.accept(mathEvent(2));
  assert.deepEqual(seen, [['status', target, route, 'running'], ['math', 'step-1']]);
  assert.equal(view.consumer.last_seq, 2);
  assert.deepEqual(view.consumer.view().completions, []);
  assert.deepEqual(Object.keys(view).sort(), ['consumer', 'pollOnce', 'start', 'stop']);
});

test('legacy saved math is adapted at read boundaries without touching decision.display or saved hashes', () => {
  const legacy = step();
  for (const value of [...legacy.before, ...legacy.after]) {
    value.display = value.latex; delete value.latex;
  }
  const original = structuredClone(legacy);
  const view = mountStageThreeStream(identity);
  view.consumer.accept(mathEvent(1, legacy));
  const current = view.consumer.view().math_steps[0];
  assert.deepEqual(current.before, [{expression: 'x^2+a', latex: 'x^2+a'}]);
  assert.equal(current.math_step_sha256, legacy.math_step_sha256);
  const decision = {expression: 'a', display: '<p>{expression}</p>'};
  view.consumer.accept(event(2, 'lesson.chunk_ready', {kind: 'D1', chunk: {decision}}));
  assert.deepEqual(view.consumer.view().selection_chunks[0].chunk.decision, decision);
  view.consumer.hydrate({...identity, last_seq: 3, math_steps: [legacy], goals: {}, checkpoints: [], handoffs: [], qa: []});
  assert.deepEqual(view.consumer.view().math_steps[0], current);
  assert.deepEqual(legacy, original);
  assert.equal(view.consumer.view().math_steps.length, 1);
});

test('failed data subscribers retry the same mathematical event', () => {
  let fail = true;
  const received = [];
  const view = mountStageThreeStream(identity, {onMathStep(value) {
    if (fail) throw new Error('subscriber loading');
    received.push(value.step_id);
  }});
  assert.throws(() => view.consumer.accept(mathEvent(1)), /subscriber loading/);
  assert.equal(view.consumer.view().math_steps.length, 0);
  assert.equal(view.consumer.last_seq, 0);
  fail = false;
  view.consumer.accept(mathEvent(1));
  assert.deepEqual(received, ['step-1']);
  assert.equal(view.consumer.last_seq, 1);
});

test('duplicate, out-of-order and old-run deliveries cannot duplicate or mix cards', () => {
  const received = [], gaps = [];
  const consumer = createEventConsumer(identity, {onMathStep: value => received.push(value.step_id), onGap: seq => gaps.push(seq)});
  consumer.accept(mathEvent(2, step(2)));
  assert.deepEqual(received, []);
  assert.deepEqual(gaps, [0]);
  consumer.accept(mathEvent(1));
  assert.deepEqual(received, ['step-1', 'step-2']);
  consumer.accept(mathEvent(1));
  consumer.accept({...mathEvent(3, step(3)), run_id: 'old-run'});
  assert.deepEqual(received, ['step-1', 'step-2']);
  assert.equal(consumer.last_seq, 2);
});

test('modified mathematical content cannot overwrite a published step', () => {
  const consumer = createEventConsumer(identity);
  consumer.accept(mathEvent(1));
  const changed = {...step(), title: 'different claim'};
  assert.throws(() => consumer.accept(mathEvent(2, changed)), /immutable_math_step/);
  assert.equal(consumer.last_seq, 1);
  assert.equal(consumer.view().math_steps[0].title, '计算判别式');
});

test('same route and step names in sibling questions remain distinct', () => {
  const consumer = createEventConsumer(identity);
  consumer.accept(mathEvent(1));
  consumer.accept(mathEvent(2, step(1, '/root/children/0/goals/0')));
  assert.equal(consumer.view().math_steps.length, 2);
});

test('QA is forwarded independently and replayed on refresh without repeating math callbacks', () => {
  const mathematics = [], supplementary = [], snapshots = [];
  const view = mountStageThreeStream(identity, {
    onMathStep: value => mathematics.push(value), onQA: value => supplementary.push(value),
    onSnapshot: value => snapshots.push(value.last_seq),
  });
  view.consumer.accept(mathEvent(1));
  view.consumer.accept(doneEvent(2));
  view.consumer.accept(qaEvent(3));
  assert.deepEqual(supplementary, [qa()]);
  view.consumer.hydrate({...identity, last_seq: 4, math_steps: [step()], goals: {},
    handoffs: [{target_ref: target, route_id: route, available: true, verified_route_sha256: 'route-hash'}], qa: [qa()]});
  assert.deepEqual(supplementary, [qa(), qa()]);
  assert.deepEqual(mathematics, [step()]);
  assert.deepEqual(snapshots, [4]);
});

for (const field of ['math_step_sha256', 'verified_route_sha256', 'step_id', 'target_ref']) test(`QA cannot bind to mismatched ${field}`, () => {
  const consumer = createEventConsumer(identity);
  consumer.accept(mathEvent(1));
  consumer.accept(doneEvent(2));
  assert.throws(() => consumer.accept(qaEvent(3, {...qa(), [field]: 'incorrect'})), /qa_hash_mismatch/);
  assert.deepEqual(consumer.view().qa, []);
});

test('late conflict marks completion unavailable and stops forwarding stale QA', () => {
  const supplementary = [], goals = [];
  const view = mountStageThreeStream(identity, {
    onQA: value => supplementary.push(value), onGoalStatus: (...args) => goals.push(args),
  });
  view.consumer.accept(mathEvent(1));
  view.consumer.accept(event(2, 'lesson.goal_status', {status: 'solved', available: true}));
  view.consumer.accept(doneEvent(3));
  view.consumer.accept(qaEvent(4));
  view.consumer.accept(event(5, 'lesson.goal_status', {status: 'conflict', available: false}));
  view.consumer.accept(qaEvent(6));
  view.consumer.accept(doneEvent(7));
  assert.deepEqual(view.consumer.view().math_steps, [step()]);
  assert.equal(view.consumer.view().completions[0].available, false);
  assert.deepEqual(supplementary, [qa()]);
  assert.deepEqual(goals.at(-1), [target, {status: 'conflict', available: false}]);
});

test('cursor expiry hydrates an atomic snapshot, then polls after its watermark', async () => {
  const cursors = [];
  let call = 0;
  const snapshot = {...identity, last_seq: 3, math_steps: [step()], goals: {}, checkpoints: [], handoffs: [], qa: []};
  const view = mountStageThreeStream(identity, {
    fetchEvents: async cursor => { cursors.push(cursor); return ++call === 1 ? {cursor_expired: true} : {events: [mathEvent(4, step(2))]}; },
    fetchSnapshot: async () => snapshot,
  });
  await view.pollOnce();
  assert.equal(view.consumer.last_seq, 3);
  await view.pollOnce();
  assert.deepEqual(cursors, [0, 3]);
  assert.equal(view.consumer.view().math_steps.length, 2);
});

test('refresh snapshot restores mathematical state without resending known cards', () => {
  const received = [], view = mountStageThreeStream(identity, {onMathStep: value => received.push(value.step_id)});
  view.consumer.accept(mathEvent(1));
  view.consumer.accept(mathEvent(2, step(2)));
  view.consumer.hydrate({...identity, last_seq: 10, math_steps: [step(), step(2)], goals: {}, checkpoints: [], handoffs: [], qa: []});
  assert.deepEqual(received, ['step-1', 'step-2']);
  assert.equal(view.consumer.last_seq, 10);
});

test('late transport response after subscription closure cannot publish data', async () => {
  let respond;
  const view = mountStageThreeStream(identity, {fetchEvents: () => new Promise(resolve => { respond = resolve; })});
  const pending = view.pollOnce();
  view.stop();
  respond({events: [mathEvent(1)]});
  await pending;
  assert.deepEqual(view.consumer.view().math_steps, []);
});

test('selection chunks and committed call evidence survive snapshot hydration', () => {
  const consumer = createEventConsumer(identity), d3 = {id: 'D3'}, d4 = {id: 'D4'};
  consumer.accept(event(1, 'lesson.chunk_ready', {kind: 'D3', chunk: d3}));
  consumer.hydrate({...identity, last_seq: 3, selection_chunks: [{target_ref: target, kind: 'D3', chunk: d3},
    {target_ref: target, kind: 'D4', chunk: d4}], math_steps: [], goals: {},
    checkpoints: [{target_ref: target, route_id: route, driver_state: {trajectory: {steps: [{seq: 1, calls: [{public_ref: 'skill-example'}]}]}}}]});
  assert.equal(consumer.view().selection_chunks.length, 2);
  assert.equal(consumer.view().trajectories[0].steps[0].calls[0].public_ref, 'skill-example');
  assert.throws(() => consumer.accept(event(4, 'lesson.chunk_ready', {kind: 'D3', chunk: {id: 'different'}})), /immutable_selection/);
});

test('a failed QA mount can retry the same sequence without losing the attachment', () => {
  let count = 0;
  const consumer = createEventConsumer(identity, {onQA() { if (++count === 1) throw new Error('temporary render failure'); }});
  consumer.accept(mathEvent(1)); consumer.accept(doneEvent(2));
  assert.throws(() => consumer.accept(qaEvent(3)), /temporary/);
  assert.equal(consumer.last_seq, 2);
  assert.equal(consumer.view().qa.length, 0);
  consumer.accept(qaEvent(3));
  assert.equal(consumer.last_seq, 3);
  assert.equal(consumer.view().qa.length, 1);
  assert.equal(count, 2);
});

const pendingEvent = (seq, value = step(), status = 'pending') => {
  const result = mathEvent(seq, value);
  result.payload.interaction_status = status;
  return result;
};
const interaction = (values, status = 'interactive', id = `interaction-${values.map(value => value.ordinal).join('-')}`) => ({
  contract: 'graph-step-interaction/v1', ...identity, target_ref: values[0].target_ref, route_id: route,
  interaction_id: id, steps: values.map(value => ({step_id: value.step_id, math_step_sha256: value.math_step_sha256})),
  interaction_revision: 'rules-01', status, parts: status === 'interactive' ? [{kind: 'choice', options: ['A', 'B']}] : [],
  ...(status === 'readonly' ? {reason: 'no_rule'} : {}), interaction_sha256: `${id}-hash`,
});
const interactionEvent = (seq, chunk) => event(seq, 'lesson.chunk_ready', {
  kind: 'step_interaction', interaction_id: chunk.interaction_id, status: chunk.status, chunk}, chunk.target_ref);
const statuses = consumer => consumer.view().interaction_states.map(value => [value.step_id, value.status, value.interaction_id]);
const interactionSnapshot = (cards, chunks, lastSeq) => ({
  ...identity, last_seq: lastSeq, math_steps: cards, goals: {},
  interaction_protocol: 'graph-step-interaction/v1', interactions: chunks,
  interaction_states: cards.map(card => {
    const chunk = chunks.find(value => value.target_ref === card.target_ref && value.route_id === card.route_id &&
      value.steps.some(ref => ref.step_id === card.step_id));
    return {target_ref: card.target_ref, route_id: card.route_id, step_id: card.step_id, ordinal: card.ordinal,
      math_step_sha256: card.math_step_sha256, status: chunk?.status || 'pending',
      ...(chunk ? {interaction_id: chunk.interaction_id} : {})};
  }),
});

test('math cards appear pending and a merged interaction resolves both cards at once', () => {
  const received = [];
  const view = mountStageThreeStream(identity, {onInteraction: chunk => received.push(chunk.interaction_id)});
  view.consumer.accept(pendingEvent(1));
  view.consumer.accept(pendingEvent(2, step(2)));
  assert.deepEqual(statuses(view.consumer), [['step-1', 'pending', undefined], ['step-2', 'pending', undefined]]);
  const merged = interaction([step(), step(2)]);
  view.consumer.accept(interactionEvent(3, merged));
  assert.deepEqual(statuses(view.consumer), [['step-1', 'interactive', merged.interaction_id], ['step-2', 'interactive', merged.interaction_id]]);
  assert.deepEqual(view.consumer.view().interactions, [merged]);
  assert.equal(view.consumer.view().interaction_protocol, 'graph-step-interaction/v1');
  assert.deepEqual(received, [merged.interaction_id]);
  assert.equal(view.consumer.view().math_steps[0].title, '计算判别式');
});

for (const status of ['pending', 'readonly']) test(`the first ${status} card enables interactions after an earlier empty snapshot`, () => {
  const consumer = createEventConsumer(identity);
  consumer.hydrate({...identity, last_seq: 0, math_steps: [], goals: {}, interaction_protocol: null,
    interaction_states: [], interactions: []});
  assert.equal(consumer.view().interaction_protocol, null);
  consumer.accept(pendingEvent(1, step(), status));
  assert.equal(consumer.view().interaction_protocol, 'graph-step-interaction/v1');
  assert.deepEqual(statuses(consumer), [['step-1', status, undefined]]);
  assert.deepEqual(consumer.view().interactions, []);
  const chunk = interaction([step()], status === 'pending' ? 'interactive' : 'readonly');
  consumer.accept(interactionEvent(2, chunk));
  assert.deepEqual(consumer.view().interactions, [chunk]);
});

test('a rejected status cannot activate the protocol', () => {
  const consumer = createEventConsumer(identity);
  assert.throws(() => consumer.accept(pendingEvent(1, step(), 'unknown')), /invalid_interaction_status/);
  assert.equal(consumer.view().interaction_protocol, null);
  assert.deepEqual(consumer.view().interaction_states, []);
});

test('a failed math callback does not leave an enabled protocol or pending state behind', () => {
  let fail = true;
  const consumer = createEventConsumer(identity, {onMathStep() { if (fail) throw new Error('temporary'); }});
  assert.throws(() => consumer.accept(pendingEvent(1)), /temporary/);
  assert.equal(consumer.last_seq, 0);
  assert.equal(consumer.view().interaction_protocol, null);
  assert.deepEqual(consumer.view().math_steps, []);
  assert.deepEqual(consumer.view().interaction_states, []);
  fail = false;
  consumer.accept(pendingEvent(1));
  assert.equal(consumer.view().interaction_protocol, 'graph-step-interaction/v1');
  assert.deepEqual(statuses(consumer), [['step-1', 'pending', undefined]]);
});

test('legacy streams without the protocol keep no interaction state', () => {
  const consumer = createEventConsumer(identity);
  consumer.accept(mathEvent(1));
  consumer.hydrate({...identity, last_seq: 1, math_steps: [step()], goals: {}});
  consumer.hydrate({...identity, last_seq: 2, math_steps: [step(), step(2)], goals: {},
    interaction_protocol: null, interaction_states: [], interactions: []});
  assert.deepEqual(consumer.view().interaction_states, []);
  assert.equal(consumer.view().math_steps.length, 2);
  assert.equal(consumer.view().interaction_protocol, null);
});

const pendingConsumer = (count, hooks) => {
  const consumer = createEventConsumer(identity, hooks);
  for (let ordinal = 1; ordinal <= count; ordinal += 1) consumer.accept(pendingEvent(ordinal, step(ordinal)));
  return consumer;
};

test('a resolved interaction is immutable and an identical retry is idempotent', () => {
  const chunk = interaction([step()]);
  const resolved = () => {
    const consumer = pendingConsumer(2);
    consumer.accept(interactionEvent(3, chunk));
    return consumer;
  };
  const consumer = resolved();
  consumer.hydrate(interactionSnapshot([step(), step(2)], [chunk], 3));
  consumer.accept(interactionEvent(4, chunk));
  assert.deepEqual(consumer.view().interactions, [chunk]);
  for (const [changed, error] of [[{...chunk, parts: [{kind: 'choice', options: ['B', 'C']}]}, /immutable_interaction/],
    [interaction([step(), step(2)], 'readonly', 'other'), /interaction_conflict/]]) {
    const current = resolved();
    assert.throws(() => current.accept(interactionEvent(4, changed)), error);
    assert.equal(current.last_seq, 3);
    assert.deepEqual(statuses(current), [['step-1', 'interactive', chunk.interaction_id], ['step-2', 'pending', undefined]]);
  }
});

test('an interaction must cover published, unchanged and contiguous cards', () => {
  const chunk = interaction([step()]);
  for (const [value, error] of [
    [interactionEvent(4, interaction([step(4)])), /interaction_hash_mismatch/],
    [interactionEvent(4, interaction([{...step(), math_step_sha256: 'changed'}])), /interaction_hash_mismatch/],
    [interactionEvent(4, interaction([step(), step(3)])), /interaction_noncontiguous/],
    [interactionEvent(4, {...chunk, contract: 'other/v1'}), /invalid_interaction/],
    [event(4, 'lesson.chunk_ready', {kind: 'step_interaction', interaction_id: 'different', status: chunk.status, chunk}),
      /interaction_identity_mismatch/],
  ]) {
    const consumer = pendingConsumer(3);
    assert.throws(() => consumer.accept(value), error);
    assert.equal(consumer.last_seq, 3);
    assert.deepEqual(consumer.view().interactions, []);
  }
});

for (const {name, count = 1, status = 'interactive', change, valid = false} of [
  {name: 'three-card groups', count: 3},
  {name: 'interactive results without parts', change: chunk => { chunk.parts = []; }},
  {name: 'readonly results with parts', status: 'readonly', change: chunk => { chunk.parts = [{kind: 'choice'}]; }},
  {name: 'foreign-run identity', change: chunk => { chunk.run_id = 'other'; }},
  {name: 'foreign-lesson identity', change: chunk => { chunk.lesson_version = 'other'; }},
  {name: 'unknown contracts', change: chunk => { chunk.contract = 'other/v1'; }},
  {name: 'empty interaction identifiers', change: chunk => { chunk.interaction_id = ''; }},
  {name: 'one-card interactive results', valid: true},
  {name: 'two-card interactive results', count: 2, valid: true},
  {name: 'one-card readonly results', status: 'readonly', valid: true},
  {name: 'two-card readonly results', count: 2, status: 'readonly', valid: true},
]) test(`live events and snapshots enforce the same result shape: ${name}`, () => {
  const cards = [step(), step(2), step(3)], chunk = interaction(cards.slice(0, count), status);
  change?.(chunk);
  for (const path of ['event', 'snapshot']) {
    const calls = [];
    const consumer = pendingConsumer(cards.length, {
      onInteraction: value => calls.push(['interaction', value.interaction_id]),
      onSnapshot: value => calls.push(['snapshot', value.last_seq]),
      onEvent: value => calls.push(['event', value.seq]),
    });
    const before = consumer.view(), beforeCalls = structuredClone(calls);
    const snapshot = interactionSnapshot(cards, [chunk], 4);
    const apply = () => path === 'event' ? consumer.accept(interactionEvent(4, chunk)) : consumer.hydrate(snapshot);
    if (!valid) {
      assert.throws(apply, {message: path === 'event' ? 'stream.invalid_interaction' : 'stream.snapshot_interaction_changed'});
      assert.deepEqual(consumer.view(), before);
      assert.deepEqual(calls, beforeCalls, 'invalid results do not publish callbacks');
      assert.equal(consumer.last_seq, 3);
      if (path === 'snapshot') {
        // Rejected projections must not poison the subsequent valid refresh.
        const replacement = interaction(cards.slice(0, Math.min(count, 2)), status);
        consumer.hydrate(interactionSnapshot(cards, [replacement], 4));
        assert.deepEqual(consumer.view().interactions, [replacement]);
      }
    } else {
      apply();
      assert.deepEqual(consumer.view().interactions, [chunk]);
      assert.deepEqual(statuses(consumer), cards.map((card, index) => [card.step_id,
        index < count ? status : 'pending', index < count ? chunk.interaction_id : undefined]));
      assert.equal(consumer.last_seq, 4);
      assert.equal(calls.filter(([kind]) => kind === 'interaction').length, 1);
    }
  }
});

test('a failed interaction hook can retry the same sequence', () => {
  let count = 0;
  const consumer = createEventConsumer(identity, {onInteraction() { if (++count === 1) throw new Error('temporary'); }});
  consumer.accept(pendingEvent(1));
  const chunk = interaction([step()], 'readonly');
  assert.throws(() => consumer.accept(interactionEvent(2, chunk)), /temporary/);
  assert.deepEqual(statuses(consumer), [['step-1', 'pending', undefined]]);
  assert.equal(consumer.view().interaction_protocol, 'graph-step-interaction/v1');
  consumer.accept(interactionEvent(2, chunk));
  assert.deepEqual(statuses(consumer), [['step-1', 'readonly', chunk.interaction_id]]);
  assert.equal(consumer.view().interaction_protocol, 'graph-step-interaction/v1');
});

test('snapshot hook failure restores existing interaction state and retries every new chunk', () => {
  const cards = [step(), step(2), step(3), step(4)];
  const chunks = cards.map((card, index) => interaction([card], index % 2 ? 'readonly' : 'interactive'));
  const calls = [];
  let fail = true;
  const consumer = pendingConsumer(cards.length, {onInteraction(chunk) {
    calls.push(chunk.interaction_id);
    if (fail && chunk.interaction_id === chunks[2].interaction_id) throw new Error('temporary snapshot hook failure');
  }});
  consumer.accept(interactionEvent(5, chunks[0]));
  const before = consumer.view();
  const snapshot = interactionSnapshot(cards, chunks, 8);
  assert.throws(() => consumer.hydrate(snapshot), /temporary snapshot hook failure/);
  assert.deepEqual(consumer.view(), before);
  assert.deepEqual(calls, chunks.slice(0, 3).map(chunk => chunk.interaction_id));
  fail = false;
  consumer.hydrate(snapshot);
  assert.equal(consumer.last_seq, 8);
  assert.deepEqual(consumer.view().interactions, chunks);
  assert.deepEqual(statuses(consumer), chunks.map((chunk, index) => [cards[index].step_id, chunk.status, chunk.interaction_id]));
  assert.deepEqual(calls, [chunks[0], chunks[1], chunks[2], chunks[1], chunks[2], chunks[3]].map(chunk => chunk.interaction_id));
  consumer.hydrate(snapshot);
  assert.equal(calls.length, 6, 'successful snapshot retries do not redeliver terminal chunks');
});

test('fresh snapshot hook failure restores the empty interaction projection without rebuilding math', () => {
  const cards = [step(), step(2), step(3)], chunks = cards.map(card => interaction([card]));
  const received = [], math = [], snapshots = [];
  let fail = true;
  const consumer = createEventConsumer(identity, {
    onMathStep: card => math.push(card.step_id),
    onInteraction(chunk) {
      received.push(chunk.interaction_id);
      if (fail && chunk.interaction_id === chunks[1].interaction_id) throw new Error('temporary snapshot hook failure');
    },
    onSnapshot: value => snapshots.push(value.last_seq),
  });
  const snapshot = interactionSnapshot(cards, chunks, 6);
  assert.throws(() => consumer.hydrate(snapshot), /temporary snapshot hook failure/);
  assert.equal(consumer.last_seq, 0);
  assert.equal(consumer.view().interaction_protocol, null);
  assert.deepEqual(consumer.view().interaction_states, []);
  assert.deepEqual(consumer.view().interactions, []);
  assert.deepEqual(consumer.view().math_steps, cards);
  assert.deepEqual(snapshots, []);
  fail = false;
  consumer.hydrate(snapshot);
  assert.equal(consumer.last_seq, 6);
  assert.deepEqual(consumer.view().interactions, chunks);
  assert.deepEqual(math, cards.map(card => card.step_id), 'accepted math cards are reused on retry');
  assert.deepEqual(received, [chunks[0], chunks[1], ...chunks].map(chunk => chunk.interaction_id));
  assert.deepEqual(snapshots, [6]);
});

test('snapshot hydration restores card states and final chunks but cannot rewrite them', () => {
  const view = mountStageThreeStream(identity);
  const chunk = interaction([step()]), readonly = interaction([step(2)], 'readonly');
  const snapshot = {...identity, last_seq: 4, math_steps: [step(), step(2), step(3)], goals: {},
    interaction_protocol: 'graph-step-interaction/v1', interactions: [chunk, readonly], interaction_states: [
      {target_ref: target, route_id: route, step_id: 'step-1', ordinal: 1, math_step_sha256: step().math_step_sha256,
        status: 'interactive', interaction_id: chunk.interaction_id},
      {target_ref: target, route_id: route, step_id: 'step-2', ordinal: 2, math_step_sha256: step(2).math_step_sha256,
        status: 'readonly', interaction_id: readonly.interaction_id},
      {target_ref: target, route_id: route, step_id: 'step-3', ordinal: 3, math_step_sha256: step(3).math_step_sha256, status: 'pending'}]};
  view.consumer.hydrate(snapshot);
  assert.deepEqual(statuses(view.consumer), [['step-1', 'interactive', chunk.interaction_id],
    ['step-2', 'readonly', readonly.interaction_id], ['step-3', 'pending', undefined]]);
  view.consumer.hydrate({...snapshot, last_seq: 5});
  assert.throws(() => view.consumer.hydrate({...snapshot, last_seq: 6, interactions: [readonly]}), /snapshot_interaction_changed/);
  const rewritten = structuredClone(snapshot);
  rewritten.last_seq = 6; rewritten.interaction_states[0].status = 'readonly';
  assert.throws(() => view.consumer.hydrate(rewritten), /snapshot_interaction_changed/);
  const final = interaction([step(3)], 'readonly');
  const later = structuredClone(snapshot);
  later.last_seq = 7; later.interactions.push(final);
  Object.assign(later.interaction_states[2], {status: 'readonly', interaction_id: final.interaction_id});
  view.consumer.hydrate(later);
  assert.equal(statuses(view.consumer)[2][1], 'readonly');
});

for (const [name, damage] of [
  ['orphan final-state references', value => { value.interactions = []; }],
  ['state/chunk status conflicts', value => { value.interaction_states[1].status = 'readonly'; }],
  ['missing card states', value => { value.interaction_states.pop(); }],
  ['duplicate card states', value => { value.interaction_states.push(structuredClone(value.interaction_states[0])); }],
  ['duplicate final chunks', value => { value.interactions.push(structuredClone(value.interactions[0])); }],
  ['a chunk that does not cover its referenced final states', value => { value.interactions[0].steps.pop(); }],
  ['a chunk whose covered card references another result', value => { value.interaction_states[1].interaction_id = 'other'; }],
  ['a pending state already covered by a final chunk', value => {
    value.interaction_states[1].status = 'pending'; delete value.interaction_states[1].interaction_id;
  }],
  ['pending states with a final reference', value => { value.interaction_states[1].status = 'pending'; }],
  ['state hash mismatches', value => { value.interaction_states[1].math_step_sha256 = 'changed'; }],
  ['chunk hash mismatches', value => { value.interactions[0].steps[1].math_step_sha256 = 'changed'; }],
  ['state ordinal mismatches', value => { value.interaction_states[1].ordinal = 3; }],
  ['noncontiguous merged coverage', value => { value.interactions[0].steps.reverse(); }],
  ['foreign-run chunks', value => { value.interactions[0].run_id = 'other'; }],
  ['interactive chunks without questions', value => { value.interactions[0].parts = []; }],
  ['readonly chunks with questions', value => {
    value.interactions[0].status = 'readonly';
    value.interaction_states.forEach(row => { row.status = 'readonly'; });
  }],
  ['interaction data without its protocol', value => { delete value.interaction_protocol; }],
]) test(`snapshot rejects ${name} before mutating state or publishing callbacks`, () => {
  const calls = [];
  const consumer = createEventConsumer(identity, {
    onMathStep: value => calls.push(['math', value.step_id]),
    onInteraction: value => calls.push(['interaction', value.interaction_id]),
    onSnapshot: value => calls.push(['snapshot', value.last_seq]),
  });
  consumer.accept(pendingEvent(1));
  consumer.accept(event(2, 'lesson.goal_status', {status: 'running'}));
  const before = consumer.view(), beforeCalls = structuredClone(calls);
  const valid = interactionSnapshot([step(), step(2)], [interaction([step(), step(2)])], 4);
  valid.goals = {[target]: {status: 'solved'}};
  const damaged = structuredClone(valid);
  damage(damaged);
  assert.throws(() => consumer.hydrate(damaged), /snapshot_interaction_changed/);
  assert.deepEqual(consumer.view(), before);
  assert.deepEqual(calls, beforeCalls);
  assert.equal(consumer.last_seq, 2);
  // Rejection must not poison state and prevent the subsequent valid refresh.
  consumer.hydrate(valid);
  assert.equal(consumer.last_seq, 4);
  assert.deepEqual(consumer.view().interactions, valid.interactions);
});

test('a fresh snapshot cannot resolve a card without the corresponding interaction chunk', () => {
  const consumer = createEventConsumer(identity);
  const before = consumer.view();
  const snapshot = interactionSnapshot([step()], [interaction([step()])], 2);
  snapshot.interactions = [];
  assert.throws(() => consumer.hydrate(snapshot), /snapshot_interaction_changed/);
  assert.deepEqual(consumer.view(), before);
  assert.equal(consumer.last_seq, 0);
});

test('snapshot restores a merged interaction before applying buffered later events', () => {
  const consumer = createEventConsumer(identity), chunk = interaction([step(), step(2)]);
  consumer.accept(pendingEvent(4, step(3)));
  consumer.accept(interactionEvent(5, interaction([step(3)], 'readonly')));
  consumer.hydrate(interactionSnapshot([step(), step(2)], [chunk], 3));
  assert.equal(consumer.last_seq, 5);
  assert.deepEqual(statuses(consumer), [['step-1', 'interactive', chunk.interaction_id],
    ['step-2', 'interactive', chunk.interaction_id], ['step-3', 'readonly', 'interaction-3']]);
});

const descriptor = {...identity, snapshot_url: '/snapshot', events_url: '/events', websocket_url: '/ws'};
const emptySnapshot = () => ({...identity, last_seq: 0, math_steps: [], goals: {}});
const response = (value, status = 200) => ({ok: status === 200, status, json: async () => value});
class Socket {
  static instances = [];
  constructor(url) { this.url = url; Socket.instances.push(this); }
  message(value) { this.onmessage?.({data: JSON.stringify(value)}); }
  close(code = 1000) { this.onclose?.({code}); }
}
const flush = () => new Promise(resolve => setTimeout(resolve, 0));

test('WebSocket and HTTP fallback share a cursor and deduplicate delivery', async () => {
  Socket.instances.length = 0;
  const consumer = createEventConsumer(identity), requested = [];
  let delivered = false;
  const transport = connectStageThreeStream(consumer, descriptor, {WebSocket: Socket, pollInterval: 100000,
    fetch: async address => {
      const url = new URL(address); requested.push(url.pathname + url.search);
      return response(url.pathname === '/snapshot' ? emptySnapshot() : {events: delivered ? [mathEvent(1), mathEvent(2, step(2))] : []});
    }});
  try {
    await transport.start();
    assert.match(Socket.instances[0].url, /\/ws\?after=0/);
    Socket.instances[0].message({events: [mathEvent(1)]}); await flush();
    delivered = true; Socket.instances[0].close(); await flush();
    await transport.pollOnce();
    assert.equal(consumer.last_seq, 2);
    assert.equal(consumer.view().math_steps.length, 2);
    assert.ok(requested.some(value => value === '/events?after_seq=1'));
  } finally { transport.stop(); }
});

test('unavailable WebSocket does not report a disconnection while HTTP fallback succeeds', async () => {
  const consumer = createEventConsumer(identity), errors = [];
  let failHTTP = false, updates = 0, connections = 0;
  class UnavailableSocket { constructor() { connections++; throw new Error('WebSocket unavailable'); } }
  const transport = connectStageThreeStream(consumer, descriptor, {WebSocket: UnavailableSocket, pollInterval: 100000,
    onError: error => errors.push(error.message), onUpdate: () => { updates++; },
    fetch: async address => {
      if (failHTTP) throw new Error('HTTP unavailable');
      return response(new URL(address).pathname === '/snapshot' ? emptySnapshot() : {events: [mathEvent(1)]});
    }});
  try {
    await transport.start();
    assert.ok(connections >= 2, 'both initial and retry socket failures use the fallback');
    assert.equal(consumer.last_seq, 1);
    assert.deepEqual(errors, []);
    failHTTP = true;
    await assert.rejects(transport.pollOnce(), /HTTP unavailable/);
    assert.deepEqual(errors, ['HTTP unavailable']);
    const previousUpdates = updates;
    failHTTP = false;
    await transport.pollOnce();
    assert.equal(updates, previousUpdates + 1, 'HTTP recovery reports a normal successful update');
  } finally { transport.stop(); }
});

test('HTTP cursor expiry restores selection and forwards QA without replaying known cards', async () => {
  const received = [], supplementary = [];
  const view = mountStageThreeStream(identity, {onMathStep: value => received.push(value.step_id), onQA: value => supplementary.push(value)});
  view.consumer.accept(mathEvent(1));
  let snapshots = 0;
  const transport = connectStageThreeStream(view.consumer, descriptor, {WebSocket: null,
    fetch: async address => {
      const url = new URL(address);
      if (url.pathname === '/events') return response({cursor_expired: true}, 409);
      snapshots++;
      return response({...identity, last_seq: 5, math_steps: [step()], goals: {},
        selection_chunks: [{target_ref: target, kind: 'D3', chunk: {id: 'D3'}}],
        handoffs: [{target_ref: target, route_id: route, available: true, status: 'partial', verified_route_sha256: 'route-hash'}], qa: [qa()]});
    }});
  try {
    await transport.pollOnce();
    assert.equal(snapshots, 1);
    assert.equal(view.consumer.last_seq, 5);
    assert.deepEqual(received, ['step-1']);
    assert.deepEqual(supplementary.at(-1), qa());
    assert.equal(view.consumer.view().selection_chunks[0].kind, 'D3');
  } finally { transport.stop(); }
});
