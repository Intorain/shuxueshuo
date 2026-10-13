/* Public graph resource: opening and zeros decide the sign of ax² + bx + c. Purely local. */

const BOUNDS = [-1, 6, -3, 3];
const plot = {left: 24, right: 336, top: 10, bottom: 140};
const sx = x => plot.left + (x - BOUNDS[0]) / (BOUNDS[1] - BOUNDS[0]) * (plot.right - plot.left);
const sy = y => plot.bottom - (y - BOUNDS[2]) / (BOUNDS[3] - BOUNDS[2]) * (plot.bottom - plot.top);
const LINE_Y = 200;

const OPENINGS = {
  up: {label: '向上', formula: '$a&gt;0$', sign: 1},
  down: {label: '向下', formula: '$a&lt;0$', sign: -1},
};
// Opening-up versions; opening down multiplies by −1.
const ZEROS = {
  two: {label: '两个', roots: [1, 4], names: ['x₁', 'x₂'], f: x => 0.45 * (x - 1) * (x - 4)},
  one: {label: '一个', roots: [2.5], names: ['x₀'], f: x => 0.45 * (x - 2.5) ** 2},
  none: {label: '没有', roots: [], names: [], f: x => 0.45 * (x - 2.5) ** 2 + 0.8},
};
const SAME = '两根之外与 $a$ 同号，两根之间与 $a$ 异号。';
const ONE = '只在 $x_0$ 处为零，其余地方都与 $a$ 同号。';
const NONE = '图像整条在 $x$ 轴一侧，处处与 $a$ 同号。';
const READ = {
  'up-two': {pos: '$x&lt;x_1$ 或 $x&gt;x_2$', zero: '$x=x_1$ 或 $x=x_2$', neg: '$x_1&lt;x&lt;x_2$', rule: SAME},
  'down-two': {pos: '$x_1&lt;x&lt;x_2$', zero: '$x=x_1$ 或 $x=x_2$', neg: '$x&lt;x_1$ 或 $x&gt;x_2$', rule: SAME},
  'up-one': {pos: '$x\\ne x_0$', zero: '$x=x_0$', neg: '没有', rule: ONE},
  'down-one': {pos: '没有', zero: '$x=x_0$', neg: '$x\\ne x_0$', rule: ONE},
  'up-none': {pos: '全体实数', zero: '没有', neg: '没有', rule: NONE},
  'down-none': {pos: '没有', zero: '没有', neg: '全体实数', rule: NONE},
};
const START = 'up-two';

function path(g, from, to) {
  return Array.from({length: 41}, (_, i) => from + (to - from) * i / 40)
    .map((x, i) => `${i ? 'L' : 'M'}${sx(x).toFixed(1)} ${sy(g(x)).toFixed(1)}`).join(' ');
}

// Every combination is drawn up front and toggled with `hidden`.
function layer(open, zeros) {
  const key = `${open}-${zeros}`;
  const s = OPENINGS[open].sign;
  const {roots, names, f} = ZEROS[zeros];
  const g = x => s * f(x);
  const cuts = [BOUNDS[0], ...roots, BOUNDS[1]];
  const pieces = cuts.slice(1).map((to, i) => ({from: cuts[i], to, sign: g((cuts[i] + to) / 2) > 0 ? 'pos' : 'neg'}));
  const curves = pieces.map(p => `<path d="${path(g, p.from, p.to)}" class="sc-curve ${p.sign}"/>`).join('');
  const segments = pieces.map(p => {
    const mid = (sx(p.from) + sx(p.to)) / 2;
    return `<path d="M${sx(p.from)} ${LINE_Y}H${sx(p.to)}" class="sc-seg ${p.sign}"/><circle cx="${mid}" cy="${LINE_Y - 18}" r="10" class="sc-badge ${p.sign}"/><text x="${mid}" y="${LINE_Y - 12.5}" text-anchor="middle" class="sc-sign">${p.sign === 'pos' ? '+' : '−'}</text>`;
  }).join('');
  const labelY = s > 0 ? sy(0) + 18 : sy(0) - 8;
  const anchor = i => roots.length === 1 ? 'middle' : i ? 'start' : 'end';
  const shift = i => roots.length === 1 ? 0 : i ? 7 : -7;
  const marks = roots.map((x, i) => `<path d="M${sx(x)} ${sy(0)}V${LINE_Y}" class="sc-guide"/>
    <circle cx="${sx(x)}" cy="${sy(0)}" r="4.4" class="sc-zero"/>
    <text x="${sx(x) + shift(i)}" y="${labelY}" text-anchor="${anchor(i)}" class="sc-root-label">${names[i]}</text>
    <circle cx="${sx(x)}" cy="${LINE_Y}" r="4.8" class="sc-zero"/>
    <text x="${sx(x)}" y="${LINE_Y + 20}" text-anchor="middle" class="sc-zero-label">0</text>`).join('');
  return `<g data-sc-layer="${key}"${key === START ? '' : ' hidden'}><g clip-path="url(#sc-clip)">${curves}</g>${segments}${marks}</g>`;
}

