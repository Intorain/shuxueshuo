/* Where a parabola's highest and lowest values on an interval sit, as the axis of symmetry is dragged. Purely local. */
import {escapeHtml as escape, problemNote} from '../shared/html.js?v=1';

// Fixed interval [1, 3] (or (1, 3)); the parabola is 0.55(x − h)² − 1 opening up, or −0.55(x − h)² + 4 opening down.
const INTERVAL = {left: 1, right: 3, mid: 2};
const AXIS = {min: -0.25, max: 4.25, step: 0.25, value: 0.5};
const BOUNDS = [-1, 5, -2, 5.5];
const plot = {left: 30, right: 340, top: 14, bottom: 206};
const sx = x => plot.left + (x - BOUNDS[0]) / (BOUNDS[1] - BOUNDS[0]) * (plot.right - plot.left);
const sy = y => plot.bottom - (y - BOUNDS[2]) / (BOUNDS[3] - BOUNDS[2]) * (plot.bottom - plot.top);
const fromSx = px => BOUNDS[0] + (px - plot.left) / (plot.right - plot.left) * (BOUNDS[1] - BOUNDS[0]);
const curve = (up, h) => x => up ? 0.55 * (x - h) ** 2 - 1 : -0.55 * (x - h) ** 2 + 4;
const NAMES = {[INTERVAL.left]: '左端点 x = 1', [INTERVAL.right]: '右端点 x = 3'};

function path(f, from, to) {
  return Array.from({length: 97}, (_, i) => from + (to - from) * i / 96)
    .map((x, i) => `${i ? 'L' : 'M'}${sx(x).toFixed(1)} ${sy(f(x)).toFixed(1)}`).join(' ');
}

// The vertex side compares the axis with both endpoints; the far side compares it with the midpoint.
function analyse({up, open, h}) {
  const {left, right, mid} = INTERVAL;
  const inside = open ? h > left && h < right : h >= left && h <= right;
  const vertexSide = inside
    ? {xs: [h], where: '对称轴在区间里', why: '顶点在区间里'}
    : h <= left
      ? {xs: [left], where: h === left ? '对称轴在左端点上' : '对称轴在区间左侧', why: `这一段${up ? '一直上升' : '一直下降'}，看离对称轴近的左端点`}
      : {xs: [right], where: h === right ? '对称轴在右端点上' : '对称轴在区间右侧', why: `这一段${up ? '一直下降' : '一直上升'}，看离对称轴近的右端点`};
  const farSide = h < mid
    ? {xs: [right], where: '对称轴在中点左侧', why: '右端点离对称轴更远'}
    : h > mid
      ? {xs: [left], where: '对称轴在中点右侧', why: '左端点离对称轴更远'}
      : {xs: [left, right], where: '对称轴在中点上', why: '两端一样远，函数值相等'};
  const [low, high] = up ? [vertexSide, farSide] : [farSide, vertexSide];
  const attained = x => !(open && (x === left || x === right));
  const describe = (side, word, end) => {
    const at = side.xs.map(x => x === h && side === vertexSide && inside ? '顶点' : NAMES[x]).join('、');
    const reached = side.xs.every(attained);
    return {
      title: reached ? word : `${end}（取不到）`,
      at, reached, xs: side.xs,
      why: `${side.where}：${side.why}${reached ? '' : '；开区间端点取不到，只能无限接近'}`,
    };
  };
  return {low: describe(low, '最小值', '下端'), high: describe(high, '最大值', '上端')};
}

