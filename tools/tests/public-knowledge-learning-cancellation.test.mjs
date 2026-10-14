import test from 'node:test';
import assert from 'node:assert/strict';
import {learningApi} from '../../site/assets/knowledge-next/learning-model.mjs';

const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return {promise, resolve, reject};
};
const response = (data = {nodes: []}) => ({ok: true, status: 200, json: async () => data});

// Exercise the actual request wrapper with both newer static APIs absent.
function legacy(t, fetch) {
  const any = Object.getOwnPropertyDescriptor(AbortSignal, 'any');
  const timeout = Object.getOwnPropertyDescriptor(AbortSignal, 'timeout');
  Object.defineProperty(AbortSignal, 'any', {configurable: true, value: undefined});
  Object.defineProperty(AbortSignal, 'timeout', {configurable: true, value: undefined});
  t.after(() => {
    if (any) Object.defineProperty(AbortSignal, 'any', any); else delete AbortSignal.any;
    if (timeout) Object.defineProperty(AbortSignal, 'timeout', timeout); else delete AbortSignal.timeout;
  });
  const timers = new Map();
  let next = 0;
  t.mock.method(globalThis, 'fetch', fetch);
  t.mock.method(globalThis, 'setTimeout', (callback, delay) => {
    const id = ++next;
    timers.set(id, {callback, delay});
    return id;
  });
  t.mock.method(globalThis, 'clearTimeout', id => timers.delete(id));
  return timers;
}

function track(t, signal) {
  const listeners = new Set();
  const add = signal.addEventListener.bind(signal), remove = signal.removeEventListener.bind(signal);
  t.mock.method(signal, 'addEventListener', (type, callback, options) => {
    if (type === 'abort') listeners.add(callback);
    return add(type, callback, options);
  });
  t.mock.method(signal, 'removeEventListener', (type, callback) => {
    if (type === 'abort') listeners.delete(callback);
    return remove(type, callback);
  });
  return listeners;
}

function pendingFetch(url, {signal}) {
  return new Promise((resolve, reject) => {
    signal.addEventListener('abort', () => reject(signal.reason || Object.assign(Error('aborted'), {name:'AbortError'})), {once: true});
  });
}

test('legacy Safari request succeeds without AbortSignal.any/timeout and cleans up', async t => {
  const parent = new AbortController(), listeners = track(t, parent.signal);
  let received;
  const timers = legacy(t, async (url, options) => {
    received = options;
    assert.equal(url, '/api/learning/nodes');
    assert.equal(options.signal.aborted, false);
    assert.equal(listeners.size, 1);
    return response();
  });
  assert.deepEqual(await learningApi('/nodes', {signal:parent.signal, user:'account'}), {nodes:[]});
  assert.equal(received.headers['X-Learning-User'], 'account');
  assert.equal(timers.size, 0); assert.equal(listeners.size, 0);
  parent.abort(); assert.equal(received.signal.aborted, false);
});

test('account cancellation aborts the fetch immediately and removes deadline and listener', async t => {
  const parent = new AbortController(), listeners = track(t, parent.signal);
  const timers = legacy(t, pendingFetch);
  const promise = learningApi('/nodes', {signal:parent.signal});
  const error = new Error('account changed');
  const rejected = assert.rejects(promise, value => value === error);
  parent.abort(error);
  assert.equal(timers.size, 0); assert.equal(listeners.size, 0);
  await rejected;
});

test('an already cancelled caller never starts a request or timer', async t => {
  const parent = new AbortController(); parent.abort();
  const listeners = track(t, parent.signal);
  const timers = legacy(t, () => { throw Error('must not fetch'); });
  await assert.rejects(learningApi('/nodes', {signal:parent.signal}), {name:'AbortError'});
  assert.equal(globalThis.fetch.mock.callCount(), 0);
  assert.equal(globalThis.setTimeout.mock.callCount(), 0);
  assert.equal(timers.size, 0); assert.equal(listeners.size, 0);
});

for (const withParent of [false, true]) test(`15-second timeout works without native timeout (${withParent ? 'with' : 'without'} caller)`, async t => {
  const parent = new AbortController(), listeners = track(t, parent.signal);
  const timers = legacy(t, pendingFetch);
  const promise = learningApi('/nodes', withParent ? {signal:parent.signal} : {});
  const rejected = assert.rejects(promise, {name:'TimeoutError'});
  assert.equal(timers.size, 1);
  const timer = [...timers.values()][0]; assert.equal(timer.delay, 15000);
  timer.callback();
  await rejected;
  assert.equal(timers.size, 0); assert.equal(listeners.size, 0);
  assert.equal(parent.signal.aborted, false);
});

test('deadline remains active during body loading and is cleaned after body cancellation', async t => {
  const parent = new AbortController(), listeners = track(t, parent.signal);
  const body = deferred();
  const timers = legacy(t, async () => ({...response(), json: () => body.promise}));
  const promise = learningApi('/nodes', {signal:parent.signal});
  await Promise.resolve();
  assert.equal(timers.size, 1); assert.equal(listeners.size, 1);
  const error = new Error('logged out');
  const rejected = assert.rejects(promise, value => value === error);
  parent.abort(error); body.resolve({private: 'stale'});
  await rejected;
  assert.equal(timers.size, 0); assert.equal(listeners.size, 0);
});

for (const failure of ['network', 'json', 'http']) test(`${failure} failure cleans up timer and caller listener`, async t => {
  const parent = new AbortController(), listeners = track(t, parent.signal);
  const timers = legacy(t, async () => {
    if (failure === 'network') throw Error('network');
    if (failure === 'json') return {...response(), json:async () => {throw Error('json');}};
    return {...response({detail:'service unavailable'}),ok:false,status:503};
  });
  await assert.rejects(learningApi('/nodes', {signal:parent.signal}));
  assert.equal(timers.size, 0); assert.equal(listeners.size, 0);
});

test('caller cancellation still works when legacy signals do not expose a reason', async t => {
  const parent = new AbortController(), listeners = track(t, parent.signal);
  Object.defineProperty(parent.signal, 'reason', {value:undefined});
  const timers = legacy(t, pendingFetch);
  const promise = learningApi('/nodes', {signal:parent.signal});
  const rejected = assert.rejects(promise, {name:'AbortError'});
  parent.abort(); await rejected;
  assert.equal(timers.size, 0); assert.equal(listeners.size, 0);
});
