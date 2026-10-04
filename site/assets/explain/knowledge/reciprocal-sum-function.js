/* y = x + k/x (k > 0): the lowest point at x = √k, and highest/lowest values on a sliding window. Purely local. */
import {escapeHtml as escape, problemNote} from '../shared/html.js?v=1';

const KS = {1: {root: '1', low: '2'}, 2: {root: '√2', low: '2√2'}, 4: {root: '2', low: '4'}};
const WIDTH = 1.5;
const WINDOW = {min: 0.5, max: 4, step: 0.5, value: 0.5};
const BOUNDS = [-4.5, 6, -8, 9];
const plot = {left: 24, right: 344, top: 12, bottom: 212};
const sx = x => plot.left + (x - BOUNDS[0]) / (BOUNDS[1] - BOUNDS[0]) * (plot.right - plot.left);
const sy = y => plot.bottom - (y - BOUNDS[2]) / (BOUNDS[3] - BOUNDS[2]) * (plot.bottom - plot.top);
const fromSx = px => BOUNDS[0] + (px - plot.left) / (plot.right - plot.left) * (BOUNDS[1] - BOUNDS[0]);
const f = (k, x) => x + k / x;

const gcd = (a, b) => b ? gcd(b, a % b) : Math.abs(a);
const frac = (num, den) => {
  const g = gcd(num, den);
  return den / g === 1 ? String(num / g) : `${num / g}/${den / g}`;
};
// Window ends are multiples of 1/2, so x = n/2 gives f(x) = (n² + 4k) / (2n) exactly.
const half = n => frac(n, 2);
const valueAt = (k, n) => frac(n * n + 4 * k, 2 * n);

function path(k, from, to) {
  return Array.from({length: 121}, (_, i) => from + (to - from) * i / 120)
    .map((x, i) => `${i ? 'L' : 'M'}${sx(x).toFixed(1)} ${sy(f(k, x)).toFixed(1)}`).join(' ');
}

// Start each branch where it enters the plot, so the steep part near the y-axis stays short.
const entry = k => (10 - Math.sqrt(100 - 4 * k)) / 2;

function analyse(k, p) {
  const n = Math.round(p * 2), m = n + WIDTH * 2;
  const root = Math.sqrt(k), q = p + WIDTH;
  const names = {left: `左端点 x = ${half(n)}`, right: `右端点 x = ${half(m)}`};
  const low = root < p
    ? {xs: [p], at: names.left, why: '区间在最低点右侧，这一段一直上升'}
    : root > q
      ? {xs: [q], at: names.right, why: '区间在最低点左侧，这一段一直下降'}
      : {xs: [root], at: `最低点 x = ${KS[k].root}`, why: '最低点在区间里'};
  low.value = root >= p && root <= q ? KS[k].low : root < p ? valueAt(k, n) : valueAt(k, m);
  const product = p * q, compare = `${half(n)} × ${half(m)} = ${frac(n * m, 4)}`;
  const high = product < k
    ? {xs: [p], at: names.left, value: valueAt(k, n), why: `两端点之积 ${compare}，比 k 小，左端更高`}
    : product > k
      ? {xs: [q], at: names.right, value: valueAt(k, m), why: `两端点之积 ${compare}，比 k 大，右端更高`}
      : {xs: [p, q], at: `${names.left}、${names.right}`, value: valueAt(k, n), why: `两端点之积 ${compare}，等于 k，两端一样高`};
  return {low, high};
}

