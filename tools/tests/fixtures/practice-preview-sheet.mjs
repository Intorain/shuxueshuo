// Exercise the real sheet controller with failing resource/text transports.
// Only the DOM surface and transport are substituted; browser checks cover layout.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import vm from 'node:vm';
import { repoRoot, generate } from '../../build-public-knowledge-graph.mjs';
import * as selectors from '../../../site/assets/knowledge-next/teaching-model.mjs';
import * as model from '../../../site/assets/knowledge-next/model.mjs';
import * as links from '../../../site/assets/knowledge-next/resource-links.mjs';

class Element {
  constructor() {
    this.children = new Map();
    this.listeners = {};
    this.hidden = false;
    this.textContent = '';
  }
  set innerHTML(value) {
    this.html = value;
    this.children.clear();
  }
  get innerHTML() {
    return this.html || '';
  }
  querySelector(selector) {
    if (!this.children.has(selector)) this.children.set(selector, new Element());
    return this.children.get(selector);
  }
  querySelectorAll() {
    return [];
  }
  setAttribute() {}
  addEventListener(type, fn) {
    this.listeners[type] = fn;
  }
  append(child) {
    this.lastChild = child;
    (this.appended ||= []).push(child);
  }
  insertAdjacentHTML(_position, html) {
    this.html = html + this.innerHTML;
  }
  showModal() {
    this.open = true;
  }
  close() {
    this.open = false;
    this.listeners.close?.();
  }
}
const { outputs, teaching } = await generate();
const lesson = teaching.lessons.get('basic-inequality-q01');
const problem = JSON.parse(outputs.get('teaching/problems/basic-inequality-q01.json'));
const tip = problem.routes.direct.steps.structure.tip;
let diagramFails = true,
  resourceFails = true,
  textFails = false,
  unmounts = 0;
const requests = [],
  stripped = [],
  mounts = [],
  document = new Element();
document.body = new Element();
document.createElement = () => new Element();
document.getElementById = id => document.querySelector('#' + id);
const scope = vm.createContext({
  document,
  window: {},
  URL,
  location: { href: 'http://localhost/1/q01/?knowledge=next', origin: 'http://localhost' },
  DOMParser: class {
    parseFromString(html) {
      return {
        querySelectorAll: (selector) => {
          stripped.push(selector);
          return [];
        },
        querySelector: () => null,
        getElementById: () => ({ outerHTML: html }),
        body: { innerHTML: html }
      };
    }
  },
  fetch: async (url) => {
    requests.push(url);
    const file = url.replace('/knowledge/', '');
    const isDetail = file.startsWith('teaching/nodes/');
    const failed = (isDetail && textFails) || (file.startsWith('teaching/resources/') && resourceFails);
    return {
      ok: !failed,
      status: failed ? 503 : 200,
      json: async () =>
        file === 'teaching/problems/basic-inequality-q01.json' ? problem : JSON.parse(outputs.get(file))
    };
  }
});
const dependencies = {
  './teaching-model.mjs': selectors,
  './model.mjs': model,
  './resource-links.mjs': links,
  './resource-runtime.mjs': {
    stylesheet: async () => {},
    mountResource: async (_root, _resource, options) => {
      mounts.push(options);
      if (diagramFails) throw Error('offline');
      return () => {
        unmounts++;
      };
    }
  }
};
const source = await fs.readFile(repoRoot + '/site/assets/knowledge-next/practice-preview.mjs', 'utf8');
const module = new vm.SourceTextModule(source, {
  context: scope,
  initializeImportMeta: (meta) => {
    meta.url = 'http://localhost/assets/knowledge-next/practice-preview.mjs';
  }
});
await module.link(
  (spec) =>
    new vm.SyntheticModule(
      Object.keys(dependencies[spec]),
      function () {
        for (const [key, value] of Object.entries(dependencies[spec])) this.setExport(key, value);
      },
      { context: scope }
    )
);
await module.evaluate();
const shown = [];
const previewHost = new Element();
const preview = await module.namespace.createPreview(lesson, previewHost, {onShown:(view, stage, tip) => shown.push({view, stage, tip})});
const snapshot = (active) => ({ state: { method: 'direct', active, choices: {} } });
const unlocked = (detail) => !detail.innerHTML.includes('kxp-locked') && /<(article|section|ol|ul|p)\b/.test(detail.innerHTML);
preview.update(snapshot(0));
assert.match(previewHost.lastChild.innerHTML, /href="\/knowledge\/topics\/basic-inequality\/review\/\?preview=1">关联审阅表/);
assert.match(previewHost.lastChild.innerHTML, /<button type="button" class="kxp-chip"[^>]*data-node-ref="type-sum-product-extremum"/);
await preview.openStep('direct', 0, snapshot(0));
const body = document.body.lastChild.querySelector('.kxp-sheet-body');
assert.equal(requests.filter((u) => u.includes('/nodes/')).length, 0);
assert.equal(mounts.length, 0);
assert.equal(shown.length, 0);
assert.match(body.querySelector('.kxp-detail').innerHTML, /kxp-locked/);
assert.match(body.querySelector('.kxp-load-status').textContent, /图解加载失败/);
assert.deepEqual(
  requests.filter((u) => u.includes('/resources')),
  [`/knowledge/teaching/resources/${tip.resource}.json`]
);
resourceFails = false;
await body.querySelector('.kxp-retry').onclick();
assert.equal(mounts.at(-1).tip, null);
assert.match(body.querySelector('.kxp-load-status').textContent, /图解加载失败/);

