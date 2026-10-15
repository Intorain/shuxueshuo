import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {spawnSync} from 'node:child_process';
import {
  createState, currentDecision, submitAnswer, projectDecision,
  graphState, undo, switchRoute, replayState, gradeDecision,
} from '../../site/assets/graph-walk/walk-state.mjs';

const bundlePath = new URL('../../site/data/graph-walk/quadratic-always-q01.json', import.meta.url);
const bundle = JSON.parse(fs.readFileSync(bundlePath, 'utf8'));
const methodFor = (decision, route) => decision.interaction.methods.find(method => method.route === route).value;
const correct = (decision, route = 'discriminant') => decision.interaction.type === 'plane'
  ? [...decision.expected_answer.cell, methodFor(decision, route)]
  : decision.interaction.type === 'grid' ? decision.expected_answer.cell
  : decision.interaction.type === 'multi' ? decision.expected_answer.required
    : decision.interaction.type === 'choice' ? decision.expected_answer.one_of[0]
      : decision.expected_answer.terms;

function advance(state, route) {
  const decision = currentDecision(bundle, state);
  const next = submitAnswer(bundle, state, {decision: decision.id, answer: correct(decision, route)});
  assert.equal(next.lastFeedback.status, 'passed', `${decision.id}: ${next.lastFeedback.message}`);
  return next;
}

function startRoute(route) {
  let state = createState(bundle);
  for (const _ of bundle.intro) state = advance(state, route);
  return state;
}

for (const route of Object.keys(bundle.routes)) {
  test(`${route}: every step uses shared grading; replay and undo reproduce state`, () => {
    let state = createState(bundle);
    const actions = [];
    while (!state.done) {
      const decision = currentDecision(bundle, state);
      const before = structuredClone(state);
      const invalid = submitAnswer(bundle, state, {decision: decision.id, answer: null});
      assert.equal(invalid.lastFeedback.status, 'wrong');
      assert.deepEqual(invalid.run, before.run);
      assert.deepEqual(invalid.introCompleted, before.introCompleted);
      assert.equal(currentDecision(bundle, invalid).id, decision.id);
      const action = {decision: decision.id, answer: correct(decision, route)};
      state = submitAnswer(bundle, state, action);
      actions.push(action);
      const back = undo(bundle, state);
      assert.deepEqual(back.run, before.run);
      assert.deepEqual(back.introCompleted, before.introCompleted);
    }
    assert.equal(state.run.completed.length, bundle.routes[route].steps.length);
    const replay = {schemaVersion: 2, problemId: bundle.problemId, bundleVersion: bundle.bundleVersion, routes: [route], actions, status: 'completed'};
    assert.deepEqual(replayState(bundle, replay), state);
    assert.throws(() => replayState(bundle, {...replay, bundleVersion: 'old'}), /版本/);
    assert.throws(() => replayState(bundle, {...replay, actions: actions.slice(1)}), /顺序/);
    assert.throws(() => replayState(bundle, {...replay, actions: actions.slice(0, -1)}), /未完成/);
  });
}

test('one replay walks the chosen route, then switches to the other route', () => {
  const walk = route => { const actions = []; let state = createState(bundle);
    while (!state.done) { const decision = currentDecision(bundle, state); const action = {decision: decision.id, answer: correct(decision, route)}; state = submitAnswer(bundle, state, action); actions.push(action); }
    return actions; };
  const first = walk('extremum');
  const second = bundle.routes.discriminant.steps.map(step => ({decision: step.id, answer: correct(step)}));
  const actions = [...first, {switch_route: 'discriminant'}, ...second];
  const replay = {schemaVersion: 2, problemId: bundle.problemId, bundleVersion: bundle.bundleVersion,
    routes: ['extremum', 'discriminant'], actions, status: 'completed'};
  const done = replayState(bundle, replay);
  assert.equal(done.done, true);
  assert.equal(done.run.route, 'discriminant');
  assert.deepEqual(done.archives.map(run => run.route), ['extremum']);
  assert.equal(replayState(bundle, replay, first.length + 1).run.route, 'discriminant');
  assert.throws(() => replayState(bundle, {...replay, routes: ['discriminant', 'extremum']}), /路线不一致/);
  assert.throws(() => replayState(bundle, {...replay, actions: [...first.slice(0, -1), {switch_route: 'discriminant'}]}), /换路线/);
  assert.throws(() => replayState(bundle, {...replay, actions: first}), /未完成/);
  assert.throws(() => replayState(bundle, {...replay, schemaVersion: 1}), /版本/);
});

