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
  mounts = [],
  document = new Element();
document.body = new Element();
document.createElement = () => new Element();
const scope = vm.createContext({
  document,
  window: {},
  URL,
  location: { href: 'http://localhost/1/q01/?knowledge=next', origin: 'http://localhost' },
  DOMParser: class {
    parseFromString(html) {
      return {
        querySelectorAll: () => [],
        getElementById: () => ({ outerHTML: html }),
        body: { innerHTML: html }
      };
    }
  },
  fetch: async (url) => {
    requests.push(url);
    const file = url.replace('/knowledge-next/', '');
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
    meta.url = 'http://localhost/knowledge-next/assets/test/practice-preview.mjs';
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
const preview = await module.namespace.createPreview(lesson, new Element(), {onShown:(view, stage, tip) => shown.push({view, stage, tip})});
const snapshot = (active) => ({ state: { method: 'direct', active, choices: {} } });
await preview.openStep('direct', 0, snapshot(0));
const body = document.body.lastChild.querySelector('.kxp-sheet-body');
assert.equal(requests.filter((u) => u.includes('/nodes/')).length, 0);
assert.equal(mounts.length, 0);
assert.equal(shown.length, 0);
assert.doesNotMatch(body.querySelector('.kxp-detail').innerHTML, /本题/);
assert.match(body.querySelector('.kxp-load-status').textContent, /图解加载失败/);
assert.deepEqual(
  requests.filter((u) => u.includes('/resources')),
  [`/knowledge-next/teaching/resources/${tip.resource}.json`]
);
resourceFails = false;
await body.querySelector('.kxp-retry').onclick();
assert.equal(mounts.at(-1).tip, null);
assert.match(body.querySelector('.kxp-load-status').textContent, /图解加载失败/);

await preview.openStep('direct', 0, snapshot(1));
assert.match(body.querySelector('.kxp-detail').innerHTML, /本题/);
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
assert.ok(!requests.includes('/knowledge-next/teaching/resources.json'));

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
assert.match(body.querySelector('.kxp-detail').innerHTML, /本题/);

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
console.log('sheet boundaries, independent failures, retry and text-only fallback: passed');

// Restored standard answers are UI conclusions, not confirmed student selections.
const q30Lesson = teaching.lessons.get('basic-inequality-q30');
let confirmed = {};
let passedFields = [];
const learning = await module.namespace.createPreview(q30Lesson, new Element(), {
  learning:true, getConfirmedChoices:() => confirmed, getPassedFields:() => passedFields});
const q30Stage = q30Lesson.routes.symmetric.findIndex(step => step.id === 'inequality');
const restored = {state:{method:'symmetric', active:q30Stage + 1, choices:{inequality_form:'p_le'}}};
await learning.openStep('symmetric', q30Stage, restored);
assert.match(document.body.lastChild.querySelector('.kxp-sheet-body').textContent, /作答后显示/);
// A server-confirmed LLM completion unlocks the candidates, but does not turn
// the restored p_le value into a real selected branch.
passedFields = ['inequality_form'];
await learning.openStep('symmetric', q30Stage, restored);
const completedBody = document.body.lastChild.querySelector('.kxp-sheet-body');
assert.match(completedBody.innerHTML, /本步已通过，但没有记录具体选择/);
assert.equal(completedBody.querySelector('.kxp-tip-options').appended.length, 2);
await completedBody.querySelector('.kxp-tip-options').lastChild.onclick();
assert.ok(completedBody.querySelector('.kxp-tip-content').querySelector('.kxp-detail').innerHTML.includes('本题'));
confirmed = {inequality_form:'p_le'};
await learning.openStep('symmetric', q30Stage, restored);
assert.ok(document.body.lastChild.querySelector('.kxp-sheet-body').innerHTML.includes('kx'));
