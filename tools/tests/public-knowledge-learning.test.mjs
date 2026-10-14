import test from 'node:test';
import assert from 'node:assert/strict';
import {learningHref, ABILITY_KINDS, learningDirectoryHref, progressScope, practiceEventView, renderLearningMath, preserveLearningLink} from '../../site/assets/knowledge-next/learning-model.mjs';
import {previewHref, previewTarget} from '../../site/assets/knowledge-next/teaching-model.mjs';

test('published links are clean and preserve their navigation context', () => {
  assert.equal(learningHref('/knowledge/node/?graph=chapter&learning=1#entry'), '/knowledge/node/?graph=chapter#entry');
  assert.equal(previewHref('/1/q01/', true), '/1/q01/');
  const targets = {paths:['/1/q01/'], library:'/1/', topic:'/knowledge-next/topics/basic-inequality/', learning:true};
  assert.equal(previewTarget(new URL('https://site/1/'), targets), '/1/');
  assert.equal(previewTarget(new URL('https://site/1/q01/'), targets), '/1/q01/');
  assert.deepEqual(ABILITY_KINDS, ['knowledge','skill','method','problem_type']);
});

test('textbook redirects preserve aggregate scope without replacing the graph scope', () => {
  const config = {kind:'textbook',id:'book-1',redirectHref:'/knowledge/'};
  assert.equal(learningDirectoryHref(config, 'https://site/book/'), '/knowledge/?progress=book-1');
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
    ['/knowledge/chapters/ch2/', '/knowledge/chapters/ch2/'],
    ['/1/q01/?knowledge=next', '/1/q01/?preview=1'],
    ['https://other.test/knowledge-next/', 'https://other.test/knowledge-next/'],
    ['/knowledge-next/', '/knowledge-next/', true],
  ]) {
    const anchor = link(href, exit);
    preserveLearningLink(anchor, 'https://site/knowledge/');
    assert.equal(anchor.getAttribute('href'), expected);
  }
  const exit = link('/knowledge/', true);
  preserveLearningLink(exit, 'https://site/knowledge/?preview=1');
  assert.equal(exit.getAttribute('href'), '/knowledge/');
});

test('evidence retains actual answer labels, structure choice and grading source', () => {
  const contexts = new Map([
    ['choice', {interaction:{type:'choice',options:[{value:'sq',label:'$x^2$'}]}}],
    ['structure', {interaction:{type:'structure',term_labels:{a:'$x$',b:'$1/x$'}}}]
  ]);
  assert.equal(practiceEventView({event_type:'answer',related_event_id:'choice',payload:{value:'sq'}}, contexts).text, '$x^2$');
  assert.deepEqual(practiceEventView({event_type:'answer',related_event_id:'structure',payload:{terms:['a','b'],fixed:'product'}}, contexts),
    {title:'你的作答',text:'$x$，$1/x$',details:['定积']});
  assert.equal(practiceEventView({event_type:'grade',payload:{source:'rule',result:'passed'}}).title, '自动判定');
  assert.equal(practiceEventView({event_type:'grade',payload:{source:'llm',result:'passed'}}).title, '导师判定');
});

test('hint evidence distinguishes diagrams, candidates and acknowledged display', () => {
  const view = practiceEventView({event_type:'hint',displayed_at:'now',payload:{source:'node_explainer',
    ref:'node#entry',resource_id:'diagram',candidate:true,text:'通用说明'}});
  assert.deepEqual(view, {title:'看了图解',text:'通用说明',details:[
    '当时还没选定做法，这是备选提示，不代表用了这种方法。'
  ]});
  assert.deepEqual(practiceEventView({event_type:'hint',payload:{source:'node_explainer',node_id:'node'}}),
    {title:'看了学习提示',text:'',details:['没有显示出来']});
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
