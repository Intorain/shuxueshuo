import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import method from '../../site/assets/explain/method/method-discriminant.js';
import {validateGraph} from '../../site/assets/knowledge-next/model.mjs';
import {textHtml} from '../lib/public-knowledge-html.mjs';

const directory = new URL('../../site/data/knowledge-next/', import.meta.url);
const read = name => JSON.parse(fs.readFileSync(new URL(name, directory), 'utf8'));
const text = html => html.replace(/<[^>]*>/g, '').replaceAll('&gt;', '>').replaceAll('&lt;', '<').trim();
const compare = (value, relation) => ({'>': value > 0, '≥': value >= 0, '<': value < 0, '≤': value <= 0})[relation];

test('the displayed full-real sign table agrees with quadratic signs for both quantifiers and openings', () => {
  const tbody = method.figure().match(/<tbody>([\s\S]*?)<\/tbody>/)[1];
  const rows = [...tbody.matchAll(/<tr>([\s\S]*?)<\/tr>/g)].map(match =>
    [...match[1].matchAll(/<t[hd][^>]*>([\s\S]*?)<\/t[hd]>/g)].map(cell => text(cell[1])));
  assert.equal(rows.length, 8);
  assert.deepEqual(rows.map(row => row[0]), ['恒 > 0', '恒 ≥ 0', '恒 < 0', '恒 ≤ 0',
    '存在 > 0', '存在 ≥ 0', '存在 < 0', '存在 ≤ 0']);
  const tableCondition = (label, delta) => {
    if (label === '总有解') return true;
    if (label === '不成立') return false;
    const match = /^Δ ([<>≤≥]) 0$/.exec(label);
    assert.ok(match, `unrecognized displayed condition: ${label}`);
    return compare(delta, match[1]);
  };
  for (const [label, up, down] of rows) {
    const [quantifier, relation] = label.split(' ');
    for (const a of [-2, 2]) for (const delta of [-4, 0, 4]) {
      // These quadratics have vertex x=1; the vertex and either tail expose
      // every sign they attain, including the sole zero when delta is zero.
      const values = [1, -10, 10].map(x => a * (x - 1) ** 2 - delta / (4 * a));
      const exact = quantifier === '恒'
        ? values.every(value => compare(value, relation)) : values.some(value => compare(value, relation));
      assert.equal(tableCondition(a > 0 ? up : down, delta), exact, `${label}; a=${a}; delta=${delta}`);
    }
  }
});

test('geometry does not label an intersection wrong before choosing the quantifier', () => {
  const figure = method.figure(), full = method.render();
  assert.equal((figure.match(/<svg /g) || []).length, 6);
  assert.match(figure, /开口向上/);
  assert.match(figure, /开口向下/);
  assert.doesNotMatch(figure, /class="bad"|ok-mark|bad-mark|✓|✗/);
  assert.match(text(figure), /a ≠ 0，x ∈ ℝ/);
  assert.match(text(figure), /b ≠ 0 的一次式取遍 ℝ，四种关系都有解、都不恒成立/);
  assert.match(text(figure), /b = 0 时直接检查常数 c 是否满足原关系/);
  assert.match(text(full), /只在某个区间内取值时，不能直接使用下表/);
  assert.ok(fs.existsSync(new URL(method.stylesheet)));
});

test('public method, basis and selection prose include existence without changing graph identities', () => {
  const methodNode = read('nodes/method-discriminant.json');
  assert.deepEqual(methodNode.steps.map(step => step.id), ['degree', 'normalize', 'conditions', 'solve', 'merge']);
  assert.match(methodNode.input, /存在/);
  assert.match(methodNode.conditions, /某个区间/);
  assert.match(methodNode.steps.find(step => step.id === 'degree').body.join(''), /四种正负关系都至少有一个解/);
  assert.ok(methodNode.examples.some(example => example.prompt.includes('存在') && example.prompt.includes('x^2+m>0')));
  const basis = read('nodes/quadratic-inequality.json').entries.find(entry => entry.id === 'all-real');
  assert.equal(basis.body.filter(line => line.startsWith('存在实数')).length, 2);
  assert.match(basis.conditions, /a=0.*单独处理/);
  const skill = read('nodes/skill-quadratic-sign.json');
  assert.ok(skill.basis.includes('quadratic-inequality#all-real'));
  assert.ok(skill.operations.some(operation => operation.id === 'quantified'));
  const branch = read('nodes/rule-quadratic-method.json').branches.find(branch => branch.id === 'discriminant');
  assert.equal(branch.target, 'method-discriminant');
  assert.match(branch.condition, /恒成立或存在/);
  assert.match(read('catalog.json').resources['discriminant-positions'].note, /不必再限制判别式/);
  const nodes = fs.readdirSync(new URL('nodes/', directory)).filter(name => name.endsWith('.json'))
    .map(name => read(`nodes/${name}`));
  assert.doesNotThrow(() => validateGraph(nodes, read('catalog.json')));
});

test('all revised public strings pass the publication math renderer', () => {
  const renderStrings = value => {
    if (typeof value === 'string') textHtml(value);
    else if (Array.isArray(value)) value.forEach(renderStrings);
    else if (value && typeof value === 'object') Object.values(value).forEach(renderStrings);
  };
  for (const name of ['method-discriminant', 'skill-quadratic-sign', 'quadratic-inequality', 'rule-quadratic-method']) {
    assert.doesNotThrow(() => renderStrings(read(`nodes/${name}.json`)), name);
  }
  assert.doesNotThrow(() => renderStrings(read('catalog.json').resources['discriminant-positions']));
});
