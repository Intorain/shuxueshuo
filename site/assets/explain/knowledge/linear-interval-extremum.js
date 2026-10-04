/* f(t) = kt + b on [−1, 1]: the slope's sign picks the ends, and the two ends decide the whole segment. Purely local. */
import {escapeHtml as escape, problemNote} from '../shared/html.js?v=1';

const INTERVAL = [-1, 1];
const SLOPE = {min: -1.5, max: 1.5, step: 0.25, value: 0.75};
const INTERCEPT = {min: -2, max: 3, step: 0.25, value: 1};
const BOUNDS = [-2.5, 2.5, -4.5, 5];
const plot = {left: 24, right: 344, top: 12, bottom: 200};
const sx = t => plot.left + (t - BOUNDS[0]) / (BOUNDS[1] - BOUNDS[0]) * (plot.right - plot.left);
const sy = y => plot.bottom - (y - BOUNDS[2]) / (BOUNDS[3] - BOUNDS[2]) * (plot.bottom - plot.top);
const num = x => `${x < 0 ? '−' : ''}${Math.abs(x)}`;

function analyse({k, b}) {
  const [left, right] = INTERVAL.map(t => k * t + b);
  const ends = {left: `f(−1) = ${num(left)}`, right: `f(1) = ${num(right)}`};
  const slope = k > 0 ? `k = ${num(k)} > 0：递增` : k < 0 ? `k = ${num(k)} < 0：递减` : 'k = 0：常数函数，图像是水平线';
  const [low, high] = k > 0 ? [ends.left, ends.right] : k < 0 ? [ends.right, ends.left] : [`处处等于 ${num(b)}`, `处处等于 ${num(b)}`];
  const positive = left > 0 && right > 0;
  const bad = [left <= 0 && ends.left, right <= 0 && ends.right].filter(Boolean);
  return {
    left, right, slope, low, high,
    check: positive ? '是' : '否',
    reason: positive ? '两端都在 x 轴上方，中间的线段夹在两端之间，整段都在上方'
      : `${bad.join('，')}，${bad.length === 2 ? '两端都' : '这一端'}不在 x 轴上方`,
  };
}

function layer(state) {
  const {k, b} = state;
  const f = t => k * t + b;
  const result = analyse(state);
  const role = side => k === 0 ? 'flat' : (k > 0) === (side === 'right') ? 'high' : 'low';
  const end = (t, side) => {
    const y = f(t), anchor = side === 'left' ? 'end' : 'start';
    return `<circle cx="${sx(t)}" cy="${sy(y)}" r="6" class="li-point ${role(side)}"/>
      <text x="${sx(t) + (side === 'left' ? -10 : 10)}" y="${sy(y) + 4}" text-anchor="${anchor}" class="li-value">${side === 'left' ? 'f(−1)' : 'f(1)'} = ${num(y)}</text>`;
  };
  return `<g clip-path="url(#li-clip)"><path d="M${sx(BOUNDS[0])} ${sy(f(BOUNDS[0]))}L${sx(BOUNDS[1])} ${sy(f(BOUNDS[1]))}" class="li-line-outside"/></g>
    <path d="M${sx(-1)} ${sy(f(-1))}L${sx(1)} ${sy(f(1))}" class="li-line${result.check === '是' ? '' : ' bad'}"/>
    ${end(-1, 'left')}${end(1, 'right')}`;
}

function figure() {
  return `<svg class="li-graph" viewBox="0 0 360 222" role="img" aria-labelledby="li-graph-title">
    <title id="li-graph-title">一次函数 f(t) = kt + b 在区间 −1 到 1 上的线段</title>
    <defs><clipPath id="li-clip"><rect x="${plot.left}" y="${plot.top}" width="${plot.right - plot.left}" height="${plot.bottom - plot.top}"/></clipPath></defs>
    <rect x="${plot.left}" y="${plot.top}" width="${plot.right - plot.left}" height="${plot.bottom - plot.top}" rx="6" class="li-plot"/>
    <rect x="${sx(-1)}" y="${plot.top}" width="${sx(1) - sx(-1)}" height="${plot.bottom - plot.top}" class="li-band"/>
    <path d="M${plot.left} ${sy(0)}H${plot.right}M${sx(0)} ${plot.top}V${plot.bottom}" class="li-axis"/>
    ${[[-1, '−1'], [0, '0'], [1, '1']].map(([t, text]) => `<text x="${sx(t)}" y="${plot.bottom + 16}" text-anchor="middle" class="li-tick">${text}</text>`).join('')}
    <text x="${plot.right - 4}" y="${sy(0) - 6}" text-anchor="end" class="li-tick">t</text>
    <g data-li-layer></g>
  </svg>`;
}

