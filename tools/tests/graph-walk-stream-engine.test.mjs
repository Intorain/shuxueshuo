import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import * as stateAPI from '../../site/assets/graph-walk/walk-state.mjs';
import * as mathDOM from '../../site/assets/graph-walk/stream-math-dom.mjs';

const source = fs.readFileSync(new URL('../../site/assets/graph-walk/walk.mjs', import.meta.url), 'utf8');
const components = fs.readFileSync(new URL('../../site/assets/practice/components.js', import.meta.url), 'utf8');
const read = path => JSON.parse(fs.readFileSync(new URL(path, import.meta.url), 'utf8'));
const base = read('../../site/lab/search/demo-lesson-q01.json').goals[0].walk.bundle;
const graph = read('../../site/knowledge/graph.json');
const d3 = read('../../site/data/graph-walk/quadratic-always-q01.source.json').intro.find(item => item.id === 'D3');
const identity = {run_id: 'engine-run', lesson_version: 'engine-lesson', stream_id: 'engine-run'};
const target = '/root/goals/0';
const routes = ['discriminant', 'extremum'];
const card = (ordinal, route = routes[0]) => ({...identity, target_ref: target, route_id: route,
  step_id: `math-${ordinal}`, ordinal, math_step_sha256: `${route}-${ordinal}-hash`, local_check: 'passed',
  title: `数学步骤 ${ordinal}`, before: [{latex: `before-${ordinal}`}], after: [{latex: `secret-after-${ordinal}`}],
  explanation: `secret-explanation-${ordinal}`, source_refs: [], used_basis: []});
const part = (id, type = 'choice') => ({id, title: id, question: `请判断 ${id}`,
  interaction: type === 'fill' ? {type, slot_labels: ['第一项'], terms: ['yes', 'no']}
    : {type, field: id, options: [{value: 'yes', label: '成立'}, {value: 'no', label: '不成立'}]},
  expected_answer: type === 'fill' ? {terms: ['yes']} : {one_of: ['yes']}});
function fixture({parts = [part('first'), part('last')], merged = false, readonly = false} = {}) {
  const math_steps = routes.flatMap(route => Array.from({length: merged ? 2 : 1}, (_, i) => card(i + 1, route)));
  const interactions = routes.map(route => ({...identity, target_ref: target, route_id: route,
    interaction_id: `${route}-interaction`, status: readonly ? 'readonly' : 'interactive',
    steps: math_steps.filter(step => step.route_id === route).map(({step_id, math_step_sha256}) => ({step_id, math_step_sha256})),
    parts: readonly ? [] : structuredClone(parts)}));
  const view = {...identity, goals: {}, math_steps, interaction_protocol: 'graph-step-interaction/v1',
    selection_chunks: [{target_ref: target, kind: 'D3', chunk: d3}, {target_ref: target, kind: 'D4', chunk: {id: 'D4', title: '选路线', options: [
      {branch: 'discriminant', route_id: routes[0], method: 'method-discriminant', route_plan: 'planned'},
      {branch: 'separation', route_id: routes[1], method: 'method-separation', route_plan: 'planned'},
    ]}}], interactions, interaction_states: interactions.flatMap(chunk => chunk.steps.map(step => ({...step,
      target_ref: target, route_id: chunk.route_id, interaction_id: chunk.interaction_id, status: chunk.status}))),
    completions: routes.map(route => ({identity: [target, route], status: 'verified', available: true,
      verified_route_sha256: `${route}-verified`, answer: {kind: 'find_range', status: 'set', set: {latex: '[0,+\\infty)'}}})),
  };
  const bundle = stateAPI.extendStreamBundle(base, view, target, graph);
  let state = stateAPI.createState(bundle);
  for (const decision of bundle.intro) {
    const answer = decision.interaction.type === 'plane'
      ? [...decision.expected_answer.cell, decision.interaction.methods.find(method => method.route === routes[0]).value]
      : decision.id === 'D4' ? routes[0] : decision.interaction.type === 'multi'
        ? decision.expected_answer.required : decision.expected_answer.one_of?.[0] || decision.expected_answer.terms;
    state = stateAPI.submitAnswer(bundle, state, {decision: decision.id, answer});
    assert.equal(state.lastFeedback.status, 'passed');
  }
  return {bundle, state, view};
}

