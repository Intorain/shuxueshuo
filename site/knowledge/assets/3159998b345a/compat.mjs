import { chapterPath, scopeMembers } from './model.mjs';

// Compatibility pages contain only a destination and a normal fallback link.
// Query state is carried forward, but destinations always come from our manifest.
export function compatibilityHref(target, current) {
  const source = new URL(current, 'https://knowledge.invalid');
  const next = new URL(target, source);
  if (next.origin !== source.origin || !next.pathname.startsWith('/knowledge/')) {
    throw new Error('兼容入口必须指向本站知识图谱');
  }
  for (const [key, value] of source.searchParams) {
    if (!next.searchParams.has(key)) next.searchParams.set(key, value);
  }
  const graph = next.searchParams.get('graph');
  if (graph?.startsWith('/knowledge-next/')) {
    next.searchParams.set('graph', graph.replace('/knowledge-next/', '/knowledge/'));
  }
  // An explicitly mapped entry wins over an obsolete entry on the old node.
  if (!next.hash) next.hash = source.hash;
  return next.pathname + next.search + next.hash;
}

export function legacyGraphHref(graph, migration, current) {
  const source = new URL(current, 'https://knowledge.invalid');
  const topics = { 'basic-inequality': 'section-2-2', 'quadratic-always': 'section-2-3' };
  const oldId = source.searchParams.get('node') || decodeURIComponent(source.hash.slice(1));
  const row = migration.nodes.find(node => node.legacy === oldId);
  const ref = migration.legacyRefs[oldId] || oldId;
  if (row?.targets.length > 1 && !migration.legacyRefs[oldId]) {
    source.hash = '';
    source.searchParams.delete('node');
    return compatibilityHref(`/knowledge/${oldId}/`, source.href);
  }
  const [id] = ref.split('#');
  const byId = new Map(graph.nodes.map(node => [node.id, node]));
  const node = byId.get(id);
  const scope = topics[source.searchParams.get('topic')] || source.searchParams.get('scope');
  const home = node?.home || byId.get(scope)?.home;
  if (!home) return null;
  const chapter = graph.chapters.find(chapter => chapter.id === home);
  if (!chapter) return null;
  const next = new URL(chapterPath(home), source);
  source.searchParams.forEach((value, key) => next.searchParams.set(key, value));
  next.searchParams.delete('topic');
  if (node) {
    next.searchParams.set('node', id);
    const expanded = new Set((next.searchParams.get('expand') || '').split(',').filter(Boolean));
    expanded.add(id);
    next.searchParams.set('expand', [...expanded].join(','));
  }
  if (!scope || ![chapter.node, ...chapter.sections.map(section => section.id)].includes(scope)) {
    next.searchParams.set('scope', chapter.sections.find(section => scopeMembers(graph, section.id).has(id))?.id || chapter.node);
  } else next.searchParams.set('scope', scope);
  if (!next.searchParams.has('view') && node) {
    next.searchParams.set('view', node.kind === 'knowledge' ? 'knowledge' : ['textbook', 'chapter', 'section'].includes(node.kind) ? 'curriculum' : 'solution');
  }
  return next.pathname + next.search;
}

if (typeof document !== 'undefined') {
  const config = document.querySelector('#compat-config');
  if (config) {
    const { target } = JSON.parse(config.textContent);
    const href = compatibilityHref(target, location.href);
    document.querySelector('[data-compat-link]').href = href;
    location.replace(href);
  }
}
