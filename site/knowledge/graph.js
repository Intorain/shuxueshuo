/* Renders graph.json: knowledge points layered by prerequisite, methods in the last column. */
import {loadKnowledge, escapeHtml as escape, openSheet, kindLabel} from '/knowledge/data.js?v=2';
import {detailHref} from '/assets/explain/links.js?v=1';

const NODE_W = 150;
const NODE_H = 46;
const COL_GAP = 62;
const ROW_GAP = 12;
const PAD = {top: 44, right: 64, bottom: 24, left: 24};
const LINE_UNITS = 10.5;
const TOPIC_COLORS = ['#0f8f86', '#d08a1e', '#5b6fd6', '#c2547a'];
const SVG_NS = 'http://www.w3.org/2000/svg';

const config = JSON.parse(document.getElementById('knowledge-config').textContent);
const data = await loadKnowledge(config);
const {graph, nodes, topics, prerequisites, uses, before, after, usedBy, usesOf, topicsOf, practiceOf} = data;
const topicColor = topic => TOPIC_COLORS[topics.indexOf(topic) % TOPIC_COLORS.length];

function closure(id, step) {
  const seen = new Set();
  const visit = next => step(next).forEach(other => { if (!seen.has(other)) { seen.add(other); visit(other); } });
  visit(id);
  return seen;
}

const svg = (tag, attrs = {}) => {
  const element = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs)) element.setAttribute(key, value);
  return element;
};

/* Layout: a knowledge point sits as far right as its successors allow, so points without
   prerequisite links end up next to the methods that use them. */
function layout() {
  const knowledge = [...nodes.values()].filter(node => node.kind === 'knowledge');
  const depth = new Map();
  const toSink = id => {
    if (!depth.has(id)) depth.set(id, Math.max(-1, ...after(id).map(toSink)) + 1);
    return depth.get(id);
  };
  knowledge.forEach(node => toSink(node.id));
  const knowledgeCols = Math.max(...depth.values()) + 1;
  const columns = Array.from({length: knowledgeCols + 1}, () => []);
  knowledge.forEach(node => columns[knowledgeCols - 1 - depth.get(node.id)].push(node.id));
  nodes.forEach(node => { if (node.kind === 'method') columns[knowledgeCols].push(node.id); });

  // Edges run left to right. One that skips columns gets an empty slot in every column it
  // crosses, so it passes through a gap instead of behind other nodes.
  const columnOf = new Map(columns.flatMap((ids, index) => ids.map(id => [id, index])));
  const adjacent = new Map();
  const connect = (a, b) => [[a, b], [b, a]].forEach(([p, q]) => adjacent.set(p, [...(adjacent.get(p) || []), q]));
  const via = new Map();
  [...prerequisites.map(edge => [edge.from, edge.to]), ...uses.map(edge => [edge.to, edge.from])].forEach(([left, right]) => {
    const slots = [];
    for (let col = columnOf.get(left) + 1; col < columnOf.get(right); col += 1) {
      slots.push(`${left}>${right}@${col}`);
      columns[col].push(slots.at(-1));
    }
    [left, ...slots, right].reduce((a, b) => { connect(a, b); return b; });
    via.set(`${left}>${right}`, slots);
  });
  const neighbours = id => adjacent.get(id) || [];
  const height = Math.max(...columns.map(column => column.length)) * (NODE_H + ROW_GAP) - ROW_GAP;
  const y = new Map();
  const place = () => columns.forEach(column => {
    const top = PAD.top + (height - (column.length * (NODE_H + ROW_GAP) - ROW_GAP)) / 2;
    column.forEach((id, index) => y.set(id, top + index * (NODE_H + ROW_GAP)));
  });
  place();
  // A few barycentre sweeps keep related nodes at similar heights.
  for (let sweep = 0; sweep < 8; sweep += 1) {
    const order = sweep % 2 ? [...columns].reverse() : columns;
    for (const column of order) {
      const centre = id => {
        const ys = neighbours(id).map(other => y.get(other));
        return ys.length ? ys.reduce((sum, value) => sum + value, 0) / ys.length : y.get(id);
      };
      const keys = new Map(column.map(id => [id, centre(id)]));
      column.sort((a, b) => keys.get(a) - keys.get(b));
      place();
    }
  }
  const x = new Map();
  columns.forEach((column, index) => column.forEach(id => x.set(id, PAD.left + index * (NODE_W + COL_GAP))));
  return {
    x, y, via, knowledgeCols,
    width: PAD.left + columns.length * (NODE_W + COL_GAP) - COL_GAP + PAD.right,
    height: PAD.top + height + PAD.bottom,
  };
}

/* Two lines at most: break after punctuation or a space when both halves fit, otherwise
   at the visual middle. Widths are in CJK characters. */
