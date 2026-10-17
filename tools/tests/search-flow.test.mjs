import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

function setup(file, search = '') {
  const nodes = new Map();
  const element = selector => {
    if (!nodes.has(selector)) nodes.set(selector, {
      hidden: true, disabled: false, innerHTML: '', textContent: '', dataset: {}, style: {}, children: [],
      naturalWidth: 1000, naturalHeight: 2000,
      classList: {add() {}, remove() {}}, decode: async () => {},
      addEventListener() {}, setAttribute() {}, append() {},
      getContext: () => ({drawImage() {}}), toDataURL: () => 'data:image/jpeg;base64,fixture',
    });
    return nodes.get(selector);
  };
  const location = {search, href: '', reloads: 0, reload() { this.reloads++; }};
  const context = vm.createContext({
    URLSearchParams, location, performance: {now: () => 0}, window: {},
    setTimeout: (callback, delay) => { if (delay !== 2400) callback(); return 1; }, clearTimeout() {},
    sessionStorage: {getItem() { return null; }, setItem() {}, removeItem() {}},
    document: {
      body: {dataset: {}}, querySelector: element,
      querySelectorAll: selector => selector === '#pq-phases li' ? [0, 1, 2].map(i => element(`phase${i}`)) : [],
      createElement: element, addEventListener() {},
    },
  });
  vm.runInContext(fs.readFileSync(new URL(`../../site/lab/search/${file}`, import.meta.url), 'utf8'), context);
  return {context, element, location};
}

const crop = {page_id: '123456789abc', box: [0, 0, 1, 1]};
const rect = {x: 0, y: 0, w: 1, h: 1};
const response = value => ({ok: true, json: async () => value});
const page = {page_id: crop.page_id, latency_ms: {detect: 1000}, regions: [], mode: 'whole_content'};
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return {promise, resolve}; };
const tick = () => new Promise(resolve => setImmediate(resolve));

for (const order of ['decode-first', 'upload-first']) test(`submitting waits for both image decoding and upload: ${order}`, async () => {
  const {context, element, location} = setup('camera.js');
  const decoded = deferred(), uploaded = deferred(), requests = [];
  element('#cm-photo').decode = () => decoded.promise;
  context.fetch = async (url, options) => {
    requests.push({url, body: options.body});
    return url.endsWith('/pages') ? uploaded.promise : response({search_id: 'fedcba987654'});
  };
  const pick = context.openPick('photo.png', {type: 'image/png'}, []);
  const submitted = context.go(rect);
  assert.equal(element('#cm-whole').disabled, true);
  if (order === 'decode-first') decoded.resolve(); else uploaded.resolve(response(page));
  await tick();
  assert.equal(requests.length, 1);
  assert.equal(location.href, '');
  decoded.resolve(); uploaded.resolve(response(page));
  await Promise.all([pick, submitted]);
  assert.deepEqual(JSON.parse(requests[1].body), crop);
  assert.equal(location.href, 'problem.html?search=fedcba987654');
});

test('a network submission failure is visible and the same crop can be retried', async () => {
  const {context, element, location} = setup('camera.js');
  let disconnected = true;
  const posted = [];
  context.fetch = async (url, options) => {
    if (url.endsWith('/pages')) return response(page);
    posted.push(JSON.parse(options.body));
    if (disconnected) throw new TypeError('Failed to fetch');
    return response({search_id: 'fedcba987654'});
  };
  await context.openPick('photo.png', {type: 'image/png'}, []);
  await assert.doesNotReject(context.go(rect));
  assert.equal(location.href, '');
  assert.equal(element('#sq-toast').hidden, false);
  assert.match(element('#sq-toast').textContent, /提交失败.*重试/);
  for (const selector of ['#cm-go', '#cm-crop-go', '#cm-whole']) assert.equal(element(selector).disabled, false);
  disconnected = false;
  await context.go(rect);
  assert.deepEqual(posted, [crop, crop]);
  assert.equal(location.href, 'problem.html?search=fedcba987654');
});

for (const mode of ['terminal', 'transient', 'lost']) test(`polling and retry preserve the correct run: ${mode}`, async () => {
  const {context, location} = setup('problem.js', '?search=0123456789ab');
  let gets = 0;
  const posted = [];
  context.fetch = async (url, options = {}) => {
    if (options.method === 'POST') {
      posted.push(JSON.parse(options.body));
      return response({search_id: 'fedcba987654'});
    }
    gets++;
    assert.ok(gets <= 6, 'polling must stop after repeated failures');
    if ((mode === 'lost' && gets >= 2) || (mode === 'transient' && gets === 2)) throw new TypeError('Failed to fetch');
    const cropDetails = {...crop, crop_size: [1000, 2000], bytes: 1000};
    if (mode === 'terminal' || (mode === 'transient' && gets === 3)) return response({state: 'done', crop: cropDetails, outcome: 'error'});
    return response({state: 'running', crop: cropDetails, calls: [], preview: null});
  };
  await context.runLive();
  assert.equal(gets, mode === 'lost' ? 6 : mode === 'transient' ? 3 : 1);
  assert.deepEqual(posted, []);
  await context.retry();
  assert.equal(location.reloads, mode === 'lost' ? 1 : 0);
  assert.deepEqual(posted, mode === 'lost' ? [] : [crop]);
});
