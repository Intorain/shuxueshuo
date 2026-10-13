// Personal state is available only in the explicit, version-matched learning mode.
export const ABILITY_KINDS = ['knowledge', 'skill', 'method', 'problem_type'];
export const STATUS_LABELS = {unassessed: '未评估', mastered: '已掌握', needs_review: '待巩固'};

// API events retain their real source: diagram displays are hint events, not a
// separate reference type. Keep the display projection independent of the DOM.
export function practiceEventView(event, contexts = new Map()) {
  const value = event.payload || {};
  let title = {context: '题目上下文', answer: '学生提交', grade: '判定',
    message: value.role === 'student' ? '学生对话' : '导师对话', hint: '导师提示'}[event.event_type] || event.event_type;
  let text = value.text || value.question || '';
  const details = [];
  if (event.event_type === 'answer') {
    const interaction = contexts.get(event.related_event_id)?.interaction;
    text = interaction?.type === 'choice'
      ? interaction.options.find(option => option.value === value.value)?.label || value.value
      : (value.terms || []).map(term => interaction?.term_labels?.[term] || term).join('，');
    if (value.fixed) details.push(({sum: '定和', product: '定积'})[value.fixed] || value.fixed);
  } else if (event.event_type === 'grade') {
    title = value.source === 'rule' ? '规则判定' : value.source === 'llm' ? '导师判定' : '判定';
    text = {passed: '通过', wrong: '错误', incomplete: '信息不足'}[value.result] || value.result;
  } else if (event.event_type === 'hint' && value.source === 'node_explainer') {
    title = value.resource_id ? '查看图解' : '查看学习说明';
    details.push(`关联：${value.ref || value.node_id}`);
    if (value.candidate) details.push('候选提示，不表示已经采用该方法或技能。');
  }
  if (event.event_type === 'hint' || value.role === 'tutor') {
    details.push(event.displayed_at ? '已确认展示' : '尚未确认展示');
  }
  return {title, text, details};
}

let mathReady;
export async function renderLearningMath(root) {
  mathReady ||= (async () => {
    if (!window.katex) await import('/assets/practice/vendor/katex-0.18.9/katex.min.js');
    if (!window.renderMathInElement) await import('/assets/practice/vendor/katex-0.18.9/auto-render.min.js');
    if (!window.PracticeMath) await import('/assets/practice/math-text.js?v=1');
  })().catch(error => { mathReady = null; throw error; });
  await mathReady;
  root.querySelectorAll('[data-math-text]').forEach(el => window.PracticeMath.render(el, el.textContent));
}

export function learningHref(path, base = 'https://knowledge.invalid') {
  const url = new URL(path, base);
  url.searchParams.set('learning', '1');
  return url.pathname + url.search + url.hash;
}

export function preserveLearningLink(anchor, base) {
  if (!anchor || anchor.hasAttribute('data-learning-exit')) return;
  const href = anchor.getAttribute('href');
  if (!href) return;
  const current = new URL(base);
  const url = new URL(href, current);
  if (url.origin !== current.origin) return;
  if (url.pathname.startsWith('/knowledge-next/') || url.searchParams.get('knowledge') === 'next') {
    // SVG chapter links expose a read-only SVGAnimatedString as .href.
    anchor.setAttribute('href', learningHref(url.href));
  }
}

export function learningDirectoryHref(config, base) {
  const url = new URL(learningHref(config.redirectHref, base), base);
  if (config.kind === 'textbook') url.searchParams.set('progress', config.id);
  return url.pathname + url.search + url.hash;
}

export function progressScope(search, graph) {
  const params = new URLSearchParams(search);
  return graph ? params.get('scope') || graph.defaultScope : params.get('progress');
}

export async function learningVersion(read) {
  const [page, published] = await Promise.all([
    read('/knowledge-next/teaching/version.json'), read('/api/learning/content')
  ]);
  if (!page.content_version || page.content_version !== published.content_version) {
    throw Error('页面与学习服务的内容版本不同，请刷新页面后重试。');
  }
  return page.content_version;
}

export async function learningApi(path, {body, user, signal} = {}) {
  const response = await fetch(path.startsWith('/api/') ? path : `/api/learning${path}`, {
    method: body === undefined ? 'GET' : 'POST', credentials: 'same-origin', cache: 'no-store',
    headers: {'Content-Type': 'application/json', ...(user ? {'X-Learning-User': user} : {})},
    body: body === undefined ? undefined : JSON.stringify(body), signal: signal || AbortSignal.timeout(15000)
  });
  let data;
  try { data = await response.json(); }
  catch { throw Object.assign(Error('服务响应暂不可用，请重试。'), {retryable: response.ok || response.status >= 500}); }
  if (!response.ok) {
    const detail = data.detail;
    throw Object.assign(Error(typeof detail === 'string' ? detail : detail?.message || '学习记录暂不可用，请重试。'), {
      status: response.status, code: detail?.code, retryable: [401, 429].includes(response.status) || response.status >= 500
    });
  }
  return data;
}
