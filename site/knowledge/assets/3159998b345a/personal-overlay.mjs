import {STATUS_LABELS} from './learning-model.mjs';

const NS = 'http://www.w3.org/2000/svg';
const symbols = {mastered: '✓', needs_review: '!', unassessed: '·'};
export function progressText(name, row) {
  return `${name} ${row.total} 个：已掌握 ${row.statuses.mastered} · 待巩固 ${row.statuses.needs_review} · 未检测 ${row.statuses.unassessed} · 有检测题 ${row.eligible}`;
}

// A round's local progress is separate from its assessed mastery state.
export function updateLocalDrillProgress(host, detail, userId, nodeId) {
  if (!host || !detail || detail.userId !== userId || detail.nodeId !== nodeId) return;
  host.textContent = detail.status === 'in_progress' ? ` · 本轮已答 ${detail.answered} / ${detail.total}` : '';
}

// DOM labels cover SVG, CSS2D labels and ordinary links. Status never changes
// the public node's kind color, membership or outgoing relationships.
export function bindPersonalOverlay(store, root = document) {
  const signatures = new WeakMap();
  let scheduled = false;
  const schedule = () => {
    if (!scheduled) { scheduled = true; queueMicrotask(() => { scheduled = false; apply(); }); }
  };
  function apply() {
    const current = store.snapshot(), active = current.phase === 'ready';
    root.querySelectorAll('[data-learning-node], [data-directory-node]').forEach(host => {
      const id = host.dataset.learningNode || host.dataset.directoryNode;
      let state = active ? current.nodes.get(id) : null;
      // Untested is the default for most nodes: only a selected node's own panel says so.
      if (state?.status === 'unassessed' && !('learningFull' in host.dataset)) state = null;
      const signature = state?.status || '';
      if (signatures.get(host) === signature) return;
      signatures.set(host, signature);
      host.querySelectorAll(':scope > .kx-personal-badge, :scope > .kx-personal-mark').forEach(el => el.remove());
      if (!state || !STATUS_LABELS[state.status]) return;
      if (host.namespaceURI === NS) {
        const mark = document.createElementNS(NS, 'g');
        mark.setAttribute('class', `kx-personal-mark ${state.status}`);
        mark.setAttribute('aria-label', `我的状态：${STATUS_LABELS[state.status]}`);
        const circle = document.createElementNS(NS, 'circle'); circle.setAttribute('r', '9');
        const text = document.createElementNS(NS, 'text'); text.setAttribute('y', '4.5'); text.textContent = symbols[state.status];
        const title = document.createElementNS(NS, 'title'); title.textContent = `我的状态：${STATUS_LABELS[state.status]}`;
        mark.append(circle, text, title); host.append(mark);
      } else {
        const badge = document.createElement('span');
        badge.className = `kx-personal-badge ${state.status}`;
        badge.textContent = state.status === 'unassessed' ? STATUS_LABELS.unassessed : `${symbols[state.status]} ${STATUS_LABELS[state.status]}`;
        badge.setAttribute('aria-label', `我的状态：${STATUS_LABELS[state.status]}`);
        host.append(badge);
      }
    });
    const scopes = [];
    root.querySelectorAll('[data-progress-scope]').forEach(host => {
      const scope = host.dataset.progressScope;
      if (!scope) return;
      host.classList.add('kx-directory-progress');
      const row = active && current.progress.get(scope);
      const error = active && current.progressErrors.get(scope);
      const groups = row ? [['课内', 'contains'], ['拓展', 'extends']].filter(([, key]) => row[key].total) : [];
      const text = row ? groups.map(([name, key]) => progressText(name, row[key])).join('\n') : error ? '个人进度暂不可用' : active ? '正在读取个人进度…' : '';
      host.hidden = !active;
      if (signatures.get(host) !== text) {
        signatures.set(host, text); host.replaceChildren();
        if (row) for (const [name, key] of groups) {
          const line = document.createElement('span');
          line.className = 'kx-progress-line';
          line.textContent = host.hasAttribute('data-progress-compact') ? `${name}：${row[key].statuses.mastered} / ${row[key].total} 已掌握` : progressText(name, row[key]);
          host.append(line);
        } else if (text) host.textContent = text;
        if (error) {
          const retry = document.createElement('button'); retry.type = 'button'; retry.textContent = '重试';
          retry.setAttribute('aria-label', '重新读取个人进度');
          retry.onclick = event => {
            event?.stopPropagation();
            return store.getProgress([scope], {retry: true});
          };
          host.append(retry);
        }
      }
      if (active && !row && !error) scopes.push(scope);
    });
    if (scopes.length) store.getProgress(scopes);
  }
  const unsubscribe = store.subscribe(schedule);
  const observer = new MutationObserver(schedule);
  observer.observe(root, {childList: true, subtree: true});
  return () => { unsubscribe(); observer.disconnect(); };
}