await preview.openStep('direct', 0, snapshot(1));
assert.ok(unlocked(body.querySelector('.kxp-detail')));
// A tip's worked examples may include this very problem's solution.
assert.ok(stripped.at(-1).split(',').includes('#examples'), '学习提示正文去掉题例');
assert.match(body.querySelector('.kxp-load-status').textContent, /图解加载失败/);
assert.equal(body.querySelector('.kxp-retry').hidden, false);
diagramFails = false;
await body.querySelector('.kxp-retry').onclick();
assert.equal(body.querySelector('.kxp-load-status').textContent, '');
assert.equal(body.querySelector('.kxp-retry').hidden, true);
assert.equal(mounts.at(-1).retry, true);
assert.equal(shown.length, 1);
assert.equal(shown[0].stage, 0);
assert.equal(shown[0].tip.ref, tip.ref);
assert.equal(
  requests.filter((u) => u.includes('/resources/')).length,
  2,
  '只重试失败的资源文件；成功后同页复用'
);
assert.ok(!requests.includes('/knowledge/teaching/resources.json'));

textFails = true;
await preview.openStep('direct', 0, snapshot(1));
assert.match(body.querySelector('.kxp-load-status').textContent, /正文加载失败/);
assert.ok(body.querySelector('.kxp-resource').innerHTML.length > 0);
assert.ok(unmounts > 0);
textFails = false;
delete tip.resource;
delete tip.case;
const before = mounts.length;
await preview.openStep('direct', 0, snapshot(1));
assert.equal(mounts.length, before);
assert.equal(body.querySelector('.kxp-load-status').textContent, '');
assert.ok(unlocked(body.querySelector('.kxp-detail')));

// Viewing a safe candidate is recorded as a display, not as adopting its branch.
const candidateStage = lesson.routes.elimination.findIndex(step => step.id === 'quadratic');
const candidateView = {state:{method:'elimination', active:candidateStage, choices:{}}};
await preview.openStep('elimination', candidateStage, candidateView);
const countBeforeCandidate = shown.length;
await body.querySelector('.kxp-tip-options').lastChild.onclick();
assert.equal(shown.length, countBeforeCandidate + 1);
assert.equal(shown.at(-1).stage, candidateStage);
assert.equal(shown.at(-1).view, candidateView);

await assert.rejects(
  module.namespace.createPreview(lesson, new Element(), {learning:true, expectedContentVersion:'stale'}),
  error => error.code === 'content_version_mismatch'
);

