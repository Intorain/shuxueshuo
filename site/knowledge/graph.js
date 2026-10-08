/* Knowledge graph page: selection, detail panel, topic filter and personal coverage.
   Drawing is done by graph-3d.js (WebGL) or graph-svg.js (flat). */
import {loadKnowledge, escapeHtml as escape, openSheet, kindLabel} from '/knowledge/data.js?v=3';
import {detailHref} from '/assets/explain/links.js?v=2';
import {layout, TOPIC_COLORS, PROGRESS} from '/knowledge/graph-layout.js?v=1';

import {states, block as masteryBlock, badge, watch} from '/knowledge/personal.js?v=1';
let mastery=null;
const config = JSON.parse(document.getElementById('knowledge-config').textContent);
const data = await loadKnowledge(config);
const {graph, nodes, topics, prerequisites, uses, before, after, usedBy, usesOf, topicsOf, practiceOf} = data;
const topicColor = topic => TOPIC_COLORS[topics.indexOf(topic) % TOPIC_COLORS.length];
const box = layout(data);

function closure(id, step) {
  const seen = new Set();
  const visit = next => step(next).forEach(other => { if (!seen.has(other)) { seen.add(other); visit(other); } });
  visit(id);
  return seen;
}

const count = test => graph.nodes.filter(test).length;
document.querySelector('[data-kg-stats]').innerHTML =
  `<b>${count(node => node.kind === 'knowledge')}</b> 个知识点 · <b>${count(node => node.kind === 'method')}</b> 个方法`
  + `（其中 <b>${count(node => node.subtype === 'technique')}</b> 个表达式的变形方法）`
  + ` · <b>${prerequisites.length}</b> 条前提关系 · <b>${uses.length}</b> 条方法依据`;

/* Topic filter: a topic shows the nodes its file selects; "cross" shows nodes chosen by two or more topics. */
const FILTERS = [
  {id: 'all', label: '全部', test: () => true},
  ...topics.map(topic => ({id: topic.id, label: topic.label, color: topicColor(topic), test: id => topic.nodes.includes(id)})),
  ...(topics.length > 1 ? [{id: 'cross', label: '只看跨专题', test: id => topicsOf(id).length > 1}] : []),
];
const filterBar = document.querySelector('[data-kg-filter]');
filterBar.innerHTML = FILTERS.map(item => `<button type="button" class="kg-filter-button" data-filter="${item.id}" aria-pressed="false">${item.color ? `<span class="kg-filter-dot" style="background:${item.color}" aria-hidden="true"></span>` : ''}${escape(item.label)}</button>`).join('');
let filter = FILTERS.find(item => item.id === new URLSearchParams(location.search).get('topic')) || FILTERS[0];

/* Highlight: a knowledge point lights up its whole prerequisite chain and the methods that use it;
   a method lights up the knowledge it uses together with their prerequisites. */
function related(id) {
  const node = nodes.get(id);
  const set = new Set([id]);
  if (node.kind === 'knowledge') {
    closure(id, before).forEach(other => set.add(other));
    closure(id, after).forEach(other => set.add(other));
    usedBy(id).forEach(other => set.add(other));
  } else {
    usesOf(id).forEach(other => { set.add(other); closure(other, before).forEach(more => set.add(more)); });
  }
  return set;
}

// Links between highlighted nodes, so the chain can light up one step at a time from the selection.
function hopsFrom(id, set) {
  const hops = new Map([[id, 0]]);
  const queue = [id];
  const links = next => [...before(next), ...after(next), ...usedBy(next), ...usesOf(next)].filter(other => set.has(other));
  while (queue.length) {
    const next = queue.shift();
    for (const other of links(next)) if (!hops.has(other)) { hops.set(other, hops.get(next) + 1); queue.push(other); }
  }
  return hops;
}

function stateFor(id) {
  const set = id ? related(id) : null;
  return {
    id, related: set, hops: id ? hopsFrom(id, set) : null,
    edgeState(edge) {
      if (!set) return 'shown';
      const shown = edge.type === 'prerequisite' ? set.has(edge.from) && set.has(edge.to) : edge.from === id || edge.to === id;
      return shown ? 'strong' : 'hidden';
    },
  };
}