function layer(state) {
  const f = curve(state.up, state.h);
  const {left, right, mid} = INTERVAL;
  const result = analyse(state);
  const marks = (side, kind) => side.xs
    .map(x => `<circle cx="${sx(x)}" cy="${sy(f(x))}" r="6" class="qi-point ${kind}${side.reached ? '' : ' open'}"/>`).join('');
  const ends = [left, right].map(x => `<circle cx="${sx(x)}" cy="${sy(f(x))}" r="3.4" class="qi-end${state.open ? ' open' : ''}"/>`).join('');
  return `<g clip-path="url(#qi-clip)"><path d="${path(f, BOUNDS[0], BOUNDS[1])}" class="qi-curve-outside"/></g>
    <path d="${path(f, left, right)}" class="qi-curve"/>
    ${ends}
    <path d="M${sx(state.h)} ${plot.top}V${plot.bottom}" class="qi-sym"/>
    <rect x="${sx(state.h) - 34}" y="${plot.top}" width="68" height="20" rx="10" class="qi-handle"/>
    <text x="${sx(state.h)}" y="${plot.top + 14}" text-anchor="middle" class="qi-handle-text">对称轴 ⇆</text>
    <path d="M${sx(mid)} ${sy(0) - 6}V${sy(0) + 6}" class="qi-mid"/>
    ${marks(result.low, 'low')}${marks(result.high, 'high')}`;
}

function figure() {
  const {left, right, mid} = INTERVAL;
  return `<svg class="qi-graph" viewBox="0 0 360 244" role="img" aria-labelledby="qi-graph-title">
    <title id="qi-graph-title">一条抛物线和区间 1 到 3，对称轴可以左右拖动</title>
    <defs><clipPath id="qi-clip"><rect x="${plot.left}" y="${plot.top}" width="${plot.right - plot.left}" height="${plot.bottom - plot.top}"/></clipPath></defs>
    <rect x="${plot.left}" y="${plot.top}" width="${plot.right - plot.left}" height="${plot.bottom - plot.top}" rx="6" class="qi-plot"/>
    <rect x="${sx(left)}" y="${plot.top}" width="${sx(right) - sx(left)}" height="${plot.bottom - plot.top}" class="qi-band"/>
    <path d="M${plot.left} ${sy(0)}H${plot.right}" class="qi-axis"/>
    ${[[left, '1'], [mid, '2 中点'], [right, '3']].map(([x, text]) => `<text x="${sx(x)}" y="${plot.bottom + 18}" text-anchor="middle" class="qi-tick">${text}</text>`).join('')}
    <text x="${(sx(left) + sx(right)) / 2}" y="${plot.bottom + 32}" text-anchor="middle" class="qi-band-label">x 的取值范围</text>
    <g data-qi-layer></g>
  </svg>`;
}

const explorer = () => `<div class="qi-explorer">
      <div class="qi-switches">
        <div class="qi-switch" role="group" aria-label="开口方向">
          <button type="button" data-qi-up="1" aria-pressed="true">开口向上</button>
          <button type="button" data-qi-up="0" aria-pressed="false">开口向下</button>
        </div>
        <div class="qi-switch" role="group" aria-label="区间">
          <button type="button" data-qi-open="0" aria-pressed="true">闭区间 [1, 3]</button>
          <button type="button" data-qi-open="1" aria-pressed="false">开区间 (1, 3)</button>
        </div>
      </div>
      ${figure()}
      <input class="qi-slider" type="range" data-qi-slider min="${AXIS.min}" max="${AXIS.max}" step="${AXIS.step}" value="${AXIS.value}" aria-label="对称轴的位置">
      <div class="qi-status" aria-live="polite">
        <p class="qi-row low"><span class="qi-tag low" data-qi-title="low"></span><b data-qi-at="low"></b><small data-qi-why="low"></small></p>
        <p class="qi-row high"><span class="qi-tag high" data-qi-title="high"></span><b data-qi-at="high"></b><small data-qi-why="high"></small></p>
      </div>
    </div>`;

