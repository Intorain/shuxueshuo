import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

function setup(file, search = '') {
  const nodes = new Map();
  const delays = [];
  const draws = [];
  const imageLoads = [];
  const documentListeners = new Map();
  let created = 0;
  let imageDecoder = async () => {};
  const element = selector => {
    if (!nodes.has(selector)) nodes.set(selector, {
      hidden: true, disabled: false, innerHTML: '', textContent: '', dataset: {}, style: {}, children: [],
      naturalWidth: 1000, naturalHeight: 2000,
      classList: {add() {}, remove() {}}, decode: async () => {},
      listeners: new Map(),
      addEventListener(type, callback) { this.listeners.set(type, callback); }, setAttribute() {}, append() {},
      removeAttribute(name) { delete this[name]; },
      replaceWith(node) { nodes.set('#cm-photo', node); },
      getContext: () => ({drawImage(...args) { draws.push(args); }}), toDataURL: () => 'data:image/jpeg;base64,fixture',
    });
    return nodes.get(selector);
  };
  const location = {search, href: '', reloads: 0, reload() { this.reloads++; }};
  const context = vm.createContext({
    URLSearchParams, location, performance: {now: () => 0}, window: {},
    setTimeout: (callback, delay) => { delays.push(delay); if (delay !== 2400) callback(); return 1; }, clearTimeout() {},
    sessionStorage: {getItem() { return null; }, setItem() {}, removeItem() {}},
    document: {
      body: {dataset: {}}, querySelector: element,
      querySelectorAll: selector => selector === '#pq-phases li' ? [0, 1, 2].map(i => element(`phase${i}`)) : [],
      createElement(tag) {
        const node = element(`created-${tag}-${created++}`);
        if (tag === 'img') node.decode = () => { imageLoads.push(node.src); return imageDecoder(node); };
        return node;
      }, addEventListener(type, callback) { documentListeners.set(type, callback); },
    },
  });
  vm.runInContext(fs.readFileSync(new URL(`../../site/lab/search/${file}`, import.meta.url), 'utf8'), context);
  return {context, element, location, delays, draws, imageLoads, documentListeners, setImageDecode(fn) { imageDecoder = fn; }};
}

const crop = {page_id: '123456789abc', box: [0, 0, 1, 1]};
const rect = {x: 0, y: 0, w: 1, h: 1};
const response = value => ({ok: true, json: async () => value});
const page = {page_id: crop.page_id, image_url: `/api/search/pages/${crop.page_id}/image`,
  orientation: {status: 'upright', rotation_degrees: 0, predicted_degrees: 0, confidence: .99},
  latency_ms: {detect: 1000}, regions: [], mode: 'whole_content'};
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return {promise, resolve}; };
const tick = () => new Promise(resolve => setImmediate(resolve));

test('problem meaning follows the confirmed conversion and ignores another goal or bundle version', () => {
  const {context, element} = setup('problem.js');
  vm.runInContext(`renderMath = () => {}; lesson.part = 0;
    lesson.data = {goals: [{target_ref: '/root/goals/0', walk: {bundle: {
      problemId: 'conversion/goal', bundleVersion: 'current', problem: {
        normalization_decision: 'D1-transform', source_meaning: '原命题为假', normalized_text: '存在反例，求参数范围'
      }}}}]};`, context);
  context.renderMeaning();
  assert.match(element('#pq-meaning-body').innerHTML, /原命题为假/);
  const accepted = {actor: 'student', problem_id: 'conversion/goal', base_bundle_version: 'current',
    teaching_context: {transformed: true, text: 'ignore arbitrary text'}};
  context.savePageProgress(accepted);
  assert.match(element('#pq-meaning-body').innerHTML, /存在反例，求参数范围/);
  assert.doesNotMatch(element('#pq-meaning-body').innerHTML, /arbitrary/);
  assert.equal(element('#pq-meaning-title').textContent, '转化后的条件与目标');
  context.savePageProgress({...accepted, teaching_context: {transformed: false}});
  assert.match(element('#pq-meaning-body').innerHTML, /原命题为假/);
  context.savePageProgress({...accepted, problem_id: 'another/goal'});
  context.savePageProgress({...accepted, base_bundle_version: 'old'});
  assert.match(element('#pq-meaning-body').innerHTML, /原命题为假/);
});