/* Personal coverage (design §9.1): each problem that uses a node counts once, by the student's mark. */
let progress = null;
let signedIn = false;
const problemsOf = id => new Set(practiceOf(id).flatMap(entry => entry.problems.map(problem => problem.id)));
const segmentOf = mark => !mark?.practiced ? 'unpracticed'
  : mark.learning_status === 'mastered' ? 'mastered' : mark.learning_status === 'needs_review' ? 'review' : 'practiced';

function summarise(marks) {
  const map = new Map();
  nodes.forEach((node, id) => {
    const problems = problemsOf(id);
    if (!problems.size) return;
    const counts = Object.fromEntries(PROGRESS.map(([key]) => [key, 0]));
    problems.forEach(problem => { counts[segmentOf(marks.get(problem))] += 1; });
    map.set(id, {...counts, total: problems.size});
  });
  return map;
}

let progressTicket = 0;
async function loadProgress(user) {
  const ticket = ++progressTicket;
  signedIn = Boolean(user);
  let next = null, nextMastery = null;
  if (user) {
    try { nextMastery = await states(user); } catch { /* Keep unavailable distinct from unassessed. */ }
    try {
      const response = await fetch('/api/learning/marks', {
        credentials: 'same-origin', cache: 'no-store', headers: {'X-Learning-User': user.id},
      });
      if (response.ok) next = summarise(new Map((await response.json()).marks.map(mark => [mark.problem_id, mark])));
    } catch { /* Coverage is optional; the graph works without it. */ }
  }
  if (ticket !== progressTicket) return;
  progress = next; mastery = nextMastery;
  view?.progress(progress);
  view?.mastery?.(mastery);
  document.querySelectorAll('[data-item]').forEach(item=>{item.querySelector('summary .kn-mastery')?.remove();item.querySelector('summary')?.insertAdjacentHTML('beforeend',badge(mastery?.get(item.dataset.item)));});
  renderLegend();
  refreshPanel();
}

function progressBlock(id) {
  const problems = problemsOf(id).size;
  if (!problems) return '';
  const counts = progress?.get(id);
  if (counts) {
    return `<div class="kg-coverage"><p class="kg-coverage-title">你的练习<small>按你完成的题目和自评汇总</small></p>
      <ul>${PROGRESS.map(([key, label]) => `<li><span class="kg-coverage-swatch ${key}" aria-hidden="true"></span>${label}<b>${counts[key]}</b></li>`).join('')}</ul></div>`;
  }
  if (signedIn || !window.SiteAuth?.enabled) return '';
  return `<p class="kg-coverage-guest">本站有 ${problems} 道题用到它。<button type="button" class="kg-login" data-kg-login>登录</button>后显示你的练习情况。</p>`;
}

const chips = (ids, empty = '无') => ids.length
  ? ids.map(id => `<button type="button" class="kg-chip ${nodes.get(id).kind}" data-node="${id}">${escape(nodes.get(id).label)}</button>`).join('')
  : `<span class="kg-none">${empty}</span>`;

function detail(id) {
  const node = nodes.get(id);
  const rows = node.kind === 'knowledge'
    ? [['前提', before(id)], ['后续', after(id)], ['以它为核心依据的方法', usedBy(id)]]
    : [['核心知识依据', usesOf(id), '暂无固定连线；具体用到的知识记录在各题步骤中']];
  return `<button type="button" class="kg-panel-close" data-kg-close aria-label="关闭">×</button>
    <p class="kg-kicker ${node.kind}">${kindLabel(node)}</p>
    <h2 class="kg-title">${escape(node.label)}</h2>
    ${node.summary ? `<p class="kg-summary">${escape(node.summary)}</p>` : ''}
    <p class="kg-actions"><a class="kg-detail-link" href="${detailHref(id)}">查看详情 →</a>${node.sheet ? `<button type="button" class="kg-sheet-button" data-sheet="${node.sheet}">看图解</button>` : ''}</p>
    ${masteryBlock(mastery?.get(id))}
    ${progressBlock(id)}
    <dl class="kg-relations">${rows.map(([title, ids, empty]) => `<div><dt>${title}</dt><dd>${chips(ids, empty)}</dd></div>`).join('')}</dl>`;
}

const board = document.querySelector('[data-kg-board]');
const panel = document.querySelector('[data-kg-panel]');
const emptyPanel = panel.innerHTML;
let selected = null;

