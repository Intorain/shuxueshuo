import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = fs.readFileSync(new URL('../../site/lab/search/search-session.js', import.meta.url), 'utf8');
const historySource = fs.readFileSync(new URL('../../site/lab/search/search.js', import.meta.url), 'utf8');
const sharedAuthSource = fs.readFileSync(new URL('../../site/assets/auth/site-auth.js', import.meta.url), 'utf8');
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return {promise, resolve}; };
const tick = () => new Promise(resolve => setImmediate(resolve));
const authBroadcast = (events, reason) => {
  const event = new Event('storage');
  Object.assign(event, {key: 'sss-auth-change', newValue: JSON.stringify({reason, at: Date.now()})});
  events.dispatchEvent(event);
};

function storage(hooks = {}) {
  const data = {};
  Object.defineProperties(data, {
    getItem: {value: key => { hooks.read?.(key); return data[key] ?? null; }},
    setItem: {value: (key, value) => { hooks.write?.(key, value); data[key] = String(value); }},
    removeItem: {value: key => { hooks.remove?.(key); delete data[key]; }},
  });
  return data;
}

function harness(initial = {id: 'a'}, localStorage = storage()) {
  const events = new EventTarget();
  const sessionStorage = storage();
  let listener;
  const auth = {user: initial, ready: Promise.resolve(), refresh: async () => {},
    requireLogin: async () => auth.user, subscribe(callback) { listener = callback; }};
  const context = vm.createContext({AbortController, DOMException, CustomEvent, Response, localStorage, sessionStorage,
    setTimeout: () => 1, clearTimeout() {}, URL, Image: class {}});
  context.window = {SiteAuth: auth, addEventListener: events.addEventListener.bind(events),
    dispatchEvent: events.dispatchEvent.bind(events), confirm: () => true};
  vm.runInContext(source, context);
  const session = context.window.SearchSession;
  const nodes = new Map();
  const documentListeners = new Map();
  function element(key) {
    if (!nodes.has(key)) nodes.set(key, {hidden: false, disabled: false, textContent: '', innerHTML: '', dataset: {}, children: [], listeners: {},
      append(...children) { this.children.push(...children); }, replaceChildren(...children) { this.children = children; },
      setAttribute() {}, click() {}, addEventListener(name, callback) { this.listeners[name] = callback; }});
    return nodes.get(key);
  }
  let created = 0;
  context.document = {querySelector: element, createElement: name => element(name + ++created),
    addEventListener(name, callback) { documentListeners.set(name, callback); }};
  context.IntersectionObserver = class { observe() {} };
  context.location = {href: ''};
  return {context, session, auth, localStorage, sessionStorage, events, element, documentListeners,
    change(next) { auth.user = next; listener(next); },
    history() { vm.runInContext(historySource, context); }};
}

function sharedRefresh(context, publishAuth, readAuth) {
  Object.assign(context, {publishAuth, readAuth});
  const refresh = sharedAuthSource.slice(sharedAuthSource.indexOf('  async function refresh('), sharedAuthSource.indexOf('  function settle('));
  const broadcastListener = sharedAuthSource.slice(sharedAuthSource.indexOf("    window.addEventListener('storage'"), sharedAuthSource.indexOf("    window.addEventListener('pageshow'"));
  vm.runInContext(`(() => {
    let user=window.SiteAuth.user, enabled=true, reachable=true, epoch=0, busy=false, refreshPending=false;
    const refreshWaiters=[], dialog={open:false}, render=()=>{}, api=()=>readAuth();
    const publish=next=>{user=next;publishAuth(next)};
    ${refresh}
    window.SiteAuth.refresh=refresh;
    ${broadcastListener}
  })()`, context);
}

