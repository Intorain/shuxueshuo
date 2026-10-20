/** Safe mathematical card DOM shared by completed/read steps and debug views.
 * This module never controls progress, transport, or interaction availability.
 */

const expressionText = value => typeof value === 'string' ? value : value?.latex || '';
const text = (document, tag, value, className) => {
  const node = document.createElement(tag);
  node.textContent = value;
  if (className) node.className = className;
  return node;
};

export function routeAnswerSummary(answer = {}) {
  if (answer.kind === 'find_range' && answer.status === 'set') {
    const formula = expressionText(answer.set);
    return formula ? {label: '参数范围：', formula} : null;
  }
  if (!['find_minimum', 'find_maximum'].includes(answer.kind)) return null;
  const minimum = answer.kind === 'find_minimum', name = minimum ? '最小值' : '最大值';
  if (answer.status === 'attained' || answer.status === 'not_attained') {
    const value = answer.status === 'attained' ? answer.value : answer.bound;
    const formula = expressionText(value);
    if (!formula || ['Infinity', 'NegativeInfinity'].includes(value?.exact?.$math)) return null;
    return {label: answer.status === 'attained' ? `${name}：`
      : `${name}不存在；${minimum ? '下确界' : '上确界'}为：`, formula};
  }
  if (answer.status === (minimum ? 'unbounded_below' : 'unbounded_above')) {
    return {label: `${name}不存在：可行集没有${minimum ? '下' : '上'}界。`, formula: ''};
  }
  if (answer.status === 'empty_feasible_set') return {label: `没有满足题设的参数，${name}不存在。`, formula: ''};
  return null;
}

/** Return a detached card; renderer failure cannot publish a partially built card. */
export function createMathCard(document, step, options = {}) {
  const node = document.createElement('article');
  node.className = 'stage-three-math-step';
  Object.assign(node.dataset, {stepId: step.step_id, mathStepSha256: step.math_step_sha256,
    targetRef: step.target_ref, routeId: step.route_id, ordinal: String(step.ordinal)});
  node.append(text(document, 'h3', step.title));
  for (const field of ['before', 'after']) for (const value of step[field] || []) {
    const formula = text(document, 'p', expressionText(value), `stage-three-${field}`);
    formula.dataset.mathFormula = 'true'; node.append(formula);
  }
  const explanation = text(document, 'p', step.explanation || '', 'stage-three-explanation');
  explanation.dataset.mathText = 'true'; node.append(explanation);
  const qa = document.createElement('aside');
  qa.className = 'stage-three-qa'; qa.hidden = true; node.append(qa);
  options.renderMath?.(node);
  const card = {node, qa, step: structuredClone(step)};
  if (options.qa) attachMathQA(card, options.qa, options);
  return card;
}

/** Question context deliberately excludes conclusions, explanation and QA. */
export function createMathContext(document, steps, options = {}) {
  const node = document.createElement('div');
  node.className = 'stage-three-context';
  for (const step of steps) for (const value of step.before || []) {
    const formula = text(document, 'p', expressionText(value), 'stage-three-before');
    formula.dataset.mathFormula = 'true'; node.append(formula);
  }
  options.renderMath?.(node);
  return node;
}

/** Only replace the QA region. The caller decides whether the card is completed. */
export function attachMathQA(card, chunk, options = {}) {
  if (['run_id', 'lesson_version', 'target_ref', 'route_id', 'step_id', 'math_step_sha256']
    .some(key => chunk[key] !== card.step[key])) throw new Error('stream.qa_hash_mismatch');
  const document = card.node.ownerDocument, staging = document.createElement('aside');
  const labels = {questions: '想一想', possible_questions: '你可能会问', hints: '提示', common_errors: '常见错误', feedback: '反馈'};
  for (const [key, value] of Object.entries(chunk.qa || {})) {
    const values = Array.isArray(value) ? value : [value];
    const lines = values.map(item => typeof item === 'string' ? item : item?.text || item?.question || item?.message || '').filter(Boolean);
    if (!lines.length) continue;
    staging.append(text(document, 'strong', labels[key] || '补充说明'));
    for (const line of lines) {
      const node = text(document, 'p', line);
      node.dataset.mathText = 'true'; staging.append(node);
    }
  }
  options.renderMath?.(staging);
  card.qa.replaceChildren(...staging.childNodes);
  card.qa.hidden = false;
}

/** Detached route answer; unknown/unavailable answers never claim completion. */
export function createRouteCompletion(document, payload, options = {}) {
  const answer = payload.answer || {}, summary = routeAnswerSummary(answer);
  const complete = Boolean(summary) && payload.available !== false;
  const node = text(document, 'p', '', 'stage-three-completion');
  node.hidden = !complete;
  const answerStatus = summary ? answer.status : 'unknown';
  node.dataset.answerStatus = answerStatus;
  node.append(text(document, 'span', summary?.label || '目标答案尚未确定。'));
  if (summary?.formula) {
    const formula = text(document, 'span', summary.formula, 'stage-three-answer');
    formula.dataset.mathFormula = 'true'; node.append(formula);
  }
  options.renderMath?.(node);
  return {node, complete, answerStatus, statusText: complete ? '本路线已完成数学验证。'
    : '目标答案尚未确定，暂不发布完成结论。'};
}
