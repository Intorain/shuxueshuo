// Compatibility API for independent practice pages. Public identity and body
// come from the current graph; module paths are never inferred from IDs.
import {escapeHtml} from './shared/html.js?v=1';

const kinds = {knowledge: '知识点', skill: '技能', method: '方法', problem_type: '题型', judgment_rule: '判断规则'};
let dialog;
const read = async path => {
  const response = await fetch(path, {cache: 'no-cache', signal: AbortSignal.timeout(15000)});
  if (!response.ok) throw Error('学习说明暂不可用，请重试。');
  return response.json();
};

async function content(id) {
  const [catalog, migration] = await Promise.all([
    read('/knowledge/teaching/catalog.json'), read('/knowledge/teaching/migration.json'),
  ]);
  const row = migration.nodes.find(row => row.legacy === id);
  const ref = migration.legacyRefs[id] || (catalog[id] ? id : row?.targets.length === 1 ? row.targets[0] : null);
  if (!ref) {
    if (!row) throw Error('未找到对应的学习说明。');
    return {label: '原节点的新位置', kind: 'method', href: `/knowledge/${id}/`, html: `<p>请按当前使用的方法选择说明：</p><ul>${row.targets.map(target => {
      const [node, entry] = target.split('#');
      return `<li><a href="/knowledge/${node}/${entry ? '#' + entry : ''}">${escapeHtml(catalog[node].label)}${entry ? ' · ' + escapeHtml(catalog[node].entries[entry] || entry) : ''}</a></li>`;
    }).join('')}</ul>`};
  }
  const [node, entry] = ref.split('#');
  if (!catalog[node]) throw Error('未找到对应的学习说明。');
  const body = await read(`/knowledge/teaching/nodes/${node}.json`);
  return {...catalog[node], html: body.html, href: `/knowledge/${node}/${entry ? '#' + entry : ''}`};
}

export async function openExplainer(id, {tip = null, detail = true} = {}) {
  if (!dialog) {
    dialog = document.createElement('dialog');
    dialog.className = 'public-reference-dialog';
    dialog.setAttribute('aria-label', '学习说明');
    dialog.style.cssText = 'max-width:760px;width:calc(100% - 48px);max-height:85vh;border:1px solid #cbd5d2;border-radius:16px;padding:24px;';
    document.body.append(dialog);
  }
  const show = async () => {
    dialog.innerHTML = '<p>正在加载学习说明…</p>';
    if (!dialog.open) dialog.showModal();
    try {
      const node = await content(id);
      dialog.innerHTML = `<button type="button" data-close style="float:right">关闭</button><p>${kinds[node.kind] || '学习说明'}</p><h2>${escapeHtml(node.label)}</h2>${node.html}${tip?.note ? `<p data-tip-note>${escapeHtml(tip.note)}</p>` : ''}${detail ? `<p><a href="${node.href}">查看详情 →</a></p>` : ''}`;
      const note = dialog.querySelector('[data-tip-note]');
      if (note && window.PracticeMath?.render) window.PracticeMath.render(note, tip.note);
      dialog.querySelector('[data-close]').onclick = () => dialog.close();
    } catch {
      dialog.innerHTML = '<p>学习说明加载失败，仍可继续作答。</p><button data-retry>重试</button> <button data-close>关闭</button>';
      dialog.querySelector('[data-retry]').onclick = show;
      dialog.querySelector('[data-close]').onclick = () => dialog.close();
    }
  };
  await show();
  return true;
}

export async function renderExplainer(root, id) {
  root.innerHTML = (await content(id)).html;
  return null;
}