// Problem-level chips open node details in the same sheet instead of navigating.
const dialog = document.body.lastChild;
const title = () => dialog.querySelector('#kxp-sheet-title').textContent;
dialog.close();
await preview.openNode('type-sum-product-extremum');
assert.equal(dialog.open, true);
assert.match(title(), /和积/);
assert.ok(requests.includes('/knowledge/teaching/nodes/type-sum-product-extremum.json'));
assert.equal(dialog.querySelector('.kxp-back').hidden, true);
assert.match(dialog.querySelector('.kxp-sheet-foot').innerHTML, /href="\/knowledge\/type-sum-product-extremum\/\?preview=1" target="_blank"/);
textFails = true;
await preview.openNode('method-amgm-direct');
assert.equal(dialog.querySelector('.kxp-back').hidden, false);
assert.match(dialog.querySelector('.kxp-sheet-body').querySelector('.kxp-detail').innerHTML, /详细内容加载失败/);
textFails = false;
await dialog.querySelector('.kxp-sheet-body').querySelector('.kxp-retry').onclick();
assert.doesNotMatch(dialog.querySelector('.kxp-sheet-body').querySelector('.kxp-detail').innerHTML, /加载失败/);
assert.equal(dialog.querySelector('.kxp-back').hidden, false, '重试不重复记入返回栈');
await dialog.querySelector('.kxp-back').onclick();
assert.match(title(), /和积/);
assert.equal(dialog.querySelector('.kxp-back').hidden, true);
// Links anywhere in the sheet body, diagrams included, never navigate the exercise away.
const click = (href, extra = {}) => {
  const link = { getAttribute: () => href, target: '' };
  const event = { target: { closest: (selector) => (selector.includes('.kxp-sheet-body') ? link : null) },
    preventDefault() { this.prevented = true; }, ...extra };
  dialog.listeners.click(event);
  return { link, event };
};
let followed = click('/knowledge/method-amgm-direct/');
assert.equal(followed.event.prevented, true);
await new Promise((resolve) => setTimeout(resolve));
assert.match(title(), /基本不等式|均值|直接/);
assert.equal(dialog.querySelector('.kxp-back').hidden, false);
followed = click('/1/q05/');
assert.equal(followed.event.prevented, undefined);
assert.equal(followed.link.target, '_blank');
followed = click('/knowledge/method-amgm-direct/', { metaKey: true });
assert.equal(followed.event.prevented, undefined);
assert.equal(followed.link.target, '_blank');
followed = click('/knowledge/method-amgm-direct/', { defaultPrevented: true });
assert.equal(followed.link.target, '', '图解自己处理的点击不再接管');
// Same-attempt progress keeps the sheet; switching route closes it.
preview.update(snapshot(1));
assert.equal(dialog.open, true);
preview.update({state:{method:'elimination', active:0, choices:{}}});
assert.equal(dialog.open, false);
console.log('sheet boundaries, independent failures, retry, text-only fallback and in-place node sheet: passed');

// Restored standard answers are UI conclusions, not confirmed student selections.
const q30Lesson = teaching.lessons.get('basic-inequality-q30');
let confirmed = {};
let passedFields = [];
const learning = await module.namespace.createPreview(q30Lesson, new Element(), {
  learning:true, getConfirmedChoices:() => confirmed, getPassedFields:() => passedFields});
const q30Stage = q30Lesson.routes.symmetric.findIndex(step => step.id === 'inequality');
const restored = {state:{method:'symmetric', active:q30Stage + 1, choices:{inequality_form:'p_le'}}};
await learning.openStep('symmetric', q30Stage, restored);
assert.match(document.body.lastChild.querySelector('.kxp-sheet-body').textContent, /还没保存到账号/);
await learning.openStep('symmetric', q30Stage, {state:{...restored.state, active:q30Stage}});
assert.match(document.body.lastChild.querySelector('.kxp-sheet-body').textContent, /作答后显示/);
// A server-confirmed LLM completion unlocks the candidates, but does not turn
// the restored p_le value into a real selected branch.
passedFields = ['inequality_form'];
await learning.openStep('symmetric', q30Stage, restored);
const completedBody = document.body.lastChild.querySelector('.kxp-sheet-body');
assert.match(completedBody.innerHTML, /本步已通过，但没有记录具体选择/);
assert.equal(completedBody.querySelector('.kxp-tip-options').appended.length, 2);
await completedBody.querySelector('.kxp-tip-options').lastChild.onclick();
assert.ok(unlocked(completedBody.querySelector('.kxp-tip-content').querySelector('.kxp-detail')));
confirmed = {inequality_form:'p_le'};
await learning.openStep('symmetric', q30Stage, restored);
assert.ok(document.body.lastChild.querySelector('.kxp-sheet-body').innerHTML.includes('kx'));

