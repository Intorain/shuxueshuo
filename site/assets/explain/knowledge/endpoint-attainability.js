/* Whether a boundary value of the parameter is kept: four side-by-side pictures per question type. Purely local. */
import {escapeHtml as escape, problemNote} from '../shared/html.js?v=1';

// Each picture is the boundary moment: the deciding value of f(x) is exactly 0.
// "reach": that value is taken at a point of the range (solid dot); "miss": only approached at an open end (hollow dot).
const SCENES = {
  forall: {
    reach: {curve: 'M30 12Q80 88 130 12', touch: [80, 50], ends: [[30, 12], [130, 12]], open: false},
    miss: {curve: 'M30 50Q80 50 130 12', touch: [30, 50], ends: [[130, 12]], open: true},
  },
  exists: {
    reach: {curve: 'M30 88Q80 12 130 88', touch: [80, 50], ends: [[30, 88], [130, 88]], open: false},
    miss: {curve: 'M30 88Q80 50 130 50', touch: [130, 50], ends: [[30, 88]], open: true},
  },
};
const VERDICTS = {
  forall: {
    gt: {reach: [false, '最低点正好等于 $0$，不满足 $>0$'], miss: [true, '每一点都大于 $0$，只是在端点附近无限接近 $0$']},
    ge: {reach: [true, '最低点等于 $0$，$\\ge0$ 允许取等'], miss: [true, '每一点都大于 $0$']},
  },
  exists: {
    gt: {reach: [false, '最高点也只等于 $0$，没有一点大于 $0$'], miss: [false, '每一点都小于 $0$']},
    ge: {reach: [true, '最高点等于 $0$，这一点满足 $\\ge0$'], miss: [false, '每一点都小于 $0$，$0$ 碰不到']},
  },
};
const MODES = {
  forall: {tag: '恒成立', question: '每一点都满足', rule: '恒成立：只有“不带等号、又取得到”时排除。', deciding: '最低点（或取值范围的下端）'},
  exists: {tag: '存在', question: '至少一点满足', rule: '存在：只有“带等号、又取得到”时才保留。', deciding: '最高点（或取值范围的上端）'},
};
const RELATIONS = {gt: '$f(x)>0$', ge: '$f(x)\\ge0$'};

function picture(mode, reach) {
  const scene = SCENES[mode][reach];
  const dot = ([x, y], r, cls) => `<circle cx="${x}" cy="${y}" r="${r}" class="${cls}"/>`;
  // For-all curves sit above the axis, exists curves below it; crop to the half that is used.
  return `<svg class="ea-graph" viewBox="0 ${mode === 'forall' ? 4 : 40} 160 56" aria-hidden="true">
    <path d="M6 50H154" class="ea-axis"/><text x="156" y="46" text-anchor="end" class="ea-axis-label">y=0</text>
    <path d="${scene.curve}" class="ea-curve"/>
    ${scene.ends.map(end => dot(end, 3, scene.open ? 'ea-end open' : 'ea-end')).join('')}
    ${dot(scene.touch, 5.5, reach === 'reach' ? 'ea-touch' : 'ea-touch open')}
  </svg>`;
}

function cell(mode, relation, reach) {
  const [kept, why] = VERDICTS[mode][relation][reach];
  return `<figure class="ea-cell ${kept ? 'kept' : 'dropped'}">
    <figcaption><span data-math-text>${RELATIONS[relation]}</span><b>${kept ? '✓ 保留' : '✗ 排除'}</b></figcaption>
    ${picture(mode, reach)}
    <p data-math-text>${why}</p>
  </figure>`;
}

function panel(mode) {
  const {rule, deciding} = MODES[mode];
  return `<div class="ea-panel" data-ea-panel="${mode}">
    <p class="ea-lead">边界时，${deciding}正好等于 <span data-math-text>$0$</span>。</p>
    <div class="ea-grid">
      <span class="ea-col">取得到<small>实心点</small></span><span class="ea-col">取不到<small>空心点，开区间端点</small></span>
      ${cell(mode, 'gt', 'reach')}${cell(mode, 'gt', 'miss')}${cell(mode, 'ge', 'reach')}${cell(mode, 'ge', 'miss')}
    </div>
    <p class="ea-rule">${rule}</p>
  </div>`;
}

export default {
  stylesheet: new URL('endpoint-attainability.css?v=1', import.meta.url).href,

  render({tip}) {
    return `<p class="ea-core">解出参数范围后，边界那一刻，起决定作用的值（最低点、最高点，或取值范围的端点）正好等于临界值。这个边界保不保留，看两件事：原题允不允许取等，这个值能不能取到。</p>
    ${tip?.note ? `<p class="ea-problem"><span class="ea-badge">本题</span><span data-math-text>${problemNote(tip.note)}</span></p>` : ''}
    <div class="ea-explorer">
      <div class="ea-modes" role="group" aria-label="问法">
        ${Object.entries(MODES).map(([mode, {tag, question}]) => `<button type="button" data-ea-mode="${mode}" aria-pressed="false"><span>${tag}</span><small>${question}</small></button>`).join('')}
      </div>
      ${panel('forall')}${panel('exists')}
    </div>
    <p class="ea-motto">拿不准时，把边界值代回原不等式。</p>
    <div class="ea-notes">
      <section class="ea-note">
        <h3>不能只看原题带不带等号</h3>
        <p data-math-text>$x\\in(1,3)$ 时 $(x-1)^2>0$ 恒成立：不带等号，等于 $0$ 的 $x=1$ 不在范围里，边界照样保留。</p>
        <p data-math-text>存在 $x\\in(0,1)$ 使 $x+1\\ge2$：带等号，但要 $x\\ge1$，范围里没有这样的点，边界要排除。</p>
        <p>取不到时怎样比较上端、下端，见 <button type="button" class="ea-link" data-explain-open="extremum-transfer"></button>。</p>
      </section>
      <section class="ea-note">
        <h3>退化情形留下的边界</h3>
        <p data-math-text>二次项系数含参数时，边界可能正是系数为 $0$ 的值。这时已经不是二次式，判别式的条件管不到它，要回到原不等式检验。</p>
        <p data-math-text>例如 $mx^2-mx-1&lt;0$ 恒成立，$m\\ne0$ 时解得 $-4&lt;m&lt;0$：$m=0$ 时为 $-1&lt;0$，成立，保留；$m=-4$ 时为 $-(2x-1)^2&lt;0$，$x=\\frac12$ 时等于 $0$，排除。</p>
      </section>
    </div>`;
  },

  mount(root, {tip}) {
    const show = mode => {
      for (const button of root.querySelectorAll('[data-ea-mode]')) button.setAttribute('aria-pressed', String(button.dataset.eaMode === mode));
      for (const element of root.querySelectorAll('[data-ea-panel]')) element.hidden = element.dataset.eaPanel !== mode;
    };
    for (const button of root.querySelectorAll('[data-ea-mode]')) button.addEventListener('click', () => show(button.dataset.eaMode));
    show(tip?.case?.startsWith('exists') ? 'exists' : 'forall');
  },
};
