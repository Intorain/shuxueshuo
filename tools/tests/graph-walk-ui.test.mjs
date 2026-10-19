import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {RELATIONS, createWalkGraph, nodeHref, panoramaLayout, treeLayout} from '../../site/assets/graph-walk/walk-graph.mjs';
import {createState, replayState} from '../../site/assets/graph-walk/walk-state.mjs';

const source = fs.readFileSync(new URL('../../site/assets/graph-walk/walk.mjs', import.meta.url), 'utf8');
const components = fs.readFileSync(new URL('../../site/assets/practice/components.js', import.meta.url), 'utf8');
const bundle = JSON.parse(fs.readFileSync(new URL('../../site/data/graph-walk/quadratic-always-q01.json', import.meta.url), 'utf8'));

function viewContext() {
  const nodes = new Map();
  const document = {querySelector(selector) {
    if (!nodes.has(selector)) nodes.set(selector, {textContent: '', hidden: false});
    return nodes.get(selector);
  }};
  const context = vm.createContext({document, matchMedia: () => ({matches: true}), URL,
    location: {origin: 'http://127.0.0.1:8779'}, setTimeout, clearTimeout, structuredClone});
  context.window = context;
  vm.runInContext(components, context);
  vm.runInContext(source.replace(/^import .*;\n/gm, '').split("if (document.readyState === 'loading')")[0], context);
  context.fixture = structuredClone(bundle);
  vm.runInContext('bundle = fixture; state = {run: {id: 1}, events: [], lastFeedback: null};', context);
  return {context, nodes, run: code => vm.runInContext(code, context)};
}

test('stream arrival preserves the AI replay reading position and chooses an executable route', async () => {
  const {context, run} = viewContext();
  const bridge = source.slice(source.indexOf('function streamReplay()'), source.indexOf('/** The same safe text/LaTeX renderer'));
  vm.runInContext(bridge.replace(/^export /gm, ''), context);
  context.extendStreamBundle = value => structuredClone(value);
  context.replayState = (_bundle, _replay, position) => ({introCompleted: [], run: {route: 'discriminant'}, readingPosition: position});
  run(`options = {bundle: {problemId: 'sample', bundleVersion: 'stable', graph: {nodes: [], edges: []},
      intro: [{id: 'D3', expected_answer: {cell: ['real', 'free']}, interaction: {methods: [
        {value: 'discriminant', route: 'discriminant'}, {value: 'unsupported', route: 'unsupported'}]}}, {id: 'D4'}],
      routes: {discriminant: {route_plan: 'planned'}, unsupported: {route_plan: 'capability_gap'}}},
      stream: {run_id: 'run', lesson_version: 'version', target_ref: '/root/goals/0'},
      replay: {actions: [{decision: 'D1'}, {decision: 'D2'}]}};
    bundle = options.bundle; actor = 'replay'; replayPosition = 1;
    state = {introCompleted: [], run: {route: 'unsupported'}};
    renderGraph = () => {};`);
  assert.equal(run('streamReplay().routes[0]'), 'discriminant');
  await run(`updateStreamSelection({run_id: 'run', lesson_version: 'version'})`);
  assert.equal(run('replayPosition'), 1);
  assert.equal(run('state.readingPosition'), 1);
  const parkSource = source.slice(source.indexOf('export function parkWalk()'), source.indexOf('/* The actor the walk'));
  vm.runInContext(parkSource.replace(/^export /gm, ''), context);
  let compiled = 0;
  context.extendStreamBundle = value => { compiled++; return structuredClone(value); };
  run('stopReplay = () => {}; park = () => {};');
  const pending = run(`updateStreamSelection({run_id: 'run', lesson_version: 'version'})`);
  run('parkWalk()');
  await pending;
  assert.equal(compiled, 0, 'parked questions reject queued updates before recompiling or rendering');
});

