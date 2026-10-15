import {bindModeLinks} from '/assets/practice/learning-mode.mjs';

bindModeLinks(document, location.href);
try {
  const response = await fetch('/knowledge/graph.json', {cache: 'no-cache'});
  if (!response.ok) throw Error('图谱暂不可用');
  const graph = await response.json();
  const kinds = {knowledge: '知识点', skill: '技能', method: '方法', problem_type: '题型'};
  document.querySelector('[data-graph-desc]').textContent = Object.entries(kinds)
    .map(([kind, label]) => `${graph.nodes.filter(node => node.kind === kind).length} 个${label}`)
    .join('、');
} catch { /* The static overview and all topic links remain usable. */ }
