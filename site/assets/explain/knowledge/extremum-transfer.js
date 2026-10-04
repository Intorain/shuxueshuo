/* For-all / exists as a curve against a draggable horizontal line. Purely local: opening it never calls the tutor. */
import {escapeHtml as escape, problemNote} from '../shared/html.js?v=1';

// One picture covers all four cases: the curve y = f(x) on an interval against the horizontal line y = a.
const curve = {
  f: x => (x - 1) ** 2 - 1,
  interval: [-0.5, 3],
  lowest: {x: 1, y: -1},
  highest: {x: 3, y: 3},
  bounds: [-1.3, 3.6, -2, 4.2],
  line: {min: -1.75, max: 3.75, step: 0.25, value: 1},
};
const plot = {left: 44, right: 332, top: 18, bottom: 206};
const sx = x => plot.left + (x - curve.bounds[0]) / (curve.bounds[1] - curve.bounds[0]) * (plot.right - plot.left);
const sy = y => plot.bottom - (y - curve.bounds[2]) / (curve.bounds[3] - curve.bounds[2]) * (plot.bottom - plot.top);
const fromSy = py => curve.bounds[2] + (plot.bottom - py) / (plot.bottom - plot.top) * (curve.bounds[3] - curve.bounds[2]);
const holds = (y, relation, a) => relation === 'gt' ? y > a : y < a;
// Which point decides each question: "for all" needs the least favourable point, "exists" the most favourable.
const decisive = {
  gt: {forall: 'lowest', exists: 'highest'},
  lt: {forall: 'highest', exists: 'lowest'},
};
const pointName = {lowest: '最低点', highest: '最高点'};
const side = {gt: '上方', lt: '下方'};
// The four cells of the summary table; a finished step's tip.case names one of them.
const CELLS = {
  'forall-gt': ['f(x)_{\\min}&gt;a', '看最低点'],
  'forall-lt': ['f(x)_{\\max}&lt;a', '看最高点'],
  'exists-gt': ['f(x)_{\\max}&gt;a', '看最高点'],
  'exists-lt': ['f(x)_{\\min}&lt;a', '看最低点'],
};

function samples(from, to, extra = []) {
  const values = Array.from({length: 121}, (_, i) => from + (to - from) * i / 120);
  return [...values, ...extra.filter(x => x > from && x < to)].sort((p, q) => p - q);
}

function segments(points, keep) {
  const runs = [];
  let run = [];
  for (const x of points) {
    if (keep(x)) run.push(x);
    else if (run.length) { runs.push(run); run = []; }
  }
  if (run.length) runs.push(run);
  return runs.filter(r => r.length > 1).map(r => r.map((x, i) => `${i ? 'L' : 'M'}${sx(x).toFixed(1)} ${sy(curve.f(x)).toFixed(1)}`).join(' ')).join(' ');
}

function layer(a, relation) {
  const [left, right] = curve.interval;
  // Include the exact crossings so the highlighted part meets the line instead of stopping short.
  const roots = a >= -1 ? [1 - Math.sqrt(a + 1), 1 + Math.sqrt(a + 1)] : [];
  const xs = samples(left, right, roots);
  const ok = segments(xs, x => holds(curve.f(x), relation, a) || roots.some(r => Math.abs(r - x) < 1e-9));
  const bad = segments(xs, x => !holds(curve.f(x), relation, a) || roots.some(r => Math.abs(r - x) < 1e-9));
  const point = key => {
    const {x, y} = curve[key];
    const met = holds(y, relation, a);
    const label = key === 'lowest'
      ? `<text x="${sx(x)}" y="${sy(y) + 24}" text-anchor="middle" class="kt-point-label">最低点</text>`
      : `<text x="${sx(x) - 11}" y="${sy(y) + 4}" text-anchor="end" class="kt-point-label">最高点</text>`;
    return `<circle cx="${sx(x)}" cy="${sy(y)}" r="6.5" class="kt-point ${met ? 'met' : 'unmet'}"/>${label}`;
  };
  const y = sy(a);
  return `<path d="${bad}" class="kt-curve-unmet"/>
    <path d="${ok}" class="kt-curve-met"/>
    <path d="M${plot.left} ${y}H${plot.right}" class="kt-line"/>
    <rect x="${plot.right - 62}" y="${y - 12}" width="60" height="24" rx="12" class="kt-handle"/>
    <text x="${plot.right - 32}" y="${y + 4.5}" text-anchor="middle" class="kt-handle-text">y = a ⇅</text>
    ${point('lowest')}${point('highest')}`;
}