for (const mode of ['playing', 'at-end', 'paused']) test(`stage-two to stream migration preserves AI playback intent: ${mode}`, async () => {
  const {context, nodes, run} = viewContext();
  const bridge = source.slice(source.indexOf('function streamReplay()'), source.indexOf('/** The same safe text/LaTeX renderer'));
  vm.runInContext(bridge.replace(/^export /gm, ''), context);
  context.document.body = {dataset: {}};
  context.PracticeMath = {render() {}};
  context.createState = value => ({bundleVersion: value.bundleVersion, introCompleted: [], run: {route: null}, events: []});
  context.replayState = (value, recording, position) => ({bundleVersion: value.bundleVersion,
    introCompleted: recording.actions.slice(0, position), run: {route: position === 4 ? 'discriminant' : null}, events: []});
  context.migrateStageTwoState = (_base, value, state) => ({...state, bundleVersion: value.bundleVersion});
  context.extendStreamBundle = value => ({...structuredClone(value), bundleVersion: 'stream-version',
    intro: [...value.intro, {id: 'D3', expected_answer: {cell: ['real', 'free']},
      interaction: {methods: [{value: 'discriminant', route: 'discriminant'}]}}, {id: 'D4'}],
    routes: {discriminant: {route_plan: 'planned'}}});
  run(`options = {bundle: {problemId: 'sample', bundleVersion: 'base-version', graphVersion: 'graph',
      graph: {nodes: [], edges: [], layout: {}}, templates: {}, problem: {text: ''},
      intro: [{id: 'D1'}, {id: 'D2'}], routes: {}},
      stream: {run_id: 'run', lesson_version: 'version', target_ref: '/root/goals/0'},
      replay: {actions: [{decision: 'D1'}, {decision: 'D2'}]}};
    bundle = options.bundle; publicGraph = {}; actor = 'replay';
    studentState = state = createState(bundle); replay = options.replay;
    render = () => {}; updatePlayButton = () => {}; toggleSteps = () => {};
    mountProblemBar = () => {}; mountCaption = () => {}; mountPlayer = () => {};
    createGraph = async () => ({destroy() {}});`);
  for (const selector of ['#gw-graph-panel', '#gw-student', '#gw-ai']) {
    context.document.querySelector(selector);
    Object.assign(nodes.get(selector), {classList: {contains: () => false}, setAttribute() {}});
  }
  run(`replayPosition = ${mode === 'at-end' ? 2 : 1}; replayPlaying = ${mode === 'playing'};`);
  await run('load()');
  assert.equal(run('bundle.bundleVersion'), 'stream-version');
  assert.equal(run('replayPosition'), mode === 'paused' ? 1 : 4);
  assert.equal(run('state.introCompleted.length'), mode === 'paused' ? 1 : 4);
  assert.equal(nodes.get('#gw-error')?.hidden, true);
});

test('draft choices do not reveal checklist notes or wrong-attempt calculations', () => {
  const {run} = viewContext();
  run(`testDecision = {id: 'draft', board: null, interaction: {type: 'checklist', slots: [
    {label: '判断', options: [{value: 'yes', label: '符合', note: 'This belongs after submission'}]}]}};
    draft = ['yes'];`);
  assert.doesNotMatch(run('interactionHTML(testDecision)'), /checklist-note|This belongs/);
  run(`bundle.templates.attempt = '<p>Submitted attempt</p>';
    testDecision.attempt_calculations = {yes: 'attempt'};
    state.lastFeedback = {status: 'wrong'}; submitted = null;`);
  assert.equal(run('attemptedCalculation(testDecision)'), '');
  run(`submitted = {decision: 'draft', answer: ['yes']};`);
  assert.match(run('attemptedCalculation(testDecision)'), /Submitted attempt/);
  run('submitted = null;');
  assert.equal(run('feedbackHTML()'), '');
  assert.equal(run('state.events.length'), 0);
});

test('malformed replay answers render safely without changing original evidence or feedback', () => {
  const {context, run} = viewContext();
  const decisions = [...bundle.intro, ...Object.values(bundle.routes).flatMap(route => route.steps)];
  for (const type of new Set(decisions.map(decision => decision.interaction.type))) {
    context.testDecision = structuredClone(decisions.find(decision => decision.interaction.type === type));
    for (const answer of [null, 42, {}, 'wrong shape', [null, {}, 3]]) {
      context.rawAnswer = structuredClone(answer);
      const original = JSON.stringify(answer);
      run(`actor = 'replay'; draftKey = ''; submitted = {decision: testDecision.id, answer: rawAnswer};
        state.lastFeedback = {status: 'wrong', message: '保留本次提交的判定'}; ensureDraft(testDecision);`);
      assert.doesNotThrow(() => run('interactionHTML(testDecision)'), type);
      assert.match(run('feedbackHTML()'), /保留本次提交的判定/);
      assert.equal(run('JSON.stringify(submitted.answer)'), original);
      assert.equal(run('state.lastFeedback.status'), 'wrong');
      if (type !== 'choice') assert.equal(run('Array.isArray(draft)'), true);
    }
  }
});

