// Single source of the site-wide header. Hand-written pages are synced by
// tools/sync-site-header.mjs; generators import these functions directly.
export const SITE_HEADER_CSS = '/assets/css/site-header.css?v=1';
export const BEGIN = '<!-- site-header:begin -->';
export const END = '<!-- site-header:end -->';

export const SECTIONS = [
  {id: 'home', label: '首页', href: '/'},
  {id: 'search', label: '拍题学', href: '/lab/search/'},
  {id: 'junior', label: '初中题库', href: '/nav/'},
  {id: 'topics', label: '高中专题', href: '/topics/'},
  {id: 'knowledge', label: '知识图谱', href: '/knowledge/'},
];

export const TOPICS_TABS = [
  {id: 'practice', label: '专题练习', href: '/topics/'},
  {id: 'library', label: '解析题库', href: '/senior-high/'},
];

export const KNOWLEDGE_TABS = [
  {id: 'graph', label: '知识图谱', href: '/knowledge/'},
  {id: '3d', label: '3D 知识图谱', href: '/knowledge/3d/'},
  {id: 'nodes', label: '全部节点', href: '/knowledge/nodes/'},
];

const esc = s => String(s).replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'})[c]);

// `exact` marks the section root itself (aria-current="page"); deeper pages get "true".
export function siteHeader({section = null, exact = false} = {}) {
  const links = SECTIONS.map(s => {
    const current = s.id === section ? ` aria-current="${exact ? 'page' : 'true'}"` : '';
    return `<a href="${s.href}"${current}>${s.label}</a>`;
  }).join('');
  return `<header class="site-header"><div class="site-header-inner">`
    + `<a class="site-brand" href="/" aria-label="数学说首页"><span class="site-brand-mark" aria-hidden="true">数</span><span class="site-brand-name">数学说</span></a>`
    + `<nav class="site-nav" aria-label="站内导航">${links}</nav>`
    + `<div class="site-header-account" data-site-auth></div>`
    + `</div></header>`;
}

// One second row per page: section tabs or breadcrumbs, plus optional page tools.
export function siteSubbar({tabs = null, current = null, tabsLabel = '栏目', crumbs = null, tools = '', width = null} = {}) {
  let body = '';
  if (tabs) {
    body = `<nav class="site-tabs" aria-label="${esc(tabsLabel)}">${tabs.map(t =>
      `<a href="${t.href}"${t.id === current ? ' aria-current="page"' : ''}>${esc(t.label)}</a>`).join('')}</nav>`;
  } else if (crumbs) {
    body = `<nav class="site-crumbs" aria-label="当前位置"><ol>${crumbs.map((c, i) =>
      i === crumbs.length - 1 || !c.href
        ? `<li><span${i === crumbs.length - 1 ? ' aria-current="page"' : ''}>${esc(c.label)}</span></li>`
        : `<li><a href="${c.href}">${esc(c.label)}</a></li>`).join('')}</ol></nav>`;
  }
  const style = width ? ` style="--site-subbar-width:${width}"` : '';
  return `<div class="site-subbar"${style}><div class="site-subbar-inner">${body}${tools ? `<div class="site-subbar-tools">${tools}</div>` : ''}</div></div>`;
}

export function siteChrome({section, exact, subbar} = {}) {
  return siteHeader({section, exact}) + (subbar ? siteSubbar(subbar) : '');
}
