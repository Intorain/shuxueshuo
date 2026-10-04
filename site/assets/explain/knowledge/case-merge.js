/* Merging the results of a case analysis, shown as stacked number lines revealed one case at a time. Purely local. */
import {escapeHtml as escape, problemNote} from '../shared/html.js?v=1';

// Worked example: x in [0,2], x^2 - 2mx + 1 > 0 for all x, cases by where the axis x = m sits.
// A set is a list of intervals [from, to, fromClosed, toClosed]; ±Infinity means the ray goes on.
const ALL = [[-Infinity, Infinity, false, false]];
const CASES = [
  {name: '情况①', where: '对称轴在区间左侧', premise: [[-Infinity, 0, false, true]], premiseText: 'm≤0', solved: ALL, solvedText: '全部满足', result: [[-Infinity, 0, false, true]], resultText: 'm≤0'},
  {name: '情况②', where: '对称轴在区间里', premise: [[0, 2, false, false]], premiseText: '0&lt;m&lt;2', solved: [[-1, 1, false, false]], solvedText: '−1&lt;m&lt;1', result: [[0, 1, false, false]], resultText: '0&lt;m&lt;1'},
  {name: '情况③', where: '对称轴在区间右侧', premise: [[2, Infinity, true, false]], premiseText: 'm≥2', solved: [[-Infinity, 1.25, false, false]], solvedText: 'm&lt;5/4', result: [], resultText: '无解'},
];
const UNION = {set: [[-Infinity, 1, false, false]], text: 'm&lt;1'};
// 1 and 5/4 are close: their labels lean apart so they cannot read as "15/4".
const TICKS = [[-1, '−1'], [0, '0'], [1, '1', 'end'], [1.25, '5/4', 'start'], [2, '2']];
const tickX = (m, anchor) => px(m) + (anchor === 'end' ? 3 : anchor === 'start' ? -3 : 0);
const STEPS = [
  '对称轴 $x=m$ 在区间左侧、区间里、区间右侧时，最小值在不同的地方取到，所以分三种情况。',
  '情况① $m\\le0$：$f(x)$ 在 $[0,2]$ 上递增，最小值 $f(0)=1>0$。这种情况下的 $m$ 全部满足，结果就是整个前提 $m\\le0$。',
  '情况② $0&lt;m&lt;2$：最小值 $f(m)=1-m^2&gt;0$，解得 $-1&lt;m&lt;1$；与前提取交集，得 $0&lt;m&lt;1$。',
  '情况③ $m\\ge2$：最小值 $f(2)=5-4m&gt;0$，解得 $m&lt;\\frac54$；与前提 $m\\ge2$ 没有公共部分，这种情况无解。',
  '三种情况满足其一即可，取并集：$m\\le0$ 并上 $0&lt;m&lt;1$，得 $m&lt;1$。$m=0$ 在情况①的结果里，并集中不留空洞。',
];

const AXIS = {left: 104, right: 338, min: -1.6, max: 2.6};
const px = m => m === -Infinity ? AXIS.left : m === Infinity ? AXIS.right : AXIS.left + (m - AXIS.min) / (AXIS.max - AXIS.min) * (AXIS.right - AXIS.left);

function bar(set, y, kind) {
  return set.map(([from, to, fromClosed, toClosed]) => {
    const [x1, x2] = [px(from), px(to)];
    const end = (x, value, closed, side) => Number.isFinite(value)
      ? `<circle cx="${x}" cy="${y}" r="4.2" class="cm-dot ${kind}${closed ? '' : ' open'}"/>`
      : `<path d="M${x} ${y}L${x - side * 8} ${y - 5}V${y + 5}Z" class="cm-arrow ${kind}"/>`;
    return `<path d="M${x1} ${y}H${x2}" class="cm-bar ${kind}"/>${end(x1, from, fromClosed, -1)}${end(x2, to, toClosed, 1)}`;
  }).join('');
}

function row(y, label, text, set, kind) {
  const body = set.length ? bar(set, y, kind) : `<text x="${(AXIS.left + AXIS.right) / 2}" y="${y + 4}" text-anchor="middle" class="cm-empty">空集：没有公共部分</text>`;
  return `<path d="M${AXIS.left} ${y}H${AXIS.right}" class="cm-track"/>
    <text x="8" y="${y + 4}" class="cm-label">${label}</text><text x="92" y="${y + 4}" text-anchor="end" class="cm-value ${kind}">${text}</text>${body}`;
}

// Vertical layout: the scale, one block per case, then the union. The picture grows as steps are revealed.
const TOP = 40;
const BLOCK = 112;
const HEIGHT = TOP + CASES.length * BLOCK + 64;
const visibleHeight = step => step === 0 ? 32 : step > CASES.length ? HEIGHT : TOP + step * BLOCK + 4;

