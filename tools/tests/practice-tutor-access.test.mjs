import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(new URL('../../site/assets/practice/runtime.js', import.meta.url), 'utf8');
const gate = source.slice(0, source.indexOf('const practiceAuthReady'));
const requestSource = source.slice(source.indexOf('  function updateBusy()'), source.indexOf('  function conversation(')) +
  source.slice(source.indexOf('  async function request(payload)'), source.indexOf('  function sendEvent('));
const reply = body => ({ok:true, headers:new Headers(), json:async () => body});

function harness({search = '', hostname = 'example.org', content = 'missing'} = {}) {
  const calls = [], state = {method:null, active:0};
  let mode = content;
  const scope = {
    URLSearchParams, AbortSignal, AbortController, Headers, setTimeout, clearTimeout, structuredClone,
    location:{search, hostname}, document:{currentScript:{src:'https://example.org/assets/practice/runtime.js'},
      getElementById:() => ({textContent:'{"id":"q01"}'}), querySelectorAll:() => [], querySelector:() => null},
    busy:false, dialoguePause:null, generation:0, state, snapshot:{attempt_id:'local-attempt',state},
    retryRequest:null, requestController:null, remote:null, pendingOperations:[], practiceAuthReady:Promise.resolve(),
    // An unavailable recording channel must never hold an ordinary tutor request.
    recorderReady:new Promise(() => {}),
    window:{SiteAuth:{requireLogin:async () => ({id:'student'})}}, api:'/api/tutor-demo', lesson:{id:'q01'},
    steps:{querySelectorAll:() => [],setAttribute() {}}, picker:{querySelectorAll:() => []},
    messageInput:{value:'为什么？'}, sendButton:{}, retryButton:{}, networkStatus:{},
    pauseIdle() {}, resumeIdle() {}, showProgress() {}, announce() {}, completed:() => false,
    PracticeContext:{reconcile:data => ({view:data,remaining:[]})},
    acceptSnapshot(data) { scope.snapshot = data; scope.state = data.state; },
    fetch:async (url, options) => {
      calls.push({url, body:options?.body ? JSON.parse(options.body) : null});
      if (url === '/api/learning/content') {
        if (mode === 'pending') return new Promise(() => {});
        if (mode === 'offline') throw Error('offline');
        if (mode === 'missing') return {ok:false,status:404};
        if (mode === 'malformed') return reply({});
        return reply({schema_version:2,content_version:'current'});
      }
      if (url.startsWith('/knowledge-next/')) return reply({content_version:mode === 'mismatch' ? 'old' : 'current'});
      if (url.endsWith('/sessions')) return reply({session_id:'standalone',revision:0});
      return reply({session_id:'standalone',revision:1,attempt_id:'local-attempt',state,messages:[{text:'提示内容'}]});
    }
  };
  vm.createContext(scope);
  const contentReady = vm.runInContext(gate + '\npracticeContentReady', scope);
  vm.runInContext(requestSource, scope);
  return {scope,calls,contentReady,setMode(value) { mode = value; },run:code => vm.runInContext(code, scope)};
}

test('ordinary tutor never requests learning metadata and works independently', async () => {
  const h = harness({content:'current'});
  await h.contentReady;
  assert.equal(h.run('practiceAccess.enabled'), false);
  h.scope.updateBusy();
  assert.equal(Boolean(h.scope.messageInput.disabled), false);
  assert.equal(Boolean(h.scope.sendButton.disabled), false);
  await h.scope.request({event_id:'ask',revision:0,kind:'text',text:'为什么？',pending_operations:[]});
  const start = h.calls.find(call => call.url.endsWith('/sessions'));
  assert.deepEqual(start.body, {lesson_id:'q01'});
  assert.equal(h.calls.filter(call => call.url.includes('/api/tutor-demo/')).length, 2);
  assert.ok(!h.calls.some(call => call.url.startsWith('/api/learning/') || call.url.startsWith('/knowledge-next/')));
  assert.equal(h.scope.messageInput.value, '');
});

