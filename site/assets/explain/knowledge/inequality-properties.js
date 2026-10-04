/* Properties of inequalities: what one operation on both sides does to the order of two numbers. Purely local. */
import {escapeHtml as escape, problemNote} from '../shared/html.js?v=1';

// Each operation maps two numbers on the upper line to the lower line; crossing connectors mean the order flipped.
const OPS = [
  {key: 'add', label: '两边加同一个数', domain: [-0.5, 6], before: [[1, 'a = 1'], [3, 'b = 3']], after: [[3, 'a+2 = 3'], [5, 'b+2 = 5']],
    example: '$1&lt;3$，两边加 $2$', verdict: 'keep', rule: '$a&lt;b\\Rightarrow a+c&lt;b+c$', why: '整体平移，先后顺序不变；减去同一个数也一样。'},
  {key: 'mulpos', label: '两边乘正数', domain: [-0.5, 7], before: [[1, 'a = 1'], [3, 'b = 3']], after: [[2, '2a = 2'], [6, '2b = 6']],
    example: '$1&lt;3$，两边乘 $2$', verdict: 'keep', rule: '$a&lt;b,\\ c&gt;0\\Rightarrow ac&lt;bc$', why: '从原点向外拉伸，顺序不变；除以正数也一样。'},
  {key: 'mulneg', label: '两边乘负数', domain: [-7, 4], before: [[1, 'a = 1'], [3, 'b = 3']], after: [[-2, '−2a = −2'], [-6, '−2b = −6']],
    example: '$1&lt;3$，两边乘 $-2$', verdict: 'flip', rule: '$a&lt;b,\\ c&lt;0\\Rightarrow ac&gt;bc$', why: '先翻到原点另一侧，顺序颠倒；除以负数也一样。'},
  {key: 'recip', label: '两边取倒数', domain: [-0.5, 3.5], before: [[1, 'a = 1'], [3, 'b = 3']], after: [[1, '1/a = 1'], [1 / 3, '1/b = 1/3']],
    example: '$1&lt;3$，两边取倒数', verdict: 'flip', rule: '$a,b$ 同号且 $a&lt;b\\Rightarrow \\frac1a&gt;\\frac1b$', why: '两边同号才变向；一正一负时不变，如 $-1&lt;2$，$-1&lt;\\frac12$。'},
  {key: 'square', label: '两边平方', domain: [-4, 10], before: [[-3, 'a = −3'], [1, 'b = 1']], after: [[9, 'a² = 9'], [1, 'b² = 1']],
    example: '$-3&lt;1$，两边平方', verdict: 'unsure', rule: '$0\\le a&lt;b\\Rightarrow a^2&lt;b^2$', why: '两边都非负才能直接平方；这里 $-3&lt;1$，平方后 $9&gt;1$。'},
  {key: 'sub', label: '两个不等式相减', domain: [-3, 4], before: [[1, 'a = 1'], [3, 'b = 3']], after: [[1, 'a−c = 1'], [-2, 'b−d = −2']],
    example: '$1&lt;3$ 与 $0&lt;5$ 相减', verdict: 'unsure', rule: '同向相加可以：$a&lt;b,\\ c&lt;d\\Rightarrow a+c&lt;b+d$', why: '相减不行：$1-0&gt;3-5$。要减，先把 $c&lt;d$ 变成 $-d&lt;-c$，再同向相加。'},
];
const VERDICTS = {keep: '方向不变', flip: '方向改变', unsure: '不一定'};
const LINES = {top: 34, bottom: 104};
const X = [64, 326];