test('a failed replay that stopped before any route was picked still plays back', () => {
  const wrong = {decision: 'D1', answer: ['every'], reason: '只看量词'};
  const replay = {schemaVersion: 2, problemId: bundle.problemId, bundleVersion: bundle.bundleVersion,
    routes: [], actions: [wrong, wrong, wrong], status: 'failed'};
  const state = replayState(bundle, replay);
  assert.equal(state.run.route, null);
  assert.equal(state.lastFeedback.status, 'wrong');
  assert.equal(currentDecision(bundle, state).id, 'D1');
  assert.throws(() => replayState(bundle, {...replay, status: 'completed'}), /不一致/);
  const picked = [...bundle.intro.map(decision => ({decision: decision.id, answer: correct(decision)}))];
  assert.throws(() => replayState(bundle, {...replay, actions: picked}), /路线不一致/);
});

test('unfinished or unsupported choices do not release results', () => {
  let state = advance(createState(bundle));
  const decision = currentDecision(bundle, state);
  assert.equal(decision.id, 'D2');
  const [alternative] = Object.keys(decision.alternatives);
  const next = submitAnswer(bundle, state, {decision: 'D2', answer: alternative});
  assert.equal(next.lastFeedback.status, 'uncovered');
  assert.deepEqual(next.introCompleted, state.introCompleted);
  assert.equal(next.run.route, null);
  assert.equal(currentDecision(bundle, next).id, 'D2');
});

test('switching routes isolates results, preserves occurrence history and supports undo', () => {
  let state = startRoute('discriminant');
  while (!state.done) state = advance(state);
  const prior = structuredClone(state);
  state = switchRoute(bundle, state, 'extremum');
  assert.equal(state.archives.length, 1);
  assert.equal(state.run.completed.length, 0);
  assert.notEqual(state.run.id, prior.run.id);
  assert.equal(state.done, false);
  assert.equal(currentDecision(bundle, state).id, 'e_basis');
  assert.ok(projectDecision(bundle, state).results.every(result => !result.step.startsWith('d_')));
  assert.ok(graphState(bundle, state).calls.every(call => call.runId === state.run.id));
  assert.ok(graphState(bundle, state).archivedEdges.length > 0);
  assert.deepEqual(undo(bundle, state).run, prior.run);
  while (!state.done) state = advance(state, 'extremum');
  const graph = graphState(bundle, state);
  assert.ok(graph.calls.some(call => call.method === 'method-separation' && call.ref === 'method-square-extremum'));
  assert.ok(graph.calls.some(call => call.method === 'method-square-extremum' && call.ref === 'method-complete-square'));
  assert.ok(!graph.calls.some(call => ['method-elimination', 'method-substitution'].includes(call.ref)));
  assert.ok(!graph.usedBasis.includes('quantifiers#existential'));
  assert.ok(!graph.usedBasis.some(ref => ref.startsWith('reciprocal')));
  assert.equal(new Set(graph.calls.map(call => `${call.runId}:${call.decision}:${call.executionIndex}`)).size, graph.calls.length);
  for (const call of graph.calls) {
    const edge = bundle.graph.edges.find(edge => edge.id === call.edge);
    assert.equal(edge.occurrences[call.occurrence].step, call.step);
  }
});

