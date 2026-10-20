// Exercise the real photo-search page with recorded input and real streamed computations.
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import fs from 'node:fs';
import {pathToFileURL} from 'node:url';
const require = createRequire(import.meta.url);

const checked = call => call.postconditions?.length && call.postconditions.every(item => item.passed === true);
const trajectoryFor = (snapshot, route) => {
  const trajectory = snapshot.checkpoints.find(item => item.route_id === route)?.driver_state?.trajectory;
  assert.ok(trajectory, `missing durable trajectory for ${route}`);
  return trajectory;
};
const callsFor = trajectory => trajectory.steps.flatMap((record, stepIndex) =>
  record.calls.flatMap((call, index) => checked(call) ? [{record, call, source_ref: `/steps/${stepIndex}/calls/${index}`}] : []));
const cardsForCall = (snapshot, route, source) => snapshot.math_steps.filter(card => card.route_id === route && card.source_refs.includes(source));

/** Independent source evidence, kept from the previous reader acceptance. */
export function graphEvidence(snapshot, route) {
  const paths = callsFor(trajectoryFor(snapshot, route)).filter(({call}) => call.public_ref).map(({record, call, source_ref}) => {
    const cards = cardsForCall(snapshot, route, source_ref).filter(card =>
      JSON.stringify(card.case_path) === JSON.stringify(record.case_path));
    assert.ok(cards.length, `${route}:${source_ref} needs a mathematical source card`);
    return {method: record.method, rule: call.rule_ref, skill: call.public_ref,
      source_ref, step_ids: cards.map(card => card.step_id), edges: call.rule_ref
        ? [`${record.method}|step_rule|${call.rule_ref}`, `${call.rule_ref}|selects|${call.public_ref}`]
        : [`${record.method}|calls|${call.public_ref.split('#')[0]}`]};
  });
  return paths;
}