function renderNotice({search = '', hostname = 'example.org'} = {}) {
  const h = harness({search, hostname, content:'offline'});
  const from = source.indexOf('  let learningNotice = null;');
  const notice = source.slice(from, source.indexOf('  practiceContentReady.then(() => {', from));
  const composer = {hidden:false}, aside = {innerHTML:'', setAttribute() {}, querySelector:() => ({})};
  Object.assign(h.scope, {
    location:{search, hostname, href:`https://${hostname}/1/q01/${search}`},
    document:{...h.scope.document, querySelector:() => composer, createElement:() => aside},
    steps:{before() {}}, URL
  });
  return h.contentReady.then(() => {
    h.run(source.slice(source.indexOf('  const escapeHTML'), source.indexOf('\n', source.indexOf('  const escapeHTML'))) +
      `\n${notice}\nrenderLearningNotice();`);
    return {composer, aside};
  });
}

test('ordinary page notice is a single sentence without retry actions', async () => {
  const {composer, aside} = await renderNotice();
  assert.equal(composer.hidden, false);
  assert.match(aside.innerHTML, /本页不保存练习进度/);
  assert.doesNotMatch(aside.innerHTML, /<button|进入新关联登录联调/);
  const local = await renderNotice({hostname:'localhost'});
  assert.doesNotMatch(local.aside.innerHTML, /<button/);
  assert.match(local.aside.innerHTML, /进入新关联登录联调/);
});

test('failed explicit learning page keeps retry and refresh actions', async () => {
  const {composer, aside} = await renderNotice({search:'?knowledge=next&learning=1'});
  assert.equal(composer.hidden, true);
  assert.match(aside.innerHTML, /data-check-learning/);
  assert.match(aside.innerHTML, /data-refresh-learning/);
});

test('unrecorded preview and a mismatched explicit learning page do not open tutor sessions', async () => {
  for (const search of ['?knowledge=next','?knowledge=next&learning=1']) {
    const h = harness({search,content:'mismatch'});
    await h.contentReady;
    h.scope.updateBusy();
    assert.equal(h.scope.messageInput.disabled, true);
    await h.scope.request({kind:'text'});
    assert.equal(h.calls.filter(call => call.url.includes('/api/tutor-demo/')).length, 0);
    if (search === '?knowledge=next') assert.equal(h.calls.length, 0);
  }
});

test('retry revalidates failed learning metadata and development links stay on loopback hosts', async () => {
  const h = harness({search:'?knowledge=next&learning=1',content:'offline'});
  await h.contentReady;
  assert.equal(h.run('practiceTutorEnabled()'), false);
  h.setMode('current');
  await h.run('checkPracticeContent()');
  assert.equal(h.run('practiceAccess.contentVersion'), 'current');
  assert.equal(h.run('practiceTutorEnabled()'), true);
  for (const hostname of ['localhost','127.0.0.1','127.0.1.2','[::1]','::1']) {
    const local = harness({hostname}); await local.contentReady;
    assert.equal(local.run('practiceLocalHost'), true, hostname);
  }
  for (const hostname of ['example.org','localhost.example.org','192.168.1.1']) {
    const remote = harness({hostname}); await remote.contentReady;
    assert.equal(remote.run('practiceLocalHost'), false, hostname);
  }
});

test('confirmed completed fields come from server passed steps without inventing a choice', () => {
  const from = source.indexOf('  const confirmedProgress =');
  const helper = source.slice(from, source.indexOf('  const restorePractice', from));
  const scope = {lesson:{routes:{main:[
    {id:'choose',interaction:{type:'choice',field:'rule'}},
    {id:'fill',interaction:{type:'structure',field:'terms'}},
    {id:'later',interaction:{type:'choice',field:'later'}}
  ]}}};
  vm.createContext(scope);
  vm.runInContext('let confirmedOnServer = {}, passedFieldsOnServer = [];\n' + helper, scope);
  vm.runInContext("confirmedProgress({route_id:'main',confirmed_choices:{},steps:[{step_id:'choose',passed:true},{step_id:'fill',passed:true},{step_id:'later',passed:false}]})", scope);
  assert.deepEqual(Array.from(vm.runInContext('passedFieldsOnServer', scope)), ['rule']);
  assert.deepEqual(Object.keys(vm.runInContext('confirmedOnServer', scope)), []);
});
