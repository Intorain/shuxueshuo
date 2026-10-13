/* Homogeneous expressions: count each term's degree, multiply to reach degree 0, and see that a degree-0 expression ignores scaling. Purely local. */
import {escapeHtml as escape, problemNote} from '../shared/html.js?v=1';

const K = {min: 0.5, max: 3, step: 0.1, value: 1};
const ONE_OVER_K = '<span class="he-frac"><span>1</span><span>k</span></span>';
// Values at (x, y) = (2k, k); each row's degree decides how it reacts to k.
const ROWS = [
  {expr: '$x+5y$', degree: '一次', value: k => 7 * k, scale: '变成 k 倍'},
  {expr: '$\\frac5x+\\frac4y$', degree: '负一次', value: k => 6.5 / k, scale: `变成 ${ONE_OVER_K}`},
  {expr: '$\\frac{25y}x+\\frac{4x}y$', degree: '零次', value: () => 20.5, scale: '不变'},
];
const MAX = 21;
const TERMS = [['$5x^{-1}$', '$-1$'], ['$\\frac ab=ab^{-1}$', '$0$'], ['$4xy$', '$2$'], ['$\\frac1{\\sqrt x}=x^{-\\frac12}$', '$-\\frac12$']];

function grid() {
  const left = [['$\\frac5x$', '−1'], ['$\\frac4y$', '−1']], top = [['$x$', '1'], ['$5y$', '1']];
  const cells = [['$5$', '$\\frac{25y}x$'], ['$\\frac{4x}y$', '$20$']];
  return `<table class="he-grid">
    <caption>负一次 × 一次：每个乘积都是零次</caption>
    <thead><tr><th scope="col">×</th>${top.map(([t, d]) => `<th scope="col"><span data-math-text>${t}</span><small>${d} 次</small></th>`).join('')}</tr></thead>
    <tbody>${left.map(([t, d], i) => `<tr><th scope="row"><span data-math-text>${t}</span><small>${d} 次</small></th>${cells[i].map(c => `<td><span data-math-text>${c}</span><small>0 次</small></td>`).join('')}</tr>`).join('')}</tbody>
  </table>`;
}

const explorer = () => `<ul class="he-terms" aria-label="数次数的例子">
      ${TERMS.map(([term, degree]) => `<li><span data-math-text>${term}</span><span class="he-degree" data-math-text>${degree} 次</span></li>`).join('')}
    </ul>
    ${grid()}
    <div class="he-explorer">
      <p class="he-ask" data-math-text>取 $x=2k$、$y=k$（比值 $\\frac yx$ 始终是 $\\frac12$），拖动 $k$，看三个式子怎样变：</p>
      <input class="he-slider" type="range" data-he-slider min="${K.min}" max="${K.max}" step="${K.step}" value="${K.value}" aria-label="放大倍数 k">
      <p class="he-k" aria-live="polite" data-he-k></p>
      <div class="he-rows">
        ${ROWS.map((row, i) => `<div class="he-row">
          <span class="he-expr" data-math-text>${row.expr}</span>
          <span class="he-tag">${row.degree}</span>
          <span class="he-bar"><i data-he-bar="${i}"></i></span>
          <span class="he-value" data-he-value="${i}"></span>
        </div>`).join('')}
      </div>
      <p class="he-legend">x、y 同时放大 k 倍：一次式变成 k 倍，负一次式变成 ${ONE_OVER_K}，零次式不变。</p>
    </div>`;

export default {
  stylesheet: new URL('homogeneous-expression.css?v=2', import.meta.url).href,

  figure: explorer,

  render({tip}) {
    return `<p class="he-core" data-math-text>一项的次数是各字母指数之和，数字系数不算。各项次数都相同的式子叫齐次式；相乘时次数相加，所以负一次式乘一次式得到零次式，零次齐次式的值只与 $x$、$y$ 的比值有关。</p>
    ${tip?.note ? `<p class="he-problem"><span class="he-badge">本题</span><span data-math-text>${problemNote(tip.note)}</span></p>` : ''}
    ${explorer()}
    <div class="he-notes">
      <section class="he-note">
        <h3>各项次数不同：只给缺的那部分乘</h3>
        <p data-math-text>$\\frac1a+\\frac ab$ 里 $\\frac1a$ 是负一次，$\\frac ab$ 已经是零次。条件 $2a+b=1$ 只乘给 $\\frac1a$：$\\frac{2a+b}a+\\frac ab=2+\\frac ba+\\frac ab$。</p>
        <p>见 <button type="button" class="he-link" data-explain-open="method-homogeneous"></button>。</p>
      </section>
      <section class="he-note">
        <h3>乘入的式子要等于 1</h3>
        <p data-math-text>条件是 $a+b=2$ 时，乘入 $\\frac{a+b}2$；条件是 $\\frac1x+\\frac1y=3$ 时，乘入 $\\frac13\\left(\\frac1x+\\frac1y\\right)$。值不变，次数才能配。</p>
      </section>
      <section class="he-note">
        <h3>零次式化成一个比值</h3>
        <p data-math-text>$x,y&gt;0$ 时令 $t=\\frac yx&gt;0$，$\\frac{25y}x+\\frac{4x}y=25t+\\frac4t$，两项的积是定值 $100$，就能用基本不等式。</p>
        <p>见 <button type="button" class="he-link" data-explain-open="amgm-formula"></button>。</p>
      </section>
    </div>`;
  },

  mount(root) {
    const slider = root.querySelector('[data-he-slider]');
    const draw = () => {
      const k = Number(slider.value);
      root.querySelector('[data-he-k]').textContent = `k = ${k.toFixed(1)}：x = ${(2 * k).toFixed(1)}，y = ${k.toFixed(1)}`;
      ROWS.forEach((row, i) => {
        const value = row.value(k);
        root.querySelector(`[data-he-bar="${i}"]`).style.width = `${Math.min(100, value / MAX * 100)}%`;
        root.querySelector(`[data-he-value="${i}"]`).innerHTML = `${value.toFixed(2)}（${row.scale}）`;
      });
    };
    slider.addEventListener('input', draw);
    draw();
  },
};