/** Validate mathematics from durable execution, independently of UI answers. */
export function verifyMathematics(config, paused, completed) {
  const [route, alternate] = config.routes, cards = completed.math_steps.filter(card => card.route_id === route);
  assert.ok(paused.math_steps.length > 0 && paused.math_steps.every(card => card.local_check === 'passed'));
  assert.equal(paused.handoffs.length, 0);
  if (config.prefix_cards !== undefined) assert.equal(paused.math_steps.length, config.prefix_cards);
  if (config.completed_cards !== undefined) assert.equal(completed.math_steps.length, config.completed_cards);
  if (config.qa_cards !== undefined) assert.equal(cards.length, config.qa_cards);
  assert.equal(completed.handoffs.length, config.routes.length);
  assert.ok(completed.checkpoints.every(checkpoint => checkpoint.status === 'verified'));
  assert.equal(new Set(completed.math_steps.map(card => card.step_id)).size, completed.math_steps.length);
  assert.deepEqual(cards.slice(0, paused.math_steps.length), paused.math_steps, 'verification preserves its committed prefix');
  for (const id of config.routes) {
    const handoff = completed.handoffs.find(item => item.route_id === id);
    assert.ok(handoff?.available);
    const reference = ({step_id, math_step_sha256, ordinal}) => ({step_id, math_step_sha256, ordinal});
    assert.deepEqual(handoff.math_steps.map(reference), completed.math_steps.filter(card => card.route_id === id).map(reference));
  }
  const trajectory = trajectoryFor(completed, route), traced = callsFor(trajectory);
  const result = {prefix_cards: paused.math_steps.length, completed_cards: completed.math_steps.length,
    graph_paths: Object.fromEntries(config.routes.map(id => [id, graphEvidence(completed, id)]))};
  if (config.interval_cases) {
    const cases = trajectory.steps.flatMap(record => record.case_results || []);
    assert.equal(cases.length, config.interval_cases);
    assert.equal(new Set(cases.map(item => JSON.stringify(item.case_path))).size, cases.length);
    assert.ok(cases.every(item => item.case_path.length && item.source_refs.length && cards.some(card =>
      JSON.stringify(card.case_path) === JSON.stringify(item.case_path))));
    if (config.constant_case) {
      const constants = traced.filter(({call}) => call.capability === 'linear_range' && call.used_basis.includes('skill-linear-range#constant'));
      assert.equal(constants.length, 1);
      const {record, call} = constants[0], item = cases.find(value => JSON.stringify(value.case_path) === JSON.stringify(record.case_path));
      assert.deepEqual(item.domain.exact, {$math: 'FiniteSet', args: [{$math: 'Integer', value: '0'}]});
      assert.equal(call.inputs.expression.expression, '-1');
      assert.equal(call.outputs.range.inf.expression, '-1'); assert.equal(call.outputs.range.sup.expression, '-1');
    }
    result.classification = cases.map(item => ({case_path: item.case_path, condition: item.condition}));
  }
  if (config.separation) {
    const calls = callsFor(trajectoryFor(completed, alternate));
    const divisions = calls.filter(({call}) => call.capability === 'separation_division');
    const ranges = calls.filter(({call}) => call.capability === config.separation.range_capability);
    assert.equal(divisions.length, 1); assert.equal(ranges.length, 1);
    const division = divisions[0].call, range = ranges[0].call;
    assert.equal(division.outputs.divisor_sign, config.separation.division);
    assert.equal(division.outputs.transformation, `${config.separation.division}_division`);
    assert.ok(division.operations.includes(`multiply_${config.separation.division}`));
    if (config.separation.division === 'negative') {
      assert.ok(division.postconditions.some(item => item.kind === 'strict_negative_divisor' && item.passed));
      assert.equal(division.outputs.operator, '<=');
    } else {
      assert.equal(range.outputs.range.inf.expression, '1/6'); assert.equal(range.outputs.range.sup.expression, '1/2');
      assert.ok(range.outputs.range.inf_attained && range.outputs.range.sup_attained);
    }
    for (const basis of config.separation.basis) assert.ok(range.used_basis.includes(basis));
    assert.equal(cardsForCall(completed, alternate, ranges[0].source_ref)[0].display_unit, config.separation.range_unit);
    result.separation = {division: config.separation.division, range: range.outputs.range};
  }
  if (config.variable_swap) {
    const ranges = traced.filter(({call}) => call.capability === 'parameter_linear_case_range');
    assert.equal(ranges.length, 1);
    assert.equal(ranges[0].call.outputs.slope_sign, config.variable_swap.slope_sign);
    assert.equal(ranges[0].call.outputs.endpoint_mode, config.variable_swap.endpoint_mode);
    const applied = traced.filter(({call, record}) => call.capability === 'apply_quantifier_policy' && record.method === 'method-variable-swap');
    assert.equal(applied.length, 1); assert.equal(applied[0].call.public_ref, null);
    assert.equal(applied[0].call.outputs.combiner, 'all');
    assert.equal(applied[0].call.outputs.conditions.length, config.variable_swap.endpoint_conditions);
    assert.ok(traced.every(({call}) => !call.used_basis.some(ref => ref.startsWith('method-interval-extremum'))));
    const rootRefs = new Set(result.graph_paths[route].filter(path => path.method === 'method-variable-swap').map(path => path.skill));
    for (const ref of ['skill-simplify', 'skill-quantified-range', 'skill-linear-range', 'skill-inequality-transform', 'quadratic-inequality-solve']) assert.ok(rootRefs.has(ref));
    assert.deepEqual(completed.checkpoints.find(item => item.route_id === route).driver_state.feasible_set_exact, config.gold.feasible_set_exact);
    const boundaries = trajectory.finalization.map((call, index) => ({call, index})).filter(({call}) => call.capability === 'endpoint_check');
    assert.equal(boundaries.length, 1);
    const {call, index} = boundaries[0];
    assert.ok(checked(call)); assert.equal(call.public_ref, null); assert.equal(call.outputs.status, 'passed');
    assert.deepEqual(call.outputs.points.map(point => point.point.expression), config.gold.boundary_points);
    assert.ok(call.outputs.points.every(point => point.included === false && point.holds === false && point.passed));
    assert.equal(cards.at(-1).display_unit, 'boundary'); assert.deepEqual(cards.at(-1).source_refs, [`/finalization/${index}`]);
    assert.ok(call.used_basis.includes('function-range-extrema#attainability'));
    assert.ok(paused.math_steps.every(card => card.display_unit !== 'boundary'));
    result.variable_swap = {gold_source: config.gold.source, exact_answer_matches_gold: true, boundary_points: call.outputs.points};
  }
  if (config.goal_extremum) {
    assert.ok(paused.math_steps.every(card => !['boundary', 'goal_finalization'].includes(card.display_unit)));
    assert.equal(config.provenance.kind, 'real_recorded_image_and_review');
    assert.equal(config.provenance.historical_semantic_calls, 2); assert.equal(config.provenance.historical_network_attempts, 2);
    assert.equal(config.provenance.new_semantic_calls, 0); assert.equal(config.provenance.new_network_attempts, 0);
    assert.ok(Object.keys(config.provenance.retained_files_sha256).length > 2);
    result.goal_finalization = config.routes.map(id => {
      const checkpoint = completed.checkpoints.find(item => item.route_id === id), execution = trajectoryFor(completed, id);
      const handoff = completed.handoffs.find(item => item.route_id === id), steps = completed.math_steps.filter(card => card.route_id === id);
      assert.deepEqual(execution.constraint_context.goal, config.gold.goal);
      assert.deepEqual(checkpoint.driver_state.feasible_set_exact, config.gold.feasible_set_exact);
      assert.deepEqual(handoff.answer, config.gold.answer);
      const finalizations = execution.finalization.map((call, index) => ({call, index}));
      const boundaries = finalizations.filter(({call}) => call.capability === 'endpoint_check');
      const closures = finalizations.filter(({call}) => call.capability === 'finalize_goal');
      assert.equal(boundaries.length, 1); assert.equal(closures.length, 1);
      const boundary = boundaries[0], closure = closures[0];
      assert.ok(checked(boundary.call)); assert.ok(checked(closure.call));
      assert.equal(boundary.call.outputs.status, 'passed');
      assert.deepEqual(boundary.call.outputs.points.map(point => point.point.expression), config.gold.boundary_points);
      assert.ok(boundary.call.outputs.points.every(point => point.included && point.holds && point.passed));
      assert.equal(closure.call.public_ref, null); assert.deepEqual(closure.call.answer, config.gold.answer);
      assert.deepEqual(closure.call.outputs.answer, config.gold.answer); assert.ok(closure.call.operations.includes('goal_finalization'));
      const proof = closure.call.outputs.evidence;
      assert.equal(proof.kind, 'goal_closure'); assert.equal(proof.goal_kind, config.goal_extremum.kind);
      assert.equal(proof.status, config.goal_extremum.status); assert.equal(proof.direction, 'lower');
      assert.equal(proof.empty, false); assert.equal(proof.bounded, true); assert.equal(proof.member, true); assert.equal(proof.attained, true);
      assert.deepEqual(proof.feasible_set.exact, config.gold.feasible_set_exact); assert.deepEqual(proof.bound, config.gold.answer.value);
      assert.ok(proof.checks.length && proof.checks.every(check => check.passed === true));
      assert.ok(proof.checks.some(check => check.kind === 'goal_answer_matches_feasible_set'));
      assert.equal(steps.filter(card => card.display_unit === 'goal_finalization').length, 1);
      const goalCard = steps.at(-1), boundaryCard = steps.at(-2);
      assert.equal(goalCard.display_unit, 'goal_finalization'); assert.equal(goalCard.title, '确定最小值');
      assert.equal(boundaryCard.display_unit, 'boundary'); assert.deepEqual(boundaryCard.source_refs, [`/finalization/${boundary.index}`]);
      assert.deepEqual(goalCard.source_refs, [`/finalization/${closure.index}`]);
      assert.deepEqual(goalCard.before[0].exact, config.gold.feasible_set_exact); assert.deepEqual(goalCard.after[0].exact, config.gold.answer.value.exact);
      assert.ok(goalCard.used_basis.includes('function-range-extrema#attainability'));
      return {route: id, answer: handoff.answer, proof, closure_step_id: goalCard.step_id};
    });
  }
  return result;
}

