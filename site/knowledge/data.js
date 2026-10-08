/* Loads graph.json, display.json and topic files, and derives per-node practice usage. */
const fetchJson = url => fetch(url).then(response => {
  if (!response.ok) throw new Error(`${url}: ${response.status}`);
  return response.json();
});

export async function loadKnowledge({graph: graphUrl, display: displayUrl, topics: topicUrls = []}) {
  const [graph, display, ...topics] = await Promise.all([graphUrl, displayUrl, ...topicUrls].map(fetchJson));
  const nodes = new Map(graph.nodes.map(node => [node.id, {...node, ...display[node.id]}]));
  const edges = type => graph.edges.filter(edge => edge.type === type);
  const prerequisites = edges('prerequisite');
  const uses = edges('uses');

  // usage.get(topicId).get(nodeId) = {problems: [{id, label, path}], steps}
  // A route practises its own method even when no step is tagged with it (e.g. /1/ direct), so that method
  // counts the problem with no extra steps.
  const usage = new Map(topics.map(topic => {
    const byNode = new Map();
    const routeMethod = new Map(topic.methods.map(method => [method.route, method.node]));
    const add = (nodeId, id, problem, steps) => {
      const entry = byNode.get(nodeId) || {problems: [], steps: 0};
      entry.steps += steps;
      if (!entry.problems.some(item => item.id === id)) entry.problems.push({id, label: problem.label, path: problem.path});
      byNode.set(nodeId, entry);
    };
    for (const [id, problem] of Object.entries(topic.problems)) {
      for (const [route, steps] of Object.entries(problem.routes)) {
        if (routeMethod.has(route)) add(routeMethod.get(route), id, problem, 0);
        for (const ids of Object.values(steps)) for (const nodeId of ids) add(nodeId, id, problem, 1);
      }
    }
    return [topic.id, byNode];
  }));

  return {
    graph, nodes, topics, usage, prerequisites, uses,
    before: id => prerequisites.filter(edge => edge.to === id).map(edge => edge.from),
    after: id => prerequisites.filter(edge => edge.from === id).map(edge => edge.to),
    usedBy: id => uses.filter(edge => edge.to === id).map(edge => edge.from),
    usesOf: id => uses.filter(edge => edge.from === id).map(edge => edge.to),
    topicsOf: id => topics.filter(topic => topic.nodes.includes(id)),
    practiceOf: id => topics.map(topic => ({topic, ...usage.get(topic.id).get(id)})).filter(entry => entry.problems?.length),
  };
}

export const escapeHtml = text => String(text).replace(/[&<>"]/g, ch => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[ch]));

let explainModule = null;
export function openSheet(id, options = {}) {
  explainModule ||= import('/assets/explain/explain.js?v=2');
  explainModule.then(module => module.openExplainer(id, options)).catch(() => { explainModule = null; });
}

export const kindLabel = node => node.subtype === 'technique' ? '方法 · 表达式的变形' : node.kind === 'method' ? '方法' : '知识点';