test('initialization removes legacy anonymous progress without reading or assigning it to an account', async () => {
  const reads = [], writes = [];
  const saved = storage({read: key => reads.push(key), write: key => writes.push(key)});
  saved.setItem('search-walk:old-question', 'private legacy page');
  saved.setItem('graph-walk:old-problem:version', 'private legacy answers');
  saved.setItem('search-walk:graph-folded', '1');
  saved.setItem('search-walk:graph-folded:old-progress', 'not a preference');
  saved.setItem('search-progress:v1:a:one:page', 'account A');
  saved.setItem('search-progress:v1:b:one:walk:version', 'account B');
  saved.setItem('gw-graph-mode', '3d');
  saved.setItem('other-site-setting', 'keep');
  writes.length = 0;
  const {session, change} = harness({id: 'a'}, saved);
  await session.init();
  assert.deepEqual(reads, ['search-progress:legacy-cleanup:v1']);
  assert.deepEqual(writes, ['search-progress:legacy-cleanup:v1']);
  assert.equal(saved['search-walk:old-question'], undefined);
  assert.equal(saved['graph-walk:old-problem:version'], undefined);
  assert.equal(saved['search-walk:graph-folded:old-progress'], undefined);
  assert.equal(saved['search-walk:graph-folded'], '1');
  assert.equal(saved['search-progress:v1:a:one:page'], 'account A');
  assert.equal(saved['search-progress:v1:b:one:walk:version'], 'account B');
  assert.equal(saved['gw-graph-mode'], '3d');
  assert.equal(saved['other-site-setting'], 'keep');
  assert.equal(saved['search-progress:legacy-cleanup:v1'], '1');
  change({id: 'b'});
  await session.init();
  assert.equal(saved['search-progress:v1:a:one:page'], 'account A');
  assert.equal(saved['search-progress:v1:b:one:walk:version'], 'account B');
});

test('a completed cleanup marker skips repeated initialization and later page sessions', async () => {
  const removed = [], writes = [];
  const saved = storage({remove: key => removed.push(key), write: key => writes.push(key)});
  saved.setItem('graph-walk:initial', 'old');
  const first = harness({id: 'a'}, saved);
  await first.session.init();
  saved.setItem('graph-walk:written-by-an-old-tab', 'not read by the new runtime');
  writes.length = 0;
  await first.session.init();
  await first.session.login();
  const second = harness({id: 'b'}, saved);
  await second.session.init();
  assert.deepEqual(removed, ['graph-walk:initial']);
  assert.deepEqual(writes, []);
  assert.equal(saved['graph-walk:written-by-an-old-tab'], 'not read by the new runtime');
  assert.equal(second.session.user.id, 'b');
});

for (const failure of ['remove', 'marker']) test('failed legacy cleanup remains unmarked and retries safely: ' + failure, async () => {
  let failing = true;
  const saved = storage({
    remove: key => { if (failing && failure === 'remove' && key === 'graph-walk:second') throw new Error('storage locked'); },
    write: key => { if (failing && failure === 'marker' && key === 'search-progress:legacy-cleanup:v1') throw new Error('quota'); },
  });
  saved.setItem('search-walk:first', 'old');
  saved.setItem('graph-walk:second', 'old');
  saved.setItem('search-progress:v1:a:one:page', 'owned');
  const {session} = harness({id: 'a'}, saved);
  assert.equal((await session.init()).id, 'a');
  assert.equal(saved['search-progress:legacy-cleanup:v1'], undefined);
  assert.equal(saved['search-progress:v1:a:one:page'], 'owned');
  failing = false;
  saved.setItem('search-walk:retry', 'old');
  await session.init();
  assert.equal(saved['search-walk:first'], undefined);
  assert.equal(saved['graph-walk:second'], undefined);
  assert.equal(saved['search-walk:retry'], undefined);
  assert.equal(saved['search-progress:legacy-cleanup:v1'], '1');
  assert.equal(saved['search-progress:v1:a:one:page'], 'owned');
});

test('disabled browser storage does not block authentication and cleanup retries when access returns', async () => {
  const {context, session, localStorage} = harness();
  localStorage.setItem('graph-walk:old', 'legacy');
  Object.defineProperty(context, 'localStorage', {configurable: true, get() { throw new DOMException('disabled', 'SecurityError'); }});
  assert.equal((await session.init()).id, 'a');
  assert.equal((await session.login()).id, 'a');
  assert.equal(localStorage['search-progress:legacy-cleanup:v1'], undefined);
  Object.defineProperty(context, 'localStorage', {configurable: true, value: localStorage});
  await session.init();
  assert.equal(localStorage['graph-walk:old'], undefined);
  assert.equal(localStorage['search-progress:legacy-cleanup:v1'], '1');
});