// A small DOM fixture with real parent/child ownership. The engine's authored HTML
// stays opaque; only its mathematical mounting hosts need parsing in these tests.
function documentFixture() {
  const roots = new Map(), document = {body: {dataset: {}, classList: {contains: () => false, toggle() {}}}};
  const dataKey = name => name.replace(/-([a-z])/g, (_, letter) => letter.toUpperCase());
  class Element {
    constructor(tag = 'div') { this.tagName = tag; this.ownerDocument = document; this.children = []; this.dataset = {}; this.hidden = false; this._text = ''; this._html = ''; this.classList = {contains: () => false}; }
    get childNodes() { return this.children; }
    get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
    set textContent(value) { this._text = String(value ?? ''); this.children = []; }
    append(...nodes) { for (const node of nodes) { if (node.parentNode) node.parentNode.children.splice(node.parentNode.children.indexOf(node), 1); node.parentNode = this; this.children.push(node); } }
    replaceChildren(...nodes) { for (const child of this.children) child.parentNode = null; this.children = []; this.append(...nodes); }
    setAttribute(name, value) { this[name] = value; }
    set innerHTML(value) {
      this._html = value; this.replaceChildren();
      for (const match of value.matchAll(/<div[^>]*\bdata-stream-(context|completed|retained)(?:="([^"]*)")?[^>]*>/g)) {
        const node = new Element(); node.dataset[dataKey(`stream-${match[1]}`)] = match[2] || ''; this.append(node);
      }
    }
    get innerHTML() { return this._html; }
    querySelectorAll(selector) {
      const attr = /^\[data-([^\]]+)\](?::not\(\[data-([^\]]+)\]\))?$/.exec(selector);
      const found = [];
      for (const child of this.children) {
        if (attr && Object.hasOwn(child.dataset, dataKey(attr[1])) && (!attr[2] || !Object.hasOwn(child.dataset, dataKey(attr[2])))) found.push(child);
        else if (selector.startsWith('.') && child.className === selector.slice(1)) found.push(child);
        found.push(...child.querySelectorAll(selector));
      }
      return found;
    }
    querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  }
  document.createElement = tag => new Element(tag);
  document.querySelector = selector => {
    if (!roots.has(selector)) roots.set(selector, new Element());
    return roots.get(selector);
  };
  return {document, roots};
}

function engine(value = fixture()) {
  const {document, roots} = documentFixture(), storage = new Map();
  const context = vm.createContext({document, matchMedia: () => ({matches: true}), URL, structuredClone,
    setTimeout, clearTimeout, ...stateAPI, ...mathDOM,
    PracticeMath: {render(node, text) { node.textContent = text; }},
    localStorage: {getItem: key => storage.get(key), setItem: (key, text) => storage.set(key, text)}});
  context.window = context;
  vm.runInContext(components, context);
  const definitions = source.replace(/^import .*;\n/gm, '').split("if (document.readyState === 'loading')")[0];
  const bridge = source.slice(source.indexOf('export async function mountWalk'), source.indexOf("if (document.body.dataset.walk !== 'mount')"));
  vm.runInContext(definitions + '\n' + bridge.replace(/^export /gm, ''), context);
  Object.assign(context, {fixture: value, initialBase: base});
  const run = code => vm.runInContext(code, context);
  run(`bundle = fixture.bundle; state = studentState = fixture.state; streamView = fixture.view;
    graphView = bundle.graph; options = {bundle: initialBase, stream: {...fixture.view, target_ref: bundle.stream.target_ref}};
    actor = 'student'; renderCount = 0; realRender = render; realRenderGraph = renderGraph; realStopReplay = stopReplay;
    renderGraph = () => {}; stopReplay = () => {}; toggleSteps = () => {};
    render = () => {renderCount++; const current = currentDecision(bundle,state); if (current) ensureDraft(current); park();};`);
  return {context, roots, run, storage, value};
}