function explorerFigure() {
  const [left, right] = curve.interval;
  const outside = samples(curve.bounds[0], curve.bounds[1]).map((x, i) => `${i ? 'L' : 'M'}${sx(x).toFixed(1)} ${sy(curve.f(x)).toFixed(1)}`).join(' ');
  return `<svg class="kt-graph" viewBox="0 0 360 236" role="img" aria-labelledby="kt-graph-title">
    <title id="kt-graph-title">曲线 y = f(x) 在一个区间上的一段，和一条可以上下拖动的水平线 y = a</title>
    <defs><clipPath id="kt-clip"><rect x="${plot.left}" y="${plot.top}" width="${plot.right - plot.left}" height="${plot.bottom - plot.top}"/></clipPath></defs>
    <rect x="${plot.left}" y="${plot.top}" width="${plot.right - plot.left}" height="${plot.bottom - plot.top}" rx="6" class="kt-plot"/>
    <rect x="${sx(left)}" y="${plot.top}" width="${sx(right) - sx(left)}" height="${plot.bottom - plot.top}" class="kt-band"/>
    <path d="M${plot.left - 14} ${sy(0)}H${plot.right + 12}M${sx(0)} ${plot.bottom + 10}V${plot.top - 6}" class="kt-axis"/>
    <text x="${plot.right + 16}" y="${sy(0) + 5}" class="kt-axis-label">x</text>
    <text x="${sx(0) - 8}" y="${plot.top - 2}" text-anchor="end" class="kt-axis-label">y</text>
    <path d="M${plot.left} ${sy(curve.lowest.y)}H${plot.right}M${plot.left} ${sy(curve.highest.y)}H${plot.right}" class="kt-guide"/>
    <g clip-path="url(#kt-clip)"><path d="${outside}" class="kt-curve-outside"/></g>
    <text x="${(sx(left) + sx(right)) / 2}" y="${plot.bottom + 24}" text-anchor="middle" class="kt-band-label">x 的取值范围</text>
    <g data-kt-layer></g>
  </svg>`;
}

function cell(key, problemCase) {
  const [formula, hint] = CELLS[key];
  const mine = key === problemCase;
  return `<td data-kt-col="${key.slice(-2)}" data-kt-cell="${key}"${mine ? ' class="kt-problem-cell"' : ''}>${mine ? '<span class="kt-badge">本题</span>' : ''}<span data-math-text>$${formula}$</span><small>${hint}</small></td>`;
}

