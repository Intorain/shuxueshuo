// Offline acceptance for the actual photo-search page and its HTTP/WS adapter.
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import fs from 'node:fs';
const require = createRequire(import.meta.url);
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const [origin, output, searchId, configPath] = process.argv.slice(2);
const config = configPath ? JSON.parse(fs.readFileSync(configPath, 'utf8')) : {
  case: 'q01', routes: ['discriminant', 'extremum'], prefix_cards: 4, completed_cards: 10, qa_cards: 5,
};
assert.ok(config.routes.length >= 1 && config.routes.length <= 2, 'acceptance supports one or two actual routes');
const [firstRoute, secondRoute] = config.routes;
const base = `/api/search/problems/${searchId}`;
const browser = await chromium.launch({headless: true,
  ...(process.env.CHROME_EXECUTABLE ? {executablePath: process.env.CHROME_EXECUTABLE} : {})});
try {
  const page = await browser.newPage({viewport: {width: 1380, height: 1000}, reducedMotion: 'reduce'});
  const errors = [], events = {websocket_frames: 0, expired_cursors: 0, snapshots: 0};
  page.on('pageerror', error => errors.push(String(error)));
  page.on('websocket', ws => ws.on('framereceived', () => { events.websocket_frames += 1; }));
  page.on('response', response => {
    if (response.url().includes('/snapshot')) events.snapshots += 1;
    if (response.url().includes('/events') && response.status() === 409) events.expired_cursors += 1;
  });
  await page.addInitScript(() => {
    // Stable inspectable SVG evidence in this isolated acceptance context.
    localStorage.setItem('gw-graph-mode', '2d');
    const Native = window.WebSocket;
    window.__testSockets = [];
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
  const waitState = async (predicate, message) => {
    const deadline = Date.now() + 30_000;
    while (Date.now() < deadline) {
      const state = await api('/test/state');
      if (predicate(state)) return state;
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    assert.fail(message);
  };
  const checked = call => call.postconditions?.length && call.postconditions.every(item => item.passed === true);
  const trajectoryFor = (snapshot, route) => {
    const checkpoint = snapshot.checkpoints.find(item => item.route_id === route);
    assert.ok(checkpoint?.driver_state?.trajectory, `missing durable trajectory for ${route}`);
    return checkpoint.driver_state.trajectory;
  };
  const callsFor = trajectory => trajectory.steps.flatMap((record, stepIndex) =>
    record.calls.filter(checked).map(call => ({record, call,
      source_ref: `/steps/${stepIndex}/calls/${record.calls.indexOf(call)}`})));
  const cardForCall = (snapshot, route, source) => {
    const cards = snapshot.math_steps.filter(card => card.route_id === route && card.source_refs.includes(source));
    assert.equal(cards.length, 1, `checked call ${route}:${source} must belong to one visible mathematical card`);
    return cards[0];
  };
  const collectRulePaths = (snapshot, route) => {
    const grouped = new Map();
    for (const {record, call, source_ref} of callsFor(trajectoryFor(snapshot, route)).filter(item => item.call.rule_ref)) {
      const card = cardForCall(snapshot, route, source_ref);
      const key = JSON.stringify([record.method, call.rule_ref, call.branch, call.public_ref]);
      const path = grouped.get(key) || {method: record.method, rule: call.rule_ref, branch: call.branch,
        skill: call.public_ref, read_cards: card.ordinal, case_paths: [], source_refs: [],
        edges: [`${record.method}|step_rule|${call.rule_ref}`, `${call.rule_ref}|selects|${call.public_ref}`]};
      path.read_cards = Math.min(path.read_cards, card.ordinal);
      path.case_paths.push(record.case_path); path.source_refs.push(source_ref);
      grouped.set(key, path);
    }
    return [...grouped.values()];
  };
  const collectPublicPaths = (snapshot, route) => {
    const paths = [];
    for (const {record, call, source_ref} of callsFor(trajectoryFor(snapshot, route))
      .filter(item => item.call.public_ref && !item.call.rule_ref)) {
      const cards = snapshot.math_steps.filter(card => card.route_id === route &&
        JSON.stringify(card.case_path) === JSON.stringify(record.case_path) && card.source_refs.includes(source_ref));
      assert.ok(cards.length, `public call ${route}:${source_ref} needs a readable source card`);
      // A parent summary may cite a child call again. Activation follows the
      // earliest real readable card, not the later summary or execution time.
      paths.push({method: record.method, step: record.step, capability: call.capability,
        public_ref: call.public_ref, source_ref, step_ids: cards.map(card => card.step_id),
        read_cards: Math.min(...cards.map(card => card.ordinal)),
        edge: `${record.method}|calls|${call.public_ref.split('#')[0]}`});
    }
    return paths;
  };
  const assertPublicPathsAt = async (paths, readCards) => {
    const thresholds = new Map();
    for (const path of paths) thresholds.set(path.edge, Math.min(thresholds.get(path.edge) ?? Infinity, path.read_cards));
    const expected = [...thresholds].map(([edge, ordinal]) => [edge, ordinal <= readCards ? 'chosen' : 'idle']);
    await page.waitForFunction(rows => rows.every(([edge, state]) => [...document.querySelectorAll('[data-edge]')]
      .some(node => node.dataset.edge === edge && node.dataset.state === state)), expected);
    const methods = [...new Set(paths.map(path => path.method))];
    const actual = await page.locator('[data-edge][data-state="chosen"]').evaluateAll((nodes, callers) =>
      nodes.map(node => node.dataset.edge).filter(edge => callers.some(method => edge.startsWith(`${method}|calls|`))), methods);
    assert.deepEqual(actual.sort(), expected.filter(([, state]) => state === 'chosen').map(([edge]) => edge).sort(),
      'chosen public call edges must have checked sources on cards the student has read');
  };
  const assertRulePathsAt = async (paths, readCards) => {
    // The method→rule edge is shared by cases. A later skill branch must stay
    // idle until the first actual source card that invokes that branch is read.
    const thresholds = new Map();
    for (const path of paths) for (const edge of path.edges) {
      thresholds.set(edge, Math.min(thresholds.get(edge) ?? Infinity, path.read_cards));
    }
    const expected = [...thresholds].map(([edge, ordinal]) => [edge, ordinal <= readCards ? 'chosen' : 'idle']);
    await page.waitForFunction(rows => rows.every(([edge, state]) => [...document.querySelectorAll('[data-edge]')]
      .some(node => node.dataset.edge === edge && node.dataset.state === state)), expected);
    for (const path of paths) {
      assert.equal(await page.locator(`[data-edge=${JSON.stringify(`${path.method}|calls|${path.skill}`)}]`).count(), 0,
        'rule-selected skills must not receive synthetic direct method edges');
    }
  };
  const basisLinkFor = ref => {
    const [node, anchor] = ref.split('#');
    const href = `/knowledge/${encodeURIComponent(node)}/${anchor ? '#' + encodeURIComponent(anchor) : ''}`;
    return page.locator(`#gw-used a[href=${JSON.stringify(href)}]`);
  };
  await api(base + '/lesson/start', 'POST');
  await page.goto(`${origin}/lab/search/problem.html?search=${searchId}`);
  await page.locator('[data-actor="replay"]').click();
  await page.waitForFunction(expected => document.querySelectorAll('.stage-three-math-step').length >= expected, config.prefix_cards ?? 1);
  await page.waitForFunction(() => [...document.querySelectorAll('.stage-three-math-step')].some(node => node.getClientRects().length));
  const paused = (await waitState(state => state.paused.includes(firstRoute),
    'the first route must reach its verification barrier before the interruption probe')).snapshot;
  const prefixCards = paused.math_steps.length;
  assert.ok(prefixCards > 0, 'actual mathematical cards are committed before independent finalization');
  if (config.prefix_cards !== undefined) assert.equal(prefixCards, config.prefix_cards);
  await page.waitForFunction(expected => document.querySelectorAll('.stage-three-math-step').length === expected, prefixCards);
  assert.ok(paused.math_steps.every(card => card.local_check === 'passed'));
  if (config.variable_swap) {
    assert.ok(paused.math_steps.every(card => card.route_id === firstRoute && card.display_unit !== 'boundary'));
    assert.ok(!(trajectoryFor(paused, firstRoute).finalization || []).some(call => call.capability === 'endpoint_check'));
  }
  if (config.goal_extremum) {
    assert.ok(paused.math_steps.every(card => !['boundary', 'goal_finalization'].includes(card.display_unit)),
      'independent boundary and goal conclusion must remain absent before verification');
    assert.ok(!(trajectoryFor(paused, firstRoute).finalization || [])
      .some(call => ['endpoint_check', 'finalize_goal'].includes(call.capability)));
    assert.equal(config.provenance.kind, 'real_recorded_image_and_review');
    assert.equal(config.provenance.historical_semantic_calls, 2);
    assert.equal(config.provenance.historical_network_attempts, 2);
    assert.equal(config.provenance.new_semantic_calls, 0);
    assert.equal(config.provenance.new_network_attempts, 0);
    assert.ok(Object.keys(config.provenance.retained_files_sha256).length > 2,
      'raw image extraction/review and revalidation receipts must remain linked in this artifact');
  }
  assert.equal(paused.handoffs.length, 0);
  assert.equal(await page.locator('.stage-three-completion:visible').count(), 0);
  assert.ok(await page.locator('.stage-three-math-step .katex').count() > 0);
  await page.locator('.stage-three-math-step').first().scrollIntoViewIfNeeded();
  await page.screenshot({path: `${output}/01-running-prefix.png`, fullPage: true});
  console.log(`Verified running prefix: ${prefixCards} mathematical cards before completion.`);
  await page.evaluate(() => {
    window.__firstMathCard = document.querySelector('.stage-three-math-step');
    window.__firstMathBody = [...window.__firstMathCard.children].filter(node => !node.classList.contains('stage-three-qa'));
    window.__prefixMathCards = [...document.querySelectorAll('.stage-three-math-step')].map(node => ({
      node, stepId: node.dataset.stepId, body: [...node.children].filter(child => !child.classList.contains('stage-three-qa')),
    }));
  });

  // A worker can disappear without emitting a terminal event. Construct only
  // that metadata change while the real solver remains behind its barrier;
  // the open page must discover it and offer an explicit, non-blocking resume.
  const metadataUrl = origin + base;
  const resumePath = `${origin}${base}/lesson/${paused.run_id}/resume`;
  let executionStatus = 'interrupted', resumeRequests = 0;
  await page.route(metadataUrl, async route => {
    const upstream = await route.fetch();
    const status = await upstream.json();
    status.lesson.execution_status = executionStatus;
    await route.fulfill({response: upstream, json: status});
  });
  await page.route(resumePath, async route => {
    assert.equal(route.request().method(), 'POST');
    resumeRequests++;
    executionStatus = 'running';
    await route.fulfill({json: {status: 'running'}});
  });
  await page.locator('#pq-stream-action').filter({hasText: '继续计算'}).waitFor({state: 'visible', timeout: 15000});
  assert.equal(resumeRequests, 0, 'status polling must not resume execution automatically');
  assert.equal((await api('/test/state')).snapshot.last_seq, paused.last_seq,
    'the interruption is noticed without any new mathematical event');
  assert.ok(await page.evaluate(() => window.__firstMathCard === document.querySelector('.stage-three-math-step')));
  await page.locator('#pq-stream-action').scrollIntoViewIfNeeded();
  await page.screenshot({path: `${output}/01a-interrupted-prefix.png`, fullPage: true});
  await page.locator('#pq-stream-action').click();
  await page.waitForFunction(() => !document.querySelector('#pq-stream-action').disabled);
  assert.equal(resumeRequests, 1);
  assert.ok(await page.evaluate(() => window.__firstMathCard === document.querySelector('.stage-three-math-step')));
  await page.unroute(metadataUrl);
  await page.unroute(resumePath);
  console.log('Verified interruption detection without new events or page reload, and explicit resume preserves cards.');
  await api(`/test/release/${firstRoute}`, 'POST');
  await page.waitForFunction(() => [...document.querySelectorAll('.stage-three-completion')].filter(node => node.getClientRects().length).length === 1);
  const firstDone = (await api('/test/state')).snapshot;
  assert.equal(firstDone.handoffs.length, 1, 'the first verified route is independently publishable');
  assert.ok(firstDone.handoffs[0].available);

  // Let a committed QA fragment fall beyond this client's cursor, then prune
  // delivery history. HTTP recovery must restore both D3/D4 and the new QA.
  const pollPattern = '**/lesson/*/events?*';
  await page.route(pollPattern, route => route.abort());
  await page.evaluate(() => { window.__blockTestSockets = true; for (const socket of window.__testSockets) socket.close(); });
  await api('/test/qa/partial', 'POST');
  await api('/test/prune', 'POST');
  await page.unroute(pollPattern);
  await page.waitForFunction(() => document.querySelectorAll('.stage-three-qa:not([hidden])').length >= 1);
  assert.ok(events.expired_cursors >= 1, 'stale polling cursor explicitly requests a fresh snapshot');
  assert.ok(events.websocket_frames >= 1, 'initial steps came through the real WebSocket');
  assert.ok(await page.evaluate(() => window.__firstMathCard === document.querySelector('.stage-three-math-step') &&
    window.__firstMathBody.every(node => node.parentNode === window.__firstMathCard)), 'QA recovery preserves mathematical DOM');
  assert.ok(await page.evaluate(() => window.__prefixMathCards.every(({node, stepId, body}) =>
    node === document.querySelector(`.stage-three-math-step[data-step-id="${stepId}"]`) &&
    body.every(child => child.parentNode === node))), 'QA snapshot recovery preserves every existing mathematical card');
  await page.screenshot({path: `${output}/02-first-route-with-qa.png`, fullPage: true});
  console.log('Verified first-route handoff and cursor-expiry QA recovery.');

  if (secondRoute) await api(`/test/release/${secondRoute}`, 'POST');
  const completedState = await waitState(state => state.snapshot.handoffs.length === config.routes.length &&
    state.snapshot.checkpoints.every(checkpoint => checkpoint.status === 'verified'),
  'every actual route must complete its independent verification');
  assert.equal(completedState.llm_provider_attempts, 0);
  let completed = completedState.snapshot;
  const completedCards = completed.math_steps.length;
  const firstRouteCards = completed.math_steps.filter(card => card.route_id === firstRoute);
  const qaCards = firstRouteCards.length;
  if (config.completed_cards !== undefined) assert.equal(completedCards, config.completed_cards);
  if (config.qa_cards !== undefined) assert.equal(qaCards, config.qa_cards);
  await page.waitForFunction(expected => document.querySelectorAll('.stage-three-math-step').length === expected, completedCards);
  await page.waitForFunction(routes => routes.every(route =>
    document.querySelector(`.stage-three-route[data-route-id="${route}"]`)?.dataset.mathStatus === 'verified'), config.routes);
  assert.equal(completed.handoffs.length, config.routes.length);
  assert.deepEqual(firstDone.handoffs[0].math_steps.map(step => step.step_id), firstRouteCards.map(step => step.step_id));
  assert.equal(completed.qa.length, 1);
  assert.ok(completed.checkpoints.every(checkpoint => checkpoint.status === 'verified'));
  const originalIds = completed.math_steps.map(step => step.step_id);
  const originalMathSteps = JSON.stringify(completed.math_steps);
  assert.equal(new Set(originalIds).size, originalIds.length);
  assert.equal(await page.locator('.katex-error').count(), 0);
  await page.evaluate(() => {
    window.__completedMathCards = [...document.querySelectorAll('.stage-three-math-step')].map(node => ({
      node, stepId: node.dataset.stepId, body: [...node.children].filter(child => !child.classList.contains('stage-three-qa')),
    }));
  });

  // Student decisions remain separate from AI playback. Answer D1/D2 from the
  // same recorded contract, then use the actual plane/route UI for D3/D4.
  await page.locator('#gw-student').click();
  const lesson = (await api(base)).lesson;
  for (const decision of lesson.goals[0].walk.bundle.intro.filter(item => !['D3', 'D4'].includes(item.id))) {
    await page.locator('#gw-current-title').filter({hasText: decision.title}).waitFor();
    if (decision.interaction.type === 'checklist') {
      for (const [slot, value] of decision.expected_answer.terms.entries()) {
        await page.locator(`[data-pair-answer="${slot}"][data-value=${JSON.stringify(value)}]`).click();
      }
    } else {
      await page.locator(`[data-choice][data-value=${JSON.stringify(decision.expected_answer.one_of[0])}]`).click();
    }
    await page.locator('#gw-submit').click();
  }
  const d3 = completed.selection_chunks.find(item => item.kind === 'D3').chunk;
  const d4 = completed.selection_chunks.find(item => item.kind === 'D4').chunk;
  assert.deepEqual(d4.options.filter(item => item.route_plan === 'planned').map(item => item.route_id), config.routes);
  const planeMethod = d4.options.find(item => item.route_id === firstRoute).branch;
  await page.locator(`[data-plane-cell=${JSON.stringify(d3.expected_answer.cell.join('|'))}]`).click();
  await page.locator(`[data-plane-method=${JSON.stringify(planeMethod)}]`).click();
  await page.locator('#gw-submit').click();
  // The public bridge may use a confirm button or a route-choice card; the
  // acceptance expects D4 to remain a real student decision in either form.
  await page.locator('#gw-current-title').filter({hasText: '解题路线'}).waitFor();
  await page.locator(`[data-choice][data-value=${JSON.stringify(firstRoute)}]`).click();
  await page.locator('#gw-submit').click();
  await page.waitForFunction(() => [...document.querySelectorAll('.stage-three-math-step')].filter(node => node.getClientRects().length).length === 1);
  assert.equal(await page.locator('.stage-three-math-step:visible').count(), 1,
    'completed computation does not advance the student reading position');
  let rulePaths = [];
  let publicPaths = [];
  if (config.variable_swap) {
    publicPaths = collectPublicPaths(completed, firstRoute);
    const rootRefs = new Set(publicPaths.filter(path => path.method === 'method-variable-swap').map(path => path.public_ref));
    for (const ref of ['skill-simplify', 'skill-quantified-range', 'skill-linear-range',
      'skill-inequality-transform', 'quadratic-inequality-solve']) {
      assert.ok(rootRefs.has(ref), `missing actual variable-route public call ${ref}`);
    }
    await assertPublicPathsAt(publicPaths, 1);
  }
  if (config.internal_basis) {
    rulePaths = collectRulePaths(completed, firstRoute);
    assert.ok(rulePaths.length, 'the interval route must retain its actual rule-selected range calls');
    if (!config.interval_cases) assert.equal(rulePaths.length, 1);
    await assertRulePathsAt(rulePaths, 1);
  }
  await page.locator(`[data-stream-next=${JSON.stringify(firstRoute)}]`).click();
  const studentVisible = await page.locator('.stage-three-math-step:visible').count();
  assert.equal(studentVisible, 2);
  if (rulePaths.length) await assertRulePathsAt(rulePaths, studentVisible);
  if (publicPaths.length) await assertPublicPathsAt(publicPaths, studentVisible);
  const progress = await page.locator('#gw-progress').textContent();
  const readingScroll = await page.locator('.gw-lesson').evaluate(node => node.scrollTop);
  await api('/test/qa/completed', 'POST');
  await page.waitForFunction(route => document.querySelector(`[data-route-id="${route}"]`)?.dataset.enrichmentStatus === 'completed', firstRoute);
  assert.equal(await page.locator('.stage-three-math-step:visible').count(), studentVisible);
  assert.equal(await page.locator('#gw-progress').textContent(), progress, 'QA retry preserves student decisions');
  assert.equal(await page.locator('.gw-lesson').evaluate(node => node.scrollTop), readingScroll, 'QA retry does not jump reading position');
  assert.ok(await page.evaluate(() => window.__firstMathCard === document.querySelector('.stage-three-math-step')));
  assert.ok(await page.evaluate(() => window.__completedMathCards.every(({node, stepId, body}) =>
    node === document.querySelector(`.stage-three-math-step[data-step-id="${stepId}"]`) &&
    body.every(child => child.parentNode === node))), 'constructed QA completion preserves every mathematical DOM body');
  completed = (await api('/test/state')).snapshot;
  assert.equal(JSON.stringify(completed.math_steps), originalMathSteps, 'constructed QA cannot rewrite committed mathematics');
  assert.equal(completed.qa.length, qaCards);
  await page.screenshot({path: `${output}/03-student-reading.png`, fullPage: true});
  console.log('Verified student decisions and two-step reading position survive QA retry.');
  await page.reload();
  // The page should restore the selected actor/part and its saved decisions.
  await page.waitForFunction(expected => document.querySelectorAll('.stage-three-math-step').length === expected, completedCards);
  await page.waitForFunction(expected => [...document.querySelectorAll('.stage-three-math-step')].filter(node => node.getClientRects().length).length === expected, studentVisible);
  assert.equal(await page.locator('.stage-three-math-step:visible').count(), studentVisible);
  assert.equal(await page.locator('#gw-progress').textContent(), progress);
  const restored = await api('/test/state');
  assert.equal(restored.stage_two_attempts, 1);
  assert.equal(restored.snapshot.run_id, completed.run_id);
  assert.deepEqual(restored.snapshot.math_steps.map(step => step.step_id), originalIds);
  assert.equal(restored.snapshot.last_seq, completed.last_seq, 'refresh does not run extraction or solve again');
  if (rulePaths.length) {
    await assertRulePathsAt(rulePaths, studentVisible);
    rulePaths = rulePaths.map(path => ({...path, refresh_restored: true}));
  }
  if (publicPaths.length) await assertPublicPathsAt(publicPaths, studentVisible);
  await page.screenshot({path: `${output}/04-refreshed.png`, fullPage: true});
  console.log('Verified refresh restores the same run, steps and reading position.');
  let internalBasis = null;
  if (config.internal_basis) {
    const basisLink = basisLinkFor(config.internal_basis.ref);
    assert.equal(await basisLink.count(), 0, 'an unread condition card must not light its internal basis');
    while (await page.locator('.stage-three-math-step:visible').count() < config.internal_basis.read_cards) {
      await page.locator(`[data-stream-next=${JSON.stringify(firstRoute)}]`).click();
    }
    await basisLink.waitFor({state: 'attached'});
    internalBasis = {...config.internal_basis, shown_after_reading: true, absent_before_reading: true};
    await page.screenshot({path: `${output}/05-internal-basis.png`, fullPage: true});
    console.log('Verified checked internal-operation basis appears only after reading its condition card.');
  }
  if (rulePaths.length) await assertRulePathsAt(rulePaths, await page.locator('.stage-three-math-step:visible').count());
  let classification = null, separation = null, variableSwap = null, goalFinalization = null;
  if (config.interval_cases) {
    const trajectory = trajectoryFor(completed, firstRoute);
    const cases = trajectory.steps.flatMap(record => record.case_results || []);
    assert.equal(cases.length, config.interval_cases);
    assert.equal(new Set(cases.map(item => JSON.stringify(item.case_path))).size, cases.length);
    assert.ok(cases.every(item => item.case_path.length && item.source_refs.length));
    const firstCards = completed.math_steps.filter(card => card.route_id === firstRoute);
    assert.equal(firstCards.length, qaCards);
    const caseCards = firstCards.filter(card => card.case_path.length);
    assert.ok(cases.every(item => caseCards.some(card => JSON.stringify(card.case_path) === JSON.stringify(item.case_path))),
      'every collected case must have its own student-visible mathematical source');
    let constantCase = null;
    if (config.constant_case) {
      const constants = callsFor(trajectory).filter(({call}) => call.capability === 'linear_range' &&
        call.used_basis.includes('skill-linear-range#constant'));
      assert.equal(constants.length, 1);
      const {record, call, source_ref} = constants[0];
      const item = cases.find(value => JSON.stringify(value.case_path) === JSON.stringify(record.case_path));
      assert.equal(item?.domain.exact.$math, 'FiniteSet');
      assert.deepEqual(item.domain.exact.args, [{$math: 'Integer', value: '0'}]);
      assert.equal(call.inputs.expression.expression, '-1');
      assert.equal(call.outputs.range.inf.expression, '-1');
      assert.equal(call.outputs.range.sup.expression, '-1');
      const card = cardForCall(completed, firstRoute, source_ref);
      constantCase = {case_path: record.case_path, source_ref, step_id: card.step_id,
        domain: item.domain, expression: '-1', basis: 'skill-linear-range#constant'};
    }
    while (await page.locator('.stage-three-math-step:visible').count() < firstCards.length) {
      await page.locator(`[data-stream-next=${JSON.stringify(firstRoute)}]`).click();
      await assertRulePathsAt(rulePaths, await page.locator('.stage-three-math-step:visible').count());
    }
    for (const card of caseCards) {
      const shown = page.locator(`.stage-three-math-step[data-step-id=${JSON.stringify(card.step_id)}]`);
      await shown.waitFor({state: 'visible'});
      assert.ok(await shown.locator('.katex').count() > 0);
    }
    if (constantCase) await basisLinkFor(constantCase.basis).waitFor({state: 'attached'});
    classification = {case_count: cases.length, distinct_case_paths: cases.map(item => item.case_path),
      conditions: cases.map(item => item.condition), case_cards: caseCards.map(card => card.step_id),
      constant_case: constantCase, all_cases_read: true, branch_paths_follow_actual_reading: true};
    await page.screenshot({path: `${output}/06-interval-cases.png`, fullPage: true});
    console.log(`Verified ${cases.length} real case frames, their cards, and per-branch graph activation.`);
  }
  if (rulePaths.length) {
    for (const path of rulePaths) {
      assert.equal(await page.locator(`[data-node=${JSON.stringify(path.rule)}]`).getAttribute('data-state'), 'confirmed');
    }
    rulePaths = rulePaths.map(path => ({...path, absent_before_reading: true,
      chosen_after_reading: true, no_synthetic_edge: true}));
  }
  if (config.separation) {
    const traced = callsFor(trajectoryFor(completed, secondRoute));
    const divisions = traced.filter(({call}) => call.capability === 'separation_division');
    const ranges = traced.filter(({call}) => call.capability === config.separation.range_capability);
    assert.equal(divisions.length, 1); assert.equal(ranges.length, 1);
    const division = divisions[0], range = ranges[0];
    assert.equal(division.call.outputs.divisor_sign, config.separation.division);
    assert.equal(division.call.outputs.transformation, `${config.separation.division}_division`);
    assert.ok(division.call.operations.includes(`multiply_${config.separation.division}`));
    if (config.separation.division === 'negative') {
      assert.ok(division.call.postconditions.some(item => item.kind === 'strict_negative_divisor' && item.passed));
      assert.equal(division.call.outputs.operator, '<=');
    } else {
      assert.equal(range.call.outputs.range.inf.expression, '1/6');
      assert.equal(range.call.outputs.range.sup.expression, '1/2');
      assert.ok(range.call.outputs.range.inf_attained && range.call.outputs.range.sup_attained);
    }
    for (const basis of config.separation.basis) assert.ok(range.call.used_basis.includes(basis));
    const divisionCard = cardForCall(completed, secondRoute, division.source_ref);
    const rangeCard = cardForCall(completed, secondRoute, range.source_ref);
    assert.equal(rangeCard.display_unit, config.separation.range_unit);
    await page.locator(`[data-stream-route=${JSON.stringify(secondRoute)}]`).click();
    await page.waitForFunction(route => [...document.querySelectorAll('.stage-three-route')]
      .some(node => node.dataset.routeId === route && node.getClientRects().length), secondRoute);
    assert.equal(await page.locator('.stage-three-math-step:visible').count(), 1);
    for (const basis of config.separation.basis) {
      assert.equal(await basisLinkFor(basis).count(), 0, 'an unread range must not activate its later knowledge basis');
    }
    while (await page.locator('.stage-three-math-step:visible').count() < rangeCard.ordinal) {
      await page.locator(`[data-stream-next=${JSON.stringify(secondRoute)}]`).click();
    }
    for (const basis of config.separation.basis) await basisLinkFor(basis).waitFor({state: 'attached'});
    const directEdge = `${range.record.method}|calls|${range.call.public_ref.split('#')[0]}`;
    await page.waitForFunction(edge => [...document.querySelectorAll('[data-edge]')]
      .some(node => node.dataset.edge === edge && node.dataset.state === 'chosen'), directEdge);
    await page.locator(`.stage-three-math-step[data-step-id=${JSON.stringify(rangeCard.step_id)}]`).waitFor({state: 'visible'});
    separation = {division: config.separation.division, division_source: division.source_ref,
      division_step_id: divisionCard.step_id, range_source: range.source_ref, range_step_id: rangeCard.step_id,
      range_capability: range.call.capability, range: range.call.outputs.range,
      basis: config.separation.basis, absent_before_range_reading: true, actual_direct_edge: directEdge};
    await page.screenshot({path: `${output}/07-separation-range.png`, fullPage: true});
    console.log('Verified actual division direction, range card and checked knowledge sources on the second route.');
  }
  if (config.variable_swap) {
    const trajectory = trajectoryFor(completed, firstRoute);
    const traced = callsFor(trajectory);
    const rangeCalls = traced.filter(({call}) => call.capability === 'parameter_linear_range');
    assert.equal(rangeCalls.length, 1);
    const range = rangeCalls[0];
    assert.equal(range.call.outputs.slope_sign, config.variable_swap.slope_sign);
    assert.equal(range.call.outputs.endpoint_mode, config.variable_swap.endpoint_mode);
    const applied = traced.filter(({call, record}) => call.capability === 'apply_quantifier_policy' &&
      record.method === 'method-variable-swap');
    // Root role/quantifier/range/combination evidence stays independent of how
    // many child-method cards are needed to solve the endpoint inequalities.
    assert.equal(applied.length, 1);
    assert.equal(applied[0].call.public_ref, null);
    assert.equal(applied[0].call.outputs.combiner, 'all');
    assert.equal(applied[0].call.outputs.conditions.length, config.variable_swap.endpoint_conditions);
    assert.ok(traced.every(({call}) => !call.used_basis.some(ref => ref.startsWith('method-interval-extremum'))),
      'variable-route computation must not acquire another method basis from a shared implementation');
    const checkpoint = completed.checkpoints.find(item => item.route_id === firstRoute);
    assert.deepEqual(checkpoint.driver_state.feasible_set_exact, config.gold.feasible_set_exact,
      'the final exact set must equal the independently authored gold');
    const boundaries = trajectory.finalization.map((call, index) => ({call, index}))
      .filter(({call}) => call.capability === 'endpoint_check');
    assert.equal(boundaries.length, 1);
    const boundary = boundaries[0];
    assert.ok(checked(boundary.call));
    assert.equal(boundary.call.public_ref, null);
    assert.equal(boundary.call.outputs.status, 'passed');
    assert.deepEqual(boundary.call.outputs.points.map(point => point.point.expression), config.gold.boundary_points);
    assert.ok(boundary.call.outputs.points.every(point => point.included === false && point.holds === false && point.passed));
    const boundaryCards = firstRouteCards.filter(card => card.display_unit === 'boundary');
    assert.equal(boundaryCards.length, 1);
    const boundaryCard = boundaryCards[0];
    assert.ok(completedCards > prefixCards, 'independent finalization adds its boundary card after the running prefix');
    assert.deepEqual(completed.math_steps.slice(0, prefixCards), paused.math_steps,
      'verification preserves every mathematical card committed before the barrier');
    assert.equal(boundaryCard.ordinal, Math.max(...firstRouteCards.map(card => card.ordinal)));
    assert.deepEqual(boundaryCard.source_refs, [`/finalization/${boundary.index}`]);
    assert.ok(boundary.call.used_basis.includes('function-range-extrema#attainability'));
    assert.equal(await basisLinkFor('function-range-extrema#attainability').count(), 0,
      'independent boundary basis stays absent until the boundary card is read');
    while (await page.locator('.stage-three-math-step:visible').count() < firstRouteCards.length) {
      await page.locator(`[data-stream-next=${JSON.stringify(firstRoute)}]`).click();
      await assertPublicPathsAt(publicPaths, await page.locator('.stage-three-math-step:visible').count());
    }
    for (const card of firstRouteCards) {
      await page.locator(`.stage-three-math-step[data-step-id=${JSON.stringify(card.step_id)}]`).waitFor({state: 'visible'});
    }
    await basisLinkFor('function-range-extrema#attainability').waitFor({state: 'attached'});
    assert.equal(await page.locator('.stage-three-completion:visible').count(), 1);
    assert.ok(await page.locator(`.stage-three-math-step[data-step-id=${JSON.stringify(boundaryCard.step_id)}] .katex`).count() > 0);
    publicPaths = publicPaths.map(path => ({...path, activation_follows_reading: true, refresh_restored: true}));
    variableSwap = {slope_sign: range.call.outputs.slope_sign, endpoint_mode: range.call.outputs.endpoint_mode,
      slope: range.call.outputs.slope, range_source: range.source_ref,
      combiner: applied[0].call.outputs.combiner, endpoint_conditions: applied[0].call.outputs.conditions,
      public_paths: publicPaths, gold_source: config.gold.source, exact_answer_matches_gold: true,
      boundary_source: `/finalization/${boundary.index}`, boundary_step_id: boundaryCard.step_id,
      boundary_points: boundary.call.outputs.points, boundary_after_verification: true,
      actual_prefix_cards: prefixCards, actual_completed_cards: firstRouteCards.length, all_actual_cards_read: true};
    await page.screenshot({path: `${output}/08-variable-sources.png`, fullPage: true});
    console.log('Verified variable-route public sources, reading-dependent graph activation, exact gold and independent boundaries.');
  }
  if (config.goal_extremum) {
    goalFinalization = [];
    assert.deepEqual(completed.math_steps.filter(card => card.route_id === firstRoute).slice(0, prefixCards), paused.math_steps,
      'independent goal closure preserves the complete pre-verification prefix');
    for (const route of config.routes) {
      const checkpoint = completed.checkpoints.find(item => item.route_id === route);
      const trajectory = trajectoryFor(completed, route);
      const handoff = completed.handoffs.find(item => item.route_id === route);
      const cards = completed.math_steps.filter(card => card.route_id === route);
      assert.deepEqual(trajectory.constraint_context.goal, config.gold.goal, 'the original minimum goal must survive execution');
      assert.deepEqual(checkpoint.driver_state.feasible_set_exact, config.gold.feasible_set_exact,
        'the complete feasible set must equal the independently authored gold');
      assert.deepEqual(handoff.answer, config.gold.answer, 'typed extremum answer must equal independent exact gold');
      const finalizations = trajectory.finalization.map((call, index) => ({call, index}));
      const boundaries = finalizations.filter(({call}) => call.capability === 'endpoint_check');
      const closures = finalizations.filter(({call}) => call.capability === 'finalize_goal');
      assert.equal(boundaries.length, 1); assert.equal(closures.length, 1);
      const boundary = boundaries[0], closure = closures[0];
      assert.ok(checked(boundary.call)); assert.ok(checked(closure.call));
      assert.equal(boundary.call.outputs.status, 'passed');
      assert.deepEqual(boundary.call.outputs.points.map(point => point.point.expression), config.gold.boundary_points);
      assert.ok(boundary.call.outputs.points.every(point => point.included && point.holds && point.passed));
      assert.equal(closure.call.public_ref, null, 'goal closure cites its checked internal operation');
      assert.deepEqual(closure.call.answer, config.gold.answer);
      assert.deepEqual(closure.call.outputs.answer, config.gold.answer);
      assert.ok(closure.call.operations.includes('goal_finalization'));
      const proof = closure.call.outputs.evidence;
      assert.equal(proof.kind, 'goal_closure'); assert.equal(proof.goal_kind, config.goal_extremum.kind);
      assert.equal(proof.status, config.goal_extremum.status); assert.equal(proof.direction, 'lower');
      assert.equal(proof.empty, false); assert.equal(proof.bounded, true);
      assert.equal(proof.member, true); assert.equal(proof.attained, true);
      assert.deepEqual(proof.feasible_set.exact, config.gold.feasible_set_exact);
      assert.deepEqual(proof.bound, config.gold.answer.value);
      assert.ok(proof.checks.length && proof.checks.every(check => check.passed === true));
      assert.ok(proof.checks.some(check => check.kind === 'goal_answer_matches_feasible_set'));
      const closureCards = cards.filter(card => card.display_unit === 'goal_finalization');
      assert.equal(closureCards.length, 1);
      const goalCard = closureCards[0], boundaryCard = cards.at(-2);
      assert.equal(goalCard.step_id, cards.at(-1).step_id);
      assert.equal(goalCard.title, '确定最小值'); assert.equal(boundaryCard.display_unit, 'boundary');
      assert.deepEqual(goalCard.source_refs, [`/finalization/${closure.index}`]);
      assert.deepEqual(boundaryCard.source_refs, [`/finalization/${boundary.index}`]);
      assert.deepEqual(goalCard.before[0].exact, config.gold.feasible_set_exact);
      assert.deepEqual(goalCard.after[0].exact, config.gold.answer.value.exact);
      assert.ok(goalCard.used_basis.includes('function-range-extrema#attainability'));
      const directPaths = collectPublicPaths(completed, route), selectedPaths = collectRulePaths(completed, route);
      assert.ok(directPaths.length, 'the route retains real public calls');
      if (route !== firstRoute) await page.locator(`[data-stream-route=${JSON.stringify(route)}]`).click();
      const section = page.locator(`.stage-three-route[data-route-id=${JSON.stringify(route)}]`);
      await section.waitFor({state: 'visible'});
      let readCards = await section.locator('.stage-three-math-step:visible').count();
      assert.ok(readCards < goalCard.ordinal);
      await assertPublicPathsAt(directPaths, readCards);
      if (selectedPaths.length) await assertRulePathsAt(selectedPaths, readCards);
      assert.equal(await section.locator('.stage-three-completion:visible').count(), 0,
        'a verified result must remain hidden until the final goal card is read');
      while (readCards < boundaryCard.ordinal) {
        await page.locator(`[data-stream-next=${JSON.stringify(route)}]`).click();
        readCards = await section.locator('.stage-three-math-step:visible').count();
        await assertPublicPathsAt(directPaths, readCards);
        if (selectedPaths.length) await assertRulePathsAt(selectedPaths, readCards);
      }
      assert.equal(await section.locator('.stage-three-completion:visible').count(), 0,
        'reading the complete feasible set and boundary alone must not skip the extremum conclusion');
      await page.locator(`[data-stream-next=${JSON.stringify(route)}]`).click();
      assert.equal(await section.locator('.stage-three-math-step:visible').count(), cards.length);
      await section.locator('.stage-three-completion').waitFor({state: 'visible'});
      assert.equal(await section.getAttribute('data-answer-status'), 'attained');
      assert.match(await section.locator('.stage-three-completion').textContent(), /最小值/);
      assert.ok(await section.locator('.stage-three-completion .katex').count() > 0);
      await basisLinkFor('function-range-extrema#attainability').waitFor({state: 'attached'});
      const shown = page.locator(`.stage-three-math-step[data-step-id=${JSON.stringify(goalCard.step_id)}]`);
      assert.ok(await shown.locator('.katex').count() > 0);
      await shown.scrollIntoViewIfNeeded();
      await section.locator('.stage-three-completion').scrollIntoViewIfNeeded();
      await page.screenshot({path: `${output}/09-goal-closure-${route}.png`, fullPage: true});
      goalFinalization.push({route, goal: trajectory.constraint_context.goal, answer: handoff.answer,
        feasible_set_exact: checkpoint.driver_state.feasible_set_exact, proof,
        boundary_source: `/finalization/${boundary.index}`, boundary_points: boundary.call.outputs.points,
        closure_source: `/finalization/${closure.index}`, closure_step_id: goalCard.step_id,
        actual_cards: cards.length, boundary_precedes_goal: true, completion_waits_for_goal_reading: true,
        direct_paths: directPaths, rule_paths: selectedPaths, activation_follows_actual_reading: true});
    }
    console.log('Verified both Q13 routes: exact full set, independent boundary, attained minimum, readable conclusion and actual graph sources.');
  }
  assert.equal(await page.locator('.katex-error').count(), 0);
  await api('/test/invalidate', 'POST');
  await page.waitForFunction(() => [...document.querySelectorAll('.stage-three-route')].every(node => node.dataset.available === 'false'));
  assert.equal(await page.locator('.stage-three-completion:visible').count(), 0);
  assert.equal(await page.locator('.stage-three-qa:visible').count(), 0);
  assert.equal(await page.locator('.stage-three-math-step').count(), completedCards);
  assert.deepEqual(errors, []);
  fs.writeFileSync(`${output}/browser-evidence.json`, JSON.stringify({
    source: `recorded_${config.case}`, case: config.case, routes: config.routes, new_llm_calls: 0, entry: '/lab/search/problem.html',
    prefix_cards: paused.math_steps.length, first_route_handoffs: firstDone.handoffs.length,
    completed_cards: completed.math_steps.length, completed_handoffs: completed.handoffs.length,
    qa_cards: completed.qa.length, student_visible: studentVisible, refresh_restored: true,
    interrupted_without_events: true, interruption_fixture: 'execution_metadata_only', explicit_resume_requests: resumeRequests,
    mathematical_dom_preserved: true, conflict_revoked_completion_and_qa: true, internal_basis: internalBasis,
    rule_path: rulePaths.length === 1 ? rulePaths[0] : null, rule_paths: rulePaths,
    classification, separation, variable_swap: variableSwap, goal_finalization: goalFinalization,
    provenance: config.provenance || null, llm_provider_attempts: completedState.llm_provider_attempts,
    formula_errors: 0, ...events, browser_errors: errors,
  }, null, 2));
} catch (error) {
  fs.writeFileSync(`${output}/failure.txt`, String(error.stack || error));
  for (const page of browser.contexts().flatMap(context => context.pages())) {
    await page.screenshot({path: `${output}/failure.png`, fullPage: true}).catch(() => {});
    fs.writeFileSync(`${output}/failure.html`, await page.content().catch(() => ''));
  }
  throw error;
} finally { await browser.close(); }
