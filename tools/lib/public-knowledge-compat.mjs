import { escapeHtml as h } from '../../site/assets/knowledge-next/resource-links.mjs';
import { nodeHref } from '../../site/assets/knowledge-next/model.mjs';

export function noScriptRedirect(target) {
  // The script preserves the current query/hash. This fixed fallback must be
  // inactive when scripting is enabled, so it cannot race that navigation.
  return `<noscript><meta http-equiv="refresh" content="0;url=${h(target)}"></noscript>`;
}

export function redirectPage(target, version) {
  const config = JSON.stringify({ target }).replace(/</g, '\\u003c');
  return `<!doctype html>
<!-- Generated compatibility entry. -->
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>知识图谱 · 数学说</title><link rel="canonical" href="${h(target.split('#')[0])}">${noScriptRedirect(target)}</head>
<body><main><p>知识图谱已更新。</p><a data-compat-link href="${h(target)}">打开知识图谱</a></main><script id="compat-config" type="application/json">${config}</script><script type="module" src="/knowledge/assets/${version}/compat.mjs"></script></body></html>\n`;
}

export function legacyNodeOutputs(migration, nodes, version) {
  const outputs = new Map();
  const byId = new Map(nodes.map(node => [node.id, node]));
  for (const row of migration.nodes) {
    if (byId.has(row.legacy)) continue;
    const target = migration.legacyRefs[row.legacy] || (row.targets.length === 1 ? row.targets[0] : null);
    if (target) {
      outputs.set(`${row.legacy}/index.html`, redirectPage(nodeHref(target), version));
      continue;
    }
    const links = row.targets.map(ref => {
      const [id, entry] = ref.split('#');
      const node = byId.get(id);
      const part = ['entries', 'operations', 'steps', 'branches'].flatMap(key => node[key] || []).find(item => item.id === entry);
      return `<li><a href="${nodeHref(ref)}">${h(node.label)}${part ? ` · ${h(part.title)}` : ''}</a></li>`;
    }).join('');
    outputs.set(`${row.legacy}/index.html`, `<!doctype html>
<!-- Generated compatibility entry. -->
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>原节点的新位置 · 数学说</title></head>
<body><main><h1>原节点的新位置</h1><p>这部分内容已按解题方法分别整理，请选择需要的内容。</p><ul>${links}</ul><a href="/knowledge/">返回知识图谱</a></main><script type="module" src="/knowledge/assets/${version}/learning.mjs"></script></body></html>\n`);
  }
  return outputs;
}