export default {
  stylesheet: new URL('extremum-transfer.css?v=1', import.meta.url).href,

  // An active step passes no tip, so the sheet teaches the rule without pointing at the answer still being chosen.
  render({tip}) {
    const problemCase = tip?.case;
    return `<p class="kt-core">把不等式看成曲线 <i>y</i> = <i>f</i>(<i>x</i>) 和水平线 <i>y</i> = <i>a</i> 比高低。上下拖动水平线，看两个问题的答案在哪里改变。</p>
    ${tip?.note ? `<p class="kt-problem"><span class="kt-badge">本题</span><span data-math-text>${problemNote(tip.note)}</span></p>` : ''}
    <div class="kt-explorer">
      <div class="kt-relation" role="group" aria-label="比较的方向">
        <button type="button" data-kt-relation="gt" aria-pressed="true"><span><i>f</i>(<i>x</i>) &gt; <i>a</i></span><small>曲线在线上方</small></button>
        <button type="button" data-kt-relation="lt" aria-pressed="false"><span><i>f</i>(<i>x</i>) &lt; <i>a</i></span><small>曲线在线下方</small></button>
      </div>
      ${explorerFigure()}
      <input class="kt-slider" type="range" data-kt-slider min="${curve.line.min}" max="${curve.line.max}" step="${curve.line.step}" value="${curve.line.value}" aria-label="水平线 y = a 的高度">
      <div class="kt-status" aria-live="polite">
        <p class="kt-row" data-kt-row="forall"><span class="kt-tag">恒成立</span><span class="kt-question">每一点都满足吗？</span><b class="kt-verdict"></b><small class="kt-why"></small></p>
        <p class="kt-row" data-kt-row="exists"><span class="kt-tag exists">存在</span><span class="kt-question">至少一点满足吗？</span><b class="kt-verdict"></b><small class="kt-why"></small></p>
      </div>
    </div>
    <table class="kt-table">
      <caption>四种情况一张表</caption>
      <thead><tr><th scope="col"><span class="kt-hidden">问法</span></th><th scope="col" data-kt-col="gt"><span data-math-text>$f(x)&gt;a$</span></th><th scope="col" data-kt-col="lt"><span data-math-text>$f(x)&lt;a$</span></th></tr></thead>
      <tbody>
        <tr><th scope="row">恒成立<small>每一点</small></th>${cell('forall-gt', problemCase)}${cell('forall-lt', problemCase)}</tr>
        <tr><th scope="row">存在<small>至少一点</small></th>${cell('exists-gt', problemCase)}${cell('exists-lt', problemCase)}</tr>
      </tbody>
    </table>
    <p class="kt-motto">恒成立看最不利的点，存在看最有利的点。</p>
    <p class="kt-small" data-math-text>带等号的 $\\ge$、$\\le$：最值能取到时，表中的不等号同样带上等号。</p>
    <div class="kt-notes">
      <section class="kt-note">
        <h3>参数在另一边，也一样</h3>
        <p data-math-text>把参数看成那条水平线：$a\\le h(x)$ 恒成立 $\\iff a\\le h(x)_{\\min}$；$a\\le h(x)$ 有解 $\\iff a\\le h(x)_{\\max}$。</p>
        <p data-math-text>遇到 $m&lt;-h(x)$，先读成 $-h(x)&gt;m$：$-h(x)$ 的最低点，正是 $h(x)$ 的最高点。</p>
      </section>
      <section class="kt-note">
        <h3>最值取不到时</h3>
        <p>开区间、或者只能无限接近时，改看取值范围的上端、下端，再单独检验等号：</p>
        <ul>
          <li data-math-text>恒成立的 $&gt;$ 可以放宽为 $\\ge$：$f(x)&gt;0$ 恒成立，下端 $0$ 取不到时，下端 $\\ge0$ 就够了。</li>
          <li data-math-text>存在的 $\\ge$ 要收紧为 $&gt;$：$f(x)\\ge0$ 有解，上端取不到时，需要上端 $&gt;0$。</li>
        </ul>
      </section>
    </div>`;
  },

  mount(root, {tip}) {
    const svg = root.querySelector('.kt-graph');
    const slider = root.querySelector('[data-kt-slider]');
    const state = {a: curve.line.value, relation: tip?.case?.endsWith('-lt') ? 'lt' : 'gt'};
    const why = question => {
      const key = decisive[state.relation][question];
      const y = curve[key].y;
      if (y === state.a) return `看${pointName[key]}：它正好在线上，不算${state.relation === 'gt' ? '大于' : '小于'}`;
      return `看${pointName[key]}：它${holds(y, state.relation, state.a) ? '在' : '不在'}线${side[state.relation]}`;
    };
    const draw = () => {
      root.querySelector('[data-kt-layer]').innerHTML = layer(state.a, state.relation);
      slider.value = state.a;
      for (const button of root.querySelectorAll('[data-kt-relation]')) button.setAttribute('aria-pressed', String(button.dataset.ktRelation === state.relation));
      for (const element of root.querySelectorAll('[data-kt-col]')) element.classList.toggle('kt-active-col', element.dataset.ktCol === state.relation);
      for (const question of ['forall', 'exists']) {
        const met = holds(curve[decisive[state.relation][question]].y, state.relation, state.a);
        const row = root.querySelector(`[data-kt-row="${question}"]`);
        row.classList.toggle('met', met);
        row.querySelector('.kt-verdict').textContent = met ? '✓ 成立' : '✗ 不成立';
        row.querySelector('.kt-why').textContent = why(question);
      }
    };
    const move = value => {
      const {min, max, step} = curve.line;
      state.a = Math.min(max, Math.max(min, Math.round(value / step) * step));
      draw();
    };
    const fromPointer = event => {
      const box = svg.getBoundingClientRect();
      move(fromSy((event.clientY - box.top) / box.height * 236));
    };
    svg.addEventListener('pointerdown', event => { fromPointer(event); svg.setPointerCapture(event.pointerId); });
    svg.addEventListener('pointermove', event => { if (svg.hasPointerCapture(event.pointerId)) fromPointer(event); });
    slider.addEventListener('input', () => move(Number(slider.value)));
    for (const button of root.querySelectorAll('[data-kt-relation]')) {
      button.addEventListener('click', () => { state.relation = button.dataset.ktRelation; draw(); });
    }
    draw();
  },
};