function layer({k, p}) {
  const root = Math.sqrt(k), q = p + WIDTH, start = entry(k);
  const result = analyse(k, p);
  const marks = (side, kind) => side.xs.map(x => `<circle cx="${sx(x)}" cy="${sy(f(k, x))}" r="6" class="rs-point ${kind}"/>`).join('');
  const label = (x, y, text, anchor) => `<text x="${sx(x)}" y="${y}" text-anchor="${anchor}" class="rs-label">${text}</text>`;
  return `<rect x="${sx(p)}" y="${plot.top}" width="${sx(q) - sx(p)}" height="${plot.bottom - plot.top}" class="rs-band"/>
    <rect x="${sx(p) + (sx(q) - sx(p)) / 2 - 30}" y="${plot.bottom - 22}" width="60" height="18" rx="9" class="rs-handle"/>
    <text x="${sx(p) + (sx(q) - sx(p)) / 2}" y="${plot.bottom - 9}" text-anchor="middle" class="rs-handle-text">区间 ⇆</text>
    <g clip-path="url(#rs-clip)">
      <path d="${path(k, start, BOUNDS[1])}" class="rs-curve"/>
      <path d="${path(k, -start, BOUNDS[0])}" class="rs-curve neg"/>
      <path d="${path(k, p, q)}" class="rs-curve-on"/>
    </g>
    <circle cx="${sx(root)}" cy="${sy(2 * root)}" r="3.6" class="rs-vertex"/>
    ${label(root, sy(2 * root) + 20, `(${KS[k].root}, ${KS[k].low})`, 'middle')}
    <circle cx="${sx(-root)}" cy="${sy(-2 * root)}" r="3.6" class="rs-vertex"/>
    ${label(-root, sy(-2 * root) - 12, `(−${KS[k].root}, −${KS[k].low})`, 'middle')}
    ${marks(result.low, 'low')}${marks(result.high, 'high')}`;
}

function figure() {
  return `<svg class="rs-graph" viewBox="0 0 360 230" role="img" aria-labelledby="rs-graph-title">
    <title id="rs-graph-title">函数 y = x + k/x 的图像，可以左右拖动一段区间</title>
    <defs><clipPath id="rs-clip"><rect x="${plot.left}" y="${plot.top}" width="${plot.right - plot.left}" height="${plot.bottom - plot.top}"/></clipPath></defs>
    <rect x="${plot.left}" y="${plot.top}" width="${plot.right - plot.left}" height="${plot.bottom - plot.top}" rx="6" class="rs-plot"/>
    <path d="M${plot.left} ${sy(0)}H${plot.right}M${sx(0)} ${plot.top}V${plot.bottom}" class="rs-axis"/>
    <path d="M${sx(-8)} ${sy(-8)}L${sx(BOUNDS[1])} ${sy(BOUNDS[1])}" clip-path="url(#rs-clip)" class="rs-asymptote"/>
    <text x="${sx(5.6)}" y="${sy(5.6) + 16}" text-anchor="end" class="rs-asymptote-label">y = x</text>
    ${[1, 2, 3, 4, 5].map(x => `<text x="${sx(x)}" y="${plot.bottom + 15}" text-anchor="middle" class="rs-tick">${x}</text>`).join('')}
    <text x="${sx(0)}" y="${plot.bottom + 15}" text-anchor="middle" class="rs-tick">0</text>
    <g data-rs-layer></g>
  </svg>`;
}

