import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import vm from 'node:vm';
import {topicNodeGroups} from '../../site/assets/practice/topic-knowledge.mjs';
import {isPreview} from '../../site/assets/practice/learning-mode.mjs';

test('topic summary follows actual refs and explicit kinds, not training labels or ID prefixes', () => {
  const catalog = {
    'method-skill': {id:'method-skill',kind:'skill',label:'配方'},
    'plain-method': {id:'plain-method',kind:'method',label:'配方求最值法'},
    k: {id:'k',kind:'knowledge',label:'平方非负'},
    t: {id:'t',kind:'problem_type',label:'和积最值'}
  };
  const topic = {groups:[{label:'无对应公共方法的训练分组'}],problems:{p:{path:'/1/q01/',types:['t'],routes:{
    a:{methods:{field:'technique',options:{square:['plain-method'],other:[]}},steps:{
      first:{refs:['method-skill','k#nonnegative'],tip:{ref:'method-skill'}}}},
    b:{methods:['plain-method'],steps:{second:{refs:['method-skill']}}}
  }}}};
  const groups = topicNodeGroups(topic, catalog);
  assert.deepEqual(groups.map(group => [group.kind,group.nodes.map(node => node.id)]), [
    ['knowledge',['k']],['skill',['method-skill']],['method',['plain-method']],['problem_type',['t']]
  ]);
  assert.equal(groups[1].nodes[0].problems.length, 1);
  assert.deepEqual(topicNodeGroups({...topic,groups:[]},catalog), groups);
});

test('preview skips all learning mark initialization for both problem and topic pages', async () => {
  const source = (await fs.readFile(new URL('../../site/assets/learning/learning-marks.js',import.meta.url),'utf8'))
    .replace(/^import .+;\n/gm, '').replaceAll('import.meta.url', '"https://site/assets/learning/learning-marks.js"');
  for (const search of ['?preview=1','?knowledge=next','?knowledge=next&learning=1&preview=1']) {
    const unavailable = new Proxy({}, {get() {throw Error('Preview must not initialize marks or authentication');}});
    await vm.runInNewContext(`(async () => {${source}})()`, {
      isPreview,location:{search},document:unavailable,window:unavailable,
      fetch() {throw Error('Preview must not load marks');}
    });
  }
});

test('formal topic entrypoints use current data and ordinary detail links', async () => {
  for (const path of ['1/index.html','2/index.html','topics/index.html']) {
    const html = await fs.readFile(new URL(`../../site/${path}`,import.meta.url),'utf8');
    assert.doesNotMatch(html,/\/data\/knowledge\/|\/knowledge\/topic-map\.|explain\/explain\.js|7 个题型/);
    assert.match(html,/href="\/knowledge\//);
    if (!path.startsWith('topics')) {
      assert.match(html,/topic-knowledge\.mjs/);
      assert.match(html,/data-node-ref=/);
      assert.doesNotMatch(html,/data-explain=/);
    }
  }
});