test('interactive parts expose only before; only the last completed part mounts every merged math card', () => {
  const {run, roots} = engine(fixture({merged: true}));
  run('renderInteraction(currentDecision(bundle,state))');
  const active = roots.get('#gw-active');
  assert.equal(active.dataset.decisionId, 'first');
  assert.match(active.textContent, /before-1/);
  assert.doesNotMatch(active.textContent, /before-2/, 'a later card\'s before can be the earlier card\'s conclusion');
  assert.doesNotMatch(active.textContent, /secret-/);
  assert.doesNotMatch(run(`completedHTML({decision:'first',answer:'yes'},5,1,'discriminant')`), /stream-completed|secret-/);
  run(`state = studentState = submitAnswer(bundle,state,{decision:'first',answer:'yes'}); renderInteraction(currentDecision(bundle,state));`);
  assert.doesNotMatch(active.textContent, /secret-/);
  run(`state = studentState = submitAnswer(bundle,state,{decision:'last',answer:'yes'});
    document.querySelector('#gw-steps').innerHTML=completedHTML(state.run.completed.at(-1),6,1,'discriminant'); mountCompletedMath();`);
  assert.match(roots.get('#gw-steps').textContent, /secret-after-1.*secret-explanation-1.*secret-after-2/);
  assert.equal(run('visibleStreamCards.size'), 2);
});

test('read presents the full card and advances through the normal answer state machine', () => {
  const {run, roots} = engine(fixture({readonly: true}));
  run('renderInteraction(currentDecision(bundle,state))');
  assert.equal(run('draft'), 'read');
  assert.match(roots.get('#gw-active').innerHTML, /读完了，下一步/);
  assert.match(roots.get('#gw-active').textContent, /secret-after-1/);
  run(`state = submitAnswer(bundle,state,{decision:currentDecision(bundle,state).id,answer:draft})`);
  assert.equal(run('state.lastFeedback.status'), 'passed');
  assert.equal(run('state.done'), true);
});

for (const failure of ['route', 'goal']) test(`a stopped ${failure} keeps its committed math readable without reopening practice or QA`, () => {
  const value = fixture({merged: true});
  value.state = stateAPI.submitAnswer(value.bundle, value.state, {decision: 'first', answer: 'yes'});
  if (failure === 'route') value.view.route_statuses = [[JSON.stringify([target, routes[0]]), {status: 'capability_gap'}]];
  else value.view.goals[target] = {status: 'conflict', available: false};
  value.bundle = stateAPI.extendStreamBundle(base, value.view, target, graph);
  value.state = stateAPI.refreshStreamState(value.bundle, value.state);
  const {run, roots} = engine(value);
  assert.equal(run('currentDecision(bundle,state)'), null);
  run(`document.querySelector('#gw-steps').innerHTML = waitingHTML(6); mountRetainedMath();`);
  const steps = roots.get('#gw-steps');
  assert.match(steps.innerHTML, /此路线暂不可用/);
  assert.match(steps.textContent, /secret-after-1.*secret-explanation-1.*secret-after-2/);
  assert.equal(steps.querySelectorAll('.stage-three-math-step').length, 2);
  assert.ok(steps.querySelectorAll('.stage-three-qa').every(node => node.hidden));
  assert.equal(run('visibleStreamCards.size'), 0, 'retained cards never receive late QA');
  assert.equal(run('state.done'), false);
});

test('stream undo stays disabled until the chosen route has an answer to rewind', () => {
  const {run, roots} = engine(fixture());
  run(`busy = false; renderStory = () => {}; revealStep = () => {}; realRender();`);
  assert.equal(roots.get('#gw-undo').disabled, true);
  run(`state = studentState = submitAnswer(bundle,state,{decision:'first',answer:'yes'}); realRender();`);
  assert.equal(roots.get('#gw-undo').disabled, false);
});

for (const field of ['target_ref', 'run_id', 'lesson_version']) test(`changing ${field} ${field === 'target_ref' ? 'keeps' : 'drops'} cached cards and QA`, async () => {
  const {run, context, value} = engine(fixture({parts: [part('last')]}));
  run(`state = studentState = submitAnswer(bundle,state,{decision:'last',answer:'yes'});
    document.querySelector('#gw-steps').innerHTML=completedHTML(state.run.completed.at(-1),5,1,'discriminant'); mountCompletedMath();
    bind = () => {}; bound = true; load = async () => {};`);
  context.chunk = {...value.view.math_steps[0], verified_route_sha256: 'discriminant-verified', qa: {questions: ['q']}};
  run('attachStreamQA(chunk)');
  assert.equal(run('streamCards.size'), 1);
  assert.equal(run('streamQA.size'), 1);
  context.next = {...run('options.stream'), [field]: field === 'target_ref' ? '/root/goals/1' : `next-${field}`};
  await run('mountWalk({stream: next})');
  const kept = field === 'target_ref' ? 1 : 0;
  assert.equal(run('streamCards.size'), kept);
  assert.equal(run('streamQA.size'), kept);
});

