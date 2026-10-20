import test from 'node:test';
import assert from 'node:assert/strict';
import {attachMathQA, createMathCard, createMathContext, createRouteCompletion} from '../../site/assets/graph-walk/stream-math-dom.mjs';

function documentFixture() {
  const document = {createElement(tag) { return new Element(tag); }};
  class Element {
    constructor(tag) { this.tagName = tag; this.ownerDocument = document; this.children = []; this.dataset = {}; this.hidden = false; this.textContent = ''; }
    get childNodes() { return this.children; }
    append(...children) { this.children.push(...children); }
    replaceChildren(...children) { this.children = [...children]; }
    set innerHTML(value) { throw new Error(`must not execute source markup: ${value}`); }
  }
  const find = (className, root) => [
    ...(root.className === className ? [root] : []), ...root.children.flatMap(child => find(className, child)),
  ];
  return {document, find};
}
const identity = {run_id: 'run', lesson_version: 'lesson', target_ref: '/root/goals/0', route_id: 'interval'};
const step = {...identity, step_id: 'step-1', math_step_sha256: 'step-hash', ordinal: 1,
  title: '确定最小值', before: [{latex: 'a\\ge-\\frac52'}], after: [{latex: 'a_{min}=-\\frac52'}],
  explanation: '下确界在可行集中，最小值存在。'};
const qa = {...identity, step_id: step.step_id, math_step_sha256: step.math_step_sha256, verified_route_sha256: 'route-hash',
  qa: {questions: ['为什么最小值存在？'], feedback: '因为下确界能取到。'}};
const exactValue = (value, latex = value) => ({expression: value, latex,
  exact: value.includes('/') ? {$math: 'Rational', p: value.split('/')[0], q: value.split('/')[1]} : {$math: 'Integer', value}});

test('shared card preserves identity, formula structure and a separate empty QA region', () => {
  const {document, find} = documentFixture(), rendered = [];
  const card = createMathCard(document, step, {renderMath: node => rendered.push(node)});
  assert.deepEqual(card.step, step);
  assert.notEqual(card.step, step);
  assert.equal(card.node.dataset.mathStepSha256, step.math_step_sha256);
  assert.equal(card.node.dataset.targetRef, identity.target_ref);
  assert.equal(card.node.dataset.routeId, identity.route_id);
  assert.equal(find('stage-three-before', card.node)[0].textContent, step.before[0].latex);
  assert.equal(find('stage-three-after', card.node)[0].textContent, step.after[0].latex);
  assert.equal(find('stage-three-explanation', card.node)[0].dataset.mathText, 'true');
  assert.equal(card.qa.hidden, true);
  assert.deepEqual(rendered, [card.node]);
});

test('active question context reveals only before formulas from all covered cards', () => {
  const {document, find} = documentFixture(), rendered = [];
  const other = {...step, before: [{latex: 'b>1'}], after: [{latex: 'hidden answer'}]};
  const node = createMathContext(document, [step, other], {renderMath: value => rendered.push(value)});
  assert.deepEqual(find('stage-three-before', node).map(value => value.textContent), [step.before[0].latex, 'b>1']);
  assert.equal(find('stage-three-after', node).length, 0);
  assert.equal(find('stage-three-explanation', node).length, 0);
  assert.equal(find('stage-three-qa', node).length, 0);
  assert.deepEqual(rendered, [node]);
});

test('late QA only changes its region and preserves the mathematical DOM', () => {
  const {document} = documentFixture(), rendered = [];
  const card = createMathCard(document, step), nodes = [...card.node.children];
  attachMathQA(card, qa, {renderMath: node => rendered.push(node)});
  assert.deepEqual(card.node.children, nodes);
  assert.equal(card.qa.hidden, false);
  assert.equal(card.qa.children[1].textContent, qa.qa.questions[0]);
  assert.equal(card.qa.children[1].dataset.mathText, 'true');
  assert.equal(rendered.length, 1);
  const recovered = createMathCard(document, step, {qa});
  assert.deepEqual(recovered.qa.children.map(node => node.textContent), card.qa.children.map(node => node.textContent));
});

test('a failed QA renderer leaves the previous attachment intact and can retry', () => {
  const {document} = documentFixture(), card = createMathCard(document, step);
  assert.throws(() => attachMathQA(card, qa, {renderMath() { throw new Error('renderer loading'); }}), /renderer loading/);
  assert.equal(card.qa.hidden, true);
  assert.deepEqual(card.qa.children, []);
  attachMathQA(card, qa);
  const children = [...card.qa.children];
  assert.throws(() => attachMathQA(card, qa, {renderMath() { throw new Error('renderer loading'); }}), /renderer loading/);
  assert.deepEqual(card.qa.children, children);
});