export default {
  stylesheet: new URL('quadratic-interval-extremum.css?v=1', import.meta.url).href,

  figure: explorer,

  render({tip}) {
    return `<p class="qi-core">开口向上时，最小值看顶点在不在区间里：对称轴和两个端点比；最大值看哪个端点离对称轴更远：对称轴和区间中点比。开口向下时两者对调。</p>
    ${tip?.note ? `<p class="qi-problem"><span class="qi-badge">本题</span><span data-math-text>${problemNote(tip.note)}</span></p>` : ''}
    ${explorer()}
    <table class="qi-table">
      <caption>和谁比较</caption>
      <thead><tr><th scope="col"><span class="qi-hidden">开口</span></th><th scope="col">找顶点那一侧</th><th scope="col">找离得远的端点</th></tr></thead>
      <tbody>
        <tr><th scope="row">开口向上</th><td>最小值<small>对称轴和两个端点比：左、里、右三种</small></td><td>最大值<small>对称轴和区间中点比：两种</small></td></tr>
        <tr><th scope="row">开口向下</th><td>最大值<small>对称轴和两个端点比</small></td><td>最小值<small>对称轴和区间中点比</small></td></tr>
      </tbody>
    </table>
    <div class="qi-notes">
      <section class="qi-note">
        <h3>开区间：最值可能变成取不到的上端、下端</h3>
        <p data-math-text>端点处的值取不到，只能无限接近；顶点在开区间里时，顶点值仍取得到。例如 $x^2-2x$ 在 $(0,3)$ 上，最小值 $f(1)=-1$，上端 $f(3)=3$ 取不到，取值范围是 $[-1,3)$。</p>
        <p>端点取不到时参数的边界怎么定，见 <button type="button" class="qi-link" data-explain-open="endpoint-attainability"></button>。</p>
      </section>
      <section class="qi-note">
        <h3>半无限区间：看朝无穷那一边</h3>
        <p data-math-text>开口向上时，朝无穷那一边图像无限升高，没有上端；下端看对称轴在不在区间里。例如 $x^2+2x$ 在 $(0,+\\infty)$ 上递增，下端 $f(0)=0$ 取不到，取值范围是 $(0,+\\infty)$。</p>
      </section>
      <section class="qi-note">
        <h3>二次项系数含参数</h3>
        <p data-math-text>对称轴固定、开口随参数变时，例如 $mx^2-mx-1$ 在 $[2,3]$ 上，按系数的符号分类，别漏了系数为 $0$ 的情况。</p>
      </section>
    </div>`;
  },

  mount(root) {
    const svg = root.querySelector('.qi-graph');
    const slider = root.querySelector('[data-qi-slider]');
    const state = {up: true, open: false, h: AXIS.value};
    const draw = () => {
      root.querySelector('[data-qi-layer]').innerHTML = layer(state);
      slider.value = state.h;
      for (const button of root.querySelectorAll('[data-qi-up]')) button.setAttribute('aria-pressed', String((button.dataset.qiUp === '1') === state.up));
      for (const button of root.querySelectorAll('[data-qi-open]')) button.setAttribute('aria-pressed', String((button.dataset.qiOpen === '1') === state.open));
      const result = analyse(state);
      for (const kind of ['low', 'high']) {
        root.querySelector(`[data-qi-title="${kind}"]`).textContent = result[kind].title;
        root.querySelector(`[data-qi-at="${kind}"]`).textContent = `在${result[kind].at}`;
        root.querySelector(`[data-qi-why="${kind}"]`).textContent = result[kind].why;
      }
    };
    const move = value => {
      state.h = Math.min(AXIS.max, Math.max(AXIS.min, Math.round(value / AXIS.step) * AXIS.step));
      draw();
    };
    const fromPointer = event => {
      const box = svg.getBoundingClientRect();
      move(fromSx((event.clientX - box.left) / box.width * 360));
    };
    svg.addEventListener('pointerdown', event => { fromPointer(event); svg.setPointerCapture(event.pointerId); });
    svg.addEventListener('pointermove', event => { if (svg.hasPointerCapture(event.pointerId)) fromPointer(event); });
    slider.addEventListener('input', () => move(Number(slider.value)));
    for (const button of root.querySelectorAll('[data-qi-up]')) button.addEventListener('click', () => { state.up = button.dataset.qiUp === '1'; draw(); });
    for (const button of root.querySelectorAll('[data-qi-open]')) button.addEventListener('click', () => { state.open = button.dataset.qiOpen === '1'; draw(); });
    draw();
  },
};
