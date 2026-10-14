import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import vm from 'node:vm';
import {isPreview, modeHref} from '../../site/assets/practice/learning-mode.mjs';
import {safeGraphReturn, VIEW_KINDS, writeState, nodeHref, chapterPath} from '../../site/assets/knowledge-next/model.mjs';

const origin = 'https://site';
const chapter = '/knowledge/chapters/compulsory-1-ch2/';
const detailSource = (await fs.readFile(new URL('../../site/assets/knowledge-next/detail.mjs', import.meta.url), 'utf8'))
  .replace(/^import .*;\n/gm, '');
const graphSource = await fs.readFile(new URL('../../site/assets/knowledge-next/graph.mjs', import.meta.url), 'utf8');

function detailLinks(href, kind = 'skill') {
  const links = {
    '[data-graph-return]': [{href:chapter}],
    '[data-graph-locate]': [{href:chapter}],
    '[data-node-link]': [{href:origin + '/knowledge/skill-factor/#factor'}]
  };
  vm.runInNewContext(detailSource, {
    URL, URLSearchParams, location:new URL(href, origin), safeGraphReturn, VIEW_KINDS, isPreview, modeHref,
    matchMedia:() => ({matches:false}),
    document:{
      querySelector:selector => selector === '#node-page-config'
        ? {textContent:JSON.stringify({id:'method-complete-square',kind,resources:[]})} : null,
      querySelectorAll:selector => links[selector] || []
    }
  });
  return Object.fromEntries(Object.entries(links).map(([key, value]) => [key, new URL(value[0].href, origin)]));
}

test('leaving preview never reactivates a saved preview graph and retains navigation context', () => {
  for (const savedMode of ['preview=1', 'knowledge=next']) {
    const saved = chapter + '?scope=section-2-2&view=solution&node=method-complete-square&' + savedMode + '#graph-anchor';
    const preview = new URL('/knowledge/method-complete-square/?preview=1#operation', origin);
    preview.searchParams.set('graph', saved);
    // This is the same explicit exit used by learning.mjs. The outer mode is
    // authoritative even while the nested historical graph URL has old flags.
    const formal = modeHref(preview.href);
    assert.equal(new URL(formal, origin).hash, '#operation');
    const links = detailLinks(formal);
    for (const selector of ['[data-graph-return]', '[data-graph-locate]']) {
      const link = links[selector];
      assert.equal(isPreview(link.search), false);
      assert.equal(link.searchParams.get('scope'), 'section-2-2');
      assert.equal(link.searchParams.get('view'), 'solution');
      assert.equal(link.searchParams.get('node'), 'method-complete-square');
      assert.equal(link.hash, '#graph-anchor');
    }
    const related = links['[data-node-link]'];
    assert.equal(isPreview(related.search), false);
    assert.equal(related.hash, '#factor');
    const relatedGraph = new URL(related.searchParams.get('graph'), origin);
    assert.equal(isPreview(relatedGraph.search), false);
    assert.equal(relatedGraph.hash, '#graph-anchor');
  }
});

test('preview details normalize both current and legacy modes and retain compatible graph filters', () => {
  for (const mode of ['preview=1', 'knowledge=next', 'preview=1&knowledge=next&learning=1']) {
    const detail = new URL('/knowledge/method-complete-square/?' + mode, origin);
    detail.searchParams.set('graph', chapter + '?scope=section-2-2&view=solution&node=type-sum-product-extremum&kinds=skill&relations=calls#canvas');
    const links = detailLinks(detail.href);
    const locate = links['[data-graph-locate]'];
    assert.equal(locate.searchParams.get('preview'), '1');
    assert.equal(locate.searchParams.get('scope'), 'section-2-2');
    assert.equal(locate.searchParams.get('view'), 'solution');
    assert.equal(locate.searchParams.get('kinds'), 'skill');
    assert.equal(locate.searchParams.get('relations'), 'calls');
    assert.equal(locate.searchParams.get('node'), 'method-complete-square');
    assert.equal(locate.hash, '#canvas');
    assert.equal(links['[data-node-link]'].searchParams.get('preview'), '1');
  }
  assert.equal(safeGraphReturn('https://other.test' + chapter + '#canvas'), '/knowledge/');
});

function graphNavigation(search) {
  class PageLocation extends URL {
    get href() { return super.href; }
    set href(value) { super.href = new URL(value, super.href).href; }
  }
  const location = new PageLocation(chapter + search + '#canvas', origin);
  const state = {scope:'section-2-2',view:'solution',node:'method-complete-square',q:'',kinds:[],relations:[],expanded:[]};
  const config = {chapter:'compulsory-1-ch2',base:chapter};
  const code = graphSource.slice(graphSource.indexOf('function homeHref('), graphSource.indexOf('const nodeEl=')) +
    graphSource.slice(graphSource.indexOf('function stateHref('), graphSource.indexOf('// Frames already')) +
    graphSource.slice(graphSource.indexOf('function locate('), graphSource.indexOf('function relationGroups('));
  const updates = [];
  const context = vm.createContext({
    URL, URLSearchParams, location, state, config, isPreview, modeHref, writeState, nodeHref, chapterPath,
    byId:new Map([['quantifiers',{kind:'knowledge',home:'compulsory-1-ch1'}]]),
    chapters:new Map([['compulsory-1-ch1',{id:'compulsory-1-ch1',node:'chapter-sets-logic',sections:[{id:'section-1-5'}]}]]),
    graph:{}, scopeMembers:() => new Set(['quantifiers']), elsewhere:() => true,
    window:{dispatchEvent() {}}, CustomEvent:class {},
    history:{pushState(_state, _title, href) {updates.push(href);},replaceState(_state, _title, href) {updates.push(href);}}
  });
  vm.runInContext(code, context);
  return {location, updates, run:expression => vm.runInContext(expression, context)};
}

test('cross-chapter locate preserves preview without relying on anchor click interception', () => {
  for (const [search, preview] of [['?preview=1',true],['?knowledge=next',true],['?knowledge=next&learning=1',false],['',false]]) {
    const context = graphNavigation(search);
    context.run("locate('quantifiers')");
    const result = context.location;
    assert.equal(result.pathname, '/knowledge/chapters/compulsory-1-ch1/');
    assert.equal(isPreview(result.search), preview);
    assert.equal(result.searchParams.get('scope'), 'section-1-5');
    assert.equal(result.searchParams.get('view'), 'knowledge');
    assert.equal(result.searchParams.get('node'), 'quantifiers');
    assert.equal(result.hash, '#canvas');
  }
});

test('graph state updates and detail round-trips keep mode, state and hash', () => {
  for (const [search, preview] of [['?preview=1',true],['',false]]) {
    const context = graphNavigation(search);
    context.run('updateURL()');
    const updated = new URL(context.updates[0], origin);
    assert.equal(isPreview(updated.search), preview);
    assert.equal(updated.searchParams.get('scope'), 'section-2-2');
    assert.equal(updated.searchParams.get('view'), 'solution');
    assert.equal(updated.searchParams.get('node'), 'method-complete-square');
    assert.equal(updated.hash, '#canvas');
    const detail = new URL(context.run("detailHref('method-complete-square')"), origin);
    const returned = detailLinks(detail.href)['[data-graph-return]'];
    assert.equal(returned.href, updated.href);
  }
});