test('late QA is cached until completion, is idempotent, and preserves math DOM across attachment and remount', () => {
  const {run, context, roots, value} = engine(fixture({parts: [part('last')]}));
  context.chunk = {...value.view.math_steps[0], verified_route_sha256: 'discriminant-verified', qa: {questions: ['late question']}};
  run('attachStreamQA(chunk)');
  assert.equal(run('streamCards.size'), 0);
  run(`state = studentState = submitAnswer(bundle,state,{decision:'last',answer:'yes'});
    document.querySelector('#gw-steps').innerHTML=completedHTML(state.run.completed.at(-1),5,1,'discriminant'); mountCompletedMath();`);
  const cardNode = roots.get('#gw-steps').querySelector('.stage-three-math-step');
  const beforeNode = cardNode.querySelector('.stage-three-before'), qaNode = cardNode.querySelector('.stage-three-qa');
  const question = qaNode.children[1];
  assert.match(qaNode.textContent, /late question/);
  run('attachStreamQA(chunk); mountCompletedMath()');
  assert.equal(roots.get('#gw-steps').querySelector('.stage-three-math-step'), cardNode);
  assert.equal(cardNode.querySelector('.stage-three-before'), beforeNode);
  assert.equal(qaNode.children[1], question, 'identical QA does not replace its own region either');
  assert.throws(() => run(`attachStreamQA({...chunk,qa:{questions:['changed']}})`), /immutable_qa/);
  run(`attachStreamQA({...chunk,run_id:'other',qa:{questions:['wrong run']}})`);
  assert.doesNotMatch(qaNode.textContent, /wrong run|changed/);
  run(`streamView.goals[bundle.stream.target_ref]={available:false}; mountCompletedMath()`);
  assert.equal(qaNode.hidden, true);
  assert.equal(run('renderCount'), 0, 'QA attachment never rerenders the walk');
});

test('stream revisions refresh waiting/completion and retain an unchanged fill draft and selected slot', async () => {
  const value = fixture({parts: [part('first', 'fill')]}), {run, context} = engine(value);
  run(`ensureDraft(currentDecision(bundle,state)); draft=['no']; selectedSlot=0;`);
  const updated = structuredClone(value.view);
  updated.route_statuses = [[JSON.stringify([target, routes[0]]), {status: 'running'}]];
  updated.completions = []; updated.checkpoints = [{target_ref: target, route_id: routes[0], status: 'running'}];
  context.updated = updated;
  await run('updateStreamSelection(updated)');
  assert.equal(run('JSON.stringify(draft)'), '["no"]');
  assert.equal(run('selectedSlot'), 0);
  assert.equal(run('renderCount'), 1);
  run(`state = studentState = submitAnswer(bundle,state,{decision:'first',answer:['yes']});`);
  await run('updateStreamSelection(updated)');
  assert.equal(run('state.done'), false);
  assert.match(run('waitingHTML(6)'), /正在准备这一步的练习/);
  context.finished = value.view;
  await run('updateStreamSelection(finished)');
  assert.equal(run('state.done'), true);
});

test('routes retain independent drafts and selected fill slots, including persisted student state', () => {
  const {run, storage} = engine(fixture({parts: [part('first', 'fill')]}));
  run(`ensureDraft(currentDecision(bundle,state)); draft=['no']; selectedSlot=0;
    chooseStreamRoute('extremum'); draft=['yes']; selectedSlot=null; chooseStreamRoute('discriminant');`);
  assert.equal(run('JSON.stringify(draft)'), '["no"]');
  assert.equal(run('selectedSlot'), 0);
  run('park()');
  const saved = JSON.parse([...storage.values()].at(-1));
  assert.equal(saved.studentState.streamRoutes.extremum.draft.answer[0], 'yes');
  assert.equal(saved.studentState.streamRoutes.discriminant.draft.selectedSlot, 0);
  run(`state = studentState = refreshStreamState(bundle,JSON.parse(localStorage.getItem('graph-walk:'+bundle.problemId+':'+bundle.bundleVersion)).studentState);
    draftKey=''; draft=null; selectedSlot=null; ensureDraft(currentDecision(bundle,state));`);
  assert.equal(run('JSON.stringify(draft)'), '["no"]');
  assert.equal(run('selectedSlot'), 0);
});