test('graph options pick by picture for both single and multiple choice', () => {
  const {context, run} = viewContext();
  const steps = bundle.routes.discriminant.steps;
  context.testDecision = structuredClone(steps.find(step => step.id === 'd_range'));
  run(`draft = 'outside';`);
  const single = run('interactionHTML(testDecision)');
  assert.equal((single.match(/data-quadratic-graph=/g) || []).length, 3);
  assert.match(single, /data-choice="d_range" data-value="outside" aria-pressed="true"/);
  assert.match(single, /data-value="open" aria-pressed="false"/);
  assert.doesNotMatch(single.slice(single.indexOf('gw-graph-options')), /gw-graph-option-name|data-math-text/);
  run(`draft = 42;`);
  assert.doesNotThrow(() => run('interactionHTML(testDecision)'));
  context.testDecision = structuredClone(steps.find(step => step.id === 'd_position'));
  run(`draft = ['touch'];`);
  const multi = run('interactionHTML(testDecision)');
  assert.match(multi, /data-multi="touch" aria-pressed="true"/);
  assert.match(multi, /data-multi="apart" aria-pressed="false"/);
  assert.match(multi, /gw-graph-option-name">相切</);
});

test('the separation map picks one cell and keeps the pinned map as the completed record', () => {
  const {context, run} = viewContext();
  context.testDecision = structuredClone(bundle.routes.extremum.steps.find(step => step.id === 'e_basis'));
  run(`draft = ['', ''];`);
  const empty = run('interactionHTML(testDecision)');
  assert.equal((empty.match(/data-grid-cell=/g) || []).length, 4);
  assert.doesNotMatch(empty, /gw-plane-pin|data-chosen/);
  // Same reading order as the method plane: top row first, so this problem's cell is bottom-right.
  const cells = [...empty.matchAll(/data-grid-cell="([^"]+)"/g)].map(match => match[1]);
  assert.deepEqual(cells, ['tangled|division', 'separable|division', 'tangled|no_division', 'separable|no_division']);
  run(`draft = ['separable', 'no_division'];`);
  assert.match(run('interactionHTML(testDecision)'), /data-zone="direct" data-chosen>直接比较最值<\/span><span class="gw-plane-pin"[^>]*>本题<\/span><\/button>/);
  const done = run(`completedHTML({decision: 'e_basis', answer: ['separable', 'no_division']}, 4, 1, 'extremum')`);
  assert.match(done, /gw-plane is-static" role="img" aria-label="直接比较最值（能分离，不用除）"/);
  assert.doesNotMatch(done, /data-grid-cell|checklist/);
  assert.match(done, /<details[\s\S]*完整推导[\s\S]*<\/details>/);
  run(`state = {introCompleted: [], run: {id: 1, completed: [{decision: 'e_basis', answer: ['separable', 'no_division'], results: []}]}, events: []};`);
  assert.match(run('carryHTML()'), /直接比较最值（能分离，不用除）/);
});

test('the completion card shows the answer, this route\'s key idea and next actions', () => {
  const {run} = viewContext();
  run(`actor = 'student'; state = {run: {id: 2, route: 'discriminant', completed: []}, events: []};`);
  const html = run('completionHTML([])');
  assert.match(html, /判别式法 · 完成/);
  assert.match(html, /a\\in\(-\\infty,-1\]\\cup\[4,\+\\infty\)/);
  assert.match(html, /\\Delta\\le0/);
  assert.match(html, /data-route="extremum">再用分离参数法做一遍/);
  assert.match(html, /href="\/2\/">返回恒成立题库/);
  assert.doesNotMatch(html, /最大值/);
  const both = run(`completionHTML([{route: 'extremum'}])`);
  assert.match(both, /分离参数法 · 判别式法 · 完成/);
  assert.match(both, /<b>分离参数法<\/b>[\s\S]*最大值[\s\S]*<b>判别式法<\/b>[\s\S]*\\Delta\\le0/);
  run(`actor = 'replay';`);
  assert.doesNotMatch(run('completionHTML([])'), /data-route/);
});

test('the active card carries the immediately previous step: results, else its answer', () => {
  const {run} = viewContext();
  run(`state = {introCompleted: [{decision: 'D1', results: ['读题结论']}],
    run: {id: 1, completed: [{decision: 'd_rewrite', results: ['整理结果 $x$']}]}, events: []};`);
  assert.match(run('carryHTML()'), /接第 2 步 · 整理不等式[\s\S]*整理结果/);
  run(`state.run.completed.push({decision: 'd_position', answer: ['touch', 'apart'], results: []});`);
  const html = run('carryHTML()');
  assert.match(html, /接第 3 步 · 判断图像位置[\s\S]*相切[\s\S]*不相交/);
  assert.doesNotMatch(html, /整理结果|读题结论/);
  run(`state = {introCompleted: [{decision: 'D1', results: []}, {decision: 'D2', answer: 'type-quantified-quadratic', results: []},
    {decision: 'D3', answer: ['real', 'free', 'separation'], results: []}], run: {id: 1, completed: []}, events: []};`);
  assert.match(run('carryHTML()'), /接第 3 步 · 选择解题方法[\s\S]*选用分离参数法/);
  run(`state = {introCompleted: [], run: {id: 1, completed: []}, events: []};`);
  assert.equal(run('carryHTML()'), '');
});

test('call records use the authored method step title', () => {
  const {context, run} = viewContext();
  run('graphView = bundle.graph;');
  for (const method of bundle.graph.nodes.filter(node => node.kind === 'method')) {
    for (const step of method.steps || []) {
      if (!step.calls?.length) continue;
      context.call = {method: method.id, step: step.id};
      assert.equal(run('callStepTitle(call)'), step.title);
    }
  }
  assert.equal(run(`callStepTitle({method: 'method-discriminant', step: 'normalize'})`), '移项整理成与 0 比较');
});

test('template hydration renders only math labels and graph hosts, preserving surrounding HTML', () => {
  const {context, run} = viewContext();
  const label = {textContent: '$x^2$', dataset: {}}, graphHost = {dataset: {quadraticGraph: '{}'}};
  const visited = [];
  context.PracticeMath = {render(node, text) { visited.push([node, text]); }};
  context.root = {querySelectorAll(selector) {
    if (selector.startsWith('[data-quadratic-graph]')) return [graphHost];
    if (selector.startsWith('[data-math-text]')) return [label];
    throw new Error(`Unexpected hydration target: ${selector}`);
  }};
  run(`PracticeComponents.quadraticGraph = () => '<svg></svg>'; hydrate(root);`);
  assert.equal(graphHost.innerHTML, '<svg></svg>');
  assert.equal(visited.length, 1);
  assert.equal(visited[0][0], label);
  assert.equal(label.dataset.mathRendered, 'true');
  run(`bundle.templates.uid = '<svg id="{{uid}}"><use href="#{{uid}}" /></svg>';`);
  assert.match(run(`template('uid', 'run-1')`), /id="run-1"/);
  assert.doesNotMatch(run(`template('uid', 'run-2')`), /run-1/);
});

test('replay paths resolve beside the index and reject off-demo or stale recordings', async () => {
  const {context, nodes, run} = viewContext();
  const fetched = [];
  let response = {bundleVersion: bundle.bundleVersion, problemId: bundle.problemId, actions: []};
  context.fetch = async url => { fetched.push(String(url)); return {ok: true, json: async () => response}; };
  run(`actor = 'replay'; render = () => {}; updatePlayButton = () => {}; applyReplayPosition = () => {}; playReplay = () => { played = true; };`);
  await run(`loadReplay('discriminant.json')`);
  assert.equal(fetched[0], 'http://127.0.0.1:8779/data/graph-walk/replays/discriminant.json');
  assert.equal(run('replay.problemId'), bundle.problemId);
  assert.equal(run('played'), true);
  assert.equal(run('replayNotice'), null);
  await run(`loadReplay('https://other.example/discriminant.json')`);
  assert.equal(fetched.length, 1);
  assert.match(run('replayNotice.text'), /不属于本 Demo/);
  response = {...response, bundleVersion: 'old'};
  await run(`loadReplay('discriminant.json')`);
  assert.equal(run('replay'), null);
  assert.match(run('replayNotice.text'), /版本不同/);
  assert.match(run('replayPendingHTML(null)'), /gw-replay-retry/);
});

test('leaving the AI while its replay file is still loading reads it again on return', async () => {
  const {context, run} = viewContext();
  Object.assign(context, {createState, replayState});
  const replayFile = {schemaVersion: 2, bundleVersion: bundle.bundleVersion, problemId: bundle.problemId, routes: [], actions: [], status: 'failed'};
  const pending = [], fetched = [];
  context.fetch = url => {
    fetched.push(String(url));
    if (String(url).endsWith('index.json')) {
      return Promise.resolve({ok: true, json: async () => ({bundleVersion: bundle.bundleVersion, replays: [{path: 'walk.json'}]})});
    }
    return new Promise(resolve => pending.push(() => resolve({ok: true, json: async () => replayFile})));
  };
  const element = {classList: {contains: () => false, toggle() {}}, setAttribute() {}, textContent: '', hidden: false};
  context.document.querySelector = () => element;
  context.document.body = {dataset: {}, classList: {toggle() {}, contains: () => false}};
  run(`render = () => {}; updatePlayButton = () => {}; closeGraph = () => {}; applyReplayPosition = () => {}; playReplay = () => {};`);
  run(`chooseActor('replay')`);
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(pending.length, 1);
  run(`chooseActor('student')`);
  pending.shift()();
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(run('replay'), null);
  run(`chooseActor('replay')`);
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(pending.length, 1);
  assert.equal(fetched.filter(url => url.endsWith('walk.json')).length, 2);
  pending.shift()();
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(run('replay.status'), 'failed');
  assert.equal(run('replayNotice'), null);
});

class SVGElement {
  constructor(tag) {
    this.tag = tag; this.children = []; this.attributes = {}; this.dataset = {};
    this.clientWidth = 450; this.clientHeight = 480;
    this.classList = {toggle() {}};
  }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  insertBefore(node, other) { this.children.splice(this.children.indexOf(other), 0, node); }
  addEventListener(type, listener) { (this.listeners ||= {})[type] = listener; }
  getBoundingClientRect() { return {left: 0, top: 0}; }
  setPointerCapture() {}
  hasPointerCapture() { return false; }
  closest() { return null; }
  querySelector(selector) {
    return this.children.find(node => node.attributes.class === selector.slice(1));
  }
}

test('the 2D graph shows the whole tree and stays still while the walk advances', () => {
  const globals = ['document', 'matchMedia', 'ResizeObserver', 'cancelAnimationFrame'];
  const previous = new Map(globals.map(key => [key, globalThis[key]]));
  try {
    globalThis.document = {createElement: tag => new SVGElement(tag), createElementNS: (_, tag) => new SVGElement(tag)};
    globalThis.matchMedia = () => ({matches: true});
    globalThis.ResizeObserver = class {observe() {} disconnect() {}};
    globalThis.cancelAnimationFrame = () => {};
    const host = new SVGElement('div');
    const graph = structuredClone(bundle.graph);
    const view = createWalkGraph(host, graph);
    const svg = host.children[1], viewport = svg.children[1];
    const transform = () => viewport.attributes.transform;
    const before = transform();
    const [x, y, scale] = before.match(/-?\d+(?:\.\d+)?/g).map(Number);
    const {width, height} = panoramaLayout(graph, 450, 480);
    assert.ok(x >= 0 && y >= 0 && x + width * scale <= 450 + 1e-6 && y + height * scale <= 480 + 1e-6);
    const [first, second] = graph.edges;
    view.render({nodes: {[first.from]: 'confirmed', [first.to]: 'active'}, edges: {[first.id]: 'chosen'}, focus: [first.to]});
    view.render({nodes: {[second.to]: 'active'}, edges: {}, focus: [second.to]});
    assert.equal(transform(), before);
    const edges = viewport.children.find(node => node.attributes.class === 'gw-edge-layer').children;
    assert.equal(edges.find(edge => edge.attributes['data-edge'] === first.id).children.at(-1).textContent, RELATIONS[first.type]);
    assert.equal(nodeHref({id: 'quadratic', ref: 'quadratic#sign'}), '/knowledge/quadratic/#sign');
  } finally {
    for (const key of globals) previous.get(key) === undefined ? delete globalThis[key] : globalThis[key] = previous.get(key);
  }
});

test('two fingers pinch the 2D graph around their midpoint', () => {
  const globals = ['document', 'matchMedia', 'ResizeObserver', 'cancelAnimationFrame'];
  const previous = new Map(globals.map(key => [key, globalThis[key]]));
  try {
    globalThis.document = {createElement: tag => new SVGElement(tag), createElementNS: (_, tag) => new SVGElement(tag)};
    globalThis.matchMedia = () => ({matches: true});
    globalThis.ResizeObserver = class {observe() {} disconnect() {}};
    globalThis.cancelAnimationFrame = () => {};
    const host = new SVGElement('div');
    createWalkGraph(host, structuredClone(bundle.graph));
    const svg = host.children[1], viewport = svg.children[1];
    const read = () => viewport.attributes.transform.match(/-?\d+(?:\.\d+)?/g).map(Number);
    const [x0, y0, k0] = read();
    const pointer = (type, id, x, y) => svg.listeners[type]({pointerId: id, clientX: x, clientY: y, target: svg});
    pointer('pointerdown', 1, 200, 200); pointer('pointerdown', 2, 240, 200);
    pointer('pointermove', 1, 180, 200); pointer('pointermove', 2, 260, 200);
    const [x, y, k] = read();
    assert.ok(Math.abs(k - k0 * 2) < 1e-9);
    assert.ok(Math.abs((220 - x) / k - (220 - x0) / k0) < 1e-9 && Math.abs((200 - y) / k - (200 - y0) / k0) < 1e-9);
    pointer('pointerup', 1, 180, 200); pointer('pointermove', 2, 300, 200);
    assert.deepEqual(read(), [x, y, k]);
  } finally {
    for (const key of globals) previous.get(key) === undefined ? delete globalThis[key] : globalThis[key] = previous.get(key);
  }
});

test('the 2D tree stacks the snapshot lanes top-down in a grid, without overlaps', () => {
  const {positions, bands, direction, width, height} = treeLayout(bundle.graph, {perRow: 4});
  assert.equal(direction, 'down');
  assert.deepEqual(bands.map(band => band.label), bundle.graph.layout.bands.map(band => band.label));
  assert.deepEqual([...positions.keys()].sort(), Object.keys(bundle.graph.layout.positions).sort());
  bands.forEach((band, index) => { if (index) assert.ok(band.y >= bands[index - 1].y + bands[index - 1].h); });
  const boxes = [...positions.values()];
  const rows = Map.groupBy(boxes, box => Math.round(box.y + box.h / 2));
  assert.ok([...rows.values()].every(row => row.length <= 4));
  for (const [i, a] of boxes.entries()) {
    assert.ok(a.x >= 0 && a.y >= 0 && a.x + a.w <= width && a.y + a.h <= height);
    for (const b of boxes.slice(i + 1)) assert.ok(a.x + a.w <= b.x || b.x + b.w <= a.x || a.y + a.h <= b.y || b.y + b.h <= a.y);
  }
});

test('the panorama widens its rows in a wide panel and narrows them in a tall one', () => {
  const wide = panoramaLayout(bundle.graph, 1200, 560), tall = panoramaLayout(bundle.graph, 390, 700);
  assert.ok(wide.perRow > tall.perRow);
  assert.ok(wide.width / wide.height > tall.width / tall.height);
});

test('bare formulas in AI reasons render as math; authored math and words stay as they are', () => {
  const {run} = viewContext();
  const text = reason => run(`mathText(${JSON.stringify(reason)})`);
  assert.equal(text('a^2-3a-4=(a-4)(a+1)≥0，即 a≤-1 或 a≥4。'), '$a^2-3a-4=(a-4)(a+1)\\ge 0$，即 $a\\le -1$ 或 $a\\ge 4$。');
  assert.equal(text('判别式 Δ≤0，只需 c≥f(x)_max.'), '判别式 $\\Delta \\le 0$，只需 $c\\ge f(x)_{\\mathrm{max}}$.');
  assert.equal(text('配方得 $-x^2+2x+3=4-(x-1)^2$，故常数为 4。'), '配方得 $-x^2+2x+3=4-(x-1)^2$，故常数为 4。');
  assert.equal(text('AI 看关于 x 的式子 ax^2+bx'), 'AI 看关于 $x$ 的式子 $ax^2+bx$');
  assert.equal(text('x∈ℝ，落在 real/free；需 Δ≤0'), '$x\\in \\mathbb R$，落在 real/free；需 $\\Delta \\le 0$');
});
