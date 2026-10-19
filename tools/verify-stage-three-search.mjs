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
assert.equal(config.routes.length, 2);
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
  await page.waitForFunction(expected => document.querySelectorAll('.stage-three-math-step').length >= expected, config.prefix_cards);
  await page.waitForFunction(() => [...document.querySelectorAll('.stage-three-math-step')].some(node => node.getClientRects().length));
  let paused;
  for (let attempt = 0; attempt < 100; attempt++) {
    const state = await api('/test/state');
    if (state.paused.includes(firstRoute)) { paused = state.snapshot; break; }
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  assert.ok(paused, 'the first route must reach its verification barrier before the interruption probe');
  assert.equal(paused.math_steps.length, config.prefix_cards);
  assert.equal(paused.handoffs.length, 0);
  assert.equal(await page.locator('.stage-three-completion:visible').count(), 0);
  assert.ok(await page.locator('.stage-three-math-step .katex').count() > 0);
  await page.locator('.stage-three-math-step').first().scrollIntoViewIfNeeded();
  await page.screenshot({path: `${output}/01-running-prefix.png`, fullPage: true});
  console.log(`Verified running prefix: ${config.prefix_cards} mathematical cards before completion.`);
  await page.evaluate(() => {
    window.__firstMathCard = document.querySelector('.stage-three-math-step');
    window.__firstMathBody = [...window.__firstMathCard.children].filter(node => !node.classList.contains('stage-three-qa'));
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
  assert.equal(firstDone.handoffs.length, 1, 'one verified route is publishable before the second finishes');
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
  await page.screenshot({path: `${output}/02-first-route-with-qa.png`, fullPage: true});
  console.log('Verified first-route handoff and cursor-expiry QA recovery.');

  await api(`/test/release/${secondRoute}`, 'POST');
  await page.waitForFunction(expected => document.querySelectorAll('.stage-three-math-step').length === expected, config.completed_cards);
  await page.waitForFunction(route => document.querySelector(`.stage-three-route[data-route-id="${route}"]`)?.dataset.mathStatus === 'verified', secondRoute);
  let completed = (await api('/test/state')).snapshot;
  assert.equal(completed.handoffs.length, 2);
  assert.equal(completed.qa.length, 1);
  assert.ok(completed.checkpoints.every(checkpoint => checkpoint.status === 'verified'));
  const originalIds = completed.math_steps.map(step => step.step_id);
  assert.equal(new Set(originalIds).size, originalIds.length);
  assert.equal(await page.locator('.katex-error').count(), 0);

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
  const progress = await page.locator('#gw-progress').textContent();
  const readingScroll = await page.locator('.gw-lesson').evaluate(node => node.scrollTop);
  await api('/test/qa/completed', 'POST');
  await page.waitForFunction(route => document.querySelector(`[data-route-id="${route}"]`)?.dataset.enrichmentStatus === 'completed', firstRoute);
  assert.equal(await page.locator('.stage-three-math-step:visible').count(), studentVisible);
  assert.equal(await page.locator('#gw-progress').textContent(), progress, 'QA retry preserves student decisions');
  assert.equal(await page.locator('.gw-lesson').evaluate(node => node.scrollTop), readingScroll, 'QA retry does not jump reading position');
  assert.ok(await page.evaluate(() => window.__firstMathCard === document.querySelector('.stage-three-math-step')));
  completed = (await api('/test/state')).snapshot;
  assert.equal(completed.qa.length, config.qa_cards);
  await page.screenshot({path: `${output}/03-student-reading.png`, fullPage: true});
  console.log('Verified student decisions and two-step reading position survive QA retry.');
  await page.reload();
  // The page should restore the selected actor/part and its saved decisions.
  await page.waitForFunction(expected => document.querySelectorAll('.stage-three-math-step').length === expected, config.completed_cards);
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
  let classification = null, separation = null;
  if (config.interval_cases) {
    const trajectory = trajectoryFor(completed, firstRoute);
    const cases = trajectory.steps.flatMap(record => record.case_results || []);
    assert.equal(cases.length, config.interval_cases);
    assert.equal(new Set(cases.map(item => JSON.stringify(item.case_path))).size, cases.length);
    assert.ok(cases.every(item => item.case_path.length && item.source_refs.length));
    const firstCards = completed.math_steps.filter(card => card.route_id === firstRoute);
    assert.equal(firstCards.length, config.qa_cards);
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
  assert.equal(await page.locator('.katex-error').count(), 0);
  await api('/test/invalidate', 'POST');
  await page.waitForFunction(() => [...document.querySelectorAll('.stage-three-route')].every(node => node.dataset.available === 'false'));
  assert.equal(await page.locator('.stage-three-completion:visible').count(), 0);
  assert.equal(await page.locator('.stage-three-qa:visible').count(), 0);
  assert.equal(await page.locator('.stage-three-math-step').count(), config.completed_cards);
  assert.deepEqual(errors, []);
  fs.writeFileSync(`${output}/browser-evidence.json`, JSON.stringify({
    source: `recorded_${config.case}`, case: config.case, routes: config.routes, new_llm_calls: 0, entry: '/lab/search/problem.html',
    prefix_cards: paused.math_steps.length, first_route_handoffs: firstDone.handoffs.length,
    completed_cards: completed.math_steps.length, completed_handoffs: completed.handoffs.length,
    qa_cards: completed.qa.length, student_visible: studentVisible, refresh_restored: true,
    interrupted_without_events: true, interruption_fixture: 'execution_metadata_only', explicit_resume_requests: resumeRequests,
    mathematical_dom_preserved: true, conflict_revoked_completion_and_qa: true, internal_basis: internalBasis,
    rule_path: rulePaths.length === 1 ? rulePaths[0] : null, rule_paths: rulePaths,
    classification, separation, formula_errors: 0, ...events, browser_errors: errors,
  }, null, 2));
} catch (error) {
  fs.writeFileSync(`${output}/failure.txt`, String(error.stack || error));
  for (const page of browser.contexts().flatMap(context => context.pages())) {
    await page.screenshot({path: `${output}/failure.png`, fullPage: true}).catch(() => {});
    fs.writeFileSync(`${output}/failure.html`, await page.content().catch(() => ''));
  }
  throw error;
} finally { await browser.close(); }
