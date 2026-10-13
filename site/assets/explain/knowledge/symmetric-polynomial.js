/* Symmetric polynomials in two variables: swap x and y to test, then write the expression with s = x + y and p = xy. Purely local. */
import {escapeHtml as escape, problemNote} from '../shared/html.js?v=1';

const EXPRS = [
  {key: 'quad', label: '$x^2+y^2-xy$', swapped: '$y^2+x^2-yx$', same: true, sp: '$(x+y)^2-3xy=s^2-3p$'},
  {key: 'sum', label: '$x+y$', swapped: '$y+x$', same: true, sp: '$s$'},
  {key: 'cube', label: '$x^3+y^3$', swapped: '$y^3+x^3$', same: true, sp: '$(x+y)^3-3xy(x+y)=s^3-3sp$'},
  {key: 'recip', label: '$\\frac1x+\\frac1y$', swapped: '$\\frac1y+\\frac1x$', same: true, sp: '$\\frac{x+y}{xy}=\\frac sp$'},
  {key: 'scaled', label: '$x^2+4y^2-2xy$', swapped: '$y^2+4x^2-2yx$', same: false, sp: '$4y^2=(2y)^2$，$2xy=x\\cdot2y$：令 $a=x$，$b=2y$，得 $a^2+b^2-ab=s^2-3p$（$s=a+b$，$p=ab$）'},
  {key: 'linear', label: '$\\frac x2+y$', swapped: '$\\frac y2+x$', same: false, sp: '同样令 $a=x$，$b=2y$：$\\frac x2+y=\\frac{a+b}2=\\frac s2$'},
];
const RULES = [
  ['$x^2+y^2$', '$s^2-2p$'],
  ['$(x-y)^2$', '$s^2-4p$'],
  ['$x^3+y^3$', '$s^3-3sp$'],
  ['$x^2y+xy^2$', '$sp$'],
  ['$\\frac1x+\\frac1y$', '$\\frac sp$'],
];

const swapper = () => `<div class="sp-explorer">
      <p class="sp-ask">选一个式子，交换 x、y，看它变不变：</p>
      <div class="sp-picks" role="group" aria-label="式子">
        ${EXPRS.map(expr => `<button type="button" data-sp-pick="${expr.key}" aria-pressed="false"><span data-math-text>${expr.label}</span></button>`).join('')}
      </div>
      ${EXPRS.map(expr => `<section class="sp-panel" data-sp-panel="${expr.key}" hidden>
        <dl class="sp-swap">
          <div><dt>原式</dt><dd data-math-text>${expr.label}</dd></div>
          <div><dt>交换 x、y</dt><dd data-math-text>${expr.swapped}</dd></div>
        </dl>
        <p class="sp-verdict ${expr.same ? 'same' : 'changed'}">${expr.same ? '不变：是对称式' : '改变：不是对称式，先换元构造对称'}</p>
        <p class="sp-result" data-math-text>${expr.sp}</p>
      </section>`).join('')}
    </div>`;

const explorer = () => `${swapper()}
    <table class="sp-table">
      <caption>常用的改写</caption>
      <thead><tr><th scope="col">对称式</th><th scope="col">用 s、p 表示</th></tr></thead>
      <tbody>${RULES.map(([expr, sp]) => `<tr><td data-math-text>${expr}</td><td data-math-text>${sp}</td></tr>`).join('')}</tbody>
    </table>`;

export default {
  stylesheet: new URL('symmetric-polynomial.css?v=1', import.meta.url).href,

  figure: explorer,

  swap: swapper,

  render({tip}) {
    return `<p class="sp-core" data-math-text>交换 $x$、$y$ 后不变的二元多项式叫对称多项式，它都能写成 $s=x+y$、$p=xy$ 的多项式，例如 $x^2+y^2=s^2-2p$。先交换检验，再改写。</p>
    ${tip?.note ? `<p class="sp-problem"><span class="sp-badge">本题</span><span data-math-text>${problemNote(tip.note)}</span></p>` : ''}
    ${explorer()}
    <div class="sp-notes">
      <section class="sp-note">
        <h3>为什么都能写成 s、p</h3>
        <p data-math-text>$x$、$y$ 是方程 $t^2-st+p=0$ 的两个根。交换 $x$、$y$ 不改变这个方程，所以对称式的值只由 $s$、$p$ 决定。</p>
      </section>
      <section class="sp-note">
        <h3>s、p 不能随便取</h3>
        <p data-math-text>实数 $x$、$y$ 一定满足 $s^2\\ge4p$；$x$、$y$ 都是正数时还要 $s&gt;0$、$p&gt;0$。求范围时要把这些条件带上。</p>
        <p>见 <button type="button" class="sp-link" data-explain-open="square-nonnegative"></button>。</p>
      </section>
      <section class="sp-note">
        <h3>不对称：先换元</h3>
        <p data-math-text>系数不一样时，把带系数的整体看成新变量，例如 $2y$ 记为 $b$，换完再交换检验。</p>
        <p>见 <button type="button" class="sp-link" data-explain-open="method-sum-product"></button>。</p>
      </section>
    </div>`;
  },

  mount(root, {tip}) {
    const pick = key => {
      for (const button of root.querySelectorAll('[data-sp-pick]')) button.setAttribute('aria-pressed', String(button.dataset.spPick === key));
      for (const panel of root.querySelectorAll('[data-sp-panel]')) panel.hidden = panel.dataset.spPanel !== key;
    };
    for (const button of root.querySelectorAll('[data-sp-pick]')) button.addEventListener('click', () => pick(button.dataset.spPick));
    pick(tip?.case === 'construct' ? 'scaled' : 'quad');
  },
};
