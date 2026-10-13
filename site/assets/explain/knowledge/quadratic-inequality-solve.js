/* Reading the solution set of a quadratic inequality off the parabola, plus the Δ = 0 and Δ < 0 cases. Purely local. */
import {escapeHtml as escape, problemNote} from '../shared/html.js?v=1';

// The picture uses 0.45(x − 1)(x − 4): roots x₁ = 1 and x₂ = 4, opening up.
const ROOTS = [1, 4];
const BOUNDS = [-1, 6, -1.6, 4.8];
const plot = {left: 24, right: 336, top: 10, bottom: 150};
const sx = x => plot.left + (x - BOUNDS[0]) / (BOUNDS[1] - BOUNDS[0]) * (plot.right - plot.left);
const sy = y => plot.bottom - (y - BOUNDS[2]) / (BOUNDS[3] - BOUNDS[2]) * (plot.bottom - plot.top);
const f = x => 0.45 * (x - ROOTS[0]) * (x - ROOTS[1]);
const LINE_Y = 188;

const TARGETS = {
  gt: {label: '$&gt;0$', parts: ['left', 'right'], closed: false, answer: '$x&lt;x_1$ 或 $x&gt;x_2$', tip: '图像在 $x$ 轴上方：两根之外。'},
  ge: {label: '$\\ge 0$', parts: ['left', 'right'], closed: true, answer: '$x\\le x_1$ 或 $x\\ge x_2$', tip: '再加上图像碰到 $x$ 轴的两个根。'},
  lt: {label: '$&lt;0$', parts: ['middle'], closed: false, answer: '$x_1&lt;x&lt;x_2$', tip: '图像在 $x$ 轴下方：两根之间。'},
  le: {label: '$\\le 0$', parts: ['middle'], closed: true, answer: '$x_1\\le x\\le x_2$', tip: '再加上两个根。'},
};
const PARTS = {left: [BOUNDS[0], ROOTS[0]], middle: ROOTS, right: [ROOTS[1], BOUNDS[1]]};

function path(from, to) {
  return Array.from({length: 61}, (_, i) => from + (to - from) * i / 60)
    .map((x, i) => `${i ? 'L' : 'M'}${sx(x).toFixed(1)} ${sy(f(x)).toFixed(1)}`).join(' ');
}

function arrow(x, side) {
  return `<path d="M${x} ${LINE_Y}L${x - side * 8} ${LINE_Y - 5}V${LINE_Y + 5}Z" class="qs-ray-end"/>`;
}

// Every inequality sign is drawn up front and toggled with `hidden`, so math only needs rendering once.
function layer(key) {
  const {parts, closed} = TARGETS[key];
  const curves = parts.map(part => `<path d="${path(...PARTS[part])}" class="qs-curve-on"/>`).join('');
  const rays = parts.map(part => {
    const [from, to] = PARTS[part].map(sx);
    const tip = part === 'left' ? arrow(from, -1) : part === 'right' ? arrow(to, 1) : '';
    return `<path d="M${from} ${LINE_Y}H${to}" class="qs-ray"/>${tip}`;
  }).join('');
  const dots = ROOTS.map(x => `<circle cx="${sx(x)}" cy="${sy(0)}" r="4.6" class="qs-root${closed ? '' : ' open'}"/><circle cx="${sx(x)}" cy="${LINE_Y}" r="5" class="qs-dot${closed ? '' : ' open'}"/>`).join('');
  return `<g data-qs-layer="${key}"${key === 'gt' ? '' : ' hidden'}>${curves}${rays}${dots}</g>`;
}

function figure() {
  const labels = [[ROOTS[0], 'x₁'], [ROOTS[1], 'x₂']];
  return `<svg class="qs-graph" viewBox="0 0 360 214" role="img" aria-labelledby="qs-graph-title">
    <title id="qs-graph-title">开口向上、和 x 轴交于 x₁、x₂ 两点的抛物线，下方是解集数轴</title>
    <path d="M${plot.left} ${sy(0)}H${plot.right}" class="qs-axis"/>
    <path d="M${plot.right - 8} ${sy(0) - 4}L${plot.right} ${sy(0)}L${plot.right - 8} ${sy(0) + 4}" class="qs-axis"/>
    <text x="${plot.right + 6}" y="${sy(0) + 4}" class="qs-axis-label">x</text>
    <path d="${path(BOUNDS[0], BOUNDS[1])}" class="qs-curve"/>
    <text x="${sx(5.6)}" y="${sy(f(5.6)) + 2}" text-anchor="end" class="qs-curve-label">y = ax² + bx + c（a &gt; 0）</text>
    ${labels.map(([x, text]) => `<path d="M${sx(x)} ${sy(0)}V${LINE_Y}" class="qs-guide"/><text x="${sx(x) + (x === ROOTS[0] ? -8 : 8)}" y="${sy(0) + 18}" text-anchor="${x === ROOTS[0] ? 'end' : 'start'}" class="qs-root-label">${text}</text>`).join('')}
    <path d="M${plot.left} ${LINE_Y}H${plot.right}" class="qs-line"/>
    <text x="${plot.left}" y="${LINE_Y + 22}" class="qs-line-label">解集</text>
    ${Object.keys(TARGETS).map(layer).join('')}
  </svg>`;
}