test('LLM projection contains only question data, options and confirmed results', () => {
  for (const route of Object.keys(bundle.routes)) {
    let state = createState(bundle);
    while (!state.done) {
      const projected = projectDecision(bundle, state);
      const keys = [];
      const walk = value => {
        if (!value || typeof value !== 'object') return;
        for (const [key, child] of Object.entries(value)) { keys.push(key); walk(child); }
      };
      walk(projected);
      for (const banned of ['expected_answer', 'effects', 'family_id', 'match_status', 'verdicts', 'templates', 'solution', 'display', 'tip']) {
        assert.ok(!keys.includes(banned), `${projected.id}: leaks ${banned}`);
      }
      const completed = [...state.introCompleted, ...state.run.completed].map(entry => entry.decision);
      assert.ok(projected.results.every(result => completed.includes(result.step)));
      state = advance(state, route);
    }
  }
});

test('ordered fills and checklists use original PracticeContext.validate', () => {
  const decision = bundle.routes.extremum.steps.find(step => step.id === 'e_extremum');
  assert.equal(gradeDecision(decision, ['4', '1']).status, 'passed');
  assert.equal(gradeDecision(decision, ['1', '4']).status, 'wrong');
  assert.equal(gradeDecision(decision, ['4', '1', '4']).status, 'wrong');
  const checklist = bundle.intro.find(step => step.interaction.type === 'checklist');
  assert.equal(gradeDecision(checklist, correct(checklist)).status, 'passed');
});

test('method plane grades the cell axis by axis, then the method, and picks the route', () => {
  let state = createState(bundle);
  while (currentDecision(bundle, state).interaction.type !== 'plane') state = advance(state);
  const decision = currentDecision(bundle, state);
  const grade = answer => gradeDecision(decision, answer);
  assert.equal(grade(['real', 'free']).status, 'wrong');
  assert.deepEqual(grade(['interval', 'free', 'separation']), {status: 'wrong', message: decision.feedback.x});
  assert.deepEqual(grade(['real', 'given', 'swap']), {status: 'wrong', message: decision.feedback.y});
  assert.deepEqual(grade(['real', 'free', 'swap']), {status: 'wrong', message: decision.feedback.method});
  const interval = submitAnswer(bundle, state, {decision: decision.id, answer: ['real', 'free', 'interval']});
  assert.deepEqual([interval.lastFeedback.status, interval.lastFeedback.message], ['wrong', decision.feedback.method]);
  assert.equal(interval.run.route, null);
  for (const route of Object.keys(bundle.routes)) {
    const next = submitAnswer(bundle, state, {decision: decision.id, answer: correct(decision, route)});
    assert.equal(next.run.route, route);
    assert.ok(graphState(bundle, next).logs.at(-1).text.includes(bundle.routes[route].label));
  }
  const projected = projectDecision(bundle, state).interaction;
  assert.ok(projected.methods.every(method => !('route' in method) && typeof method.implemented === 'boolean'));
});

test('separation map grades the picked cell axis by axis and projects its zones to the AI', () => {
  let state = startRoute('discriminant');
  while (!state.done) state = advance(state);
  state = switchRoute(bundle, state, 'extremum');
  const decision = currentDecision(bundle, state);
  assert.equal(decision.interaction.type, 'grid');
  assert.equal(gradeDecision(decision, ['separable', 'no_division']).status, 'passed');
  assert.deepEqual(gradeDecision(decision, ['tangled', 'no_division']), {status: 'wrong', message: decision.feedback.x});
  assert.deepEqual(gradeDecision(decision, ['separable', 'division']), {status: 'wrong', message: decision.feedback.y});
  for (const bad of [['separable'], ['separable', 'nowhere'], 'separable']) assert.equal(gradeDecision(decision, bad).status, 'wrong');
  const projected = projectDecision(bundle, state);
  assert.equal(projected.interaction.zones.length, 3);
  assert.deepEqual(projected.answerFormat.answer, ['横轴 x 选项的 value', '纵轴 y 选项的 value']);
});

test('actual graph paths preserve relation direction and only real edges', () => {
  let state = startRoute('discriminant');
  while (!state.done) state = advance(state);
  const graph = graphState(bundle, state);
  assert.equal(graph.edges['type-quantified-quadratic|involves|quantifiers'], 'chosen');
  assert.ok(!('quantifiers|involves|type-quantified-quadratic' in graph.edges));
  const ids = new Set(bundle.graph.edges.map(edge => edge.id));
  assert.ok(Object.keys(graph.edges).every(id => ids.has(id)));
  const simplifications = graph.calls.filter(call => call.ref === 'skill-simplify');
  assert.ok(simplifications.length >= 2, 'normalization and later algebra remain separate calls');
});

