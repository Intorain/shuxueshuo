import {bindModeLinks, isPreview, modeHref} from './learning-mode.mjs';

const labels = {knowledge: '知识点', skill: '技能', method: '方法', problem_type: '题型'};
const escape = text => String(text).replace(/[&<>"']/g, character =>
  ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[character]));

function leaves(tree) {
  if (!tree) return [];
  if (tree.field) return Object.values(tree.options).flatMap(leaves);
  return Array.isArray(tree) ? tree : [tree.ref];
}

// A topic overview includes all authored alternatives. It is not evidence of a
// student's selected route, and never reconstructs methods from group labels.
export function topicNodeGroups(topic, catalog) {
  const uses = new Map();
  for (const [problemId, problem] of Object.entries(topic.problems)) {
    const refs = [...problem.types];
    for (const route of Object.values(problem.routes)) {
      refs.push(...leaves(route.methods));
      for (const step of Object.values(route.steps)) refs.push(...leaves(step.refs), ...leaves(step.tip));
    }
    for (const id of new Set(refs.filter(Boolean).map(ref => ref.split('#')[0]))) {
      const node = catalog[id];
      if (!node || !labels[node.kind]) continue;
      if (!uses.has(id)) uses.set(id, {...node, problems: []});
      uses.get(id).problems.push({id: problemId, path: problem.path});
    }
  }
  return Object.entries(labels).map(([kind, label]) => ({
    kind, label, nodes: [...uses.values()].filter(node => node.kind === kind)
      .sort((a, b) => a.label.localeCompare(b.label, 'zh-CN'))
  }));
}

async function initialize() {
  bindModeLinks(document, location.href);
  const root = document.querySelector('[data-topic-map]');
  if (!root) return;
  const topicId = root.dataset.topic;
  const preview = isPreview(location.search);
  const href = path => modeHref(path, {preview}, location.href);
  const read = async url => {
    const response = await fetch(url, {cache: 'no-cache', signal: AbortSignal.timeout(15000)});
    if (!response.ok) throw Error('关联加载失败');
    return response.json();
  };
  root.hidden = false;
  const stats = root.querySelector('[data-map-stats]');
  const grid = root.querySelector('[data-map-grid]');
  let loading = false;
  async function load() {
    if (loading) return;
    loading = true;
    stats.textContent = '正在加载教学关联…';
    try {
      const [topic, catalog] = await Promise.all([
        read(`/knowledge/teaching/topics/${encodeURIComponent(topicId)}.json`),
        read('/knowledge/teaching/catalog.json')
      ]);
      const groups = topicNodeGroups(topic, catalog);
      stats.textContent = groups.map(group => `${group.nodes.length} 个${group.label}`).join(' · ');
      grid.innerHTML = groups.map(group => `<section class="tm-column" aria-label="${group.label}">
        <header class="tm-head"><h3>${group.label}</h3><span class="tm-head-meta">${group.nodes.length} 个</span></header>
        <ul class="tm-steps">${group.nodes.map(node => `<li><a class="tm-card ${node.kind}" href="${href(`/knowledge/${node.id}/`)}">
          <span class="tm-card-name">${escape(node.label)}</span><span class="tm-card-meta">${node.problems.length} 道题涉及</span>
        </a></li>`).join('')}</ul></section>`).join('');
      for (const anchor of document.querySelectorAll('[data-node-ref]')) {
        const node = catalog[anchor.dataset.nodeRef];
        if (node) anchor.setAttribute('aria-label', `查看${labels[node.kind] || '节点'}：${node.label}`);
      }
    } catch {
      stats.textContent = '暂时无法加载教学关联，题目和知识图谱链接仍可使用。';
      grid.innerHTML = '<button type="button" data-retry-map>重试加载</button>';
      grid.querySelector('[data-retry-map]').addEventListener('click', load);
    } finally {
      loading = false;
    }
  }
  await load();
}

if (typeof document !== 'undefined') initialize();