export async function runAcceptance(args = process.argv.slice(2)) {
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const [origin, output, searchId, configPath] = args;
const config = configPath ? JSON.parse(fs.readFileSync(configPath, 'utf8')) : {
  case: 'q01', routes: ['discriminant', 'extremum'], prefix_cards: 4, completed_cards: 10, qa_cards: 5,
};
assert.ok(config.routes.length >= 1 && config.routes.length <= 2);
const base = `/api/search/problems/${searchId}`;
const browser = await chromium.launch({headless: true,
  ...(process.env.CHROME_EXECUTABLE ? {executablePath: process.env.CHROME_EXECUTABLE} : {})});
const errors = [];
const evidence = {case: config.case, new_llm_calls: 0, checks: [], websocket_frames: 0, expired_cursors: 0};
let page;
try {
  page = await browser.newPage({viewport: {width: 1380, height: 1000}, reducedMotion: 'reduce'});
  page.on('pageerror', error => errors.push(String(error)));
  page.on('websocket', socket => socket.on('framereceived', () => evidence.websocket_frames++));
  page.on('response', response => { if (response.url().includes('/events') && response.status() === 409) evidence.expired_cursors++; });
  await page.addInitScript(() => {
    localStorage.setItem('gw-graph-mode', '2d');
    const Native = window.WebSocket; window.__testSockets = [];
    window.WebSocket = class extends Native {
      constructor(...args) {
        if (window.__blockTestSockets) throw new Error('constructed disconnect');
        super(...args); window.__testSockets.push(this);
      }
    };
  });
  await page.route('**/*', route => new URL(route.request().url()).origin === origin ? route.continue() : route.abort());
  const api = async (path, method = 'GET') => {
    const response = await page.request.fetch(origin + path, {method});
    assert.ok(response.ok(), `${method} ${path}: ${response.status()} ${await response.text()}`);
    return response.json();
  };
  const until = async (read, predicate, message) => {
    const deadline = Date.now() + 60_000;
    while (Date.now() < deadline) {
      const value = await read();
      if (predicate(value)) return value;
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    assert.fail(message);
  };
  const currentBundle = () => page.evaluate(async basePath => {
    const lesson = (await (await fetch(basePath)).json()).lesson;
    const snapshot = await (await fetch(lesson.stream.snapshot_url)).json();
    const {createEventConsumer} = await import('/assets/graph-walk/stage-three-stream.mjs');
    const {extendStreamBundle} = await import('/assets/graph-walk/walk-state.mjs');
    const consumer = createEventConsumer(snapshot); consumer.hydrate(snapshot);
    const graph = await (await fetch('/knowledge/graph.json')).json();
    return extendStreamBundle(lesson.goals[0].walk.bundle, consumer.view(), lesson.goals[0].target_ref, graph);
  }, base);
  const choose = async (decision, supplied) => {
    const component = decision.interaction;
    const expected = supplied ?? (component.type === 'read' ? 'read'
      : component.type === 'multi' ? decision.expected_answer.required
      : ['checklist', 'fill'].includes(component.type) ? decision.expected_answer.terms
      : decision.expected_answer.one_of?.[0]);
    const active = page.locator('#gw-active');
    await active.locator(`#gw-current-title`).waitFor();
    if (component.type === 'choice') {
      await active.locator(`[data-choice][data-value=${JSON.stringify(expected)}]`).click();
    } else if (component.type === 'multi') {
      for (const value of expected) await active.locator(`[data-multi=${JSON.stringify(value)}]`).click();
    } else if (component.type === 'checklist') {
      for (const [slot, value] of expected.entries()) {
        await active.locator(`[data-pair-answer="${slot}"][data-value=${JSON.stringify(value)}]`).click();
      }
    } else if (component.type === 'fill') {
      for (const [slot, value] of expected.entries()) {
        await active.locator(`[data-slot="${slot}"]`).click();
        await active.locator(`[data-token=${JSON.stringify(value)}]`).click();
      }
    } else if (component.type === 'plane') {
      await active.locator(`[data-plane-cell=${JSON.stringify(expected.slice(0, 2).join('|'))}]`).click();
      await active.locator(`[data-plane-method=${JSON.stringify(expected[2])}]`).click();
    } else if (component.type !== 'read') assert.fail(`Unhandled component: ${component.type}`);
  };
  let graphSnapshot = null, bundle;
  const assertGraph = async selectedRoute => {
    if (!graphSnapshot) return;
    const paths = graphEvidence(graphSnapshot, selectedRoute);
    const completedIds = new Set(await page.locator('[data-completed-decision]').evaluateAll(nodes => nodes.map(node => node.dataset.completedDecision)));
    const finished = new Set(bundle.routes[selectedRoute].steps.filter(decision => decision.stream_last_part && completedIds.has(decision.id))
      .flatMap(decision => decision.stream_steps.map(step => step.step_id)));
    const edges = new Map();
    for (const path of paths) for (const edge of path.edges) edges.set(edge, edges.get(edge) || path.step_ids.some(id => finished.has(id)));
    await page.waitForFunction(rows => rows.every(([edge, chosen]) => [...document.querySelectorAll('[data-edge]')]
      .some(node => node.dataset.edge === edge && node.dataset.state === (chosen ? 'chosen' : 'idle'))), [...edges]);
    for (const path of paths.filter(path => path.rule)) assert.equal(await page.locator(
      `[data-edge=${JSON.stringify(`${path.method}|calls|${path.skill}`)}]`).count(), 0, 'rule-selected calls cannot invent direct edges');
    if (selectedRoute === route && config.internal_basis) {
      const [node, anchor] = config.internal_basis.ref.split('#');
      const href = `/knowledge/${encodeURIComponent(node)}/${anchor ? '#' + encodeURIComponent(anchor) : ''}`;
      const reached = graphSnapshot.math_steps.filter(card => card.route_id === route && card.ordinal >= config.internal_basis.read_cards)
        .some(card => finished.has(card.step_id));
      assert.equal(await page.locator(`#gw-used a[href=${JSON.stringify(href)}]`).count(), reached ? 1 : 0);
    }
  };
  // Server-built pictures must reach the page as drawn SVG, beside the question or the finished card.
  const pictures = {stem: 0, options: 0, completion: 0, hollow_options: 0};
  const assertPictures = async decision => {
    if (decision.source !== 'stream') return;
    if (decision.graph) {
      await page.locator('#gw-active .gw-stem-graph svg').first().waitFor();
      if (!pictures.stem++) await page.locator('#gw-active').screenshot({path: `${output}/07-stem-graph.png`});
    }
    const drawn = (decision.interaction.options || []).filter(option => option.graph?.kind);
    if (drawn.length) {
      assert.equal(await page.locator('#gw-active .gw-graph-figure svg').count(), drawn.length);
      if (drawn.some(option => option.graph.params.points?.some(point => point.open))) {
        assert.ok(await page.locator('#gw-active .gw-graph-figure circle.quadratic-point[fill="#fff"]').count() > 0);
        pictures.hollow_options++;
      }
      if (!pictures.options++) await page.locator('#gw-active').screenshot({path: `${output}/05-graph-options.png`});
    }
  };
  const assertCompletionPicture = async decision => {
    if (decision.source !== 'stream' || !decision.completion_graph) return;
    const card = page.locator(`[data-completed-decision=${JSON.stringify(decision.id)}]`);
    assert.equal(await card.locator('.gw-completion-graph svg').count(), 1);
    if (!pictures.completion++) {
      await card.evaluate(node => { node.open = true; });
      await card.screenshot({path: `${output}/06-completion-graph.png`});
    }
  };
  const submit = async (decision, supplied) => {
    await page.locator(`#gw-active[data-decision-id=${JSON.stringify(decision.id)}]`).waitFor();
    await assertPictures(decision);
    await choose(decision, supplied);
    await page.locator('#gw-submit').click();
    await page.locator(`[data-completed-decision=${JSON.stringify(decision.id)}]`).waitFor();
    await assertCompletionPicture(decision);
    if (decision.source === 'stream') await assertGraph(await page.locator('[data-stream-route][aria-pressed="true"]').count()
      ? await page.locator('[data-stream-route][aria-pressed="true"]').getAttribute('data-stream-route') : route);
  };
  const [route, alternate] = config.routes;
  await api(base + '/lesson/start', 'POST');
  await page.goto(`${origin}/lab/search/problem.html?search=${searchId}`);
  await page.locator('[data-actor="student"]').click();
  await until(() => api(base), value => Boolean(value.lesson?.stream), 'run identity must be published before reading its ledger');
  const paused = await until(() => api('/test/state'), value => value.paused.includes(route) &&
    value.snapshot.interaction_states.length > 0 &&
    value.snapshot.interaction_states.every(row => row.status !== 'pending'), 'first route exercises must arrive');
  graphSnapshot = paused.snapshot;
  bundle = await currentBundle();
  for (const decision of bundle.intro) {
    const answer = decision.id === 'D3'
      ? [...decision.expected_answer.cell, decision.interaction.methods.find(method => method.route === route).value]
      : decision.id === 'D4' ? route : undefined;
    await submit(decision, answer);
  }
  const first = bundle.routes[route].steps[0];
  assert.ok(first, 'the first committed card needs an interactive or read decision');
  await page.locator(`#gw-active[data-decision-id=${JSON.stringify(first.id)}]`).waitFor();
  if (first.interaction.type !== 'read') {
    assert.equal(await page.locator('#gw-active .stage-three-after').count(), 0);
    assert.equal(await page.locator('#gw-active .stage-three-explanation').count(), 0);
  }
  const firstCard = paused.snapshot.math_steps.find(card => card.step_id === first.stream_steps[0].step_id);
  assert.ok(firstCard, 'the first exercise must refer to its committed mathematics card');
  assert.equal(await page.locator('#gw-active .stage-three-before').count() > 0, firstCard.before.length > 0);
  await assertPictures(first);
  await choose(first);
  const selectedDraft = () => page.locator('#gw-active [aria-pressed="true"], #gw-active [data-slot]').evaluateAll(nodes => nodes.map(node =>
    ({value: node.dataset.value || node.dataset.multi, text: node.textContent})));
  const originalDraft = await selectedDraft();
  await page.screenshot({path: `${output}/01-question-draft.png`, fullPage: true});
  await page.reload();
  await page.locator(`#gw-active[data-decision-id=${JSON.stringify(first.id)}]`).waitFor();
  assert.deepEqual(await selectedDraft(), originalDraft);
  evidence.checks.push('student draft and active decision survive page refresh');
  await page.locator('#gw-submit').click();
  await page.locator(`[data-completed-decision=${JSON.stringify(first.id)}]`).waitFor();
  await assertGraph(route);
  let prefix = await currentBundle();
  for (const decision of prefix.routes[route].steps.slice(1)) {
    await submit(decision);
    if (!decision.stream_last_part) {
      assert.equal(await page.locator(`[data-completed-decision=${JSON.stringify(decision.id)}] .stage-three-math-step`).count(), 0);
    }
  }
  await page.getByText('正在准备这一步的练习', {exact: false}).first().waitFor();
  assert.equal(await page.locator('.stage-three-completion:visible').count(), 0);
  evidence.checks.push('ordered pending barrier, before-only questions, last-part-only completed cards');
  await page.screenshot({path: `${output}/02-waiting.png`, fullPage: true});
  // Metadata-only interruption must be noticed without new math events or an
  // automatic resume. This changes test responses, not the paused worker.
  const metadataUrl = origin + base, resumeUrl = `${origin}${base}/lesson/${paused.snapshot.run_id}/resume`;
  let executionStatus = 'interrupted', resumeRequests = 0;
  await page.route(metadataUrl, async request => {
    const response = await request.fetch(), payload = await response.json();
    payload.lesson.execution_status = executionStatus;
    await request.fulfill({response, json: payload});
  });
  await page.route(resumeUrl, async request => {
    assert.equal(request.request().method(), 'POST'); resumeRequests++; executionStatus = 'running';
    await request.fulfill({json: {status: 'running'}});
  });
  await page.locator('#pq-stream-action').filter({hasText: '继续计算'}).waitFor({state: 'visible', timeout: 15000});
  assert.equal(resumeRequests, 0);
  assert.equal((await api('/test/state')).snapshot.last_seq, paused.snapshot.last_seq);
  await page.locator('#pq-stream-action').click();
  await page.waitForFunction(() => !document.querySelector('#pq-stream-action').disabled);
  assert.equal(resumeRequests, 1);
  await page.unroute(metadataUrl); await page.unroute(resumeUrl);
  evidence.checks.push('metadata-only interruption requires explicit resume without losing progress');
  for (const id of config.routes) await api(`/test/release/${id}`, 'POST');
  const completed = await until(() => api('/test/state'), value =>
    config.routes.every(id => value.snapshot.checkpoints.some(cp => cp.route_id === id && cp.status === 'verified') &&
      value.snapshot.handoffs.some(handoff => handoff.route_id === id && handoff.available)) &&
    value.snapshot.interaction_states.every(row => row.status !== 'pending'), 'all math and interaction work must finish');
  assert.equal(completed.llm_provider_attempts, 0);
  Object.assign(evidence, verifyMathematics(config, paused.snapshot, completed.snapshot));
  graphSnapshot = completed.snapshot;
  bundle = await currentBundle();
  for (const decision of bundle.routes[route].steps.slice(prefix.routes[route].steps.length)) await submit(decision);
  await page.locator('.stage-three-completion:visible').waitFor();
  evidence.checks.push('late interaction replaces waiting card and completed mathematics enables completion');
  // A separately delivered QA must only attach an aside, preserving the finished card DOM.
  await page.evaluate(() => {
    window.savedMath = [...document.querySelectorAll('.stage-three-math-step')];
    for (const details of document.querySelectorAll('details.gw-completed')) details.open = true;
  });
  const pollPattern = '**/lesson/*/events?*';
  await page.route(pollPattern, request => request.abort());
  await page.evaluate(() => { window.__blockTestSockets = true; for (const socket of window.__testSockets) socket.close(); });
  await api('/test/qa/partial', 'POST');
  await api('/test/prune', 'POST');
  await page.unroute(pollPattern);
  await page.waitForFunction(() => [...document.querySelectorAll('.stage-three-qa')].some(node => !node.hidden));
  assert.ok(evidence.expired_cursors >= 1, 'expired event cursor restores a fresh snapshot');
  assert.ok(evidence.websocket_frames >= 1, 'the real WebSocket delivered initial events');
  await api('/test/qa/completed', 'POST');
  await page.waitForFunction(() => [...document.querySelectorAll('.stage-three-qa')].some(node => !node.hidden));
  assert.ok(await page.evaluate(() => window.savedMath.every(node => node.isConnected &&
    node === document.querySelector(`.stage-three-math-step[data-step-id="${node.dataset.stepId}"]`))));
  evidence.checks.push('late QA attaches without replacing completed mathematical DOM');
  await page.screenshot({path: `${output}/03-completed-qa.png`, fullPage: true});
  const beforeUndo = await page.locator('[data-completed-decision]').count();
  await page.locator('#gw-undo').click();
  assert.equal(await page.locator('[data-completed-decision]').count(), beforeUndo - 1);
  await assertGraph(route);
  await submit(bundle.routes[route].steps.at(-1));
  if (alternate) {
    await page.locator(`#gw-completion [data-route=${JSON.stringify(alternate)}]`).click();
    const other = bundle.routes[alternate].steps[0];
    await page.locator(`#gw-active[data-decision-id=${JSON.stringify(other.id)}]`).waitFor();
    await choose(other);
    await page.locator(`#gw-steps [data-stream-route=${JSON.stringify(route)}]`).click();
    await page.locator('.stage-three-completion:visible').waitFor();
    await page.locator(`#gw-completion [data-route=${JSON.stringify(alternate)}]`).click();
    await page.locator(`#gw-active[data-decision-id=${JSON.stringify(other.id)}]`).waitFor();
    if (other.interaction.type === 'choice') assert.equal(
      await page.locator('#gw-active [data-choice][aria-pressed="true"]').getAttribute('data-value'),
      other.expected_answer.one_of[0]);
    evidence.checks.push('route switch restores completed work and unsubmitted draft independently');
  }
  await page.locator('#gw-ai').click();
  await page.locator('.stage-three-completion:visible').waitFor({timeout: 60_000});
  await page.locator('#gw-student').click();
  if (alternate) await page.locator(`#gw-active[data-decision-id=${JSON.stringify(bundle.routes[alternate].steps[0].id)}]`).waitFor();
  evidence.checks.push('AI playback completes independently without advancing student work');
  await page.reload();
  if (alternate) await page.locator(`#gw-active[data-decision-id=${JSON.stringify(bundle.routes[alternate].steps[0].id)}]`).waitFor();
  evidence.checks.push('selected route and actor restored on refresh');
  await page.screenshot({path: `${output}/04-restored-route.png`, fullPage: true});
  // Complete the alternate route through the same student decisions, checking
  // graph sources after each final part rather than an obsolete reading cursor.
  if (alternate) {
    await assertGraph(alternate);
    for (const decision of bundle.routes[alternate].steps) await submit(decision);
    await page.locator('.stage-three-completion:visible').waitFor();
  }
  evidence.checks.push('every route completed by student decisions; graph paths follow completed source cards and undo');
  evidence.pictures = pictures;
  if (config.pictures) for (const [kind, least] of Object.entries(config.pictures)) {
    assert.ok(pictures[kind] >= least, `${kind} pictures: ${pictures[kind]} < ${least}`);
  }
  if (Object.values(pictures).some(Boolean)) evidence.checks.push('stem, option and completion pictures drawn from server specs');
  assert.equal(await page.locator('.katex-error').count(), 0);
  assert.deepEqual(errors, []);
  const final = await api('/test/state');
  assert.deepEqual(final.snapshot.math_steps, completed.snapshot.math_steps);
  assert.equal(final.stage_two_attempts, 1);
  await api('/test/invalidate', 'POST');
  await page.getByText('此路线暂不可用', {exact: true}).waitFor();
  assert.equal(await page.locator('.stage-three-completion:visible').count(), 0);
  assert.equal(await page.locator('.stage-three-qa:visible').count(), 0);
  assert.deepEqual((await api('/test/state')).snapshot.math_steps, completed.snapshot.math_steps);
  evidence.checks.push('goal revocation hides completion and QA without changing mathematical records');
  evidence.browser_errors = errors;
  fs.writeFileSync(`${output}/browser-evidence.json`, JSON.stringify(evidence, null, 2));
} catch (error) {
  evidence.browser_errors = errors; evidence.failure = String(error);
  fs.writeFileSync(`${output}/browser-evidence.json`, JSON.stringify(evidence, null, 2));
  if (page) {
    await page.screenshot({path: `${output}/failure.png`, fullPage: true});
    fs.writeFileSync(`${output}/failure.html`, await page.content());
  }
  throw error;
} finally {
  await browser.close();
}
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) await runAcceptance();