test('AI route replay uses expected answers without completing or overwriting the student route', () => {
  const {run, context} = engine(fixture({parts: [part('first', 'fill')]}));
  context.introActions = run('state.events.map(event=>event.action).filter(action=>!["D3","D4"].includes(action.decision))');
  run(`options.replay={actions:introActions}; ensureDraft(currentDecision(bundle,state)); draft=['no']; selectedSlot=0;
    chooseActor('replay');`);
  assert.equal(run('state.done'), true);
  assert.equal(run('studentState.run.completed.length'), 0);
  run(`chooseStreamRoute('extremum'); replayPosition=4; park(); chooseActor('student');`);
  assert.equal(run('state.run.route'), 'discriminant');
  assert.equal(run('JSON.stringify(draft)'), '["no"]');
  assert.equal(run('selectedSlot'), 0);
  run(`chooseActor('replay')`);
  assert.equal(run('state.run.route'), 'extremum');
  assert.equal(run('replayPosition'), 4);
  assert.equal(run('state.done'), false);
});

test('same problem ID keeps distinct parked progress per subquestion and run even without browser storage', () => {
  const {run, context, value} = engine(fixture({parts: [part('first', 'fill')]}));
  context.other = structuredClone(value.bundle);
  context.other.bundleVersion += '-sibling-goal'; context.other.stream.target_ref = '/root/goals/1';
  context.newRun = structuredClone(value.bundle);
  context.newRun.bundleVersion += '-new-run'; context.newRun.stream.run_id = 'new-run';
  run(`localStorage.setItem=()=>{throw new Error('storage unavailable')};
    ensureDraft(currentDecision(bundle,state)); draft=['no']; selectedSlot=0; park();
    bundle=other; state=studentState=createState(bundle); draftKey=''; park();
    bundle=newRun; state=studentState=createState(bundle); draftKey=''; park();`);
  assert.equal(run('saved.size'), 3);
  assert.equal(run('savedProgress(fixture.bundle).studentState.streamDraft.answer[0]'), 'no');
  assert.equal(run('savedProgress(fixture.bundle).studentState.streamDraft.selectedSlot'), 0);
  assert.equal(run('savedProgress(other).studentState.introCompleted.length'), 0);
  assert.equal(run('savedProgress(newRun).studentState.introCompleted.length'), 0);
});

test('a late final interaction replaces the waiting state and leaves the next draft empty', async () => {
  const final = fixture({parts: [part('first')]}), pending = structuredClone(final.view);
  pending.interactions = []; pending.interaction_states.forEach(row => { row.status = 'pending'; delete row.interaction_id; });
  const pendingBundle = stateAPI.extendStreamBundle(base, pending, target, graph);
  const pendingState = stateAPI.refreshStreamState(pendingBundle, {...final.state, bundleVersion: pendingBundle.bundleVersion});
  const {run, context} = engine({bundle: pendingBundle, state: pendingState, view: pending});
  assert.equal(run('currentDecision(bundle,state)'), null);
  assert.match(run('waitingHTML(5)'), /计算已完成，正在准备练习/);
  context.finalView = final.view;
  await run('updateStreamSelection(finalView)');
  assert.equal(run('currentDecision(bundle,state).id'), 'first');
  assert.equal(run('draft'), null);
  assert.equal(run('renderCount'), 1);
  assert.equal(run('state.done'), false);
});

test('an initial D1/D2-only snapshot renders saved route progress without requiring its route metadata', () => {
  const full = fixture({parts: [part('first')]}), partial = stateAPI.extendStreamBundle(base, identity, target, graph);
  const restored = stateAPI.refreshStreamState(partial, full.state);
  const {run, roots} = engine({bundle: partial, state: restored, view: identity});
  run('renderStory=()=>{}; realRenderGraph()');
  assert.equal(roots.get('#gw-path').textContent, '正在恢复解题路线');
  assert.match(run('waitingHTML(5)'), /正在恢复解题路线/);
  assert.equal(run('state.run.route'), 'discriminant');
  assert.equal(run('state.introCompleted.length'), 4);
});

