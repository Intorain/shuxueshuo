/* Sign of a and of Δ decide where the whole parabola lies: six pictures, pick a requirement to see which qualify. Purely local. */
import {escapeHtml as escape, problemNote} from '../shared/html.js?v=1';

// Each picture runs from x = 15 to 105 with its vertex at x = 60; the axis is y = 40.
// Bezier control y = 2·vertex − end, so the curve passes through the vertex.
const SHAPES = {
  up: {end: 6, vertex: {neg: 28, zero: 40, pos: 58}},
  down: {end: 74, vertex: {neg: 52, zero: 40, pos: 22}},
};
const COLUMNS = [
  ['neg', '$\\Delta&lt;0$', '不相交'],
  ['zero', '$\\Delta=0$', '相切'],
  ['pos', '$\\Delta&gt;0$', '穿过'],
];
const ROWS = [
  ['up', '$a&gt;0$', '开口向上'],
  ['down', '$a&lt;0$', '开口向下'],
];
const SIGN = {
  up: {neg: '恒 $&gt;0$', zero: '恒 $\\ge0$，顶点处 $=0$', pos: '有正有负'},
  down: {neg: '恒 $&lt;0$', zero: '恒 $\\le0$，顶点处 $=0$', pos: '有正有负'},
};
// Which pictures meet each requirement, and the condition they add up to.
const TARGETS = {
  gt: {label: '恒 $&gt;0$', cells: ['up-neg'], condition: '$a&gt;0$ 且 $\\Delta&lt;0$：开口向上，与横轴不相交。'},
  ge: {label: '恒 $\\ge0$', cells: ['up-neg', 'up-zero'], condition: '$a&gt;0$ 且 $\\Delta\\le0$：开口向上，与横轴不相交或相切。'},
  lt: {label: '恒 $&lt;0$', cells: ['down-neg'], condition: '$a&lt;0$ 且 $\\Delta&lt;0$：开口向下，与横轴不相交。'},
  le: {label: '恒 $\\le0$', cells: ['down-neg', 'down-zero'], condition: '$a&lt;0$ 且 $\\Delta\\le0$：开口向下，与横轴不相交或相切。'},
};

function picture(row, column) {
  const {end, vertex} = SHAPES[row];
  const v = vertex[column];
  const marks = column === 'zero' ? '<circle cx="60" cy="40" r="3.6" class="qp-mark"/>'
    : column === 'pos' ? crossings(end, v) : '';
  return `<svg class="qp-graph" viewBox="0 0 120 80" aria-hidden="true">
    <path d="M4 40H116" class="qp-axis"/>
    <path d="M15 ${end}Q60 ${2 * v - end} 105 ${end}" class="qp-curve"/>
    ${marks}
  </svg>`;
}

// Where the curve meets the axis when Δ > 0: B(t) = end·(1−t)² + 2c·t(1−t) + end·t², c = 2v − end.
function crossings(end, v) {
  const c = 2 * v - end;
  const [p, q, r] = [end - 2 * c + end, 2 * (c - end), end - 40];
  const d = Math.sqrt(q * q - 4 * p * r);
  return [(-q - d) / (2 * p), (-q + d) / (2 * p)]
    .map(t => `<circle cx="${(15 + 90 * t).toFixed(1)}" cy="40" r="3.2" class="qp-mark"/>`).join('');
}

function cell(row, column) {
  return `<figure class="qp-cell" data-qp-cell="${row}-${column}">
    ${picture(row, column)}
    <figcaption data-math-text>${SIGN[row][column]}</figcaption>
  </figure>`;
}

const explorer = () => `<div class="qp-explorer">
      <p class="qp-ask">选一个要求，看哪些图像满足：</p>
      <div class="qp-targets" role="group" aria-label="对任意实数 x 的要求">
        ${Object.entries(TARGETS).map(([key, {label}]) => `<button type="button" data-qp-target="${key}" aria-pressed="false"><span data-math-text>${label}</span></button>`).join('')}
      </div>
      <div class="qp-grid">
        <span></span>${COLUMNS.map(([, formula, word]) => `<span class="qp-col"><span data-math-text>${formula}</span><small>${word}</small></span>`).join('')}
        ${ROWS.map(([row, formula, word]) => `<span class="qp-row"><span data-math-text>${formula}</span><small>${word}</small></span>${COLUMNS.map(([column]) => cell(row, column)).join('')}`).join('')}
      </div>
      ${Object.entries(TARGETS).map(([key, {condition}]) => `<p class="qp-condition" data-qp-condition="${key}" hidden><span class="qp-tag">条件</span><span data-math-text>${condition}</span></p>`).join('')}
      <p class="qp-small" data-math-text>$\\Delta&gt;0$ 的图像穿过横轴，有正有负，四种要求都不满足。</p>
    </div>`;

export default {
  stylesheet: new URL('quadratic-function-properties.css?v=1', import.meta.url).href,

  figure: explorer,

  render({tip}) {
    return `<p class="qp-core" data-math-text>二次函数 $y=ax^2+bx+c\\ (a\\ne0)$：$a$ 的符号定开口，$\\Delta=b^2-4ac$ 定与横轴有几个公共点。两者合起来，就知道整条图像在横轴的哪一边。</p>
    ${tip?.note ? `<p class="qp-problem"><span class="qp-badge">本题</span><span data-math-text>${problemNote(tip.note)}</span></p>` : ''}
    ${explorer()}
    <div class="qp-notes">
      <section class="qp-note">
        <h3>开口：只看二次项系数的符号</h3>
        <p data-math-text>系数含参数时，先判断它的符号：$m^2+1&gt;0$，开口一定向上；$k$、$a^2-1$ 的符号随参数变，还可能等于 $0$。</p>
      </section>
      <section class="qp-note">
        <h3>系数为 0：不再是二次函数</h3>
        <p data-math-text>$kx^2+2x-1$ 在 $k=0$ 时是 $2x-1$，一次函数，不会恒小于 $0$；$kx^2+2kx-2$ 在 $k=0$ 时只剩 $-2$。都要代回原式重新判断，不能套开口和 $\\Delta$。</p>
      </section>
      <section class="qp-note">
        <h3>顶点、对称轴与单调性</h3>
        <p data-math-text>配方成 $a(x-h)^2+k$：对称轴 $x=h$，顶点 $(h,k)$。$a&gt;0$ 时 $k$ 是最小值，对称轴左边递减、右边递增；$a&lt;0$ 反过来。</p>
        <p>对称轴不在某个区间里时，函数在这个区间上单调，最值在端点取到，见 <button type="button" class="qp-link" data-explain-open="quadratic-interval-extremum"></button>。</p>
      </section>
    </div>`;
  },

  mount(root) {
    const pick = key => {
      const on = new Set(TARGETS[key].cells);
      for (const button of root.querySelectorAll('[data-qp-target]')) button.setAttribute('aria-pressed', String(button.dataset.qpTarget === key));
      for (const figure of root.querySelectorAll('[data-qp-cell]')) {
        figure.classList.toggle('is-on', on.has(figure.dataset.qpCell));
        figure.classList.toggle('is-off', !on.has(figure.dataset.qpCell));
      }
      for (const line of root.querySelectorAll('[data-qp-condition]')) line.hidden = line.dataset.qpCondition !== key;
    };
    for (const button of root.querySelectorAll('[data-qp-target]')) button.addEventListener('click', () => pick(button.dataset.qpTarget));
    pick('gt');
  },
};