function wrap(label) {
  const chars = [...label];
  const widths = chars.map(ch => ch.charCodeAt(0) > 255 ? 1 : 0.55);
  const total = widths.reduce((sum, value) => sum + value, 0);
  if (total <= LINE_UNITS) return [label];
  const prefix = widths.map((_, index) => widths.slice(0, index + 1).reduce((sum, value) => sum + value, 0));
  const fits = index => prefix[index] <= LINE_UNITS && total - prefix[index] <= LINE_UNITS;
  const breaks = chars.map((ch, index) => index).filter(index => '：，、／→ '.includes(chars[index]) && fits(index));
  const nearest = list => list.reduce((best, index) => Math.abs(prefix[index] - total / 2) < Math.abs(prefix[best] - total / 2) ? index : best, list[0]);
  const index = breaks.length ? nearest(breaks) : nearest(chars.map((_, i) => i));
  return [chars.slice(0, index + 1).join('').trim(), chars.slice(index + 1).join('').trim()];
}

const box = layout();
const root = svg('svg', {
  viewBox: `0 0 ${box.width} ${box.height}`, width: box.width, height: box.height,
  class: 'kg-svg', role: 'group', 'aria-label': '知识点与方法的关系图',
});
const edgeLayer = svg('g', {class: 'kg-edges'});
const nodeLayer = svg('g', {class: 'kg-nodes'});
const defs = svg('defs');
const arrow = svg('marker', {id: 'kg-arrow', viewBox: '0 0 8 8', refX: 7, refY: 4, markerWidth: 7, markerHeight: 7, orient: 'auto-start-reverse'});
arrow.append(svg('path', {d: 'M0 0 8 4 0 8z', class: 'kg-arrow'}));
defs.append(arrow);
root.append(defs);

const titleX = col => PAD.left + col * (NODE_W + COL_GAP);
const knowledgeTitle = svg('text', {x: titleX(0), y: 22, class: 'kg-col-title'});
knowledgeTitle.textContent = '知识点 · 前提在左';
const methodTitle = svg('text', {x: titleX(box.knowledgeCols), y: 22, class: 'kg-col-title'});
methodTitle.textContent = '方法';
root.append(knowledgeTitle, methodTitle, edgeLayer, nodeLayer);

const edgeElements = [];
function link(edge, from, to) {
  let x0 = box.x.get(from) + NODE_W;
  let y0 = box.y.get(from) + NODE_H / 2;
  let d = `M${x0} ${y0}`;
  const stops = [...box.via.get(`${from}>${to}`), to];
  stops.forEach((id, index) => {
    const x1 = box.x.get(id);
    const y1 = box.y.get(id) + NODE_H / 2;
    const dx = Math.max(36, (x1 - x0) / 2);
    d += ` C${x0 + dx} ${y0} ${x1 - dx} ${y1} ${x1} ${y1}`;
    x0 = index < stops.length - 1 ? x1 + NODE_W : x1;
    y0 = y1;
    if (x0 !== x1) d += ` H${x0}`;
  });
  const path = svg('path', {d, class: `kg-edge ${edge.type}`});
  if (edge.type === 'prerequisite') path.setAttribute('marker-end', 'url(#kg-arrow)');
  edgeLayer.append(path);
  edgeElements.push({edge, path});
}
prerequisites.forEach(edge => link(edge, edge.from, edge.to));
uses.forEach(edge => link(edge, edge.to, edge.from));

const nodeElements = new Map();
nodes.forEach(node => {
  const practiced = practiceOf(node.id).length > 0;
  const group = svg('g', {
    class: ['kg-node', node.kind, node.subtype, practiced ? '' : 'is-unpracticed'].filter(Boolean).join(' '),
    transform: `translate(${box.x.get(node.id)} ${box.y.get(node.id)})`,
    tabindex: 0, role: 'button', 'data-node': node.id, 'aria-label': `${kindLabel(node)}：${node.label}`,
  });
  group.append(svg('rect', {width: NODE_W, height: NODE_H, rx: node.kind === 'method' ? 12 : 9, class: 'kg-box'}));
  topicsOf(node.id).forEach((topic, index) => {
    const tab = svg('rect', {x: 10 + index * 22, y: -3, width: 18, height: 6, rx: 3, fill: topicColor(topic), class: 'kg-topic-tab'});
    tab.append(Object.assign(svg('title'), {textContent: topic.label}));
    group.append(tab);
  });
  const lines = wrap(node.label);
  const text = svg('text', {x: NODE_W / 2, y: NODE_H / 2 - (lines.length - 1) * 8 + 4.5});
  lines.forEach((line, index) => {
    const span = svg('tspan', {x: NODE_W / 2, dy: index ? 16 : 0});
    span.textContent = line;
    text.append(span);
  });
  group.append(text);
  if (node.sheet) group.append(svg('circle', {cx: NODE_W - 9, cy: 9, r: 4, class: 'kg-sheet-dot'}));
  nodeLayer.append(group);
  nodeElements.set(node.id, group);
});
document.querySelector('[data-kg-svg]').append(root);

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