function figure() {
  const [top, block, height] = [TOP, BLOCK, HEIGHT];
  const cases = CASES.map((c, i) => {
    const y = top + i * block;
    return `<g class="cm-step" data-cm-step="${i + 1}">
      <text x="8" y="${y + 22}" class="cm-head">${c.name}　${c.where}</text>
      ${row(y + 44, '前提', c.premiseText, c.premise, 'premise')}
      ${row(y + 68, '解出', c.solvedText, c.solved, 'solved')}
      ${row(y + 92, '取交集', c.resultText, c.result, 'result')}
    </g>`;
  }).join('');
  const y = top + CASES.length * block;
  return `<svg class="cm-graph" viewBox="0 0 360 ${height}" role="img" aria-labelledby="cm-graph-title">
    <title id="cm-graph-title">三种情况各自的前提、解出的范围和交集，最后取并集</title>
    ${TICKS.map(([m]) => `<path d="M${px(m)} 24V${height - 8}" class="cm-guide"/>`).join('')}
    <path d="M${AXIS.left - 6} 20H${AXIS.right + 6}" class="cm-scale"/>
    ${TICKS.map(([m, label, anchor = 'middle']) => `<path d="M${px(m)} 16V24" class="cm-scale"/><text x="${tickX(m, anchor)}" y="12" text-anchor="${anchor}" class="cm-tick">${label}</text>`).join('')}
    <text x="${AXIS.right + 10}" y="24" class="cm-tick m">m</text>
    ${cases}
    <g class="cm-step" data-cm-step="4">
      <text x="8" y="${y + 22}" class="cm-head union">合并：三种情况取并集</text>
      ${row(y + 44, '并集', UNION.text, UNION.set, 'union')}
    </g>
  </svg>`;
}

export default {
  stylesheet: new URL('case-merge.css?v=1', import.meta.url).href,

  render({tip}) {
    return `<p class="cm-core">分类讨论分两层：每种情况内部，解出的范围要和这种情况的前提同时成立，取交集；各种情况之间满足其一即可，取并集。</p>
    ${tip?.note ? `<p class="cm-problem"><span class="cm-badge">本题</span><span data-math-text>${problemNote(tip.note)}</span></p>` : ''}
    <div class="cm-explorer">
      <p class="cm-example" data-math-text>例：当 $x\\in[0,2]$ 时，$f(x)=x^2-2mx+1&gt;0$ 恒成立，求 $m$ 的取值范围。</p>
      ${figure()}
      <ol class="cm-steps" aria-live="polite">${STEPS.map((text, i) => `<li data-cm-text="${i}" data-math-text>${text}</li>`).join('')}</ol>
      <div class="cm-controls">
        <button type="button" data-cm-move="-1">上一步</button>
        <button type="button" data-cm-move="1" class="cm-next">下一步</button>
        <button type="button" data-cm-all>全部显示</button>
      </div>
    </div>
    <div class="cm-notes">
      <section class="cm-note">
        <h3>读到什么，取什么</h3>
        <table class="cm-signals">
          <tbody>
            <tr><th scope="row">“且”、同时、都要成立、方程组</th><td>交集：公共部分</td></tr>
            <tr><th scope="row">“或”、分情况、满足其一、综上</th><td>并集：合在一起</td></tr>
          </tbody>
        </table>
        <p data-math-text>端点：交集里两边都含才含，并集里有一边含就含。例如两个端点值都要满足，$g(-1)&gt;0$ 得 $x&lt;3$，$g(2)&gt;0$ 得 $x&gt;-1$，取交集 $-1&lt;x&lt;3$。</p>
      </section>
      <section class="cm-note">
        <h3>三个常见错误</h3>
        <ul>
          <li data-math-text>忘了与前提取交集：把情况③的 $m&lt;\\frac54$ 直接并进来，会得到 $m&lt;\\frac54$。</li>
          <li data-math-text>某种情况全部满足时漏并：漏掉情况①，只剩 $0&lt;m&lt;1$。</li>
          <li data-math-text>系数为 $0$ 等退化情形单独算一种情况，成立时也要并进来。</li>
        </ul>
      </section>
    </div>`;
  },

  mount(root) {
    const last = STEPS.length - 1;
    let step = 0;
    const show = next => {
      step = Math.max(0, Math.min(last, next));
      for (const group of root.querySelectorAll('[data-cm-step]')) {
        const n = Number(group.dataset.cmStep);
        group.classList.toggle('cm-off', n > step);
        group.classList.toggle('cm-current', n === step);
      }
      for (const item of root.querySelectorAll('[data-cm-text]')) {
        const n = Number(item.dataset.cmText);
        item.hidden = n > step;
        item.classList.toggle('cm-current', n === step);
      }
      root.querySelector('.cm-graph').setAttribute('viewBox', `0 0 360 ${visibleHeight(step)}`);
      root.querySelector('[data-cm-move="-1"]').disabled = step === 0;
      root.querySelector('[data-cm-move="1"]').disabled = step === last;
      root.querySelector('[data-cm-all]').disabled = step === last;
    };
    for (const button of root.querySelectorAll('[data-cm-move]')) button.addEventListener('click', () => show(step + Number(button.dataset.cmMove)));
    root.querySelector('[data-cm-all]').addEventListener('click', () => show(last));
    show(0);
  },
};
