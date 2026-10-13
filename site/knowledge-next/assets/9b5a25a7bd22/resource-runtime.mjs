const loadingStyles = new Map();
export async function stylesheet(url) {
  if (!url) return;
  if (loadingStyles.has(url)) return loadingStyles.get(url);
  const existing = [...document.querySelectorAll('link[rel="stylesheet"]')].find(
    (l) => l.getAttribute('href') === url
  );
  if (existing?.sheet) return;
  // A pre-existing link may already have failed before our listeners were attached.
  // Take ownership of a fresh request; calls owned by us are coalesced above.
  existing?.remove();
  const pending = new Promise((resolve, reject) => {
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = url;
    link.addEventListener('load', resolve, { once: true });
    link.addEventListener(
      'error',
      () => {
        link.remove();
        reject(Error('样式加载失败'));
      },
      { once: true }
    );
    document.head.append(link);
  });
  loadingStyles.set(url, pending);
  try {
    await pending;
  } finally {
    loadingStyles.delete(url);
  }
}

export async function mountResource(root, resource, { node = null, tip = null, retry = false } = {}) {
  const mod = (await import(`${resource.module}?v=${resource.version}${retry ? `&retry=${Date.now()}` : ''}`))
    .default;
  await stylesheet(resource.stylesheet ? `${resource.stylesheet}?v=${resource.version}` : null);
  return mod.mount?.(root, { node, tip, topic: null });
}