function applyFilter() {
  filterBar.querySelectorAll('[data-filter]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.filter === filter.id)));
  nodeElements.forEach((element, id) => element.classList.toggle('is-out', !filter.test(id)));
  for (const {edge, path} of edgeElements) path.classList.toggle('is-out', !filter.test(edge.from) || !filter.test(edge.to));
  document.querySelectorAll('[data-item]').forEach(item => { item.hidden = !filter.test(item.dataset.item); });
  document.querySelectorAll('[data-list-section]').forEach(section => {
    const visible = section.querySelectorAll('[data-item]:not([hidden])').length;
    section.hidden = !visible;
    section.querySelector('[data-list-count]').textContent = visible;
  });
}

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

function highlight(id) {
  const set = id ? related(id) : null;
  nodeElements.forEach((element, key) => {
    element.classList.toggle('is-selected', key === id);
    element.classList.toggle('is-related', Boolean(set?.has(key)) && key !== id);
    element.classList.toggle('is-dim', Boolean(set) && !set.has(key));
  });
  for (const {edge, path} of edgeElements) {
    const touches = edge.from === id || edge.to === id;
    const shown = !set || (edge.type === 'prerequisite' ? set.has(edge.from) && set.has(edge.to) : touches);
    path.classList.toggle('is-shown', shown);
    path.classList.toggle('is-strong', Boolean(set) && shown);
  }
}

const chips = (ids, empty = '无') => ids.length
  ? ids.map(id => `<button type="button" class="kg-chip ${nodes.get(id).kind}" data-node="${id}">${escape(nodes.get(id).label)}</button>`).join('')
  : `<span class="kg-none">${empty}</span>`;

function detail(id) {
  const node = nodes.get(id);
  const rows = node.kind === 'knowledge'
    ? [['前提', before(id)], ['后续', after(id)], ['以它为核心依据的方法', usedBy(id)]]
    : [['核心知识依据', usesOf(id), '暂无固定连线；具体用到的知识记录在各题步骤中']];
  return `<p class="kg-kicker ${node.kind}">${kindLabel(node)}</p>
    <h2 class="kg-title">${escape(node.label)}</h2>
    ${node.summary ? `<p class="kg-summary">${escape(node.summary)}</p>` : ''}
    <p class="kg-actions"><a class="kg-detail-link" href="${detailHref(id)}">查看详情 →</a>${node.sheet ? `<button type="button" class="kg-sheet-button" data-sheet="${node.sheet}">看图解</button>` : ''}</p>
    <dl class="kg-relations">${rows.map(([title, ids, empty]) => `<div><dt>${title}</dt><dd>${chips(ids, empty)}</dd></div>`).join('')}</dl>`;
}

const panel = document.querySelector('[data-kg-panel]');
const emptyPanel = panel.innerHTML;
let selected = null;

const updateUrl = () => {
  const query = filter.id === 'all' ? '' : `?topic=${encodeURIComponent(filter.id)}`;
  history.replaceState(null, '', `${location.pathname}${query}${selected ? `#${selected}` : ''}`);
};

function select(id, {scroll = false} = {}) {
  selected = nodes.has(id) ? id : null;
  highlight(selected);
  panel.innerHTML = selected ? detail(selected) : emptyPanel;
  updateUrl();
  const item = selected && document.getElementById(`kg-item-${selected}`);
  if (item) {
    item.open = true;
    if (scroll) item.scrollIntoView({block: 'nearest', behavior: 'smooth'});
  }
}

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
  const target = event.target.closest('[data-node]');
  if (target) select(target.dataset.node, {scroll: !target.closest('svg')});
  else if (event.target.closest('.kg-svg')) select(null);
});
nodeLayer.addEventListener('keydown', event => {
  const target = event.target.closest('[data-node]');
  if (target && (event.key === 'Enter' || event.key === ' ')) { event.preventDefault(); select(target.dataset.node); }
});
document.addEventListener('keydown', event => { if (event.key === 'Escape' && selected && !document.querySelector('dialog[open]')) select(null); });
nodeLayer.addEventListener('pointerover', event => {
  const target = event.target.closest('[data-node]');
  if (target && event.pointerType === 'mouse') highlight(target.dataset.node);
});
nodeLayer.addEventListener('pointerleave', () => highlight(selected));

const fromHash = () => decodeURIComponent(location.hash.slice(1)) || null;
window.addEventListener('hashchange', () => { if (fromHash() !== selected) select(fromHash(), {scroll: true}); });
applyFilter();
select(fromHash(), {scroll: true});
