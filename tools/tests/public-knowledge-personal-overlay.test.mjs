import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import vm from 'node:vm';
import {bindPersonalOverlay} from '../../site/assets/knowledge-next/personal-overlay.mjs';
import {createPersonalState} from '../../site/assets/knowledge-next/personal-state.mjs';
import {escapeHtml} from '../../site/assets/knowledge-next/resource-links.mjs';

// Small DOM fixture: tests exercise visible state without needing WebGL or a browser.
class Element {
  constructor(tag = 'span', namespaceURI = '') {
    this.tagName = tag; this.namespaceURI = namespaceURI; this.dataset = {};
    this.children = []; this.className = ''; this.classList = {add:()=>{}}; this.attrs = {};
  }
  setAttribute(key,value) { this.attrs[key]=value; if(key==='class')this.className=value; }
  hasAttribute(key) { return key in this.attrs; }
  append(...children) { children.forEach(child => { child.parent=this; this.children.push(child); }); }
  replaceChildren(...children) { this.children=[]; this._text=''; this.append(...children); }
  remove() { this.parent.children=this.parent.children.filter(child => child!==this); }
  set textContent(text) { this._text=text; this.children=[]; }
  get textContent() { return (this._text || '') + this.children.map(child => child.textContent).join(''); }
  querySelectorAll() { return this.children.filter(child => /kx-personal-(badge|mark)/.test(child.className)); }
  closest(selector) {
    const attr = /^\[([^\]]+)\]$/.exec(selector)?.[1];
    for (let host = this; host; host = host.parent) {
      if (attr ? host.hasAttribute(attr) : host.tagName === selector) return host;
    }
    return null;
  }
}
const tick = () => new Promise(resolve => setImmediate(resolve));
function dom() {
  const previous = {document:globalThis.document,MutationObserver:globalThis.MutationObserver};
  const observer = {callback:null};
  globalThis.document = {createElement:tag => new Element(tag),createElementNS:(ns,tag) => new Element(tag,ns)};
  globalThis.MutationObserver = class {constructor(fn) { observer.callback=fn; } observe() {} disconnect() {}};
  const targets=[], scopes=[];
  return {targets,scopes,observer,root:{querySelectorAll:selector => selector==='[data-progress-scope]' ? scopes : targets},
    restore() { Object.assign(globalThis,previous); }};
}

for (const namespace of ['', 'http://www.w3.org/2000/svg']) test(`overlay removes old badges on account change before replacement arrives (${namespace ? 'SVG' : 'HTML'})`, async () => {
  const fixture=dom(); let resolveNext;
  const store=createPersonalState({loadVersion:async () => 'v',request:async (path,{user}) => {
    if(user==='second')return new Promise(resolve => {resolveNext=resolve;});
    return {content_version:'v',nodes:[{node_id:'skill',kind:'skill',status:'mastered'}]};
  }});
  const host=new Element('g',namespace); host.dataset.learningNode='skill';
  const rule=new Element(); rule.dataset.learningNode='rule';
  fixture.targets.push(host,rule);
  const dispose=bindPersonalOverlay(store,fixture.root);
  try {
    await store.setUser({id:'first'}); await tick();
    assert.equal(host.children.length,1); assert.equal(rule.children.length,0);
    assert.match(host.children[0].attrs['aria-label'],/已掌握/);
    const next=store.setUser({id:'second'}); await tick();
    assert.equal(host.children.length,0);
    resolveNext({content_version:'v',nodes:[{node_id:'skill',kind:'skill',status:'unassessed'}]});
    await next; await tick(); assert.equal(host.children.length,0,'未检测是大多数节点的默认状态，图上不标');
    const panel=new Element('div',namespace); panel.dataset.learningNode='skill'; panel.dataset.learningFull='';
    fixture.targets.push(panel); fixture.observer.callback(); await tick();
    assert.match(panel.children[0].attrs['aria-label'],/未检测/);
    await store.setUser(null); await tick(); assert.equal(host.children.length,0); assert.equal(panel.children.length,0);
  } finally { dispose(); fixture.restore(); }
});

