/* Public graph resource: y = x + 4/x across 0, splitting the interval before taking the union of ranges. Purely local. */

const K = 4;
const BOUNDS = [-4, 4, -9, 9];
const plot = {left: 30, right: 340, top: 10, bottom: 226};
const sx = x => plot.left + (x - BOUNDS[0]) / (BOUNDS[1] - BOUNDS[0]) * (plot.right - plot.left);
const sy = y => plot.bottom - (y - BOUNDS[2]) / (BOUNDS[3] - BOUNDS[2]) * (plot.bottom - plot.top);
const f = x => x + K / x;
// Where a branch leaves the plot at |y| = 9.
const ENTRY = (9 - Math.sqrt(81 - 4 * K)) / 2;

// lo/hi are ±Infinity when the branch runs off towards x = 0.
const CASES = {
  apart: {
    label: '$[-3,-1]\\cup[1,3]$',
    segments: [
      {from: -3, to: -1, points: [-3, -2, -1], lo: -5, hi: -4, range: '$[-5,-4]$', why: '$x=-2$ 处最高为 $-4$；两端 $f(-3)=-\\frac{13}3$，$f(-1)=-5$，较低的是 $-5$。'},
      {from: 1, to: 3, points: [1, 2, 3], lo: 4, hi: 5, range: '$[4,5]$', why: '$x=2$ 处最低为 $4$；两端 $f(1)=5$，$f(3)=\\frac{13}3$，较高的是 $5$。'},
    ],
    union: '$[-5,-4]\\cup[4,5]$',
    gap: '中间的 $(-4,4)$ 一个值也取不到，不能写成 $[-5,5]$。',
  },
  across: {
    label: '$[-3,3]$，$x\\ne0$',
    segments: [
      {from: -3, to: 0, points: [-3, -2], lo: -Infinity, hi: -4, range: '$(-\\infty,-4]$', why: '$x=-2$ 处最高为 $-4$；$x$ 从左边靠近 $0$ 时，函数值要多小有多小。'},
      {from: 0, to: 3, points: [2, 3], lo: 4, hi: Infinity, range: '$[4,+\\infty)$', why: '$x=2$ 处最低为 $4$；$x$ 从右边靠近 $0$ 时，函数值要多大有多大。'},
    ],
    union: '$(-\\infty,-4]\\cup[4,+\\infty)$',
    gap: '区间跨过 $0$ 时两段都能跑到无穷，但中间的 $(-4,4)$ 仍然取不到。',
  },
  uneven: {
    label: '$[-1,2]$，$x\\ne0$',
    segments: [
      {from: -1, to: 0, points: [-1], lo: -Infinity, hi: -5, range: '$(-\\infty,-5]$', why: '$-2$ 不在 $[-1,0)$ 里，这一段一直下降：从 $f(-1)=-5$ 往下没有底。'},
      {from: 0, to: 2, points: [2], lo: 4, hi: Infinity, range: '$[4,+\\infty)$', why: '$(0,2]$ 上一直下降，最低是 $f(2)=4$，靠近 $0$ 时没有顶。'},
    ],
    union: '$(-\\infty,-5]\\cup[4,+\\infty)$',
    gap: '两段不对称：缺口是 $(-5,4)$，要分别算，不能照抄另一边。',
  },
};
const START = 'apart';

function path(from, to) {
  return Array.from({length: 81}, (_, i) => from + (to - from) * i / 80)
    .map((x, i) => `${i ? 'L' : 'M'}${sx(x).toFixed(1)} ${sy(f(x)).toFixed(1)}`).join(' ');
}

const clampY = y => Math.max(BOUNDS[2], Math.min(BOUNDS[3], y));
const valueText = y => (y < 0 ? '−' : '') + Math.abs(y);
const arrow = (x, y, dir) => `<path d="M${x - 5} ${y + dir * 8}L${x} ${y}L${x + 5} ${y + dir * 8}" class="sr-range-tip"/>`;