function figure() {
  const layers = Object.keys(OPENINGS).flatMap(open => Object.keys(ZEROS).map(zeros => layer(open, zeros))).join('');
  return `<svg class="sc-graph" viewBox="0 0 360 228" role="img" aria-labelledby="sc-graph-title">
    <title id="sc-graph-title">上方是二次函数图像，下方数轴按零点分段，标出每段式子的正负</title>
    <defs><clipPath id="sc-clip"><rect x="${plot.left}" y="${plot.top}" width="${plot.right - plot.left}" height="${plot.bottom - plot.top}"/></clipPath></defs>
    <path d="M${plot.left} ${sy(0)}H${plot.right}" class="sc-axis"/>
    <path d="M${plot.right - 8} ${sy(0) - 4}L${plot.right} ${sy(0)}L${plot.right - 8} ${sy(0) + 4}" class="sc-axis"/>
    <text x="${plot.right + 6}" y="${sy(0) + 4}" class="sc-axis-label">x</text>
    <path d="M${plot.left} ${LINE_Y}H${plot.right}" class="sc-line"/>
    ${layers}
  </svg>`;
}

const read = key => {
  const r = READ[key];
  const row = (cls, tag, text) => `<p><span class="sc-tag ${cls}">${tag}</span><span data-math-text>${text}</span></p>`;
  return `<div class="sc-read" data-sc-read="${key}"${key === START ? '' : ' hidden'}>
      ${row('pos', '正', r.pos)}${row('zero', '零', r.zero)}${row('neg', '负', r.neg)}
      <p class="sc-rule" data-math-text>${r.rule}</p>
    </div>`;
};

const explorer = () => `<div class="sc-explorer">
    <div class="sc-controls">
      <div class="sc-group" role="group" aria-label="开口方向">
        <span class="sc-group-label">开口</span>
        ${Object.entries(OPENINGS).map(([key, o]) => `<button type="button" data-sc-open="${key}" aria-pressed="${key === 'up'}">${o.label} <span data-math-text>${o.formula}</span></button>`).join('')}
      </div>
      <div class="sc-group" role="group" aria-label="零点个数">
        <span class="sc-group-label">零点</span>
        ${Object.entries(ZEROS).map(([key, z]) => `<button type="button" data-sc-zeros="${key}" aria-pressed="${key === 'two'}">${z.label}</button>`).join('')}
      </div>
    </div>
    ${figure()}
    ${Object.keys(READ).map(read).join('')}
  </div>`;

export default {
  stylesheet: new URL('quadratic-sign-chart.css?v=1', import.meta.url).href,

  figure: explorer,

  render: () => explorer(),

  mount(root) {
    const state = {open: 'up', zeros: 'two'};
    const show = () => {
      const key = `${state.open}-${state.zeros}`;
      for (const button of root.querySelectorAll('[data-sc-open]')) button.setAttribute('aria-pressed', String(button.dataset.scOpen === state.open));
      for (const button of root.querySelectorAll('[data-sc-zeros]')) button.setAttribute('aria-pressed', String(button.dataset.scZeros === state.zeros));
      for (const node of root.querySelectorAll('[data-sc-layer]')) node.toggleAttribute('hidden', node.dataset.scLayer !== key);
      for (const node of root.querySelectorAll('[data-sc-read]')) node.hidden = node.dataset.scRead !== key;
    };
    for (const button of root.querySelectorAll('[data-sc-open]')) button.addEventListener('click', () => { state.open = button.dataset.scOpen; show(); });
    for (const button of root.querySelectorAll('[data-sc-zeros]')) button.addEventListener('click', () => { state.zeros = button.dataset.scZeros; show(); });
  },
};