const chips = (html) => [...html.matchAll(/class="kxp-chip( is-current)?"[^>]*data-node-ref="([^"]+)"/g)]
  .map(([, current, ref]) => (current ? '*' : '') + ref);
// Formal guests and sessions without a recorder retain local passed-branch
// hints, while formal navigation stays out of preview mode.
for (const [pid, rid, stepId] of [
  ['basic-inequality-q01', 'elimination', 'quadratic'],
  ['basic-inequality-q09', 'elimination', 'quadratic'],
  ['basic-inequality-q30', 'symmetric', 'inequality']
]) {
  const currentLesson = teaching.lessons.get(pid);
  const route = currentLesson.routes[rid];
  const stage = route.findIndex(step => step.id === stepId);
  const local = {state:{method:rid, active:stage + 1, choices:Object.fromEntries(
    route.slice(0, stage + 1).filter(step => step.interaction.type === 'choice')
      .map(step => [step.interaction.field, step.expected_answer.one_of[0]])
  )}};
  let recording = false;
  const host = new Element();
  const guest = await module.namespace.createPreview(currentLesson, host, {
    learning:true, useServerProgress:() => recording,
    getConfirmedChoices:() => ({}), getPassedFields:() => []
  });
  guest.update(local);
  // The formal bar is one line of type/method buttons: no links, no review aids.
  assert.doesNotMatch(host.lastChild.innerHTML, /<a |preview=1|作答后显示|候选关联|关联审阅表/, pid);
  const picked = {square:'method-square-extremum', vertex:'method-quadratic-extremum'}[local.state.choices.technique];
  assert.deepEqual(chips(host.lastChild.innerHTML), pid === 'basic-inequality-q30'
    ? ['type-sum-product-extremum', '*method-sum-product-range', 'method-amgm-direct']
    : ['type-sum-product-extremum', 'method-amgm-direct', `*${picked}`], pid);
  await guest.openStep(rid, stage, local);
  let sheet = document.body.lastChild.querySelector('.kxp-sheet-body');
  assert.ok(unlocked(sheet.querySelector('.kxp-detail')), pid);
  assert.doesNotMatch(sheet.innerHTML, /候选提示/, pid);

  // Switching to a live recorder immediately uses confirmed history instead of
  // accepting local/restored answers while the server has not confirmed them.
  recording = true;
  guest.update(local);
  // Unconfirmed branches list every candidate method, none marked as current.
  assert.deepEqual(chips(host.lastChild.innerHTML), pid === 'basic-inequality-q30'
    ? ['type-sum-product-extremum', '*method-sum-product-range', 'method-amgm-direct']
    : ['type-sum-product-extremum', 'method-amgm-direct', 'method-square-extremum', 'method-quadratic-extremum'], pid);
  await guest.openStep(rid, stage, local);
  sheet = document.body.lastChild.querySelector('.kxp-sheet-body');
  assert.ok(/候选提示|还没保存到账号/.test(sheet.innerHTML + sheet.textContent), pid);

  if (pid === 'basic-inequality-q30') {
    recording = false;
    local.state.active = stage;
    // All draft choices, including correct ones, remain indistinguishable.
    for (const option of route[stage].interaction.options) {
      local.state.choices.inequality_form = option.value;
      await guest.openStep(rid, stage, local);
      assert.match(document.body.lastChild.querySelector('.kxp-sheet-body').textContent, /作答后显示/);
    }
  }
}
console.log('formal guest Q01/Q09/Q30 passed choices, draft boundaries and dynamic recorder authority: passed');