function picture(op) {
  const at = x => X[0] + (x - op.domain[0]) / (op.domain[1] - op.domain[0]) * (X[1] - X[0]);
  const ticks = Array.from({length: Math.floor(op.domain[1]) - Math.ceil(op.domain[0]) + 1}, (_, i) => Math.ceil(op.domain[0]) + i);
  const axis = y => `<path d="M${X[0] - 6} ${y}H${X[1] + 6}" class="ip-line"/>${ticks.map(t => `<path d="M${at(t)} ${y - (t ? 3 : 6)}V${y + (t ? 3 : 6)}" class="ip-tick${t ? '' : ' zero'}"/>`).join('')}`;
  const labels = (points, y, dy) => {
    const order = [...points].sort((p, q) => p[0] - q[0]);
    return points.map(([x, text], i) => {
      const left = order[0][0] === x;
      return `<circle cx="${at(x)}" cy="${y}" r="5.5" class="ip-dot p${i}"/><text x="${at(x) + (left ? -7 : 7)}" y="${y + dy}" text-anchor="${left ? 'end' : 'start'}" class="ip-label p${i}">${text}</text>`;
    }).join('');
  };
  const links = op.before.map(([x], i) => `<path d="M${at(x)} ${LINES.top + 6}L${at(op.after[i][0])} ${LINES.bottom - 6}" class="ip-connector p${i}"/>`).join('');
  return `<svg class="ip-graph" viewBox="0 0 340 132" role="img" aria-label="${op.label}：上面是原来的两个数，下面是运算后的两个数">
    <text x="8" y="${LINES.top + 4}" class="ip-row">原来</text>
    <text x="8" y="${LINES.bottom + 4}" class="ip-row">之后</text>
    ${axis(LINES.top)}${axis(LINES.bottom)}
    <text x="${at(0)}" y="${LINES.top + 20}" text-anchor="middle" class="ip-zero">0</text>
    ${links}
    ${labels(op.before, LINES.top, -11)}${labels(op.after, LINES.bottom, 21)}
  </svg>`;
}

export default {
  stylesheet: new URL('inequality-properties.css?v=1', import.meta.url).href,

  render({tip}) {
    return `<p class="ip-core">不等式两边做同一种运算，改变方向的只有两种：乘（除以）同一个负数，两边同号时取倒数。平方、相减、相除都不能直接做。</p>
    ${tip?.note ? `<p class="ip-problem"><span class="ip-badge">本题</span><span data-math-text>${problemNote(tip.note)}</span></p>` : ''}
    <div class="ip-explorer">
      <p class="ip-ask">选一种运算，看两个数的先后顺序变不变：</p>
      <div class="ip-ops" role="group" aria-label="运算">
        ${OPS.map((op, i) => `<button type="button" data-ip-op="${op.key}" aria-pressed="${i === 0}">${op.label}</button>`).join('')}
      </div>
      ${OPS.map((op, i) => `<section class="ip-panel" data-ip-panel="${op.key}"${i ? ' hidden' : ''}>
        <p class="ip-example"><span data-math-text>${op.example}</span><span class="ip-verdict ${op.verdict}">${VERDICTS[op.verdict]}</span></p>
        ${picture(op)}
        <p class="ip-rule"><span class="ip-tag">规则</span><span data-math-text>${op.rule}</span><small data-math-text>${op.why}</small></p>
      </section>`).join('')}
      <p class="ip-legend">连线交叉，说明两个数的先后颠倒了。</p>
    </div>
    <div class="ip-notes">
      <section class="ip-note">
        <h3>除以含字母的式子：先看它的符号</h3>
        <p data-math-text>$mx&lt;-x^2-4$ 两边除以 $x$：$x&gt;0$ 时得 $m&lt;-x-\\frac4x$；$x&lt;0$ 时要变向，得 $m&gt;-x-\\frac4x$；符号不确定就分类讨论。</p>
        <p>分离参数时的做法，见 <button type="button" class="ip-link" data-explain-open="method-separation"></button>。</p>
      </section>
      <section class="ip-note">
        <h3>同正取倒数：大的变小</h3>
        <p data-math-text>$x^2-x$ 在 $[2,3]$ 上从 $2$ 增大到 $6$，都是正数，所以 $\\frac1{x^2-x}$ 从 $\\frac12$ 减小到 $\\frac16$，最小值是 $\\frac16$。</p>
        <p>由单调性求最值，见 <button type="button" class="ip-link" data-explain-open="function-monotonicity"></button>。</p>
      </section>
      <section class="ip-note">
        <h3>相乘、相除</h3>
        <p data-math-text>两边都是正数的同向不等式可以相乘：$0&lt;a&lt;b$，$0&lt;c&lt;d\\Rightarrow ac&lt;bd$。不能相除：$2&lt;4$，$1&lt;4$，但 $\\frac21&gt;\\frac44$。</p>
      </section>
    </div>`;
  },

  mount(root) {
    const pick = key => {
      for (const button of root.querySelectorAll('[data-ip-op]')) button.setAttribute('aria-pressed', String(button.dataset.ipOp === key));
      for (const panel of root.querySelectorAll('[data-ip-panel]')) panel.hidden = panel.dataset.ipPanel !== key;
    };
    for (const button of root.querySelectorAll('[data-ip-op]')) button.addEventListener('click', () => pick(button.dataset.ipOp));
  },
};