test('Node JSONL bridge projects input and records the same model actions', () => {
  const lines = [
    {op: 'init', bundle: bundlePath.pathname},
    {op: 'answer', action: {decision: 'D1', answer: correct(bundle.intro[0])}},
    {op: 'export'},
  ];
  const result = spawnSync(process.execPath, [new URL('../graph-walk-actor.mjs', import.meta.url).pathname], {
    input: lines.map(line => JSON.stringify(line)).join('\n') + '\n', encoding: 'utf8',
  });
  assert.equal(result.status, 0, result.stderr);
  const responses = result.stdout.trim().split('\n').map(line => JSON.parse(line));
  assert.equal(responses[0].decision.id, 'D1');
  assert.equal(responses[1].decision.id, 'D2');
  assert.equal(responses[1].feedback.status, 'passed');
  assert.deepEqual(responses[2].actions, [lines[1].action]);
});

test('Node bridge lets the AI pick its route, then switches to the remaining one', () => {
  const answer = (decision, route) => ({op: 'answer', action: {decision: decision.id, answer: correct(decision, route)}});
  const lines = [
    {op: 'init', bundle: bundlePath.pathname},
    ...bundle.intro.map(decision => answer(decision, 'extremum')),
    ...bundle.routes.extremum.steps.map(step => answer(step)),
    {op: 'switch'},
    ...bundle.routes.discriminant.steps.map(step => answer(step)),
    {op: 'switch'},
    {op: 'export'},
  ];
  const result = spawnSync(process.execPath, [new URL('../graph-walk-actor.mjs', import.meta.url).pathname], {
    input: lines.map(line => JSON.stringify(line)).join('\n') + '\n', encoding: 'utf8',
  });
  assert.equal(result.status, 0, result.stderr);
  const responses = result.stdout.trim().split('\n').map(line => JSON.parse(line));
  const plane = bundle.intro.findIndex(decision => decision.interaction.type === 'plane');
  assert.doesNotMatch(responses[plane].decision.question, /录制|指定/);
  const firstDone = bundle.intro.length + bundle.routes.extremum.steps.length;
  assert.equal(responses[firstDone].done, false);
  assert.equal(responses[firstDone].nextRoute, 'discriminant');
  assert.equal(responses[firstDone + 1].decision.id, bundle.routes.discriminant.steps[0].id);
  assert.equal(responses.at(-3).done, true);
  assert.equal(responses.at(-3).status, 'completed');
  assert.ok(responses.at(-2).error, 'no route left to switch to');
  const replay = responses.at(-1);
  assert.equal(replay.schemaVersion, 2);
  assert.deepEqual(replay.routes, ['extremum', 'discriminant']);
  assert.deepEqual(replay.actions[firstDone], {switch_route: 'discriminant'});
  assert.equal(replayState(bundle, replay).done, true);
});

test('shipped recordings match this bundle and expose only public actions', () => {
  const indexPath = new URL('../../site/data/graph-walk/replays/index.json', import.meta.url);
  const index = JSON.parse(fs.readFileSync(indexPath, 'utf8'));
  assert.equal(index.bundleVersion, bundle.bundleVersion);
  assert.equal(index.replays.length, 1);
  const [item] = index.replays;
  const replay = JSON.parse(fs.readFileSync(new URL(item.path, indexPath), 'utf8'));
  assert.deepEqual(Object.keys(replay).sort(), ['schemaVersion', 'bundleVersion', 'problemId', 'routes', 'actions', 'status'].sort());
  assert.deepEqual([...replay.routes].sort(), Object.keys(bundle.routes).sort());
  for (const action of replay.actions) {
    const keys = Object.keys(action);
    assert.ok(keys.join() === 'switch_route' || keys.every(key => ['decision', 'answer', 'reason'].includes(key)));
  }
  assert.equal(replayState(bundle, replay).done, true);
});
