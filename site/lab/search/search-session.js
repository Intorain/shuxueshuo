(() => {
  'use strict';
  let user = null;
  let epoch = 0;
  let initialized = null;
  let identityRefresh = null;
  let identityTicket = 0;
  const controllers = new Set();
  const listeners = new Set();
  const removed = new Set();
  const prefix = 'search-progress:v1:';
  const legacyCleanupMarker = 'search-progress:legacy-cleanup:v1';

  function clearLegacyProgress() {
    try {
      if (localStorage.getItem(legacyCleanupMarker) === '1') return;
      for (const key of Object.keys(localStorage)) {
        if (key === 'search-walk:graph-folded') continue;
        if (key.startsWith('search-walk:') || key.startsWith('graph-walk:')) localStorage.removeItem(key);
      }
      localStorage.setItem(legacyCleanupMarker, '1');
    } catch {}
  }

  function cancelIdentityRefresh() {
    identityTicket++;
    const pending = identityRefresh;
    identityRefresh = null;
    pending?.finish();
  }

  async function identityReady(signal) {
    while (identityRefresh) {
      const pending = identityRefresh.promise;
      if (!signal) { await pending; continue; }
      if (signal.aborted) throw cancelled();
      let abort;
      try {
        await Promise.race([pending, new Promise((_resolve, reject) => {
          abort = () => reject(cancelled());
          signal.addEventListener('abort', abort, {once: true});
        })]);
      } finally { signal.removeEventListener('abort', abort); }
    }
  }

  function refreshIdentity() {
    if (!window.SiteAuth) return;
    const previous = identityRefresh;
    const ticket = ++identityTicket;
    let finish;
    const promise = new Promise(resolve => { finish = resolve; });
    const pending = {promise, finish};
    identityRefresh = pending;
    previous?.finish();
    void (async () => {
      try {
        await window.SiteAuth.ready;
        if (ticket !== identityTicket) return;
        await window.SiteAuth.refresh();
        if (ticket === identityTicket) changed(window.SiteAuth.user);
      } catch {} finally {
        if (identityRefresh === pending) identityRefresh = null;
        finish();
      }
    })();
  }

  function changed(next) {
    if (next?.id === user?.id) return;
    cancelIdentityRefresh();
    const previous = user;
    user = next;
    epoch++;
    for (const controller of controllers) controller.abort();
    controllers.clear();
    if (previous || !next) try {
      sessionStorage.removeItem('sq-page');
      sessionStorage.removeItem('sq-image');
    } catch {}
    for (const listener of listeners) listener(user, previous);
  }

  async function init(listener) {
    clearLegacyProgress();
    if (listener) listeners.add(listener);
    initialized ||= (async () => {
      if (!window.SiteAuth) await import('/assets/auth/site-auth.js?v=4');
      await window.SiteAuth.ready;
      window.SiteAuth.subscribe(changed);
      await window.SiteAuth.refresh();
      changed(window.SiteAuth.user);
    })();
    await initialized;
    return user;
  }

  async function login() {
    await init();
    await identityReady();
    const ticket = epoch;
    const guest = !user;
    const result = await window.SiteAuth.requireLogin({title: '登录后开始拍题学', intro: '登录后保存你的拍题记录。'});
    await identityReady();
    if (epoch !== ticket && !(guest && epoch === ticket + 1)) return null;
    return result?.id === user?.id && result?.id === window.SiteAuth.user?.id ? user : null;
  }

  const cancelled = () => new DOMException('账号或题目已变更', 'AbortError');
  function valid(ticket) { return ticket === epoch && Boolean(user); }

  async function request(url, options = {}) {
    if (!user) throw cancelled();
    const ticket = epoch;
    const controller = new AbortController();
    const abort = () => controller.abort();
    const active = async read => {
      if (!valid(ticket) || controller.signal.aborted || options.signal?.aborted) throw cancelled();
      controllers.add(controller);
      options.signal?.addEventListener('abort', abort, {once: true});
      try {
        const value = await read();
        await identityReady(controller.signal);
        if (!valid(ticket) || controller.signal.aborted) throw cancelled();
        return value;
      } finally {
        controllers.delete(controller);
        options.signal?.removeEventListener('abort', abort);
      }
    };
    return active(async () => {
      const response = await fetch(url, {...options, credentials: 'same-origin', cache: 'no-store',
        headers: {...options.headers, 'X-Search-User': user.id}, signal: controller.signal});
      if (!valid(ticket)) throw cancelled();
      const mismatch = response.status === 409 && (await response.clone().json().catch(() => ({}))).detail === 'search.account_changed';
      if (!valid(ticket)) throw cancelled();
      if (mismatch) {
        changed(null);
        void window.SiteAuth.refresh();
        throw cancelled();
      }
      if (response.status === 401) {
        refreshIdentity();
        await identityReady(controller.signal);
        throw cancelled();
      }
      for (const method of ['json', 'blob', 'text', 'arrayBuffer', 'formData']) {
        if (typeof response[method] !== 'function') continue;
        const read = response[method].bind(response);
        response[method] = () => active(async () => {
          const data = await read();
          if (!valid(ticket)) throw cancelled();
          if (method === 'json' && data?.user_id && data.user_id !== user.id) {
            changed(null);
            void window.SiteAuth.refresh();
            throw cancelled();
          }
          return data;
        });
      }
      return response;
    });
  }

  function scope(searchId) {
    return user ? `${prefix}${user.id}:${searchId}:` : null;
  }

  function clearProgress(userId, searchIds, broadcast = true) {
    for (const searchId of searchIds) {
      removed.add(`${userId}:${searchId}`);
      const keyPrefix = `${prefix}${userId}:${searchId}:`;
      try {
        for (const key of Object.keys(localStorage)) if (key.startsWith(keyPrefix)) localStorage.removeItem(key);
      } catch {}
    }
    window.dispatchEvent(new CustomEvent('search-records-deleted', {detail: {user_id: userId, search_ids: searchIds}}));
    if (broadcast) try { localStorage.setItem('search-records-deleted', JSON.stringify({user_id: userId, search_ids: searchIds, at: Date.now()})); } catch {}
  }

  window.addEventListener('storage', event => {
    if (event.key === 'sss-auth-change') {
      let logout = false;
      try { logout = JSON.parse(event.newValue)?.reason === 'logout'; } catch {}
      if (logout) { cancelIdentityRefresh(); changed(null); }
      else refreshIdentity();
      return;
    }
    if (event.key !== 'search-records-deleted' || !event.newValue) return;
    try {
      const data = JSON.parse(event.newValue);
      if (typeof data.user_id === 'string' && Array.isArray(data.search_ids)) clearProgress(data.user_id, data.search_ids, false);
    } catch {}
  });

  window.SearchSession = {init, login, request, scope, clearProgress, valid,
    get user() { return user; }, get epoch() { return epoch; },
    writable(searchId) { return Boolean(user) && !removed.has(`${user.id}:${searchId}`); }};
})();
