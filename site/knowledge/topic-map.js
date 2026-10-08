/* Topic knowledge map: one column per method, its steps' knowledge in route order. */
import {loadKnowledge, escapeHtml as escape, openSheet, kindLabel} from '/knowledge/data.js?v=3';
import {detailHref} from '/assets/explain/links.js?v=2';

const root = document.querySelector('[data-topic-map]');
const config = JSON.parse(document.getElementById('topic-map-config').textContent);
const data = await loadKnowledge({...config, topics: [config.topic, ...(config.others || [])]});
const {nodes, before, after, topicsOf} = data;
const topic = data.topics[0];

const routeProblems = route => Object.values(topic.problems).filter(problem => problem.routes[route]);
const problemsInRoute = (route, id) => routeProblems(route).filter(problem => Object.values(problem.routes[route]).some(ids => ids.includes(id)));
const totalSteps = Object.values(topic.problems).reduce((sum, problem) => sum + Object.values(problem.routes).reduce((n, steps) => n + Object.keys(steps).length, 0), 0);
const alsoIn = id => topicsOf(id).filter(other => other !== topic);

root.querySelector('[data-map-stats]').innerHTML = [
  [topic.nodes.filter(id => nodes.get(id).kind === 'knowledge').length, '个知识点'],
  [topic.nodes.filter(id => nodes.get(id).kind === 'method').length, '个方法'],
  [totalSteps, '个步骤'],
].map(([value, unit]) => `<strong>${value}</strong> ${unit}`).join(' · ');

const card = (id, route) => {
  const node = nodes.get(id);
  return `<li><button type="button" class="tm-card ${node.kind} ${node.subtype || ''}" data-node="${id}">
    <span class="tm-card-name">${escape(node.label)}</span>
    <span class="tm-card-meta">${problemsInRoute(route, id).length} 题${node.sheet ? '<i class="tm-sheet-dot" aria-label="有图解"></i>' : ''}</span>
  </button></li>`;
};

root.querySelector('[data-map-grid]').innerHTML = topic.methods.map((method, index) => {
  const node = nodes.get(method.node);
  return `<section class="tm-column" aria-label="${escape(node.label)}">
    <header class="tm-head">
      <span class="type-index" aria-hidden="true">${String(index + 1).padStart(2, '0')}</span>
      <button type="button" class="tm-method" data-node="${method.node}">${escape(node.label)}</button>
      <span class="tm-head-meta">${routeProblems(method.route).length} 道题可用${node.sheet ? ` · <button type="button" class="tm-dialog" data-sheet="${node.sheet}">图解</button>` : ''}</span>
    </header>
    <ol class="tm-steps">${method.sequence.map(id => card(id, method.route)).join('')}</ol>
  </section>`;
}).join('');

const detailBox = root.querySelector('[data-map-detail]');
let selected = null;

function detail(id) {
  const node = nodes.get(id);
  const methods = topic.methods.filter(method => method.node === id || method.sequence.includes(id)).map(method => method.node).filter(other => other !== id);
  const relation = (title, ids) => ids.length ? `<div><dt>${title}</dt><dd>${ids.map(other => `<a class="tm-chip" href="/knowledge/?topic=${topic.id}#${other}">${escape(nodes.get(other).label)}</a>`).join('')}</dd></div>` : '';
  return `<div class="tm-detail-head">
      <div><p class="tm-kicker ${node.kind}">${kindLabel(node)}</p><h3>${escape(node.label)}</h3></div>
      <button type="button" class="tm-close" data-close aria-label="关闭">×</button>
    </div>
    ${node.summary ? `<p class="tm-summary">${escape(node.summary)}</p>` : ''}
    <a class="tm-detail-link" href="${detailHref(id)}">查看详情 →</a>
    <dl class="tm-relations">
      ${methods.length ? `<div><dt>本专题里用到它的方法</dt><dd>${methods.map(other => `<button type="button" class="tm-chip" data-node="${other}">${escape(nodes.get(other).label)}</button>`).join('')}</dd></div>` : ''}
      ${relation('前提', before(id))}${relation('后续', after(id))}
      ${alsoIn(id).length ? `<div><dt>也在其他专题</dt><dd>${alsoIn(id).map(other => `<a class="tm-chip" href="${other.path}">${escape(other.label)}</a>`).join('')}</dd></div>` : ''}
    </dl>
    <p class="tm-actions">
      ${node.sheet ? `<button type="button" class="tm-sheet" data-sheet="${node.sheet}">看图解 →</button>` : ''}
      <a class="tm-graph" href="/knowledge/?topic=${topic.id}#${id}">在知识图谱中查看 →</a>
    </p>`;
}

function select(id) {
  selected = id && id !== selected ? id : null;
  root.querySelectorAll('.tm-card, .tm-method').forEach(element => element.classList.toggle('is-selected', element.dataset.node === selected));
  root.classList.toggle('has-selection', Boolean(selected));
  detailBox.hidden = !selected;
  detailBox.innerHTML = selected ? detail(selected) : '';
  if (selected) detailBox.scrollIntoView({block: 'nearest', behavior: 'smooth'});
}

function hover(id) {
  root.querySelectorAll('.tm-card, .tm-method').forEach(element => element.classList.toggle('is-same', Boolean(id) && element.dataset.node === id));
}

root.addEventListener('click', event => {
  const sheet = event.target.closest('[data-sheet]');
  if (sheet) { openSheet(sheet.dataset.sheet, {topic: topic.id}); return; }
  if (event.target.closest('[data-close]')) { select(null); return; }
  const target = event.target.closest('button[data-node]');
  if (target) select(target.dataset.node);
});
root.addEventListener('pointerover', event => hover(event.target.closest('[data-node]')?.dataset.node));
root.addEventListener('pointerleave', () => hover(null));
root.addEventListener('focusin', event => hover(event.target.closest('[data-node]')?.dataset.node));
root.addEventListener('focusout', () => hover(null));
document.addEventListener('keydown', event => { if (event.key === 'Escape' && selected && !document.querySelector('dialog[open]')) select(null); });
root.hidden = false;