test('account changes abort requests and reject late HTTP bodies from the previous owner', async () => {
  const {context, session, change} = harness();
  await session.init();
  let signal;
  const pending = deferred();
  context.fetch = (_url, options) => { signal = options.signal; return pending.promise; };
  const request = session.request('/api/search/problems');
  change({id: 'b'});
  assert.equal(signal.aborted, true);
  pending.resolve(new Response(JSON.stringify({user_id: 'a', items: []})));
  await assert.rejects(request, {name: 'AbortError'});

  change({id: 'a'});
  const body = deferred();
  context.fetch = async () => ({status: 200, json: () => body.promise});
  const response = await session.request('/api/search/problems');
  const reading = response.json();
  change({id: 'b'});
  body.resolve({user_id: 'a', items: ['private']});
  await assert.rejects(reading, {name: 'AbortError'});
});

test('requests include the expected account and reject a response for another account', async () => {
  const {context, session, auth} = harness();
  await session.init();
  let sent;
  context.fetch = async (_url, options) => { sent = options; return new Response(JSON.stringify({user_id: 'b'})); };
  const response = await session.request('/api/search/problems', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'});
  assert.equal(sent.headers['X-Search-User'], 'a');
  assert.equal(sent.credentials, 'same-origin');
  assert.equal(sent.cache, 'no-store');
  auth.user = null;
  await assert.rejects(response.json(), {name: 'AbortError'});
  assert.equal(session.user, null);
});

test('maintenance remains an ordinary HTTP response without account invalidation or implicit POST retries', async () => {
  const {context, session, auth} = harness();
  await session.init();
  const epoch = session.epoch, scope = session.scope('one');
  let requests = 0;
  auth.refresh = () => assert.fail('maintenance must not refresh or invalidate the account');
  context.fetch = async () => {
    requests++;
    return new Response(JSON.stringify({detail: 'service.draining'}), {status: 503});
  };
  const response = await session.request('/api/search/problems', {method: 'POST'});
  assert.equal(response.status, 503);
  assert.equal(response.ok, false);
  assert.equal((await response.json()).detail, 'service.draining');
  assert.equal(requests, 1);
  assert.equal(session.user.id, 'a');
  assert.equal(session.epoch, epoch);
  assert.equal(session.scope('one'), scope);
});

test('a different account confirmed by refresh invalidates private reads held during login verification', async () => {
  const {context, session, events, auth} = harness();
  await session.init();
  const pending = deferred(), refreshing = deferred();
  auth.refresh = async () => { await refreshing.promise; auth.user = {id: 'b'}; };
  let signal, settled = false;
  context.fetch = (_url, options) => { signal = options.signal; return pending.promise; };
  const reading = session.request('/api/search/problems');
  const rejected = assert.rejects(reading, {name: 'AbortError'}).then(() => { settled = true; });
  authBroadcast(events, 'login');
  assert.equal(session.user.id, 'a');
  assert.equal(signal.aborted, false);
  pending.resolve(new Response(JSON.stringify({user_id: 'a', items: []})));
  await tick();
  assert.equal(settled, false);
  refreshing.resolve();
  await rejected;
  assert.equal(signal.aborted, true);
  assert.equal(session.user.id, 'b');
});

test('same-account login refresh preserves upload, lesson reads, owner scope and saved handoff', async () => {
  const {context, session, events, auth, sessionStorage} = harness();
  await session.init();
  let changes = 0;
  await session.init(() => { changes++; });
  const epoch = session.epoch, scope = session.scope('one');
  sessionStorage.setItem('sq-page', 'owned-photo');
  const upload = deferred(), body = deferred(), refreshing = deferred();
  const signals = [];
  context.fetch = (url, options) => {
    signals.push(options.signal);
    return url.endsWith('/pages') ? upload.promise : Promise.resolve({status: 200, json: () => body.promise});
  };
  const uploading = session.request('/api/search/pages', {method: 'POST'});
  const lesson = (await session.request('/api/search/problems/one/lesson/run/events')).json();
  auth.refresh = async () => { await refreshing.promise; auth.user = {id: 'a', phone: '13900001111'}; };
  authBroadcast(events, 'login');
  upload.resolve(new Response(JSON.stringify({user_id: 'a', page_id: 'page'})));
  body.resolve({user_id: 'a', events: ['step']});
  await tick();
  assert.ok(signals.every(signal => !signal.aborted));
  assert.equal(changes, 0);
  assert.equal(session.epoch, epoch);
  refreshing.resolve();
  assert.equal((await (await uploading).json()).page_id, 'page');
  assert.deepEqual(await lesson, {user_id: 'a', events: ['step']});
  assert.equal(session.scope('one'), scope);
  assert.equal(sessionStorage.getItem('sq-page'), 'owned-photo');
  assert.equal(changes, 0);
});

test('explicit logout immediately aborts work and an earlier login refresh cannot revive it', async () => {
  const {context, session, events, auth} = harness();
  await session.init();
  const refreshing = deferred();
  auth.refresh = async () => { await refreshing.promise; auth.user = {id: 'a'}; };
  let signal;
  context.fetch = async (_url, options) => { signal = options.signal; return new Response('{}'); };
  authBroadcast(events, 'login');
  const reading = session.request('/api/search/problems');
  const rejected = assert.rejects(reading, {name: 'AbortError'});
  await tick();
  authBroadcast(events, 'logout');
  assert.equal(session.user, null);
  assert.equal(signal.aborted, true);
  await rejected;
  refreshing.resolve();
  await tick();
  assert.equal(session.user, null);
});

test('overlapping login refreshes apply only the newest completion and keep old work gated', async () => {
  const {context, session, events, auth} = harness();
  await session.init();
  const first = deferred(), second = deferred();
  let refreshes = 0, settled = false;
  auth.refresh = async () => {
    const number = ++refreshes;
    await (number === 1 ? first.promise : second.promise);
    auth.user = {id: number === 1 ? 'a' : 'b'};
  };
  context.fetch = async () => new Response(JSON.stringify({user_id: 'a'}));
  authBroadcast(events, 'login');
  const reading = session.request('/api/search/problems');
  const rejected = assert.rejects(reading, {name: 'AbortError'}).then(() => { settled = true; });
  await tick();
  authBroadcast(events, 'login');
  await tick();
  first.resolve();
  await tick();
  assert.equal(session.user.id, 'a');
  assert.equal(settled, false);
  second.resolve();
  await rejected;
  assert.equal(session.user.id, 'b');
});

test('an older login refresh returning last cannot replace the newly confirmed account', async () => {
  const {session, events, auth} = harness();
  await session.init();
  const first = deferred(), second = deferred();
  let refreshes = 0;
  auth.refresh = async () => {
    const number = ++refreshes;
    await (number === 1 ? first.promise : second.promise);
    auth.user = {id: number === 1 ? 'a' : 'b'};
  };
  authBroadcast(events, 'login');
  await tick();
  authBroadcast(events, 'login');
  await tick();
  second.resolve();
  await tick();
  assert.equal(session.user.id, 'b');
  first.resolve();
  await tick();
  assert.equal(session.user.id, 'b');
});

test('unknown or malformed auth metadata refreshes identity without treating it as logout', async () => {
  const {session, events, auth} = harness();
  await session.init();
  const epoch = session.epoch;
  let refreshes = 0;
  auth.refresh = async () => { refreshes++; };
  for (const newValue of ['old-timestamp', null, '{broken', JSON.stringify({reason: 'refresh'})]) {
    const event = new Event('storage');
    Object.assign(event, {key: 'sss-auth-change', newValue});
    events.dispatchEvent(event);
    await tick();
    assert.equal(session.user.id, 'a');
    assert.equal(session.epoch, epoch);
  }
  assert.equal(refreshes, 4);
});

for (const account of ['a', 'b']) for (const order of ['old-first', 'new-first']) test(`shared auth refresh epochs suppress stale publications during login: ${account}/${order}`, async () => {
  const {context, session, events, change} = harness();
  await session.init();
  const requests = [];
  sharedRefresh(context, change, () => {
    const request = deferred(); requests.push(request); return request.promise;
  });
  let signal;
  context.fetch = async (_url, options) => { signal = options.signal; return new Response(JSON.stringify({user_id: 'a'})); };
  authBroadcast(events, 'login');
  const reading = session.request('/api/search/problems');
  const result = account === 'b' ? assert.rejects(reading, {name: 'AbortError'}) : reading;
  await tick();
  assert.equal(requests.length, 2);
  const stale = () => requests[0].resolve({enabled: true, user: {id: account === 'a' ? 'b' : 'a'}});
  const current = () => requests[1].resolve({enabled: true, user: {id: account}});
  if (order === 'old-first') {
    stale(); await tick();
    assert.equal(session.user.id, 'a');
    assert.equal(signal.aborted, false);
    current();
  } else {
    current(); await tick(); stale();
  }
  await result;
  await tick();
  assert.equal(session.user.id, account);
  assert.equal(signal.aborted, account === 'b');
});

test('failed login identity refresh keeps the known account and releases private reads', async () => {
  const {context, session, events, auth} = harness();
  await session.init();
  const epoch = session.epoch;
  auth.refresh = async () => { throw new TypeError('offline'); };
  context.fetch = async () => new Response(JSON.stringify({user_id: 'a', items: []}));
  authBroadcast(events, 'login');
  assert.equal((await (await session.request('/api/search/problems')).json()).user_id, 'a');
  assert.equal(session.epoch, epoch);
});

test('caller cancellation still rejects immediately while login identity verification is pending', async () => {
  const {context, session, events, auth} = harness();
  await session.init();
  const refreshing = deferred(), controller = new AbortController();
  auth.refresh = () => refreshing.promise;
  context.fetch = async () => new Response(JSON.stringify({user_id: 'a'}));
  authBroadcast(events, 'login');
  const reading = session.request('/api/search/pages', {method: 'POST', signal: controller.signal});
  const rejected = assert.rejects(reading, {name: 'AbortError'});
  await tick();
  controller.abort();
  await rejected;
  assert.equal(session.user.id, 'a');
  refreshing.resolve();
  await tick();
});

test('a revoked old token returning 401 after same-account login does not tear down current learning', async () => {
  const {context, session, events, auth, sessionStorage} = harness();
  await session.init();
  let changes = 0, refreshes = 0;
  await session.init(() => { changes++; });
  const epoch = session.epoch;
  sessionStorage.setItem('sq-page', 'owned-photo');
  const oldRequest = deferred(), currentUpload = deferred(), currentIdentity = deferred();
  const requests = [], signals = [];
  context.fetch = (url, options) => {
    requests.push([url, options.method]); signals.push(options.signal);
    return requests.length === 1 ? oldRequest.promise : currentUpload.promise;
  };
  auth.refresh = async () => {
    refreshes++;
    if (refreshes > 1) await currentIdentity.promise;
    auth.user = {id: 'a'};
  };
  const original = session.request('/api/search/problems', {method: 'POST'});
  const rejected = assert.rejects(original, {name: 'AbortError'});
  authBroadcast(events, 'login');
  await tick();
  const uploading = session.request('/api/search/pages', {method: 'POST'});
  oldRequest.resolve(new Response(JSON.stringify({detail: 'auth.required'}), {status: 401}));
  await tick();
  assert.equal(refreshes, 2);
  assert.equal(session.user.id, 'a');
  assert.ok(signals.every(signal => !signal.aborted));
  currentIdentity.resolve();
  await rejected;
  currentUpload.resolve(new Response(JSON.stringify({user_id: 'a', page_id: 'retained'})));
  assert.equal((await (await uploading).json()).page_id, 'retained');
  assert.equal(session.epoch, epoch);
  assert.equal(changes, 0);
  assert.equal(sessionStorage.getItem('sq-page'), 'owned-photo');
  assert.equal(requests.length, 2, 'the non-idempotent rejected POST is never retried');
});

for (const next of [null, {id: 'b'}]) test('401 revalidation still invalidates expired or switched accounts: ' + next?.id, async () => {
  const {context, session, auth} = harness();
  await session.init();
  const identity = deferred(), upload = deferred();
  let uploadSignal;
  auth.refresh = async () => { await identity.promise; auth.user = next; };
  context.fetch = (url, options) => {
    if (url.endsWith('/pages')) { uploadSignal = options.signal; return upload.promise; }
    return Promise.resolve(new Response('{}', {status: 401}));
  };
  const uploading = session.request('/api/search/pages', {method: 'POST'});
  const uploadRejected = assert.rejects(uploading, {name: 'AbortError'});
  const reading = session.request('/api/search/problems');
  const rejected = assert.rejects(reading, {name: 'AbortError'});
  await tick();
  identity.resolve();
  await rejected;
  assert.equal(session.user?.id, next?.id);
  assert.equal(uploadSignal.aborted, true);
  upload.resolve(new Response(JSON.stringify({user_id: 'a', page_id: 'stale'})));
  await uploadRejected;
});

test('account mismatch 409 fails closed without waiting for a same-account refresh', async () => {
  const {context, session, auth} = harness();
  await session.init();
  const identity = deferred();
  auth.refresh = () => identity.promise;
  context.fetch = async () => new Response(JSON.stringify({detail: 'search.account_changed'}), {status: 409});
  await assert.rejects(session.request('/api/search/problems'), {name: 'AbortError'});
  assert.equal(session.user, null);
  identity.resolve();
  await tick();
  assert.equal(session.user, null);
});

test('explicit logout wins over a pending old-token 401 revalidation', async () => {
  const {context, session, auth, events} = harness();
  await session.init();
  const identity = deferred();
  auth.refresh = async () => { await identity.promise; auth.user = {id: 'a'}; };
  context.fetch = async () => new Response('{}', {status: 401});
  const reading = session.request('/api/search/problems');
  const rejected = assert.rejects(reading, {name: 'AbortError'});
  await tick();
  authBroadcast(events, 'logout');
  await rejected;
  assert.equal(session.user, null);
  identity.resolve();
  await tick();
  assert.equal(session.user, null);
});

for (const status of [401, 409]) test('authentication rejection stops private requests: ' + status, async () => {
  const {context, session, auth} = harness();
  await session.init();
  context.fetch = async () => new Response(JSON.stringify({detail: 'search.account_changed'}), {status});
  auth.user = null;
  await assert.rejects(session.request('/api/search/problems'), {name: 'AbortError'});
  await assert.rejects(session.request('/api/search/pages'), {name: 'AbortError'});
});

test('initial login preserves an owned album handoff while switching accounts removes it', async () => {
  const {session, sessionStorage, change} = harness();
  sessionStorage.setItem('sq-page', JSON.stringify({user_id: 'a', image: 'photo'}));
  await session.init();
  assert.equal(JSON.parse(sessionStorage.getItem('sq-page')).user_id, 'a');
  change({id: 'b'});
  assert.equal(sessionStorage.getItem('sq-page'), null);
});

test('deletion clears every local target and version for this account, broadcasts, and prevents rewrites', async () => {
  const {session, localStorage, events} = harness();
  await session.init();
  for (const key of ['search-progress:v1:a:one:page', 'search-progress:v1:a:one:walk:goal/version',
    'search-progress:v1:a:two:walk:goal/version', 'search-progress:v1:b:one:page']) localStorage.setItem(key, 'progress');
  let event;
  events.addEventListener('search-records-deleted', value => { event = value.detail; });
  session.clearProgress('a', ['one']);
  assert.equal(localStorage.getItem('search-progress:v1:a:one:page'), null);
  assert.equal(localStorage.getItem('search-progress:v1:a:one:walk:goal/version'), null);
  assert.equal(localStorage.getItem('search-progress:v1:a:two:walk:goal/version'), 'progress');
  assert.equal(localStorage.getItem('search-progress:v1:b:one:page'), 'progress');
  assert.equal(session.writable('one'), false);
  assert.equal(event.user_id, 'a');
  assert.deepEqual(JSON.parse(localStorage.getItem('search-records-deleted')).search_ids, ['one']);
  const incoming = new Event('storage');
  Object.assign(incoming, {key: 'search-records-deleted', newValue: JSON.stringify({user_id: 'a', search_ids: ['two']})});
  events.dispatchEvent(incoming);
  assert.equal(localStorage.getItem('search-progress:v1:a:two:walk:goal/version'), null);
});

test('history paginates by twenty and opens the available search while showing the newest failure', async () => {
  const {context, session, history, element} = harness();
  await session.init();
  history();
  const urls = [];
  const items = Array.from({length: 20}, (_unused, index) => ({search_id: 'available-' + index, problem_id: 'problem-' + index,
    summary: '<img onerror=private()>', last_searched_at: '2026-10-24T10:00:00Z', latest_status: 'failed', lesson_available: true}));
  context.fetch = async url => {
    urls.push(url);
    return new Response(JSON.stringify({user_id: 'a', items: urls.length === 1 ? items : [{...items[0], search_id: 'pending', problem_id: null, latest_status: 'queued', lesson_available: false}], has_more: urls.length === 1}));
  };
  await context.loadHistory(true);
  const first = element('#sq-history-list').children[0].children[0];
  assert.equal(first.href, 'problem.html?search=available-0');
  assert.equal(first.children[0].textContent, '<img onerror=private()>');
  assert.equal(first.children[0].innerHTML, '');
  assert.equal(first.children[2].textContent, '可开始学习 · 最近一次处理失败');
  await context.loadHistory();
  assert.equal(urls[1], '/api/search/problems?limit=20&offset=20');
  assert.equal(element('#sq-history-list').children.length, 21);
  assert.equal(element('#sq-history-all').hidden, true);
});

test('unavailable courses never claim readiness while older available courses stay usable', async () => {
  const {context, session, history} = harness();
  await session.init();
  history();
  for (const latest_status of ['unavailable', 'ready', 'completed']) {
    const row = context.historyRow({search_id: 'missing', latest_status, lesson_available: false});
    assert.equal(row.children[0].children[2].textContent, '课程不可用');
    assert.equal(row.children[0].children[2].dataset.status, 'unsupported');
  }
  const available = context.historyRow({search_id: 'older', latest_status: 'unavailable', lesson_available: true});
  assert.equal(available.children[0].href, 'problem.html?search=older');
  assert.equal(available.children[0].children[2].textContent, '可开始学习 · 最近一次课程不可用');
});

test('history only spins for active processing, not terminal or confirmation states', async () => {
  const {context, session, history} = harness();
  await session.init();
  history();
  for (const latest of ['unsupported', 'failed', 'error', 'interrupted', 'expired', 'disabled', 'unavailable']) {
    const row = context.historyRow({search_id: 'one', latest_status: latest, lesson_available: false});
    assert.equal(row.children[0].children[2].dataset.status, 'unsupported');
  }
  for (const latest of ['needs_confirmation', 'unclear', 'figure', 'reviewed']) {
    const row = context.historyRow({search_id: 'one', latest_status: latest, lesson_available: false});
    assert.equal(row.children[0].children[2].dataset.status, 'half');
  }
  for (const latest of ['queued', 'recognizing', 'pending', 'running', 'generating']) {
    const row = context.historyRow({search_id: 'one', latest_status: latest, lesson_available: false});
    assert.equal(row.children[0].children[2].dataset.status, 'doing');
  }
});

test('a stale history response cannot repaint after an account switch', async () => {
  const {context, session, change, history, element} = harness();
  await session.init();
  history();
  await session.init(() => context.resetHistory());
  const pending = deferred();
  context.fetch = () => pending.promise;
  const loaded = context.loadHistory(true);
  change({id: 'b'});
  pending.resolve(new Response(JSON.stringify({user_id: 'a', items: [{search_id: 'private'}], has_more: false})));
  await loaded;
  assert.equal(element('#sq-history-list').children.length, 0);
  assert.equal(element('#sq-history-message').textContent, '');
});

test('failed deletion keeps the record, successful deletion clears all returned search progress', async () => {
  const {context, session, history, localStorage, element} = harness();
  await session.init();
  history();
  localStorage.setItem('search-progress:v1:a:old:page', 'answer');
  localStorage.setItem('search-progress:v1:a:new:page', 'answer');
  let failed = true;
  context.fetch = async (_url, options) => options.method === 'DELETE'
    ? new Response(JSON.stringify(failed ? {detail: 'failed'} : {deleted_search_ids: ['old', 'new']}), {status: failed ? 503 : 200})
    : new Response(JSON.stringify({user_id: 'a', items: [], has_more: false}));
  const button = element('delete');
  const item = {search_id: 'new', problem_id: 'public'};
  await context.deleteRecord(item, button);
  assert.equal(button.disabled, false);
  assert.equal(localStorage.getItem('search-progress:v1:a:old:page'), 'answer');
  failed = false;
  await context.deleteRecord(item, button);
  assert.equal(localStorage.getItem('search-progress:v1:a:old:page'), null);
  assert.equal(localStorage.getItem('search-progress:v1:a:new:page'), null);
});

for (const next of [{id: 'b'}, null]) test('a late login result cannot resurrect the previous account: ' + next?.id, async () => {
  const {session, auth, change} = harness();
  await session.init();
  const pending = deferred();
  auth.requireLogin = () => pending.promise;
  const login = session.login();
  await Promise.resolve();
  change(next);
  pending.resolve({id: 'a'});
  assert.equal(await login, null);
  assert.equal(session.user, next);
});

test('a guest login accepts the subscribed account but not a stale auth cache after another tab changes', async () => {
  const {session, auth, change, events} = harness(null);
  await session.init();
  const pending = deferred();
  auth.requireLogin = () => pending.promise;
  const login = session.login();
  await Promise.resolve();
  change({id: 'a'});
  pending.resolve({id: 'a'});
  assert.equal((await login).id, 'a');
  authBroadcast(events, 'logout');
  auth.requireLogin = async () => ({id: 'a'});
  assert.equal(await session.login(), null);
  assert.equal(session.user, null);
});

for (const method of ['json', 'blob', 'text']) test('account invalidation aborts an in-flight response body: ' + method, async () => {
  const {context, session, change} = harness();
  await session.init();
  const body = deferred();
  let signal;
  context.fetch = async (_url, options) => { signal = options.signal; return {status: 200, [method]: () => body.promise}; };
  const response = await session.request('/api/search/private');
  const reading = response[method]();
  change({id: 'b'});
  assert.equal(signal.aborted, true);
  body.resolve(method === 'json' ? {user_id: 'a'} : 'private');
  await assert.rejects(reading, {name: 'AbortError'});
});

test('caller cancellation remains effective before headers and during body consumption', async () => {
  const {context, session} = harness();
  await session.init();
  for (const phase of ['headers', 'body']) {
    const pending = deferred(), controller = new AbortController();
    let signal;
    context.fetch = (_url, options) => {
      signal = options.signal;
      return phase === 'headers' ? pending.promise : Promise.resolve({status: 200, json: () => pending.promise});
    };
    const request = session.request('/api/search/private', {signal: controller.signal});
    const reading = phase === 'headers' ? request : (await request).json();
    controller.abort();
    assert.equal(signal.aborted, true);
    pending.resolve(phase === 'headers' ? new Response('{}') : {});
    await assert.rejects(reading, {name: 'AbortError'});
  }
});

test('cross-tab deletion invalidates pending history and filters tombstoned rows from fresh snapshots', async () => {
  const {context, session, history, events, element} = harness();
  await session.init(); history();
  const stale = deferred(), fresh = deferred();
  let requests = 0;
  context.fetch = () => ++requests === 1 ? stale.promise : fresh.promise;
  const loading = context.loadHistory(true);
  const event = new Event('storage');
  Object.assign(event, {key: 'search-records-deleted', newValue: JSON.stringify({user_id: 'a', search_ids: ['removed']})});
  events.dispatchEvent(event);
  assert.equal(requests, 2);
  fresh.resolve(new Response(JSON.stringify({user_id: 'a', items: [{search_id: 'removed'}, {search_id: 'retained'}], has_more: false})));
  await new Promise(resolve => setImmediate(resolve));
  stale.resolve(new Response(JSON.stringify({user_id: 'a', items: [{search_id: 'removed'}], has_more: true})));
  await loading;
  assert.equal(element('#sq-history-list').children.length, 1);
  assert.equal(element('#sq-history-list').children[0].children[0].href, 'problem.html?search=retained');
  assert.equal(element('#sq-history-all').hidden, true);
});

test('an album picker opened under A cannot submit its selection after switching to B', async () => {
  const {context, session, history, change, element, documentListeners} = harness();
  context.fetch = async () => new Response(JSON.stringify({user_id: session.user.id, items: [], has_more: false}));
  history();
  await documentListeners.get('DOMContentLoaded')();
  await context.proceed('album');
  change({id: 'b'});
  let decoded = 0;
  context.Image = class { constructor() { decoded++; } };
  element('#sq-file').listeners.change({target: {files: [{type: 'image/png', size: 100}], value: 'old-photo'}});
  assert.equal(decoded, 0);
  assert.equal(context.location.href, '');
});