test('switching AI routes cancels its old timer and invalidates an already queued playback callback', () => {
  const {run, context} = engine(fixture({parts: [part('first'), part('last')]}));
  const scheduled = [], cancelled = [];
  context.setTimeout = callback => { scheduled.push(callback); return scheduled.length; };
  context.clearTimeout = handle => cancelled.push(handle);
  context.introActions = run('state.events.map(event=>event.action).filter(action=>!["D3","D4"].includes(action.decision))');
  run(`options.replay={actions:introActions}; chooseActor('replay');
    stopReplay=realStopReplay; updatePlayButton=()=>{}; replayPosition=4; playReplay();`);
  assert.equal(run('replayPosition'), 5);
  assert.equal(run('replayPlaying'), true);
  assert.equal(scheduled.length, 1);
  const oldTicket = run('replayTicket');
  run(`chooseStreamRoute('extremum')`);
  assert.equal(run('state.run.route'), 'extremum');
  assert.equal(run('replayPlaying'), false);
  assert.equal(run('replayTimer'), null);
  assert.ok(cancelled.includes(1));
  assert.ok(run('replayTicket') > oldTicket);
  const position = run('replayPosition'), renders = run('renderCount');
  scheduled[0]();
  assert.equal(run('replayPosition'), position);
  assert.equal(run('renderCount'), renders);
  assert.equal(run('replayNotice'), null);
});

for (const allRoutes of [true, false]) test(`withdrawing ${allRoutes ? 'all routes' : 'the playing route'} cancels stale AI callbacks and preserves student progress`, async () => {
  const value = fixture({parts: [part('first'), part('last')]});
  // The alternative has one fewer question, so a stale callback would exceed
  // its end even when a replacement route remains available.
  value.view.interactions[1].parts.pop();
  value.bundle = stateAPI.extendStreamBundle(base, value.view, target, graph);
  const {run, context} = engine(value), scheduled = [], cancelled = [];
  context.setTimeout = callback => { scheduled.push(callback); return scheduled.length; };
  context.clearTimeout = handle => cancelled.push(handle);
  context.introActions = run('state.events.map(event=>event.action).filter(action=>!["D3","D4"].includes(action.decision))');
  const studentBefore = run('JSON.stringify([studentState.introCompleted,studentState.run,studentState.events])');
  run(`options.replay={actions:introActions}; chooseActor('replay');
    stopReplay=realStopReplay; updatePlayButton=()=>{}; replayPosition=4; playReplay();`);
  assert.equal(run('replayPosition'), 5);
  assert.equal(scheduled.length, 1);
  const previousTicket = run('replayTicket');
  context.revoked = structuredClone(value.view);
  if (allRoutes) context.revoked.goals[target] = {status: 'conflict', available: false};
  else context.revoked.route_statuses = [[JSON.stringify([target, routes[0]]), {status: 'math_failed'}]];
  await assert.doesNotReject(run('updateStreamSelection(revoked)'));
  assert.equal(run('replayPlaying'), false);
  assert.equal(run('replayTimer'), null);
  assert.ok(cancelled.includes(1));
  assert.ok(run('replayTicket') > previousTicket);
  assert.equal(run('JSON.stringify([studentState.introCompleted,studentState.run,studentState.events])'), studentBefore);
  assert.equal(run('studentState.done'), false);
  assert.equal(run('currentDecision(bundle,studentState)'), null);
  assert.equal(run('replayRoutes.discriminant'), 5, 'a revoked route keeps its own last replay cursor');
  if (allRoutes) {
    assert.equal(run('replay.routes.length'), 0);
    assert.equal(run('state.done'), false);
  } else assert.equal(run('state.run.route'), 'extremum');
  const cursor = run('replayPosition'), renders = run('renderCount');
  scheduled[0]();
  assert.equal(run('replayPosition'), cursor);
  assert.equal(run('renderCount'), renders);
  assert.equal(run('replayNotice'), null);
});
