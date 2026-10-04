/* Explainers: every graph node with one has its own module under knowledge/ or method/,
   shown in a shared dialog (openExplainer) or inside a node's detail page (renderExplainer). */
import {escapeHtml as escape} from './shared/html.js?v=1';
import {TOPIC_URL, detailHref} from './links.js?v=1';

const MODULE_VERSION = 1;
const GRAPH_URL = '/data/knowledge/graph.json?v=2';
const SHELL_CSS = new URL('explain.css?v=1', import.meta.url).href;
const KATEX = '/assets/practice/vendor/katex-0.18.9';
const MATH_SCRIPTS = [`${KATEX}/katex.min.js`, `${KATEX}/auto-render.min.js`, '/assets/practice/math-text.js?v=12'];

const loading = new Map();
// A failed load is forgotten so the next click retries it.
const once = (key, load) => {
  if (!loading.has(key)) loading.set(key, load().catch(error => { loading.delete(key); throw error; }));
  return loading.get(key);
};
const fetchJson = url => once(url, () => fetch(url).then(response => {
  if (!response.ok) throw new Error(`${url}: ${response.status}`);
  return response.json();
}));
const insert = (tag, attributes) => new Promise((resolve, reject) => {
  const element = Object.assign(document.createElement(tag), attributes);
  element.onload = resolve;
  element.onerror = () => reject(new Error(attributes.href || attributes.src));
  document.head.append(element);
});
const stylesheet = href => once(href, () => insert('link', {rel: 'stylesheet', href}));
const script = src => once(src, () => insert('script', {src}));
const graph = () => once('graph', () => fetchJson(GRAPH_URL).then(data => new Map(data.nodes.map(node => [node.id, node]))));
const explainer = id => once(`module:${id}`, () => import(new URL(`${id.startsWith('method-') ? 'method' : 'knowledge'}/${id}.js?v=${MODULE_VERSION}`, import.meta.url).href).then(module => module.default));

// Catalog pages do not load KaTeX; it is fetched only when an explainer actually contains a formula.
async function renderMath(root) {
  const elements = root.querySelectorAll('[data-math-text]');
  if (!elements.length) return;
  if (!window.PracticeMath) {
    stylesheet(`${KATEX}/katex.min.css`).catch(() => {});
    for (const src of MATH_SCRIPTS) await script(src);
  }
  for (const element of elements) window.PracticeMath.render(element, element.textContent);
}

const kindLabel = node => node.kind === 'knowledge' ? '知识点' : node.subtype === 'technique' ? '变形方法' : '方法';

async function load(id, tip, topic) {
  const [nodes, module, topicData] = await Promise.all([
    graph(), explainer(id), topic ? fetchJson(TOPIC_URL(topic)).catch(() => null) : null, stylesheet(SHELL_CSS),
  ]);
  const node = nodes.get(id);
  if (!node) throw new Error(`unknown node ${id}`);
  if (module.stylesheet) await stylesheet(module.stylesheet);
  return {nodes, module, context: {node, tip, topic: topicData?.nodes.includes(id) ? topicData : null}};
}

async function fill(body, className, {nodes, module, context}) {
  body.className = `${className} explain-${context.node.id}`;
  body.innerHTML = module.render(context);
  for (const button of body.querySelectorAll('[data-explain-open]')) {
    if (!button.textContent.trim()) button.textContent = nodes.get(button.dataset.explainOpen)?.label || '';
  }
  await renderMath(body).catch(() => {});
}

let sheet = null;
let cleanup = null;
let current = null;

function shell() {
  if (sheet) return sheet;
  sheet = document.createElement('dialog');
  sheet.className = 'explain-sheet';
  sheet.setAttribute('aria-labelledby', 'explain-title');
  sheet.innerHTML = `<div class="explain-inner">
    <header class="explain-head">
      <span class="explain-kicker"></span>
      <h2 id="explain-title" tabindex="-1"></h2>
      <button class="explain-close" type="button" aria-label="关闭图解"><svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true"><path d="m4 4 8 8M12 4l-8 8" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg></button>
    </header>
    <div class="explain-body"></div>
    <footer class="explain-foot" hidden></footer>
  </div>`;
  document.body.append(sheet);
  // The inner wrapper fills the dialog, so a click on the dialog itself is the backdrop.
  sheet.addEventListener('click', event => {
    if (event.target === sheet || event.target.closest('.explain-close')) { sheet.close(); return; }
    const next = event.target.closest('[data-explain-open]');
    if (next) openExplainer(next.dataset.explainOpen, {...current, tip: null}).catch(() => {});
  });
  sheet.addEventListener('close', () => { cleanup?.(); cleanup = null; });
  return sheet;
}

// options.tip: the step's {case, note}, passed only after the step is answered.
// options.topic: the topic ID the caller is showing; method explainers read its methods.
// options.detail: false on practice pages, which do not lead the student away from the problem.
// Rejects when the explainer cannot be loaded, so callers can say so without blocking the page.
export async function openExplainer(id, {tip = null, topic = null, detail = true} = {}) {
  const loaded = await load(id, tip, topic);
  const {node} = loaded.context;
  const dialog = shell();
  cleanup?.();
  cleanup = null;
  current = {topic, detail};
  dialog.querySelector('.explain-kicker').textContent = kindLabel(node);
  dialog.querySelector('h2').textContent = node.label;
  const body = dialog.querySelector('.explain-body');
  const foot = dialog.querySelector('.explain-foot');
  foot.innerHTML = detail ? `<a class="explain-detail" href="${detailHref(id)}">查看“${escape(node.label)}”的详情 →</a>` : '';
  foot.hidden = !detail;
  await fill(body, 'explain-body', loaded);
  cleanup = loaded.module.mount?.(body, loaded.context) || null;
  if (!dialog.open) dialog.showModal();
  dialog.scrollTop = 0;
  dialog.querySelector('h2').focus({preventScroll: true});
  return true;
}

// Detail pages show the explainer in place; a link to another explainer opens that node's detail page.
// Returns the module's cleanup, or null.
export async function renderExplainer(root, id) {
  const loaded = await load(id, null, null);
  await fill(root, 'explain-inline', loaded);
  root.addEventListener('click', event => {
    const next = event.target.closest('[data-explain-open]');
    if (next) location.href = detailHref(next.dataset.explainOpen);
  });
  return loaded.module.mount?.(root, loaded.context) || null;
}
