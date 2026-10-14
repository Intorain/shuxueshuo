// Explicit preview wins over every legacy mode flag. Public pages otherwise
// use the published associations; a mode flag never grants write access.
export function isPreview(search = '') {
  const params = search instanceof URLSearchParams ? search : new URLSearchParams(search);
  return params.get('preview') === '1' ||
    (params.get('knowledge') === 'next' && params.get('learning') !== '1');
}

export function modeHref(path, {preview = false} = {}, base = 'https://mode.invalid') {
  const url = new URL(path, base);
  url.searchParams.delete('knowledge');
  url.searchParams.delete('learning');
  url.searchParams.delete('preview');
  if (preview) url.searchParams.set('preview', '1');
  return url.pathname + url.search + url.hash;
}

export function preserveModeLink(anchor, base, {preview = isPreview(new URL(base).search)} = {}) {
  if (!anchor || anchor.hasAttribute('data-learning-exit')) return;
  const href = anchor.getAttribute('href');
  if (!href || href.startsWith('#')) return;
  const current = new URL(base), url = new URL(href, current);
  if (url.origin !== current.origin || !['http:', 'https:'].includes(url.protocol)) return;
  // A formal page can deliberately offer an unrecorded preview. Do not turn
  // that explicit destination back into a recording page during navigation.
  anchor.setAttribute('href', modeHref(url.href, {preview: preview || isPreview(url.search)}, current));
}

export function bindModeLinks(root, base) {
  const apply = anchor => preserveModeLink(anchor, base);
  root.querySelectorAll('a[href]').forEach(apply);
  for (const type of ['click', 'auxclick', 'contextmenu']) {
    root.addEventListener(type, event => apply(event.target.closest('a[href]')), true);
  }
}