for (const order of ['decode-first', 'upload-first']) test(`submitting during loading is ignored until upload and decoding finish: ${order}`, async () => {
  const {context, element, location, setImageDecode} = setup('camera.js');
  const decoded = deferred(), uploaded = deferred(), requests = [];
  setImageDecode(() => decoded.promise);
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
  assert.equal(element('#cm-photo').src, page.image_url);
  assert.equal(requests.length, 1, 'a disabled whole-image action must not queue a later submission');
  assert.equal(location.href, '');
  await context.go(rect);
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

function cameraPage(id, box = [.1, .2, .6, .5], status = 'corrected') {
  return {...page, page_id: id, image_url: `/api/search/pages/${id}/image`,
    orientation: {...page.orientation, status, rotation_degrees: 90},
    regions: [{number: 3, box, crop: box}]};
}

const recognitionFailures = [
  {name: 'unsupported image', reason: /图片格式不受支持或文件已损坏.*JPEG.*PNG.*WebP/,
    response: () => ({ok: false, status: 400, json: async () => ({detail: 'page.not_an_image'})})},
  {name: 'unavailable OCR', reason: /识别服务暂不可用.*稍后重试/,
    response: () => ({ok: false, status: 503, json: async () => ({detail: 'ocr.unavailable: private_worker_failure'})})},
  {name: 'oversized image rejected by the API', reason: /照片太大.*压缩后重试/,
    response: () => ({ok: false, status: 413, json: async () => ({detail: 'page.size'})})},
  {name: 'oversized image rejected by a proxy with HTML', reason: /照片太大.*压缩后重试/,
    response: () => ({ok: false, status: 413, json: async () => { throw new SyntaxError('Unexpected token < in JSON'); }})},
  {name: 'invalid success JSON', reason: /识别服务返回了无效数据.*重试/,
    response: () => ({ok: true, status: 200, json: async () => { throw new SyntaxError('Unexpected token < in JSON'); }})},
];

for (const failure of recognitionFailures) test(`${failure.name} remains a recognition error and retries the same upload without mocked boxes`, async () => {
  const {context, element, location} = setup('camera.js');
  const requests = [], blob = {type: 'image/png'};
  const fallback = [{x: .1, y: .2, w: .5, h: .3, demo: 'ok'}];
  context.fetch = async (url, options) => {
    requests.push({url, options});
    return requests.length === 1 ? failure.response() : response(cameraPage('recovered'));
  };
  await context.openPick('blob:local-photo', blob, fallback);
  assert.match(element('#cm-proto-note').textContent, failure.reason);
  assert.doesNotMatch(element('#cm-proto-note').textContent, /离线原型|模拟|page\.not_an_image|private_worker_failure/);
  assert.equal(element('#cm-proto-note').hidden, false);
  assert.equal(element('#cm-photo').src, 'blob:local-photo');
  assert.equal(element('#cm-boxes').innerHTML, '');
  assert.equal(vm.runInContext('boxes.length', context), 0);
  assert.equal(vm.runInContext('pageId', context), null);
  assert.notEqual(vm.runInContext('currentResult?.offline', context), true);
  for (const id of ['#cm-go', '#cm-crop-go', '#cm-whole', '#cm-manual', '#cm-rotate']) assert.equal(element(id).disabled, true);
  assert.equal(element('#cm-retry').hidden, false);
  assert.equal(element('#cm-retry').textContent, '重试识别');
  assert.equal(element('#cm-retry').disabled, false);
  await context.go(rect);
  await context.go(fallback[0]);
  assert.equal(location.href, '');
  assert.equal(requests.length, 1);
  await vm.runInContext('retryAction()', context);
  assert.equal(requests.length, 2, 'retrying recognition sends a new upload, unlike retrying a completed preview');
  for (const request of requests) {
    assert.equal(request.url, '/api/search/pages');
    assert.equal(request.options.method, 'POST');
    assert.equal(request.options.body, blob);
  }
  assert.equal(element('#cm-photo').src, '/api/search/pages/recovered/image');
  assert.equal(vm.runInContext('pageId', context), 'recovered');
  assert.equal(element('#cm-retry').hidden, true);
  assert.equal(element('#cm-whole').disabled, false);
});

for (const phase of ['initial upload', 'recognition retry']) test(`a late ${phase} failure cannot overwrite a newer decoded page`, async () => {
  const {context, element} = setup('camera.js');
  const failed = deferred();
  let uploads = 0;
  context.fetch = async () => {
    uploads++;
    if (phase === 'recognition retry' && uploads === 1) return recognitionFailures[1].response();
    if (uploads === (phase === 'recognition retry' ? 2 : 1)) return failed.promise;
    return response(cameraPage('replacement'));
  };
  let pending = context.openPick('blob:old', {type: 'image/png'}, [{x: .1, y: .2, w: .5, h: .3}]);
  if (phase === 'recognition retry') {
    await pending;
    pending = vm.runInContext('retryAction()', context);
  }
  await context.openPick('blob:new', {type: 'image/png'}, []);
  const note = element('#cm-proto-note').textContent;
  failed.resolve(recognitionFailures[1].response());
  await pending;
  assert.equal(element('#cm-photo').src, '/api/search/pages/replacement/image');
  assert.equal(vm.runInContext('pageId', context), 'replacement');
  assert.equal(element('#cm-proto-note').textContent, note);
  assert.equal(element('#cm-retry').hidden, true);
  assert.equal(element('#cm-whole').disabled, false);
});

function captureToasts(context) {
  const messages = [], toast = context.toast;
  context.toast = message => { messages.push(message); toast(message); };
  return messages;
}

for (const status of ['corrected', 'manual', 'upright', 'uncertain']) test(`${status} orientation only announces an automatic correction when appropriate`, async () => {
  const {context, element} = setup('camera.js');
  const messages = captureToasts(context), timers = [];
  context.setTimeout = (callback, delay) => { timers.push({callback, delay}); return timers.length; };
  context.fetch = async () => response(cameraPage('oriented', [.1, .2, .6, .5], status));
  await context.openPick('blob:local', {type: 'image/png'}, []);
  assert.deepEqual(messages, status === 'corrected' ? ['已自动转正'] : []);
  if (status === 'corrected') {
    assert.equal(element('#sq-toast').hidden, false);
    assert.equal(timers.length, 1);
    assert.ok(timers[0].delay > 0 && timers[0].delay <= 5000, 'the confirmation is temporary');
    timers[0].callback();
    assert.equal(element('#sq-toast').hidden, true);
  }
});

test('automatic correction is announced only after its canonical preview has decoded', async () => {
  const {context, element, setImageDecode} = setup('camera.js');
  const decoded = deferred(), messages = captureToasts(context);
  setImageDecode(image => image.src.startsWith('/api/') ? decoded.promise : Promise.resolve());
  context.fetch = async () => response(cameraPage('corrected'));
  const picking = context.openPick('blob:local', {type: 'image/png'}, []);
  await tick();
  assert.equal(element('#cm-photo').src, 'blob:local');
  assert.deepEqual(messages, []);
  decoded.resolve();
  await picking;
  assert.deepEqual(messages, ['已自动转正']);
});

for (const failure of ['request', 'preview']) test(`rolling back a failed rotation ${failure} does not repeat the old automatic-correction toast`, async () => {
  const {context, element, setImageDecode} = setup('camera.js');
  const messages = captureToasts(context);
  let failing = true;
  setImageDecode(image => failing && failure === 'preview' && image.src.includes('/manual/')
    ? Promise.reject(new Error('Preview failed')) : Promise.resolve());
  context.fetch = async url => {
    if (url.endsWith('/pages')) return response(cameraPage('corrected'));
    if (failing && failure === 'request') throw new TypeError('Network failed');
    return response(cameraPage('manual', [.1, .2, .6, .5], 'manual'));
  };
  await context.openPick('blob:local', {type: 'image/png'}, []);
  assert.deepEqual(messages, ['已自动转正']);
  context.startCrop({x: .2, y: .3, w: .4, h: .5});
  await context.rotatePage();
  assert.equal(element('#cm-photo').src, '/api/search/pages/corrected/image');
  assert.equal(element('#cm-crop').style.left, '20%');
  assert.equal(messages.filter(message => message === '已自动转正').length, 1);
  if (failure === 'preview') {
    await vm.runInContext('retryAction()', context);
    assert.equal(messages.filter(message => message === '已自动转正').length, 1);
  }
  failing = false;
  if (failure === 'preview') await vm.runInContext('retryAction()', context);
  else await context.rotatePage();
  assert.equal(element('#cm-photo').src, '/api/search/pages/manual/image');
  assert.equal(messages.filter(message => message === '已自动转正').length, 1);
});

test('local preview appears during OCR while all actions wait for the canonical JPEG preview', async () => {
  const {context, element, draws, imageLoads, setImageDecode} = setup('camera.js');
  const uploaded = deferred(), decoded = deferred(), requests = [];
  const canonical = {...cameraPage('quick-preview'), preview_url: '/api/search/pages/quick-preview/preview'};
  setImageDecode(image => {
    if (image.src !== canonical.preview_url) return Promise.resolve();
    image.naturalWidth = 1600; image.naturalHeight = 900;
    return decoded.promise;
  });
  context.fetch = async (url, options) => { requests.push({url, body: options.body}); return uploaded.promise; };
  const picking = context.openPick('blob:local-photo', {type: 'image/jpeg'}, []);
  await tick();
  assert.equal(element('#cm-photo').src, 'blob:local-photo');
  assert.equal(element('#cm-photo').hidden, false);
  assert.equal(element('#cm-boxes').innerHTML, '');
  assert.equal(vm.runInContext('pageId', context), null);
  assert.equal(draws.length, 0);
  for (const id of ['#cm-go', '#cm-crop-go', '#cm-whole', '#cm-rotate', '#cm-manual']) assert.equal(element(id).disabled, true);
  await context.go(rect);
  await context.go({x: .1, y: .2, w: .5, h: .3});
  assert.equal(requests.length, 1);
  uploaded.resolve(response(canonical));
  await tick();
  assert.equal(element('#cm-photo').src, 'blob:local-photo');
  assert.equal(element('#cm-whole').disabled, true);
  await context.go(rect);
  decoded.resolve();
  await picking;
  assert.deepEqual(imageLoads, ['blob:local-photo', canonical.preview_url], 'the full-resolution PNG is not downloaded for display');
  assert.equal(requests.length, 1, 'neither loading-time submission is queued');
  assert.equal(element('#cm-photo').src, canonical.preview_url);
  assert.equal(vm.runInContext('pageId', context), canonical.page_id);
  assert.equal(element('#cm-whole').disabled, false);
  assert.equal(draws[0][0], element('#cm-photo'));
  assert.deepEqual(draws[0].slice(1, 5), [160, 180, 800, 270]);
});

for (const replacement of [false, true]) test(`a late local blob decode cannot overwrite ${replacement ? 'a replacement photo' : 'its canonical preview'}`, async () => {
  const {context, element, setImageDecode} = setup('camera.js');
  const local = deferred();
  let uploads = 0;
  setImageDecode(image => image.src === 'blob:old-local' ? local.promise : Promise.resolve());
  context.fetch = async () => response(cameraPage(++uploads === 1 ? 'first' : 'second'));
  await context.openPick('blob:old-local', {type: 'image/jpeg'}, []);
  if (replacement) await context.openPick('blob:new-local', {type: 'image/jpeg'}, []);
  const expected = replacement ? 'second' : 'first';
  local.resolve();
  await tick();
  assert.equal(element('#cm-photo').src, `/api/search/pages/${expected}/image`);
  assert.equal(vm.runInContext('pageId', context), expected);
  assert.equal(element('#cm-whole').disabled, false);
});

test('canonical image decoding gates boxes, previews, rotation and cropped submissions', async () => {
  const {context, element, draws, location, setImageDecode} = setup('camera.js');
  const decoded = deferred(), requests = [], canonical = cameraPage('oriented');
  setImageDecode(image => { image.naturalWidth = 2000; image.naturalHeight = 1000; return decoded.promise; });
  context.fetch = async (url, options) => {
    requests.push({url, body: options.body});
    return response(url.endsWith('/pages') ? canonical : {search_id: 'selected'});
  };
  const picking = context.openPick('sideways-local.jpg', {type: 'image/jpeg'}, []);
  await tick();
  assert.equal(element('#cm-boxes').innerHTML, '');
  assert.equal(draws.length, 0);
  for (const id of ['#cm-go', '#cm-crop-go', '#cm-whole', '#cm-rotate']) assert.equal(element(id).disabled, true);
  await context.go({x: .1, y: .2, w: .5, h: .3});
  assert.equal(requests.length, 1, 'a crop cannot be submitted before its image is decoded');
  decoded.resolve();
  await picking;
  assert.equal(element('#cm-photo').src, canonical.image_url);
  assert.match(element('#cm-boxes').innerHTML, /left:10%;top:20%;width:50%;height:30%/);
  assert.equal(draws[0][0], element('#cm-photo'));
  assert.deepEqual(draws[0].slice(1, 5), [200, 200, 1000, 300]);
  assert.equal(element('#cm-rotate').disabled, false);
  await context.go({x: .1, y: .2, w: .5, h: .3});
  assert.deepEqual(JSON.parse(requests[1].body), {page_id: 'oriented', box: [.1, .2, .6, .5]});
  assert.equal(location.href, 'problem.html?search=selected');
});

for (const lateStage of ['upload', 'decode']) test(`a late ${lateStage} cannot replace a newer photo or its page id`, async () => {
  const {context, element, setImageDecode} = setup('camera.js');
  const old = deferred(), posted = [];
  let uploads = 0;
  setImageDecode(image => image.src.includes('/old/') && lateStage === 'decode' ? old.promise : Promise.resolve());
  context.fetch = async (url, options) => {
    if (!url.endsWith('/pages')) { posted.push(JSON.parse(options.body)); return response({search_id: 'new-run'}); }
    if (++uploads === 1) return lateStage === 'upload' ? old.promise : response(cameraPage('old'));
    return response(cameraPage('new'));
  };
  const first = context.openPick('old.jpg', {type: 'image/jpeg'}, []);
  await tick();
  await context.openPick('new.jpg', {type: 'image/jpeg'}, []);
  old.resolve(lateStage === 'upload' ? response(cameraPage('old')) : undefined);
  await first;
  assert.equal(element('#cm-photo').src, '/api/search/pages/new/image');
  await context.go(rect);
  assert.equal(posted[0].page_id, 'new');
});

test('clockwise rotation installs the new raster and fresh coordinates and clears a manual crop', async () => {
  const {context, element, draws, setImageDecode} = setup('camera.js');
  const decoded = deferred(), requests = [];
  const rotated = cameraPage('rotated', [.2, .3, .8, .6], 'manual');
  setImageDecode(image => {
    if (!image.src.includes('/rotated/')) return Promise.resolve();
    image.naturalWidth = 2000; image.naturalHeight = 1000;
    return decoded.promise;
  });
  context.fetch = async (url, options) => {
    requests.push({url, body: options.body});
    return response(url.endsWith('/rotate') ? rotated : url.endsWith('/pages') ? cameraPage('original') : {search_id: 'rotated-run'});
  };
  await context.openPick('original.jpg', {type: 'image/jpeg'}, []);
  context.startCrop();
  assert.equal(element('#cm-crop').hidden, false);
  const rotating = context.rotatePage();
  await tick();
  assert.equal(element('#cm-photo').src, '/api/search/pages/original/image', 'the committed raster stays intact during decode');
  assert.equal(element('#cm-boxes').innerHTML, '');
  assert.equal(element('#cm-crop').hidden, true);
  assert.equal(element('#cm-rotate').disabled, true);
  await context.rotatePage();
  assert.equal(requests.length, 2, 'rotation cannot be queued against an obsolete page');
  decoded.resolve();
  await rotating;
  assert.equal(requests[1].url, '/api/search/pages/original/rotate');
  assert.deepEqual(JSON.parse(requests[1].body), {degrees: 90});
  assert.equal(element('#cm-photo').src, rotated.image_url);
  assert.equal(vm.runInContext('crop', context), null);
  assert.equal(draws.at(-1)[0], element('#cm-photo'));
  const [sx, sy, sw, sh] = draws.at(-1).slice(1, 5);
  for (const [actual, expected] of [[sx, 400], [sy, 300], [sw, 1200], [sh, 300]]) assert.ok(Math.abs(actual - expected) < 1e-9);
  await context.go({x: .2, y: .3, w: .6, h: .3});
  assert.deepEqual(JSON.parse(requests[2].body), {page_id: 'rotated', box: [.2, .3, .8, .6]});
});

for (const failure of ['request', 'image']) test(`rotation ${failure} failure restores the original raster and manual crop for a safe retry`, async () => {
  const {context, element, setImageDecode} = setup('camera.js');
  const posted = [];
  let failing = true;
  setImageDecode(image => image.src.includes('/rotated/') && failing && failure === 'image'
    ? Promise.reject(new Error('Image failed')) : Promise.resolve());
  context.fetch = async (url, options) => {
    if (url.endsWith('/pages')) return response(cameraPage('original'));
    if (url.endsWith('/rotate')) {
      if (failing && failure === 'request') throw new TypeError('Network failed');
      return response(cameraPage('rotated'));
    }
    posted.push(JSON.parse(options.body));
    return response({search_id: 'safe-crop'});
  };
  await context.openPick('original.jpg', {type: 'image/jpeg'}, []);
  context.startCrop({x: .2, y: .3, w: .4, h: .2});
  await context.rotatePage();
  assert.equal(element('#cm-photo').src, '/api/search/pages/original/image');
  assert.equal(element('#cm-crop').hidden, false);
  assert.equal(element('#cm-crop').style.left, '20%');
  assert.match(element('#sq-toast').textContent, /失败.*保留原图和选区/);
  assert.equal(element('#cm-rotate').disabled, failure === 'image');
  await context.go({x: .2, y: .3, w: .4, h: .2});
  assert.equal(posted[0].page_id, 'original');
  failing = false;
  if (failure === 'image') await vm.runInContext('retryAction()', context);
  else await context.rotatePage();
  assert.equal(element('#cm-photo').src, '/api/search/pages/rotated/image');
  assert.equal(element('#cm-crop').hidden, true);
});

for (const outcome of ['success', 'failure']) test(`an obsolete rotation ${outcome} cannot overwrite a replacement upload`, async () => {
  const {context, element} = setup('camera.js');
  const rotated = deferred();
  let uploads = 0;
  context.fetch = async url => url.endsWith('/rotate') ? rotated.promise : response(cameraPage(++uploads === 1 ? 'original' : 'replacement'));
  await context.openPick('original.jpg', {type: 'image/jpeg'}, []);
  const rotating = context.rotatePage();
  await context.openPick('replacement.jpg', {type: 'image/jpeg'}, []);
  rotated.resolve(outcome === 'success' ? response(cameraPage('rotated')) : {ok: false, status: 500});
  await rotating;
  assert.equal(element('#cm-photo').src, '/api/search/pages/replacement/image');
  assert.equal(vm.runInContext('pageId', context), 'replacement');
  assert.equal(element('#cm-rotate').disabled, false);
});

test('a queued crop and late submission response cannot cross into a new upload', async () => {
  const {context, element, location} = setup('camera.js');
  const answer = deferred(), posted = [];
  let uploads = 0;
  context.fetch = async (url, options) => {
    if (url.endsWith('/pages')) return response(cameraPage(`page${++uploads}`));
    posted.push(JSON.parse(options.body));
    return answer.promise;
  };
  await context.openPick('first.jpg', {type: 'image/jpeg'}, []);
  const queued = context.go({x: .1, y: .2, w: .5, h: .3});
  await context.openPick('second.jpg', {type: 'image/jpeg'}, []);
  await queued;
  assert.equal(posted.length, 0, 'a crop queued against a replaced page is discarded before POST');
  const submitted = context.go({x: .2, y: .3, w: .4, h: .2});
  await tick();
  assert.equal(element('#cm-rotate').disabled, true);
  await context.rotatePage();
  assert.equal(posted[0].page_id, 'page2');
  await context.openPick('third.jpg', {type: 'image/jpeg'}, []);
  answer.resolve(response({search_id: 'obsolete'}));
  await submitted;
  assert.equal(location.href, '');
  assert.equal(element('#cm-photo').src, '/api/search/pages/page3/image');
  assert.equal(element('#cm-rotate').disabled, false);
});

test('canonical image failure cannot silently enter the offline prototype or submit stale coordinates', async () => {
  const {context, element, location, imageLoads, setImageDecode} = setup('camera.js');
  let posts = 0, failing = true;
  const canonical = {...cameraPage('canonical'), preview_url: '/api/search/pages/canonical/preview'};
  context.fetch = async () => { posts++; return response(canonical); };
  setImageDecode(image => image.src === canonical.preview_url && failing ? Promise.reject(new Error('Image failed')) : Promise.resolve());
  await context.openPick('local.jpg', {type: 'image/jpeg'}, []);
  await context.go(rect);
  assert.equal(posts, 1);
  assert.equal(location.href, '');
  assert.equal(element('#cm-boxes').innerHTML, '');
  assert.equal(element('#cm-retry').hidden, false);
  assert.equal(element('#cm-whole').disabled, true);
  assert.equal(element('#cm-rotate').disabled, true);
  assert.equal(element('#cm-photo').src, 'local.jpg');
  failing = false;
  await vm.runInContext('retryAction()', context);
  assert.equal(posts, 1, 'image retry must not rerun upload or OCR');
  assert.deepEqual(imageLoads, ['local.jpg', canonical.preview_url, canonical.preview_url]);
  assert.equal(element('#cm-photo').src, canonical.preview_url);
  assert.equal(vm.runInContext('pageId', context), 'canonical');
  assert.equal(element('#cm-retry').hidden, true);
});

test('rotation preview retries preserve the latest selection and never replay the rotation POST', async () => {
  const {context, element, imageLoads, setImageDecode} = setup('camera.js');
  const requests = [];
  const original = cameraPage('original');
  original.regions.push({number: 4, box: [.2, .6, .8, .9]});
  const rotated = {...cameraPage('rotated'), preview_url: '/api/search/pages/rotated/preview'};
  let failing = true;
  setImageDecode(image => image.src === rotated.preview_url && failing ? Promise.reject(new Error('Preview failed')) : Promise.resolve());
  context.fetch = async (url, options) => {
    requests.push({url, body: options.body});
    return response(url.endsWith('/rotate') ? rotated : original);
  };
  await context.openPick('local.jpg', {type: 'image/jpeg'}, []);
  context.startCrop({x: .1, y: .2, w: .3, h: .4});
  await context.rotatePage();
  assert.equal(element('#cm-retry').hidden, false);
  assert.equal(element('#cm-rotate').disabled, true);
  assert.equal(element('#cm-crop-go').disabled, false, 'the restored original crop is still usable');
  await context.rotatePage();
  assert.equal(requests.length, 2, 'a completed rotation is retried through its image loader');
  context.startCrop({x: .4, y: .3, w: .5, h: .2});
  await vm.runInContext('retryAction()', context);
  assert.equal(element('#cm-photo').src, original.image_url);
  assert.equal(element('#cm-crop').style.left, '40%');
  context.endCrop();
  context.select(1);
  await vm.runInContext('retryAction()', context);
  assert.equal(vm.runInContext('selected', context), 1);
  assert.equal(vm.runInContext('crop', context), null);
  assert.equal(element('#cm-crop').hidden, true);
  failing = false;
  await vm.runInContext('retryAction()', context);
  assert.equal(element('#cm-photo').src, rotated.preview_url);
  assert.equal(vm.runInContext('pageId', context), 'rotated');
  assert.equal(element('#cm-retry').hidden, true);
  assert.equal(element('#cm-rotate').disabled, false);
  assert.equal(requests.filter(request => request.url.endsWith('/pages')).length, 1);
  assert.equal(requests.filter(request => request.url.endsWith('/rotate')).length, 1);
  assert.equal(imageLoads.filter(url => url === rotated.preview_url).length, 4);
});

for (const fails of [false, true]) test(`a stale preview retry ${fails ? 'failure' : 'success'} cannot overwrite a new upload`, async () => {
  const {context, element, imageLoads, setImageDecode} = setup('camera.js');
  const retried = deferred();
  let loads = 0, uploads = 0;
  setImageDecode(image => {
    if (!image.src.includes('/original/')) return Promise.resolve();
    if (++loads === 1) return Promise.reject(new Error('Initial preview failed'));
    return retried.promise.then(() => { if (fails) throw new Error('Retry failed'); });
  });
  context.fetch = async () => response(cameraPage(++uploads === 1 ? 'original' : 'replacement'));
  await context.openPick('blob:original', {type: 'image/jpeg'}, []);
  const staleRetry = vm.runInContext('retryAction', context);
  const retrying = staleRetry();
  await context.openPick('blob:replacement', {type: 'image/jpeg'}, []);
  retried.resolve();
  await retrying;
  const count = imageLoads.length;
  await staleRetry();
  assert.equal(imageLoads.length, count, 'an obsolete retry callback cannot start another image request');
  assert.equal(element('#cm-photo').src, '/api/search/pages/replacement/image');
  assert.equal(vm.runInContext('pageId', context), 'replacement');
  assert.equal(element('#cm-retry').hidden, true);
  assert.equal(element('#cm-whole').disabled, false);
  assert.equal(uploads, 2);
});

test('rotation limit preserves the current crop and asks for a new photo without uploading it again', async () => {
  const {context, element} = setup('camera.js');
  const requests = [];
  context.fetch = async url => {
    requests.push(url);
    return url.endsWith('/rotate') ? {ok: false, status: 409, json: async () => ({detail: 'page.rotation_limit'})} : response(cameraPage('limited'));
  };
  await context.openPick('local.jpg', {type: 'image/jpeg'}, []);
  context.startCrop({x: .2, y: .3, w: .4, h: .5});
  await context.rotatePage();
  assert.match(element('#sq-toast').textContent, /旋转次数上限.*重新选择照片/);
  assert.match(element('#cm-proto-note').textContent, /旋转次数上限.*重新选择照片/);
  assert.equal(element('#cm-photo').src, '/api/search/pages/limited/image');
  assert.equal(element('#cm-crop').style.left, '20%');
  assert.equal(element('#cm-crop-go').disabled, false);
  assert.equal(element('#cm-rotate').disabled, true);
  assert.equal(element('#cm-retry').hidden, true);
  await context.rotatePage();
  assert.deepEqual(requests, ['/api/search/pages', '/api/search/pages/limited/rotate']);
});

test('manual-crop click does not pass a browser event as a crop rectangle', () => {
  const {context, element, documentListeners} = setup('camera.js', '?sim=denied');
  documentListeners.get('DOMContentLoaded')();
  let args;
  context.startCrop = (...received) => { args = received; };
  element('#cm-manual').listeners.get('click')({type: 'click', w: 999, x: 12});
  assert.deepEqual(args, []);
});

test('uncertain orientation offers manual rotation and offline fallback has no real page or rotation', async () => {
  const {context, element, location} = setup('camera.js');
  context.fetch = async () => response(cameraPage('uncertain', [.1, .2, .6, .5], 'uncertain'));
  await context.openPick('local.jpg', {type: 'image/jpeg'}, []);
  assert.equal(element('#cm-orientation-note').hidden, false);
  assert.match(element('#cm-orientation-note').textContent, /方向未确定.*顺时针 90°/);
  assert.equal(element('#cm-rotate').disabled, false);
  context.fetch = async () => { throw new TypeError('Offline'); };
  await context.openPick('offline.jpg', {type: 'image/jpeg'}, [{x: .1, y: .2, w: .5, h: .3}]);
  assert.equal(element('#cm-photo').src, 'offline.jpg');
  assert.equal(element('#cm-orientation-note').hidden, true);
  assert.equal(element('#cm-rotate').disabled, true);
  assert.match(element('#cm-proto-note').textContent, /离线原型.*模拟.*暂不支持旋转/);
  assert.match(element('#cm-proto-note').textContent, /后续结果均为模拟，不识别这张照片/);
  for (const id of ['#cm-go', '#cm-crop-go']) assert.match(element(id).innerHTML, /查看模拟流程/);
  assert.equal(element('#cm-whole').textContent, '整图查看模拟流程');
  assert.equal(vm.runInContext('pageId', context), null);
  await context.go(rect);
  assert.equal(location.href, 'problem.html?demo=ok&fresh=1');
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

test('stage-two readiness keeps monitoring execution after the mathematical stream has an identity', async () => {
  const {context, delays} = setup('problem.js', '?search=0123456789ab');
  const shown = [], requests = [];
  context.showLesson = lesson => shown.push(lesson);
  context.fetch = async (url, options = {}) => {
    requests.push({url, options});
    assert.ok(requests.length <= 3);
    return response({lesson: {status: 'completed', goals: [{target_ref: '/root/goals/0'}],
      execution_status: ['starting', 'running', 'completed'][requests.length - 1],
      stream: requests.length === 1 ? null : {run_id: 'same-run'}}});
  };
  await context.pollLesson();
  assert.equal(shown.length, 3);
  assert.equal(shown.at(-1).stream.run_id, 'same-run');
  assert.deepEqual(delays, [800, 800, 3000]);
  assert.ok(requests.every(request => !request.options.method), 'metadata polling is read-only');
});

test('an explicit continuation resumes the current run without discarding its stream view', async () => {
  const {context, element} = setup('problem.js', '?search=0123456789ab');
  const requests = [];
  const monitoring = deferred();
  context.monitoring = monitoring.promise;
  context.refreshed = 0;
  context.fetch = async (url, options) => { requests.push({url, options}); return response({status: 'running'}); };
  vm.runInContext(`lesson.data = {stream: {run_id: 'preserved-run', snapshot_url: '/api/search/problems/0123456789ab/lesson/preserved-run/snapshot'}};
    pollLesson = () => monitoring; streamTransport = {refresh: async () => { refreshed++; }};`, context);
  const continuing = context.continueCalculation();
  await tick();
  try {
    assert.equal(context.refreshed, 1, 'snapshot refresh must not wait for the execution monitor to finish');
    assert.equal(element('#pq-stream-action').disabled, false);
  } finally { monitoring.resolve(); }
  await continuing;
  assert.deepEqual(JSON.parse(JSON.stringify(requests)), [{url: '/api/search/problems/0123456789ab/lesson/preserved-run/resume', options: {method: 'POST'}}]);
  assert.equal(vm.runInContext('lesson.data.stream.run_id', context), 'preserved-run');
  assert.equal(element('#pq-stream-action').disabled, false);
});

function streamedLesson(execution_status) {
  return {status: 'completed', execution_status,
    stream: {run_id: 'same-run', lesson_version: 'v1'},
    goals: [{target_ref: '/root/goals/0', scope: '/root', status: 'resolved',
      walk: {bundle: {bundleVersion: 'v1'}}}]};
}

function seedOpenStream(context, element) {
  context.initialLesson = streamedLesson('running');
  context.remounts = 0;
  context.lost = 0;
  vm.runInContext(`lesson.data = initialLesson; lesson.part = 0; lesson.opened = true; lesson.mounted = true;
    openPart = () => { remounts++; }; lessonLost = () => { lost++; };`, context);
  element('#pq-stream').hidden = false;
  element('#pq-stream').innerHTML = 'committed mathematical cards';
}

for (const terminal of ['interrupted', 'error', 'completed', 'partial', 'failed']) {
  test(`a quiet stream notices ${terminal} without remounting committed cards`, async () => {
    const {context, element, delays} = setup('problem.js', '?search=0123456789ab');
    seedOpenStream(context, element);
    let gets = 0;
    context.fetch = async (url, options) => {
      assert.equal(url, '/api/search/problems/0123456789ab');
      assert.equal(options.method, undefined, 'monitoring must not resume computation');
      assert.ok(++gets <= 2, 'execution terminal state ends metadata monitoring');
      return response({lesson: streamedLesson(gets === 1 ? 'running' : terminal)});
    };
    await context.pollLesson();
    assert.equal(vm.runInContext('lesson.data.execution_status', context), terminal);
    assert.equal(element('#pq-stream-action').hidden, !['interrupted', 'error'].includes(terminal));
    assert.equal(element('#pq-stream-action').textContent, '继续计算');
    assert.equal(context.remounts, 0);
    assert.equal(context.lost, 0);
    assert.equal(element('#pq-stream').innerHTML, 'committed mathematical cards');
    assert.equal(element('#pq-stream').hidden, false);
    assert.deepEqual(delays, [3000, 3000]);
  });
}

test('opening a page with an existing running stream starts metadata monitoring', async () => {
  const {context, element} = setup('problem.js', '?search=0123456789ab');
  seedOpenStream(context, element);
  context.settle = () => {};
  context.devCheck = () => {};
  const pollLesson = context.pollLesson;
  let monitoring;
  context.pollLesson = () => (monitoring = pollLesson());
  let gets = 0;
  context.fetch = async (_url, options) => {
    assert.equal(options.method, undefined);
    assert.ok(++gets <= 2);
    return response({state: 'done', outcome: 'ok', lesson: streamedLesson(gets === 1 ? 'running' : 'interrupted')});
  };
  await context.runLive();
  assert.ok(monitoring, 'initially readable streams still need execution monitoring');
  await monitoring;
  assert.equal(element('#pq-stream-action').hidden, false);
  assert.equal(context.remounts, 0);
});

test('metadata outages preserve the stream and keep monitoring until an interruption is visible', async () => {
  const {context, element, delays} = setup('problem.js', '?search=0123456789ab');
  seedOpenStream(context, element);
  let gets = 0;
  context.fetch = async () => {
    if (++gets <= 12) throw new TypeError('Failed to fetch');
    assert.equal(gets, 13);
    return response({lesson: streamedLesson('interrupted')});
  };
  await context.pollLesson();
  assert.equal(gets, 13);
  assert.equal(context.lost, 0);
  assert.equal(context.remounts, 0);
  assert.equal(element('#pq-stream').innerHTML, 'committed mathematical cards');
  assert.equal(element('#pq-stream-action').hidden, false);
  assert.deepEqual(delays, Array(13).fill(3000));
});

test('a replaced status monitor cannot overwrite newer execution metadata', async () => {
  const {context, element} = setup('problem.js', '?search=0123456789ab');
  seedOpenStream(context, element);
  const old = deferred();
  let gets = 0;
  context.fetch = async () => ++gets === 1 ? old.promise : response({lesson: streamedLesson('error')});
  const first = context.pollLesson();
  await tick();
  await context.pollLesson();
  old.resolve(response({lesson: streamedLesson('running')}));
  await first;
  assert.equal(gets, 2);
  assert.equal(vm.runInContext('lesson.data.execution_status', context), 'error');
  assert.equal(element('#pq-stream-action').hidden, false);
});

test('reconnecting the metadata monitor preserves an existing stream view', async () => {
  const {context, element} = setup('problem.js', '?search=0123456789ab');
  seedOpenStream(context, element);
  context.monitors = 0;
  context.pollLesson = async () => { context.monitors++; };
  context.resumeLesson();
  assert.equal(context.monitors, 1);
  assert.equal(vm.runInContext('lesson.data.stream.run_id', context), 'same-run');
  assert.equal(element('#pq-stream').hidden, false);
  assert.equal(context.remounts, 0);
});

test('late selection for a previous question cannot replace an unsupported or different current question', () => {
  const {context} = setup('problem.js', '?search=0123456789ab');
  context.updates = 0;
  vm.runInContext(`lesson.part = 1;
    lesson.data = {stream: {run_id: 'run'}, goals: [{target_ref: '/root/goals/0', walk: {}},
      {target_ref: '/root/children/0/goals/0', status: 'unsupported'}]};
    lesson.engine = {walkView: () => ({target_ref: '/root/goals/0'}), updateStreamSelection: async () => { updates++; }};`, context);
  context.updateStreamView({run_id: 'run'});
  assert.equal(context.updates, 0);
  vm.runInContext(`lesson.data.goals[1].walk = {};`, context);
  context.updateStreamView({run_id: 'run'});
  assert.equal(context.updates, 0);
  vm.runInContext(`lesson.part = 0;`, context);
  context.updateStreamView({run_id: 'run'});
  assert.equal(context.updates, 1);
});

test('late interactions and route completion refresh the engine while QA has an independent attachment path', async () => {
  const {context} = setup('problem.js', '?search=0123456789ab');
  context.updated = [];
  context.attached = [];
  vm.runInContext(`lesson.part = 0;
    lesson.data = {stream: {run_id: 'run', lesson_version: 'v1'},
      goals: [{target_ref: '/root/goals/0', walk: {}}]};
    lesson.engine = {walkView: () => ({target_ref: '/root/goals/0'}),
      updateStreamSelection: async view => { updated.push(view); },
      attachStreamQA: chunk => { attached.push(chunk); }};`, context);
  const initial = {run_id: 'run', lesson_version: 'v1', math_steps: [], selection_chunks: [], qa: []};
  context.updateStreamView(initial);
  await tick();
  const exercises = {...initial, interactions: [{interaction_id: 'one'}], interaction_states: [{status: 'interactive'}]};
  context.updateStreamView(exercises);
  await tick();
  const completed = {...exercises, completions: [{route_id: 'interval', available: true}]};
  context.updateStreamView(completed);
  await tick();
  assert.equal(context.updated.length, 3, 'late interaction and completion each refresh without intro changes');
  context.updateStreamView({...completed, qa: [{step_id: 'first', qa: {questions: ['why?']}}]});
  await tick();
  assert.equal(context.updated.length, 3, 'QA alone does not refresh the whole engine');
  assert.equal(context.attached.length, 1);
  context.updateStreamView({...completed, lesson_version: 'obsolete', qa: [{step_id: 'old'}]});
  await tick();
  assert.equal(context.attached.length, 1, 'an obsolete lesson cannot attach questions');
});