const explorer = () => {
  const keys = Object.keys(TARGETS);
  return `<div class="qs-explorer">
      <p class="qs-ask" data-math-text>$ax^2+bx+c$（$a&gt;0$，$\\Delta&gt;0$）要</p>
      <div class="qs-targets" role="group" aria-label="不等号">
        ${keys.map(key => `<button type="button" data-qs-target="${key}" aria-pressed="${key === 'gt'}" data-math-text>${TARGETS[key].label}</button>`).join('')}
      </div>
      ${figure()}
      ${keys.map(key => `<p class="qs-answer" data-qs-answer="${key}"${key === 'gt' ? '' : ' hidden'}><span class="qs-tag">解集</span><span data-math-text>${TARGETS[key].answer}</span><small data-math-text>${TARGETS[key].tip}</small></p>`).join('')}
      <p class="qs-motto">二次项系数为正时：大于取两边，小于取中间。</p>
    </div>`;
};

const SPECIAL = [
  {title: '$\\Delta=0$', example: '例：$(x-1)^2$', cells: ['$x\\ne 1$', '$\\mathbb R$', '$\\varnothing$', '$x=1$']},
  {title: '$\\Delta&lt;0$', example: '例：$x^2+x+1$', cells: ['$\\mathbb R$', '$\\mathbb R$', '$\\varnothing$', '$\\varnothing$']},
];

export default {
  stylesheet: new URL('quadratic-inequality-solve.css?v=1', import.meta.url).href,

  figure: explorer,

  render({tip}) {
    const keys = Object.keys(TARGETS);
    return `<p class="qs-core" data-math-text>先把二次项系数化成正数，求出两根 $x_1&lt;x_2$，再看图像：大于零取两根之外，小于零取两根之间；带等号就把根也算进去。</p>
    ${tip?.note ? `<p class="qs-problem"><span class="qs-badge">本题</span><span data-math-text>${problemNote(tip.note)}</span></p>` : ''}
    ${explorer()}
    <table class="qs-table">
      <caption data-math-text>没有两个不同的根时（$a&gt;0$）</caption>
      <thead><tr><th scope="col"><span class="qs-hidden">情况</span></th>${keys.map(key => `<th scope="col" data-math-text>${TARGETS[key].label}</th>`).join('')}</tr></thead>
      <tbody>
        ${SPECIAL.map(row => `<tr><th scope="row"><span data-math-text>${row.title}</span><small data-math-text>${row.example}</small></th>${row.cells.map(cell => `<td data-math-text>${cell}</td>`).join('')}</tr>`).join('')}
      </tbody>
    </table>
    <div class="qs-notes">
      <section class="qs-note">
        <h3>开口向下：先乘 −1</h3>
        <p data-math-text>两边同乘 $-1$，不等号要反向。例如 $-x^2+2x+3&gt;0$ 化成 $x^2-2x-3&lt;0$，解得 $-1&lt;x&lt;3$。</p>
      </section>
      <section class="qs-note">
        <h3>没有两个根：直接看整条图像</h3>
        <p data-math-text>开口向上且 $\\Delta&lt;0$ 时图像全在 $x$ 轴上方，所以 $&gt;0$ 的解集是 $\\mathbb R$，$&lt;0$ 无解。$\\Delta=0$ 时只在顶点碰到 $x$ 轴，别把这个点漏掉或多算。</p>
      </section>
      <section class="qs-note">
        <h3>解出参数后要和前提取交集</h3>
        <p data-math-text>恒成立题里常要解关于参数的不等式，例如 $a^2-3a-4\\ge 0$，解得 $a\\le -1$ 或 $a\\ge 4$；如果前提是 $a&gt;0$，答案是 $a\\ge 4$。</p>
        <p>多个情况怎么合并，见 <button type="button" class="qs-link" data-explain-open="case-merge"></button>。</p>
      </section>
    </div>`;
  },

  mount(root) {
    const pick = key => {
      for (const button of root.querySelectorAll('[data-qs-target]')) button.setAttribute('aria-pressed', String(button.dataset.qsTarget === key));
      for (const node of root.querySelectorAll('[data-qs-layer]')) node.toggleAttribute('hidden', node.dataset.qsLayer !== key);
      for (const node of root.querySelectorAll('[data-qs-answer]')) node.hidden = node.dataset.qsAnswer !== key;
    };
    for (const button of root.querySelectorAll('[data-qs-target]')) button.addEventListener('click', () => pick(button.dataset.qsTarget));
  },
};
