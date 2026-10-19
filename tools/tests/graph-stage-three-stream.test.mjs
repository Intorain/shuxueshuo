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

test('failed mathematical rendering retries before publishing the DOM card', () => {
  const {container, find} = documentFixture();
  let fail = true;
  const view = mountStageThreeStream(container, identity, {renderMath() { if (fail) throw new Error('renderer loading'); }});
  assert.throws(() => view.consumer.accept(mathEvent(1)), /renderer loading/);
  assert.equal(find('stage-three-math-step').length, 0);
  assert.equal(view.consumer.last_seq, 0);
  fail = false;
  view.consumer.accept(mathEvent(1));
  assert.equal(find('stage-three-math-step').length, 1);
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
  view.consumer.accept(mathEvent(2, step(2)));
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

const exactValue = (value, latex = value) => ({expression: value, latex,
  exact: value.includes('/') ? {$math: 'Rational', p: value.split('/')[0], q: value.split('/')[1]} : {$math: 'Integer', value}});
for (const [kind, status, field, label, formula] of [
  ['find_minimum', 'attained', 'value', '最小值：', '-5/2'],
  ['find_maximum', 'attained', 'value', '最大值：', '5/2'],
  ['find_minimum', 'not_attained', 'bound', '最小值不存在；下确界为：', '-5/2'],
  ['find_maximum', 'not_attained', 'bound', '最大值不存在；上确界为：', '5/2'],
  ['find_minimum', 'unbounded_below', null, '最小值不存在：可行集没有下界。', null],
  ['find_maximum', 'unbounded_above', null, '最大值不存在：可行集没有上界。', null],
  ['find_minimum', 'empty_feasible_set', null, '没有满足题设的参数，最小值不存在。', null],
  ['find_maximum', 'empty_feasible_set', null, '没有满足题设的参数，最大值不存在。', null],
]) test(`typed ${kind}/${status} distinguishes an extremum from its bound or absence`, () => {
  const {container, find} = documentFixture();
  const view = mountStageThreeStream(container, identity);
  view.consumer.accept(mathEvent(1));
  const completion = doneEvent(2);
  completion.payload.answer = {kind, status, ...(field ? {[field]: exactValue(formula)} : {})};
  view.consumer.accept(completion);
  const node = find('stage-three-completion')[0];
  assert.equal(node.hidden, false);
  assert.equal(node.children[0].textContent, label);
  assert.deepEqual(find('stage-three-answer').map(value => value.textContent), formula ? [formula] : []);
  assert.equal(container.children[0].dataset.answerStatus, status);
  assert.deepEqual(view.consumer.view().completions[0].answer, completion.payload.answer);
});

for (const answer of [
  {kind: 'find_minimum', status: 'unknown', value: exactValue('2')},
  {kind: 'find_minimum', status: 'attained'},
  {kind: 'find_maximum', status: 'not_attained'},
  {kind: 'find_maximum', status: 'unbounded_below'},
  {kind: 'find_minimum', status: 'unbounded_above'},
  {kind: 'find_range', status: 'attained', value: exactValue('2')},
  {kind: 'unrecognized', status: 'attained', value: exactValue('2')},
  {kind: 'find_minimum', status: 'attained', value: {expression: '-oo', latex: '-\\infty', exact: {$math: 'NegativeInfinity'}}},
]) test(`an unsupported or incomplete answer is never displayed as successful: ${JSON.stringify(answer)}`, () => {
  const {container, find} = documentFixture();
  const view = mountStageThreeStream(container, identity);
  view.consumer.accept(mathEvent(1));
  const completion = doneEvent(2);
  completion.payload.answer = answer;
  view.consumer.accept(completion);
  assert.equal(find('stage-three-completion')[0].hidden, true);
  assert.equal(find('stage-three-answer').length, 0);
  assert.equal(container.children[0].dataset.answerStatus, 'unknown');
  assert.match(container.children[0].children[1].textContent, /目标答案尚未确定/);
});

test('an extremum completion waits for the appended goal card and survives snapshot/QA without changing prior math', () => {
  const {container, find} = documentFixture();
  const view = mountStageThreeStream(container, identity, {mode: 'practice'});
  view.consumer.accept(mathEvent(1));
  const original = find('stage-three-math-step')[0];
  const closure = {...step(2), title: '确定最小值', display_unit: 'goal_finalization',
    source_refs: ['/finalization/3'], explanation: '下确界不属于完整可行集，因此最小值不存在。'};
  view.consumer.accept(mathEvent(2, closure));
  const completion = doneEvent(3);
  completion.payload.answer = {kind: 'find_minimum', status: 'not_attained', bound: exactValue('-5/2', '-\\frac{5}{2}')};
  view.consumer.accept(completion);
  assert.equal(find('stage-three-completion')[0].hidden, true);
  view.revealThrough(target, route, 2);
  assert.equal(find('stage-three-completion')[0].hidden, false);
  view.consumer.accept(qaEvent(4));
  view.consumer.hydrate({...identity, last_seq: 5, math_steps: [step(), closure], goals: {},
    handoffs: [{target_ref: target, route_id: route, available: true, answer: completion.payload.answer,
      feasible_set: '(−5/2,+∞)', verified_route_sha256: 'route-hash'}], qa: [qa()]});
  assert.equal(find('stage-three-math-step')[0], original);
  assert.equal(find('stage-three-math-step')[1].children[0].textContent, '确定最小值');
  assert.equal(find('stage-three-answer')[0].textContent, '-\\frac{5}{2}');
  assert.equal(find('stage-three-completion')[0].hidden, false);
  view.consumer.accept(event(6, 'lesson.goal_status', {status: 'conflict', available: false}));
  assert.equal(find('stage-three-completion')[0].hidden, true);
  assert.equal(find('stage-three-math-step')[0], original);
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

test('only arrived reading positions persist across a full page refresh', () => {
  const values = new Map(), storage = {getItem: key => values.get(key), setItem: (key, value) => values.set(key, value)};
  const first = documentFixture();
  const view = mountStageThreeStream(first.container, identity, {mode: 'practice', storage});
  view.consumer.accept(mathEvent(1));
  view.revealThrough(target, route, 50);
  view.consumer.accept(mathEvent(2, step(2)));
  assert.equal(first.find('stage-three-math-step')[1].hidden, true);
  view.revealThrough(target, route, 2);
  const refreshed = documentFixture();
  const restored = mountStageThreeStream(refreshed.container, identity, {mode: 'practice', storage});
  restored.consumer.hydrate({...identity, last_seq: 3, math_steps: [step(), step(2), step(3)], goals: {}});
  assert.deepEqual(refreshed.find('stage-three-math-step').map(node => node.hidden), [false, false, true]);
  const newer = documentFixture();
  const other = mountStageThreeStream(newer.container, {...identity, run_id: 'new'}, {mode: 'practice', storage});
  assert.equal(other.readingPosition(target, route), 1);
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

test('HTTP cursor expiry refetches selection and QA without replacing math cards', async () => {
  const {container, find} = documentFixture(), view = mountStageThreeStream(container, identity);
  view.consumer.accept(mathEvent(1));
  const original = find('stage-three-math-step')[0];
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
    assert.equal(find('stage-three-math-step')[0], original);
    assert.equal(find('stage-three-qa')[0].hidden, false);
  } finally { transport.stop(); }
});