const slider = (key, range, label) => `<label class="li-control"><span>${label}</span><input type="range" data-li-${key} min="${range.min}" max="${range.max}" step="${range.step}" value="${range.value}"><output data-li-out="${key}"></output></label>`;

export default {
  stylesheet: new URL('linear-interval-extremum.css?v=1', import.meta.url).href,

  render({tip}) {
    return `<p class="li-core" data-math-text>$f(t)=kt+b$：$k&gt;0$ 递增，$k&lt;0$ 递减，$k=0$ 是常数。所以在闭区间上，最大值、最小值都在端点；要整段大于 $0$，只要两个端点都大于 $0$。</p>
    ${tip?.note ? `<p class="li-problem"><span class="li-badge">本题</span><span data-math-text>${problemNote(tip.note)}</span></p>` : ''}
    <div class="li-explorer">
      <div class="li-controls">${slider('k', SLOPE, '斜率 k')}${slider('b', INTERCEPT, '截距 b')}</div>
      ${figure()}
      <div class="li-status" aria-live="polite">
        <p class="li-row"><span class="li-tag">单调</span><b data-li-slope></b></p>
        <p class="li-row"><span class="li-tag low">最小值</span><b data-li-low></b></p>
        <p class="li-row"><span class="li-tag high">最大值</span><b data-li-high></b></p>
        <p class="li-row"><span class="li-tag check">在 [−1, 1] 上恒 &gt; 0？</span><b data-li-check></b><small data-li-reason></small></p>
      </div>
    </div>
    <div class="li-notes">
      <section class="li-note">
        <h3>斜率含字母：不用讨论正负</h3>
        <p data-math-text>$f(a)=(x^2-x)a-x+1$ 的斜率 $x^2-x$ 可正、可负、可为 $0$，但不论哪种，最小值都在某个端点。所以 $f(a)&gt;0$ 在 $[-1,1]$ 上恒成立 $\\iff f(-1)&gt;0$ 且 $f(1)&gt;0$。</p>
        <p>把参数看成自变量，见 <button type="button" class="li-link" data-explain-open="method-variable-swap"></button>。</p>
      </section>
      <section class="li-note">
        <h3>斜率恒正：直接看右端</h3>
        <p data-math-text>$f(m)=(x^2-x+1)m+\\cdots$ 的斜率 $x^2-x+1=\\left(x-\\frac12\\right)^2+\\frac34&gt;0$，$f(m)$ 递增，在 $[1,3]$ 上的最大值是 $f(3)$、最小值是 $f(1)$。</p>
      </section>
      <section class="li-note">
        <h3>开区间：端点可以等于 0</h3>
        <p data-math-text>$f(t)&gt;0$ 在 $(-1,1)$ 上恒成立 $\\iff f(-1)\\ge0$，$f(1)\\ge0$，且两者不同时为 $0$（同时为 $0$ 时 $f(t)$ 恒等于 $0$）。</p>
        <p>见 <button type="button" class="li-link" data-explain-open="endpoint-attainability"></button>。</p>
      </section>
    </div>`;
  },

  mount(root) {
    const inputs = {k: root.querySelector('[data-li-k]'), b: root.querySelector('[data-li-b]')};
    const draw = () => {
      const state = {k: Number(inputs.k.value), b: Number(inputs.b.value)};
      root.querySelector('[data-li-layer]').innerHTML = layer(state);
      for (const key of ['k', 'b']) root.querySelector(`[data-li-out="${key}"]`).textContent = num(state[key]);
      const result = analyse(state);
      root.querySelector('[data-li-slope]').textContent = result.slope;
      root.querySelector('[data-li-low]').textContent = result.low;
      root.querySelector('[data-li-high]').textContent = result.high;
      root.querySelector('[data-li-check]').textContent = result.check;
      root.querySelector('[data-li-reason]').textContent = result.reason;
    };
    for (const input of Object.values(inputs)) input.addEventListener('input', draw);
    draw();
  },
};
