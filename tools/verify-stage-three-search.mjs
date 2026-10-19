// Offline acceptance for the actual photo-search page and its HTTP/WS adapter.
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import fs from 'node:fs';
const require = createRequire(import.meta.url);
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const [origin, output, searchId] = process.argv.slice(2);
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
  await api(base + '/lesson/start', 'POST');
  await page.goto(`${origin}/lab/search/problem.html?search=${searchId}`);
  await page.locator('[data-actor="replay"]').click();
  await page.waitForFunction(() => document.querySelectorAll('.stage-three-math-step').length >= 4);
  await page.waitForFunction(() => [...document.querySelectorAll('.stage-three-math-step')].some(node => node.getClientRects().length));
  let paused;
  for (let attempt = 0; attempt < 100; attempt++) {
    const state = await api('/test/state');
    if (state.paused.includes('discriminant')) { paused = state.snapshot; break; }
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  assert.ok(paused, 'the first route must reach its verification barrier before the interruption probe');
  assert.equal(paused.math_steps.length, 4);
  assert.equal(paused.handoffs.length, 0);
  assert.equal(await page.locator('.stage-three-completion:visible').count(), 0);
  assert.ok(await page.locator('.stage-three-math-step .katex').count() > 0);
  await page.locator('.stage-three-math-step').first().scrollIntoViewIfNeeded();
  await page.screenshot({path: `${output}/01-running-prefix.png`, fullPage: true});
  console.log('Verified running prefix: four mathematical cards before completion.');
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
  await api('/test/release/discriminant', 'POST');
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

  await api('/test/release/extremum', 'POST');
  await page.waitForFunction(() => document.querySelectorAll('.stage-three-math-step').length === 10);
  await page.waitForFunction(() => document.querySelector('.stage-three-route[data-route-id="extremum"]')?.dataset.mathStatus === 'verified');
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
  for (const decision of lesson.goals[0].walk.bundle.intro) {
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
  await page.locator('[data-plane-cell="real|free"]').click();
  await page.locator('[data-plane-method="discriminant"]').click();
  await page.locator('#gw-submit').click();
  // The public bridge may use a confirm button or a route-choice card; the
  // acceptance expects D4 to remain a real student decision in either form.
  await page.locator('#gw-current-title').filter({hasText: '解题路线'}).waitFor();
  await page.locator('[data-choice][data-value="discriminant"]').click();
  await page.locator('#gw-submit').click();
  await page.waitForFunction(() => [...document.querySelectorAll('.stage-three-math-step')].filter(node => node.getClientRects().length).length === 1);
  assert.equal(await page.locator('.stage-three-math-step:visible').count(), 1,
    'completed computation does not advance the student reading position');
  await page.locator('[data-stream-next="discriminant"]').click();
  const studentVisible = await page.locator('.stage-three-math-step:visible').count();
  assert.equal(studentVisible, 2);
  const progress = await page.locator('#gw-progress').textContent();
  const readingScroll = await page.locator('.gw-lesson').evaluate(node => node.scrollTop);
  await api('/test/qa/completed', 'POST');
  await page.waitForFunction(() => document.querySelector('[data-route-id="discriminant"]')?.dataset.enrichmentStatus === 'completed');
  assert.equal(await page.locator('.stage-three-math-step:visible').count(), studentVisible);
  assert.equal(await page.locator('#gw-progress').textContent(), progress, 'QA retry preserves student decisions');
  assert.equal(await page.locator('.gw-lesson').evaluate(node => node.scrollTop), readingScroll, 'QA retry does not jump reading position');
  assert.ok(await page.evaluate(() => window.__firstMathCard === document.querySelector('.stage-three-math-step')));
  completed = (await api('/test/state')).snapshot;
  assert.equal(completed.qa.length, 5);
  await page.screenshot({path: `${output}/03-student-reading.png`, fullPage: true});
  console.log('Verified student decisions and two-step reading position survive QA retry.');
  await page.reload();
  // The page should restore the selected actor/part and its saved decisions.
  await page.waitForFunction(() => document.querySelectorAll('.stage-three-math-step').length === 10);
  await page.waitForFunction(expected => [...document.querySelectorAll('.stage-three-math-step')].filter(node => node.getClientRects().length).length === expected, studentVisible);
  assert.equal(await page.locator('.stage-three-math-step:visible').count(), studentVisible);
  assert.equal(await page.locator('#gw-progress').textContent(), progress);
  const restored = await api('/test/state');
  assert.equal(restored.stage_two_attempts, 1);
  assert.equal(restored.snapshot.run_id, completed.run_id);
  assert.deepEqual(restored.snapshot.math_steps.map(step => step.step_id), originalIds);
  assert.equal(restored.snapshot.last_seq, completed.last_seq, 'refresh does not run extraction or solve again');
  await page.screenshot({path: `${output}/04-refreshed.png`, fullPage: true});
  console.log('Verified refresh restores the same run, steps and reading position.');
  await api('/test/invalidate', 'POST');
  await page.waitForFunction(() => [...document.querySelectorAll('.stage-three-route')].every(node => node.dataset.available === 'false'));
  assert.equal(await page.locator('.stage-three-completion:visible').count(), 0);
  assert.equal(await page.locator('.stage-three-qa:visible').count(), 0);
  assert.equal(await page.locator('.stage-three-math-step').count(), 10);
  assert.deepEqual(errors, []);
  fs.writeFileSync(`${output}/browser-evidence.json`, JSON.stringify({
    source: 'recorded_q01', new_llm_calls: 0, entry: '/lab/search/problem.html',
    prefix_cards: paused.math_steps.length, first_route_handoffs: firstDone.handoffs.length,
    completed_cards: completed.math_steps.length, completed_handoffs: completed.handoffs.length,
    qa_cards: completed.qa.length, student_visible: studentVisible, refresh_restored: true,
    interrupted_without_events: true, interruption_fixture: 'execution_metadata_only', explicit_resume_requests: resumeRequests,
    mathematical_dom_preserved: true, conflict_revoked_completion_and_qa: true, ...events, browser_errors: errors,
  }, null, 2));
} catch (error) {
  fs.writeFileSync(`${output}/failure.txt`, String(error.stack || error));
  for (const page of browser.contexts().flatMap(context => context.pages())) {
    await page.screenshot({path: `${output}/failure.png`, fullPage: true}).catch(() => {});
    fs.writeFileSync(`${output}/failure.html`, await page.content().catch(() => ''));
  }
  throw error;
} finally { await browser.close(); }