function layer(key) {
  const {segments} = CASES[key];
  const axisX = sx(0);
  const pieces = segments.map(({from, to}) => `<path d="${path(from === 0 ? ENTRY : from, to === 0 ? -ENTRY : to)}" class="sr-curve-on"/>`).join('');
  const dots = segments.flatMap(s => s.points).map(x => `<circle cx="${sx(x)}" cy="${sy(f(x))}" r="4" class="sr-point"/>`).join('');
  const bars = segments.map(({lo, hi}) => {
    const [top, bottom] = [sy(clampY(hi)), sy(clampY(lo))];
    const tips = (hi === Infinity ? arrow(axisX, top, 1) : '') + (lo === -Infinity ? arrow(axisX, bottom, -1) : '');
    const labels = [[lo, 12], [hi, -2]].filter(([y]) => Number.isFinite(y)).map(([y, dy]) => `<text x="${axisX - 8}" y="${sy(y) + dy}" text-anchor="end" class="sr-value">${valueText(y)}</text>`).join('');
    return `<path d="M${axisX} ${top}V${bottom}" class="sr-range"/>${tips}${labels}`;
  }).join('');
  const [gapLow, gapHigh] = [segments[0].hi, segments[1].lo].map(sy);
  const gap = `<path d="M${axisX} ${gapLow}V${gapHigh}" class="sr-gap"/>
    <text x="${axisX + 10}" y="${gapHigh + (gapLow - gapHigh) * 0.3 + 4}" class="sr-gap-label">取不到</text>`;
  return `<g data-sr-layer="${key}"${key === START ? '' : ' hidden'}><g clip-path="url(#sr-clip)">${pieces}</g>${dots}${gap}${bars}</g>`;
}

const bands = key => `<g data-sr-layer="${key}"${key === START ? '' : ' hidden'}>${CASES[key].segments.map(({from, to}) =>
  `<rect x="${sx(from)}" y="${plot.top}" width="${sx(to) - sx(from)}" height="${plot.bottom - plot.top}" class="sr-band"/>`).join('')}</g>`;

function figure() {
  return `<svg class="sr-graph" viewBox="0 0 360 246" role="img" aria-labelledby="sr-graph-title">
    <title id="sr-graph-title">y = x + 4/x 的正负两支图像，区间跨过 0 时两段的值域分别画在 y 轴上</title>
    <defs><clipPath id="sr-clip"><rect x="${plot.left}" y="${plot.top}" width="${plot.right - plot.left}" height="${plot.bottom - plot.top}"/></clipPath></defs>
    ${Object.keys(CASES).map(bands).join('')}
    <path d="M${plot.left} ${sy(0)}H${plot.right}M${sx(0)} ${plot.top}V${plot.bottom}" class="sr-axis"/>
    <g clip-path="url(#sr-clip)">
      <path d="${path(ENTRY, BOUNDS[1])}" class="sr-curve"/>
      <path d="${path(-ENTRY, BOUNDS[0])}" class="sr-curve"/>
    </g>
    ${Object.keys(CASES).map(layer).join('')}
    ${[-3, -2, -1, 1, 2, 3].map(x => `<text x="${sx(x)}" y="${plot.bottom + 15}" text-anchor="middle" class="sr-tick">${valueText(x)}</text>`).join('')}
    <text x="${sx(0)}" y="${plot.bottom + 15}" text-anchor="middle" class="sr-tick">0</text>
  </svg>`;
}

const read = key => {
  const {segments, union, gap} = CASES[key];
  const row = (cls, tag, main, small) => `<p class="sr-row"><span class="sr-tag ${cls}">${tag}</span><b data-math-text>${main}</b><small data-math-text>${small}</small></p>`;
  return `<div class="sr-read" data-sr-read="${key}"${key === START ? '' : ' hidden'}>
      ${row('neg', '负半段', segments[0].range, segments[0].why)}
      ${row('pos', '正半段', segments[1].range, segments[1].why)}
      ${row('union', '合起来', union, gap)}
    </div>`;
};

const explorer = () => `<div class="sr-explorer">
    <div class="sr-cases" role="group" aria-label="区间">
      ${Object.entries(CASES).map(([key, c]) => `<button type="button" data-sr-case="${key}" aria-pressed="${key === START}"><span data-math-text>${c.label}</span></button>`).join('')}
    </div>
    ${figure()}
    ${Object.keys(CASES).map(read).join('')}
  </div>`;

export default {
  stylesheet: new URL('reciprocal-split-range.css?v=1', import.meta.url).href,

  figure: explorer,

  render: () => explorer(),

  mount(root) {
    const pick = key => {
      for (const button of root.querySelectorAll('[data-sr-case]')) button.setAttribute('aria-pressed', String(button.dataset.srCase === key));
      for (const node of root.querySelectorAll('[data-sr-layer]')) node.toggleAttribute('hidden', node.dataset.srLayer !== key);
      for (const node of root.querySelectorAll('[data-sr-read]')) node.hidden = node.dataset.srRead !== key;
    };
    for (const button of root.querySelectorAll('[data-sr-case]')) button.addEventListener('click', () => pick(button.dataset.srCase));
  },
};
