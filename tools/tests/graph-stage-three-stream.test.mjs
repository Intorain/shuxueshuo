import test from 'node:test';
import assert from 'node:assert/strict';
import {createEventConsumer, mountStageThreeStream} from '../../site/assets/graph-walk/stage-three-stream.mjs';

const identity = {run_id: 'run-01', lesson_version: 'lesson-01', stream_id: 'run-01'};
const target = '/root/goals/0';
const route = 'discriminant';
const step = (ordinal = 1, targetRef = target) => ({
  contract: 'graph-math-step/v1', ...identity, target_ref: targetRef, route_id: route,
  step_id: `step-${ordinal}`, ordinal, math_step_sha256: `${targetRef}-${ordinal}-hash`, local_check: 'passed',
  title: ordinal === 1 ? '计算判别式' : '求参数范围',
  before: [{expression: 'x^2+a', display: 'x^2+a'}], after: [{expression: 'a>=0', display: 'a≥0'}],
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

function documentFixture() {
  const document = {createElement(tag) { return new Element(tag); }};
  class Element {
    constructor(tag) { this.tagName = tag; this.ownerDocument = document; this.children = []; this.dataset = {}; this.hidden = false; this.textContent = ''; }
    append(...children) { this.children.push(...children); }
    replaceChildren(...children) { this.children = [...children]; }
    set innerHTML(value) { throw new Error(`must not execute source markup: ${value}`); }
  }
  const container = new Element('main');
  const find = (className, root = container) => {
    const values = [];
    if (root.className === className) values.push(root);
    for (const child of root.children) values.push(...find(className, child));
    return values;
  };
  return {container, find};
}

test('committed first steps render while the route has no completion or QA', () => {
  const {container, find} = documentFixture();
  const view = mountStageThreeStream(container, identity);
  view.consumer.accept(event(1, 'lesson.route_status', {status: 'running'}));
  view.consumer.accept(mathEvent(2));
  assert.equal(find('stage-three-math-step').length, 1);
  assert.equal(find('stage-three-math-step')[0].hidden, false);
  assert.equal(find('stage-three-completion')[0].hidden, true);
  assert.equal(find('stage-three-qa')[0].hidden, true);
  assert.equal(view.consumer.last_seq, 2);
  assert.deepEqual(view.consumer.view().completions, []);
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

test('QA attaches without replacing mathematical DOM or revealing unread steps', () => {
  const {container, find} = documentFixture();
  const view = mountStageThreeStream(container, identity, {mode: 'practice'});
  view.consumer.accept(mathEvent(1));
  view.consumer.accept(mathEvent(2, step(2)));
  const [first, second] = find('stage-three-math-step');
  first.savedStudentAnswer = 'unchanged';
  assert.equal(first.hidden, false);
  assert.equal(second.hidden, true);
  view.consumer.accept(event(3, 'lesson.goal_status', {status: 'solved', available: true}));
  view.consumer.accept(doneEvent(4));
  view.consumer.accept(qaEvent(5));
  assert.equal(find('stage-three-math-step')[0], first);
  assert.equal(first.savedStudentAnswer, 'unchanged');
  assert.equal(second.hidden, true);
  assert.equal(find('stage-three-qa')[0].hidden, false);
  view.revealThrough(target, route, 2);
  assert.equal(second.hidden, false);
});

for (const field of ['math_step_sha256', 'verified_route_sha256', 'step_id', 'target_ref']) test(`QA cannot bind to mismatched ${field}`, () => {
  const consumer = createEventConsumer(identity);
  consumer.accept(mathEvent(1));
  consumer.accept(doneEvent(2));
  assert.throws(() => consumer.accept(qaEvent(3, {...qa(), [field]: 'incorrect'})), /qa_hash_mismatch/);
  assert.deepEqual(consumer.view().qa, []);
});

test('late conflict hides completion and QA while retaining fixed math evidence', () => {
  const {container, find} = documentFixture();
  const view = mountStageThreeStream(container, identity);
  view.consumer.accept(mathEvent(1));
  const first = find('stage-three-math-step')[0];
  view.consumer.accept(event(2, 'lesson.goal_status', {status: 'solved', available: true}));
  view.consumer.accept(doneEvent(3));
  view.consumer.accept(qaEvent(4));
  view.consumer.accept(event(5, 'lesson.goal_status', {status: 'conflict', available: false}));
  view.consumer.accept(qaEvent(6));
  view.consumer.accept(doneEvent(7));
  assert.equal(find('stage-three-math-step')[0], first);
  assert.equal(find('stage-three-completion')[0].hidden, true);
  assert.equal(find('stage-three-qa')[0].hidden, true);
  assert.equal(view.consumer.view().completions[0].available, false);
});

test('cursor expiry hydrates an atomic snapshot, then polls after its watermark', async () => {
  const {container, find} = documentFixture(), cursors = [];
  let call = 0;
  const snapshot = {...identity, last_seq: 3, math_steps: [step()], goals: {}, checkpoints: [], handoffs: [], qa: []};
  const view = mountStageThreeStream(container, identity, {
    fetchEvents: async cursor => { cursors.push(cursor); return ++call === 1 ? {cursor_expired: true} : {events: [mathEvent(4, step(2))]}; },
    fetchSnapshot: async () => snapshot,
  });
  await view.pollOnce();
  assert.equal(view.consumer.last_seq, 3);
  await view.pollOnce();
  assert.deepEqual(cursors, [0, 3]);
  assert.equal(find('stage-three-math-step').length, 2);
});

test('refresh snapshot restores exact math while keeping existing DOM and reading progress', () => {
  const {container, find} = documentFixture();
  const view = mountStageThreeStream(container, identity, {mode: 'practice'});
  view.consumer.accept(mathEvent(1));
  view.revealThrough(target, route, 2);
  const first = find('stage-three-math-step')[0];
  view.consumer.hydrate({...identity, last_seq: 10, math_steps: [step(), step(2)], goals: {}, checkpoints: [], handoffs: [], qa: []});
  assert.equal(find('stage-three-math-step')[0], first);
  assert.equal(find('stage-three-math-step')[1].hidden, false);
  assert.equal(view.consumer.last_seq, 10);
});

test('late transport response after view closure cannot mutate the page', async () => {
  const {container, find} = documentFixture();
  let respond;
  const view = mountStageThreeStream(container, identity, {fetchEvents: () => new Promise(resolve => { respond = resolve; })});
  const pending = view.pollOnce();
  view.stop();
  respond({events: [mathEvent(1)]});
  await pending;
  assert.equal(find('stage-three-math-step').length, 0);
});

test('untrusted text is inserted as text without HTML execution', () => {
  const {container, find} = documentFixture();
  const view = mountStageThreeStream(container, identity);
  const source = '<img src=x onerror="attack()">';
  view.consumer.accept(mathEvent(1, {...step(), title: source}));
  assert.equal(find('stage-three-math-step')[0].children[0].textContent, source);
});

test('completion renders readable mathematical answers and calls the shared math renderer', () => {
  const {container, find} = documentFixture(), rendered = [];
  const view = mountStageThreeStream(container, identity, {renderMath: node => rendered.push(node)});
  view.consumer.accept(mathEvent(1));
  const completion = doneEvent(2);
  completion.payload.answer.set = {type: 'interval', latex: '[0,+\\infty)'};
  view.consumer.accept(completion);
  assert.equal(find('stage-three-answer')[0].textContent, '[0,+\\infty)');
  assert.equal(rendered.at(-1), find('stage-three-completion')[0]);
  assert.equal(container.children[0].children[0].textContent, '判别式法');
  assert.equal(find('stage-three-evidence').length, 0);
});
