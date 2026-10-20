// Used by server/tools/smoke_graph_stage_three_browser.py against its paused run.
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import fs from 'node:fs';
const require = createRequire(import.meta.url);
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const [url, output] = process.argv.slice(2);
const browser = await chromium.launch({headless: true,
  ...(process.env.CHROME_EXECUTABLE ? {executablePath: process.env.CHROME_EXECUTABLE} : {})});
try {
  const page = await browser.newPage({viewport: {width: 1100, height: 900}});
  const errors = [];
  page.on('pageerror', error => errors.push(String(error)));
  await page.route('**/*', route => new URL(route.request().url()).origin === new URL(url).origin
    ? route.continue() : route.abort());
  await page.goto(url);
  await page.waitForSelector('.stage-three-math-step');
  const prefix = await page.locator('.stage-three-math-step').count();
  assert.equal(prefix, 4, 'four real calculation cards precede final validation');
  assert.equal(await page.locator('.stage-three-completion:not([hidden])').count(), 0);
  const paused = await page.evaluate(async () => (await fetch('/snapshot')).json());
  assert.ok(paused.checkpoints.every(cp => cp.status === 'running'));
  assert.equal(paused.handoffs.length, 0);
  assert.ok(await page.locator('.stage-three-math-step math').count() > 0);
  await page.screenshot({path: `${output}/before-completion.png`, fullPage: true});
  await page.evaluate(() => fetch('/test/release'));
  await page.waitForFunction(() => document.querySelectorAll('.stage-three-completion:not([hidden])').length === 2);
  assert.equal(await page.locator('.stage-three-math-step').count(), 10);
  assert.equal(await page.locator('.katex-error').count(), 0);
  const finished = await page.evaluate(async () => (await fetch('/snapshot')).json());
  assert.ok(finished.checkpoints.every(cp => cp.status === 'verified'));
  assert.equal(finished.handoffs.length, 2);
  await page.screenshot({path: `${output}/after-completion.png`, fullPage: true});
  // Refresh restores committed identities and cannot duplicate cards or tasks.
  await page.reload();
  await page.waitForFunction(() => document.querySelectorAll('.stage-three-math-step').length === 10);
  assert.equal(await page.locator('.stage-three-completion:not([hidden])').count(), 2);
  await page.evaluate(() => fetch('/test/invalidate'));
  await page.waitForFunction(() => [...document.querySelectorAll('.stage-three-route')]
    .every(node => node.dataset.available === 'false'));
  assert.equal(await page.locator('.stage-three-completion:not([hidden])').count(), 0);
  assert.equal(await page.locator('.stage-three-math-step').count(), 10);
  assert.ok((await page.locator('.stage-three-status').allTextContents())
    .every(text => text.includes('完整解答暂不可用') && !text.includes('已完成数学验证')));
  assert.deepEqual(errors, []);
  fs.writeFileSync(`${output}/browser-evidence.json`, JSON.stringify({
    prefix_cards: prefix, completed_cards: 10, before_seq: paused.last_seq, after_seq: finished.last_seq,
    before_handoffs: paused.handoffs.length, after_handoffs: finished.handoffs.length,
    refresh_restored: true, invalidation_preserves_cards_and_replaces_status: true, browser_errors: errors,
  }, null, 2));
} finally { await browser.close(); }