for (const key of ['run_id', 'lesson_version', 'target_ref', 'route_id', 'step_id', 'math_step_sha256']) {
  test(`QA helper rejects a mismatched ${key}`, () => {
    const {document} = documentFixture(), card = createMathCard(document, step);
    assert.throws(() => attachMathQA(card, {...qa, [key]: 'different'}), /qa_hash_mismatch/);
    assert.equal(card.qa.hidden, true);
  });
}

test('untrusted titles, formula text, explanation and QA never become executable HTML', () => {
  const {document, find} = documentFixture(), source = '<img src=x onerror="attack()">';
  const card = createMathCard(document, {...step, title: source, before: [{latex: source}], after: [{latex: source}], explanation: source},
    {qa: {...qa, qa: {questions: [source], extra: {text: source}}}});
  assert.equal(card.node.children[0].textContent, source);
  for (const name of ['stage-three-before', 'stage-three-after', 'stage-three-explanation']) {
    assert.equal(find(name, card.node)[0].textContent, source);
  }
  assert.equal(card.qa.children[1].textContent, source);
  assert.equal(card.qa.children[3].textContent, source);
});

test('render failure returns no partially initialized math card', () => {
  const {document} = documentFixture();
  assert.throws(() => createMathCard(document, step, {renderMath() { throw new Error('renderer loading'); }}), /renderer loading/);
  assert.equal(createMathCard(document, step).node.dataset.stepId, step.step_id);
});

test('range completion preserves readable math and calls the injected renderer', () => {
  const {document, find} = documentFixture(), rendered = [];
  const value = createRouteCompletion(document, {answer: {kind: 'find_range', status: 'set', set: {latex: '[0,+\\infty)'}}},
    {renderMath: node => rendered.push(node)});
  assert.equal(value.complete, true);
  assert.equal(value.node.hidden, false);
  assert.equal(find('stage-three-answer', value.node)[0].textContent, '[0,+\\infty)');
  assert.deepEqual(rendered, [value.node]);
});

for (const [kind, status, field, label, formula] of [
  ['find_minimum', 'attained', 'value', '最小值：', '-5/2'],
  ['find_maximum', 'attained', 'value', '最大值：', '5/2'],
  ['find_minimum', 'not_attained', 'bound', '最小值不存在；下确界为：', '-5/2'],
  ['find_maximum', 'not_attained', 'bound', '最大值不存在；上确界为：', '5/2'],
  ['find_minimum', 'unbounded_below', null, '最小值不存在：可行集没有下界。', null],
  ['find_maximum', 'unbounded_above', null, '最大值不存在：可行集没有上界。', null],
  ['find_minimum', 'empty_feasible_set', null, '没有满足题设的参数，最小值不存在。', null],
  ['find_maximum', 'empty_feasible_set', null, '没有满足题设的参数，最大值不存在。', null],
]) test(`typed ${kind}/${status} distinguishes extrema, bounds and absence`, () => {
  const {document, find} = documentFixture();
  const value = createRouteCompletion(document, {answer: {kind, status, ...(field ? {[field]: exactValue(formula)} : {})}});
  assert.equal(value.node.hidden, false);
  assert.equal(value.complete, true);
  assert.equal(value.node.children[0].textContent, label);
  assert.deepEqual(find('stage-three-answer', value.node).map(node => node.textContent), formula ? [formula] : []);
  assert.equal(value.answerStatus, status);
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
]) test(`an incomplete answer cannot render a successful completion: ${JSON.stringify(answer)}`, () => {
  const {document, find} = documentFixture(), value = createRouteCompletion(document, {answer});
  assert.equal(value.node.hidden, true);
  assert.equal(value.complete, false);
  assert.equal(find('stage-three-answer', value.node).length, 0);
  assert.equal(value.answerStatus, 'unknown');
  assert.match(value.statusText, /目标答案尚未确定/);
});

test('revoked mathematical answers do not show a successful completion', () => {
  const {document} = documentFixture();
  const value = createRouteCompletion(document, {available: false, answer: {kind: 'find_range', status: 'set', set: '[0,1]'}});
  assert.equal(value.complete, false);
  assert.equal(value.node.hidden, true);
});