test('dynamic labels reuse loaded assessments and directory failures expose retry without fabricated counts', async () => {
  const fixture=dom(); let fail=true, nodeCalls=0;
  const group={total:1,eligible:1,statuses:{mastered:1,needs_review:0,unassessed:0}};
  const store=createPersonalState({loadVersion:async () => 'v',request:async path => {
    if(path==='/nodes'){nodeCalls++;return {content_version:'v',nodes:[{node_id:'skill',kind:'skill',status:'mastered'}]};}
    if(fail)throw Error('offline');
    return {content_version:'v',progress:[{scope:'chapter',contains:group,extends:{...group,total:0,statuses:{mastered:0,needs_review:0,unassessed:0}}}]};
  }});
  const dispose=bindPersonalOverlay(store,fixture.root);
  try {
    await store.setUser({id:'first'}); await tick();
    const dynamic=new Element(); dynamic.dataset.directoryNode='skill';
    const scope=new Element(); scope.dataset.progressScope='chapter';
    fixture.targets.push(dynamic); fixture.scopes.push(scope); fixture.observer.callback(); await tick(); await tick();
    assert.equal(nodeCalls,1); assert.match(dynamic.textContent,/已掌握/);
    assert.match(scope.textContent,/暂不可用/); assert.doesNotMatch(scope.textContent,/未检测/);
    const retry=scope.children.find(child => child.tagName==='button'); assert.ok(retry);
    fail=false; await retry.onclick(); await tick(); assert.match(scope.textContent,/课内 1 个/); assert.doesNotMatch(scope.textContent,/拓展/, '没有拓展内容时不显示这一组');
    await store.setEnabled(false); await tick(); assert.equal(scope.hidden,true); assert.equal(dynamic.children.length,0);
  } finally { dispose(); fixture.restore(); }
});

test('tower progress retry is a sibling native button and mouse or keyboard activation does not enter the tower', async () => {
  const source = await fs.readFile(new URL('../../site/assets/knowledge-next/tower-view.mjs', import.meta.url), 'utf8');
  const fixture = dom(), callbacks = new Map(), entered = [];
  let html, fail = true, progressCalls = 0;
  // Render the production chapter-label template, without starting WebGL.
  vm.runInNewContext(source.split('\n').find(line => line.includes('const cityLabel = label(')), {
    group:{}, chapterId:'chapter-id', color:'#2dd4bf', top:100,
    c:{label:'二次函数',node:'chapter',built:true}, h:escapeHtml,
    chapterName:() => '第二章', nodeCount:() => 5,
    THREE:{Vector3:class {}}, label(_group, markup) { html = markup; }
  });
  const stack = [new Element('root')], elements = [];
  for (const token of html.matchAll(/<\/?([\w-]+)([^>]*)>|([^<]+)/g)) {
    if (token[3]) continue;
    if (token[0].startsWith('</')) { stack.pop(); continue; }
    const element = new Element(token[1]);
    for (const attr of token[2].matchAll(/([\w-]+)(?:="([^"]*)")?/g)) {
      element.setAttribute(attr[1], attr[2] || '');
      if (attr[1].startsWith('data-')) element.dataset[attr[1].slice(5).replace(/-([a-z])/g, (_, letter) => letter.toUpperCase())] = attr[2] || '';
    }
    stack.at(-1).append(element); elements.push(element); stack.push(element);
  }
  const scope = elements.find(element => element.dataset.progressScope);
  const navigate = elements.find(element => element.dataset.chapter);
  assert.ok(scope); assert.ok(navigate);
  assert.equal(scope.closest('button'), null, 'progress must not be inside the chapter button');
  assert.equal(scope.parent, navigate.parent, 'progress and chapter navigation share a non-interactive card');
  assert.equal(navigate.attrs.type, 'button');
  fixture.scopes.push(scope);
  vm.runInNewContext(source.slice(source.indexOf('  const nodeOf ='), source.indexOf('  /* Frame loop. */')), {
    labels:{domElement:{addEventListener:(type, callback) => callbacks.set(type, callback)}},
    select() { throw Error('retry selected a node'); }, enterTower:id => entered.push(id),
    state:{level:'city'}, setHover() {}
  });
  const group = {total:1,eligible:1,statuses:{mastered:1,needs_review:0,unassessed:0}};
  const store = createPersonalState({loadVersion:async () => 'v', request:async path => {
    if (path === '/nodes') return {content_version:'v',nodes:[]};
    progressCalls++;
    if (fail) throw Error('offline');
    return {content_version:'v',progress:[{scope:'chapter',contains:group,extends:group}]};
  }});
  const dispose = bindPersonalOverlay(store, fixture.root);
  try {
    await store.setUser({id:'student'}); await tick(); await tick();
    const retry = scope.children.find(element => element.tagName === 'button');
    assert.ok(retry); assert.equal(retry.type, 'button');
    assert.equal(retry.attrs['aria-label'], '重新读取个人进度');
    assert.equal(retry.parent.closest('button'), null);
    assert.equal(retry.closest('[data-chapter]'), null);
    for (const detail of [1, 0]) { // Mouse click, then the click emitted by Enter/Space on a native button.
      let stopped = false;
      const event = {target:retry,detail,stopPropagation() { stopped = true; }};
      fail = detail !== 0;
      await retry.onclick(event);
      if (!stopped) callbacks.get('click')(event);
      await tick();
      assert.deepEqual(entered, []);
    }
    assert.equal(progressCalls, 3); // Initial failure and the two explicit retries.
    assert.match(scope.textContent, /课内：1 \/ 1 已掌握/);
    callbacks.get('click')({target:navigate});
    assert.deepEqual(entered, ['chapter-id']);
  } finally { dispose(); fixture.restore(); }
});
