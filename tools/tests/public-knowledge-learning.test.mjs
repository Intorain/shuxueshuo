import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {learningHref, learningVersion, ABILITY_KINDS, learningDirectoryHref, progressScope, practiceEventView, renderLearningMath, preserveLearningLink} from '../../site/assets/knowledge-next/learning-model.mjs';
import {previewHref, previewTarget} from '../../site/assets/knowledge-next/teaching-model.mjs';

const runtime = fs.readFileSync(new URL('../../site/assets/practice/runtime.js', import.meta.url), 'utf8');
const gate = runtime.slice(0, runtime.indexOf('const practiceAuthReady'));
const access = async (search, {published = {schema_version:2,content_version:'same'}, page = 'same', problem = 'same', fail = false} = {}) => {
  const requests = [];
  const sandbox = {URLSearchParams, AbortSignal, location:{search}, document:{currentScript:{src:'https://site/assets/practice/runtime.js'},
    getElementById:() => ({textContent:'{"id":"q01"}'})},
    fetch:async url => {
      requests.push(url);
      if (fail) throw Error('offline');
      return {ok:true,json:async () => url.startsWith('/api/') ? published : {content_version:url.includes('/problems/') ? problem : page}};
    }};
  return {state:await vm.runInNewContext(gate + '\npracticeContentReady;', sandbox), requests};
};

test('unrecorded preview does not even request learning content', async () => {
  const {state, requests} = await access('?knowledge=next');
  assert.equal(state.enabled, false);
  assert.deepEqual(requests, []);
});

test('learning requires both static association files and database to agree', async () => {
  assert.equal((await access('?knowledge=next&learning=1')).state.enabled, true);
  for (const options of [{page:'old'}, {problem:'old'}, {fail:true}]) {
    assert.equal((await access('?knowledge=next&learning=1', options)).state.enabled, false);
  }
  assert.equal((await access('', {published:{schema_version:2,content_version:'same'}})).state.enabled, false);
  assert.equal((await access('', {fail:true})).state.enabled, false);
});

test('detail version checks and scope links preserve the explicit learning mode', async () => {
  await assert.rejects(learningVersion(async path => ({content_version:path.startsWith('/api/') ? 'new' : 'old'})), /版本不同/);
  assert.equal(await learningVersion(async () => ({content_version:'same'})), 'same');
  assert.equal(learningHref('/knowledge-next/node/?graph=chapter#entry'), '/knowledge-next/node/?graph=chapter&learning=1#entry');
  assert.equal(previewHref('/1/q01/', true), '/1/q01/?knowledge=next&learning=1');
  const targets = {paths:['/1/q01/'], library:'/1/', topic:'/knowledge-next/topics/basic-inequality/', learning:true};
  assert.equal(previewTarget(new URL('https://site/1/'), targets), '/knowledge-next/topics/basic-inequality/?learning=1');
  assert.equal(previewTarget(new URL('https://site/1/q01/'), targets), '/1/q01/?knowledge=next&learning=1');
  assert.deepEqual(ABILITY_KINDS, ['knowledge','skill','method','problem_type']);
});

test('textbook redirects preserve aggregate scope without replacing the graph scope', () => {
  const config = {kind:'textbook',id:'book-1',redirectHref:'/knowledge-next/'};
  assert.equal(learningDirectoryHref(config, 'https://site/book/'), '/knowledge-next/?learning=1&progress=book-1');
  assert.equal(progressScope('?learning=1&progress=book-1', null), 'book-1');
  assert.equal(progressScope('?learning=1&progress=book-1&scope=section-2', {defaultScope:'section-1'}), 'section-2');
  assert.equal(progressScope('?learning=1', {defaultScope:'section-1'}), 'section-1');
});

test('learning navigation supports SVG chapter links and preserves explicit exits', () => {
  const link = (href, exit = false) => {
    const attributes = new Map([['href', href], ...(exit ? [['data-learning-exit', '']] : [])]);
    return {
      get href() { throw Error('SVG href must be read through its attribute'); },
      hasAttribute: name => attributes.has(name),
      getAttribute: name => attributes.get(name),
      setAttribute: (name, value) => attributes.set(name, value),
    };
  };
  for (const [href, expected, exit] of [
    ['/knowledge-next/chapters/ch2/', '/knowledge-next/chapters/ch2/?learning=1'],
    ['/1/q01/?knowledge=next', '/1/q01/?knowledge=next&learning=1'],
    ['https://other.test/knowledge-next/', 'https://other.test/knowledge-next/'],
    ['/knowledge-next/', '/knowledge-next/', true],
  ]) {
    const anchor = link(href, exit);
    preserveLearningLink(anchor, 'https://site/knowledge-next/');
    assert.equal(anchor.getAttribute('href'), expected);
  }
});

test('evidence retains actual answer labels, structure choice and grading source', () => {
  const contexts = new Map([
    ['choice', {interaction:{type:'choice',options:[{value:'sq',label:'$x^2$'}]}}],
    ['structure', {interaction:{type:'structure',term_labels:{a:'$x$',b:'$1/x$'}}}]
  ]);
  assert.equal(practiceEventView({event_type:'answer',related_event_id:'choice',payload:{value:'sq'}}, contexts).text, '$x^2$');
  assert.deepEqual(practiceEventView({event_type:'answer',related_event_id:'structure',payload:{terms:['a','b'],fixed:'product'}}, contexts),
    {title:'学生提交',text:'$x$，$1/x$',details:['定积']});
  assert.equal(practiceEventView({event_type:'grade',payload:{source:'rule',result:'passed'}}).title, '规则判定');
  assert.equal(practiceEventView({event_type:'grade',payload:{source:'llm',result:'passed'}}).title, '导师判定');
});

test('hint evidence distinguishes diagrams, candidates and acknowledged display', () => {
  const view = practiceEventView({event_type:'hint',displayed_at:'now',payload:{source:'node_explainer',
    ref:'node#entry',resource_id:'diagram',candidate:true,text:'通用说明'}});
  assert.deepEqual(view, {title:'查看图解',text:'通用说明',details:[
    '关联：node#entry','候选提示，不表示已经采用该方法或技能。','已确认展示'
  ]});
  assert.deepEqual(practiceEventView({event_type:'hint',payload:{source:'node_explainer',node_id:'node'}}),
    {title:'查看学习说明',text:'',details:['关联：node','尚未确认展示']});
  assert.equal(practiceEventView({event_type:'hint',payload:{text:'导师给出的提示'}}).title, '导师提示');
});

test('evidence math enhances marked text using the shared renderer', async () => {
  const previous = globalThis.window;
  const rendered = [];
  const nodes = [{textContent:'$x^2$'}, {textContent:'答案：$1/x$'}];
  globalThis.window = {katex:{},renderMathInElement(){},PracticeMath:{render:(node, text) => rendered.push([node,text])}};
  try {
    await renderLearningMath({querySelectorAll:selector => {
      assert.equal(selector, '[data-math-text]');
      return nodes;
    }});
    assert.deepEqual(rendered, nodes.map(node => [node,node.textContent]));
  } finally { globalThis.window = previous; }
});