export default {
  stylesheet: new URL('reciprocal-sum-function.css?v=1', import.meta.url).href,

  render({tip}) {
    return `<p class="rs-core" data-math-text>$k&gt;0$ 时，$y=x+\\frac kx$ 在 $x&gt;0$ 上先减后增，最低点在 $x=\\sqrt k$，最小值是 $2\\sqrt k$；$x&lt;0$ 的部分和它关于原点对称，最高点是 $(-\\sqrt k,-2\\sqrt k)$。</p>
    ${tip?.note ? `<p class="rs-problem"><span class="rs-badge">本题</span><span data-math-text>${problemNote(tip.note)}</span></p>` : ''}
    <p class="rs-why" data-math-text>为什么在 $x=\\sqrt k$：$x&gt;0$ 时，$x+\\frac kx\\ge2\\sqrt{x\\cdot\\frac kx}=2\\sqrt k$，两项相等即 $x=\\frac kx$ 时取等。</p>
    <div class="rs-explorer">
      <div class="rs-switch" role="group" aria-label="k 的值">
        ${Object.keys(KS).map(k => `<button type="button" data-rs-k="${k}" aria-pressed="${k === '4'}">k = ${k}</button>`).join('')}
      </div>
      ${figure()}
      <input class="rs-slider" type="range" data-rs-slider min="${WINDOW.min}" max="${WINDOW.max}" step="${WINDOW.step}" value="${WINDOW.value}" aria-label="区间的位置">
      <div class="rs-status" aria-live="polite">
        <p class="rs-row"><span class="rs-tag interval">区间</span><b data-rs-interval></b></p>
        <p class="rs-row"><span class="rs-tag low">最小值</span><b data-rs-at="low"></b><small data-rs-why="low"></small></p>
        <p class="rs-row"><span class="rs-tag high">最大值</span><b data-rs-at="high"></b><small data-rs-why="high"></small></p>
      </div>
    </div>
    <div class="rs-notes">
      <section class="rs-note">
        <h3>两端谁更高：看两端点之积和 k</h3>
        <p data-math-text>图像不左右对称，不能像抛物线那样和中点比。因为 $f(p)-f(q)=(p-q)\\left(1-\\frac k{pq}\\right)$，$0&lt;p&lt;q$ 时：$pq&lt;k$ 左端高，$pq&gt;k$ 右端高。例如 $x+\\frac4x$ 在 $[1,3]$ 上，$1\\times3&lt;4$，最大值 $f(1)=5$，最小值 $f(2)=4$。</p>
      </section>
      <section class="rs-note">
        <h3>x &lt; 0 时：先提出负号</h3>
        <p data-math-text>例如 $h(x)=-x-\\frac2x$（$x&lt;0$）：$-x&gt;0$，$h(x)=(-x)+\\frac2{-x}\\ge2\\sqrt2$，$x=-\\sqrt2$ 时取等，最小值 $2\\sqrt2$。整个定义域上，$x+\\frac kx$ 既没有最低点，也没有最高点。</p>
      </section>
      <section class="rs-note">
        <h3>开区间与 k &lt; 0</h3>
        <p data-math-text>$x+\\frac4x$ 在 $(1,2)$ 上递减，两端取不到，取值范围是 $(4,5)$。$k&lt;0$ 时（如 $x-\\frac1x$），在 $x&gt;0$ 上一直递增，没有最低点。</p>
        <p>端点取不到时，见 <button type="button" class="rs-link" data-explain-open="endpoint-attainability"></button>。</p>
      </section>
    </div>`;
  },

  mount(root) {
    const svg = root.querySelector('.rs-graph');
    const slider = root.querySelector('[data-rs-slider]');
    const state = {k: 4, p: WINDOW.value};
    const draw = () => {
      root.querySelector('[data-rs-layer]').innerHTML = layer(state);
      slider.value = state.p;
      for (const button of root.querySelectorAll('[data-rs-k]')) button.setAttribute('aria-pressed', String(Number(button.dataset.rsK) === state.k));
      const n = Math.round(state.p * 2), result = analyse(state.k, state.p);
      root.querySelector('[data-rs-interval]').textContent = `[${half(n)}, ${half(n + WIDTH * 2)}]，k = ${state.k}，最低点 x = ${KS[state.k].root}`;
      for (const kind of ['low', 'high']) {
        root.querySelector(`[data-rs-at="${kind}"]`).textContent = `${result[kind].value}，在${result[kind].at}`;
        root.querySelector(`[data-rs-why="${kind}"]`).textContent = result[kind].why;
      }
    };
    const move = value => {
      state.p = Math.min(WINDOW.max, Math.max(WINDOW.min, Math.round(value / WINDOW.step) * WINDOW.step));
      draw();
    };
    const fromPointer = event => {
      const box = svg.getBoundingClientRect();
      move(fromSx((event.clientX - box.left) / box.width * 360) - WIDTH / 2);
    };
    svg.addEventListener('pointerdown', event => { fromPointer(event); svg.setPointerCapture(event.pointerId); });
    svg.addEventListener('pointermove', event => { if (svg.hasPointerCapture(event.pointerId)) fromPointer(event); });
    slider.addEventListener('input', () => move(Number(slider.value)));
    for (const button of root.querySelectorAll('[data-rs-k]')) button.addEventListener('click', () => { state.k = Number(button.dataset.rsK); draw(); });
    draw();
  },
};
