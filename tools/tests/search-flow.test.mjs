import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

function setup(file, search = '') {
  const nodes = new Map();
  const delays = [];
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
    setTimeout: (callback, delay) => { delays.push(delay); if (delay !== 2400) callback(); return 1; }, clearTimeout() {},
    sessionStorage: {getItem() { return null; }, setItem() {}, removeItem() {}},
    document: {
      body: {dataset: {}}, querySelector: element,
      querySelectorAll: selector => selector === '#pq-phases li' ? [0, 1, 2].map(i => element(`phase${i}`)) : [],
      createElement: element, addEventListener() {},
    },
  });
  vm.runInContext(fs.readFileSync(new URL(`../../site/lab/search/${file}`, import.meta.url), 'utf8'), context);
  return {context, element, location, delays};
}

const crop = {page_id: '123456789abc', box: [0, 0, 1, 1]};
const rect = {x: 0, y: 0, w: 1, h: 1};
const response = value => ({ok: true, json: async () => value});
const page = {page_id: crop.page_id, latency_ms: {detect: 1000}, regions: [], mode: 'whole_content'};
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
