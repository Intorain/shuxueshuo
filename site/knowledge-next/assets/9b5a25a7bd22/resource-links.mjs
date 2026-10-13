import {nodeHref} from './model.mjs';

export const escapeHtml = text => String(text).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

// Only the reviewed, trusted module HTML is passed here. Unknown links fail publication.
export function rewriteResourceLinks(html, links, labels) {
  return html.replace(/<button\b([^>]*\bdata-explain-open="([^"]+)"[^>]*)>([\s\S]*?)<\/button>/g, (_all, attrs, legacy, content) => {
    const ref = links[legacy];
    if (!ref) throw new Error(`未映射的图解链接: ${legacy}`);
    const css = attrs.match(/\bclass="([^"]*)"/)?.[1] || '';
    return `<a class="${escapeHtml(css)}" data-node-link href="${nodeHref(ref)}">${content.trim() || escapeHtml(labels[ref.split('#')[0]])}</a>`;
  });
}