function refreshPanel() {
  panel.innerHTML = selected ? detail(selected) : emptyPanel;
  panel.classList.toggle('is-open', Boolean(selected));
  document.querySelectorAll('[data-item]').forEach(item => {
    const body = item.querySelector('.kg-item-body');
    if (item.open) body.innerHTML = detail(item.dataset.item);
  });
}

const updateUrl = () => {
  const query = filter.id === 'all' ? '' : `?topic=${encodeURIComponent(filter.id)}`;
  history.replaceState(null, '', `${location.pathname}${query}${selected ? `#${selected}` : ''}`);
};

function select(id, {scroll = false, focus = false} = {}) {
  selected = nodes.has(id) ? id : null;
  view?.highlight(stateFor(selected));
  if (selected && focus) view?.focus(selected);
  refreshPanel();
  updateUrl();
  const item = selected && document.getElementById(`kg-item-${selected}`);
  if (item) {
    item.open = true;
    if (scroll) item.scrollIntoView({block: 'nearest', behavior: 'smooth'});
  }
}
const preview = id => view?.highlight({...stateFor(id || selected), preview: Boolean(id)});

const list = document.querySelector('[data-kg-list]');
const section = (title, test) => {
  // Nodes shared by several topics come first.
  const ids = [...nodes.values()].filter(test).map(node => node.id)
    .sort((a, b) => (topicsOf(b).length > 1) - (topicsOf(a).length > 1));
  const meta = id => {
    const problems = practiceOf(id).reduce((sum, entry) => sum + entry.problems.length, 0);
    return problems ? `${problems} 道题练到` : '暂无练习';
  };
  const tabs = id => topicsOf(id).map(topic => `<span class="kg-filter-dot" style="background:${topicColor(topic)}" title="${escape(topic.label)}"></span>`).join('');
  return `<div data-list-section><h2 class="kg-list-title">${title}<small data-list-count>${ids.length}</small></h2>` + ids.map(id => `<details class="kg-item ${nodes.get(id).kind}" id="kg-item-${id}" data-item="${id}">
    <summary>${tabs(id)}<span class="kg-item-name">${escape(nodes.get(id).label)}</span>${nodes.get(id).sheet ? '<span class="kg-sheet-dot-inline" aria-label="有图解"></span>' : ''}<small>${meta(id)}</small></summary>
    <div class="kg-item-body">${detail(id)}</div>
  </details>`).join('') + '</div>';
};
list.innerHTML = section('方法', node => node.kind === 'method' && node.subtype !== 'technique')
  + section('表达式的变形方法', node => node.subtype === 'technique')
  + section('知识点', node => node.kind === 'knowledge');
list.addEventListener('toggle', event => {
  if (event.target.open && event.target.dataset.item !== selected) select(event.target.dataset.item);
}, true);

function applyFilter() {
  filterBar.querySelectorAll('[data-filter]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.filter === filter.id)));
  view?.filter(filter.test);
  document.querySelectorAll('[data-item]').forEach(item => { item.hidden = !filter.test(item.dataset.item); });
  document.querySelectorAll('[data-list-section]').forEach(group => {
    const visible = group.querySelectorAll('[data-item]:not([hidden])').length;
    group.hidden = !visible;
    group.querySelector('[data-list-count]').textContent = visible;
  });
}

/* View: 3D when WebGL works and motion is welcome; the flat SVG without WebGL or when the reader picks it.
   With reduced motion the flat view is the default, and 3D only after the reader asks for it. */
const VIEW_KEY = 'kg-view';
const storage = {
  get: () => { try { return localStorage.getItem(VIEW_KEY); } catch { return null; } },
  set: value => { try { localStorage.setItem(VIEW_KEY, value); } catch { /* private mode */ } },
};
const webgl = (() => {
  try {
    const canvas = document.createElement('canvas');
    return Boolean(canvas.getContext('webgl2') || canvas.getContext('webgl'));
  } catch { return false; }
})();
const can3d = webgl;
const calm = matchMedia('(prefers-reduced-motion: reduce)').matches;
const chosen = storage.get();
let mode = can3d && (chosen === '3d' || (!calm && chosen !== 'flat')) ? '3d' : 'flat';
let view = null;
const container = document.querySelector('[data-kg-svg]');
const legend = document.querySelector('[data-kg-legend]');
const viewToggle = document.querySelector('[data-kg-view]');

function renderLegend() {
  const items = mode === '3d' ? [
    ['knowledge', '知识点'], ['method', '方法'], ['technique', '表达式的变形方法'], ['sheet', '有图解'],
    ['halo', '光环：所属专题'], ['line prerequisite', '前提'], ['line uses', '方法的核心依据'],
  ] : [
    ['knowledge', '知识点'], ['method', '方法'], ['technique', '表达式的变形方法'], ['sheet', '有图解'],
    ['tab', '顶部色条：所属专题'], ['line prerequisite', '前提'], ['line uses', '方法的核心依据'],
  ];
  const assessment = mastery ? '<li>节点检测：绿色 已掌握 · 橙色 待巩固 · 灰色 未评估</li>' : '';
  const coverage = progress ? `<li class="kg-legend-coverage">${mode === '3d' ? '外圈' : '底部细条'}：按你完成的题目和自评汇总${PROGRESS.map(([key, label]) => `<span><i class="kg-coverage-swatch ${key}" aria-hidden="true"></i>${label}</span>`).join('')}</li>` : '';
  legend.innerHTML = items.map(([kind, label]) => `<li><span class="kg-swatch ${kind}" aria-hidden="true"></span>${label}</li>`).join('') + assessment + coverage;
}

async function mountView(next) {
  view?.destroy();
  view = null;
  mode = next;
  board.classList.toggle('is-3d', mode === '3d');
  document.body.classList.toggle('kg-mode-3d', mode === '3d');
  viewToggle.hidden = !can3d;
  viewToggle.textContent = mode === '3d' ? '切换到平面图' : '切换到 3D 星图';
  renderLegend();
  const context = {data, box, topicColor, container, select, preview};
  try {
    view = (await import(mode === '3d' ? '/knowledge/graph-3d.js?v=3' : '/knowledge/graph-svg.js?v=3')).mount(context);
  } catch (error) {
    if (mode !== '3d') throw error;
    console.warn('3D graph unavailable, using the flat view.', error);
    return mountView('flat');
  }
  view.filter(filter.test);
  view.progress(progress);
  view.mastery?.(mastery);
  view.highlight(stateFor(selected));
  if (selected) view.focus(selected);
}

filterBar.addEventListener('click', event => {
  const button = event.target.closest('[data-filter]');
  if (!button) return;
  filter = FILTERS.find(item => item.id === button.dataset.filter);
  applyFilter();
  updateUrl();
});

document.addEventListener('click', event => {
  const sheet = event.target.closest('[data-sheet]');
  if (sheet) {
    // Example problems come from the filtered topic, or from the only topic that has the node.
    const owners = topicsOf(sheet.dataset.sheet);
    const topic = owners.find(item => item.id === filter.id) || (owners.length === 1 ? owners[0] : null);
    openSheet(sheet.dataset.sheet, {topic: topic?.id});
    return;
  }
  if (event.target.closest('[data-kg-login]')) { window.SiteAuth?.open(); return; }
  if (event.target.closest('[data-kg-close]')) { select(null); return; }
  if (event.target.closest('[data-kg-view]')) {
    const next = mode === '3d' ? 'flat' : '3d';
    storage.set(next);
    void mountView(next);
    return;
  }
  const target = event.target.closest('[data-node]');
  if (target && !container.contains(target)) select(target.dataset.node, {scroll: Boolean(target.closest('[data-kg-list]')), focus: true});
});
document.addEventListener('keydown', event => { if (event.key === 'Escape' && selected && !document.querySelector('dialog[open]')) select(null); });

const fromHash = () => decodeURIComponent(location.hash.slice(1)) || null;
window.addEventListener('hashchange', () => { if (fromHash() !== selected) select(fromHash(), {scroll: true, focus: true}); });
window.addEventListener('site-auth-change', event => { void loadProgress(event.detail.user); });

await mountView(mode);
applyFilter();
select(fromHash(), {scroll: true, focus: true});
watch(()=>loadProgress(window.SiteAuth?.user));
void window.SiteAuth?.ready.then(() => loadProgress(window.SiteAuth.user));
