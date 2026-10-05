/* Homogenising: multiply by the condition equal to 1 so only ratios remain — the whole target, or only the part whose degree is off. */
import {problemNote} from '../shared/html.js?v=1';

const TABS = [['whole', '整体乘入'], ['local', '只乘一部分']];

export default {
  stylesheet: new URL('method-homogeneous.css?v=1', import.meta.url).href,

  render: ({tip}) => `
    <p class="method-core"><span class="method-tag">核心</span><span>把值为 1 的条件式乘给次数不对的部分，配成 0 次，只剩比值，比值的积为定值。</span></p>
    ${tip?.note ? `<p class="method-problem"><span class="method-problem-badge">本题</span><span data-math-text>${problemNote(tip.note)}</span></p>` : ''}
    <div class="mh-tabs" role="tablist" aria-label="乘给哪一部分">
      ${TABS.map(([key, label]) => `<button type="button" role="tab" data-mh-tab="${key}" aria-selected="false">${label}</button>`).join('')}
    </div>
    <div class="method-figure" data-mh-panel="whole">
      <div class="method-template"><span class="method-node"><small>目标</small><b><var>m</var> 次</b></span><span class="op">×</span><span class="method-node"><small>条件式 = 1</small><b><var>n</var> 次</b></span><span class="method-arrow"><i aria-hidden="true">→</i></span><span class="method-node"><small>0 次式</small><b><var>m</var> + <var>n</var> = 0</b></span></div>
      <p class="method-demo"><span class="method-demo-tag">第 10 题</span><span class="method-demo-body"><span class="method-demo-group"><math><mo>(</mo><mfrac><mrow><mn>5</mn></mrow><mrow><mi>x</mi></mrow></mfrac><mo>+</mo><mfrac><mrow><mn>4</mn></mrow><mrow><mi>y</mi></mrow></mfrac><mo>)</mo><mo>(</mo><mi>x</mi><mo>+</mo><mn>5</mn><mi>y</mi><mo>)</mo></math></span><span class="method-demo-group"><span class="op">=</span><math><mn>25</mn></math><span class="op">+</span><span class="term square"><math><mfrac><mrow><mn>25</mn><mi>y</mi></mrow><mrow><mi>x</mi></mrow></mfrac></math></span><span class="op">+</span><span class="term circle"><math><mfrac><mrow><mn>4</mn><mi>x</mi></mrow><mrow><mi>y</mi></mrow></mfrac></math></span></span></span></p>
      <p class="method-pill">只剩比值：<span class="nowrap"><span class="mini-slot square" aria-label="方框"></span> · <span class="mini-slot circle" aria-label="圆圈"></span> = 100</span> 为定值</p>
    </div>
    <div class="mh-local" data-mh-panel="local" hidden>
      <p class="mh-ask" data-math-text>各项次数不同时，逐项数次数，只给缺次数的项乘。例：$x,y&gt;0$，$x+y=1$，求 $\\frac1x+\\frac xy$ 的最小值。</p>
      <div class="mh-rows">
        <div class="mh-row"><span class="mh-term" data-math-text>$\\frac1x$</span><span class="mh-deg">−1 次</span><span class="mh-op" data-math-text>$\\times(x+y)$</span><span class="mh-out" data-math-text>$1+\\frac yx$</span><span class="mh-deg is-zero">0 次</span></div>
        <div class="mh-row"><span class="mh-term" data-math-text>$\\frac xy$</span><span class="mh-deg is-zero">0 次</span><span class="mh-op">不乘</span><span class="mh-out" data-math-text>$\\frac xy$</span><span class="mh-deg is-zero">0 次</span></div>
      </div>
      <p class="mh-result" data-math-text>原式 $=1+\\frac yx+\\frac xy\\ge1+2=3$，$x=y=\\frac12$ 时取等。</p>
      <p class="mh-wrong"><span class="mh-wrong-tag">整体乘</span><span data-math-text>$\\left(\\frac1x+\\frac xy\\right)(x+y)=1+\\frac yx+\\frac{x^2}y+x$：本来是 0 次的 $\\frac xy$ 被乘成了一次，次数又不齐。</span></p>
    </div>
    <ol class="method-steps" aria-label="解题三步">
      <li><span class="method-step-no" aria-hidden="true">1</span><strong>配次数</strong><span>给次数不对的部分乘入值为 1 的条件式，<span class="nowrap"><var>m</var> + <var>n</var> = 0</span></span></li>
      <li><span class="method-step-no" aria-hidden="true">2</span><strong>展开圈出正项</strong><span>两个比值项 <span class="mini-slot square" aria-label="方框"></span>、<span class="mini-slot circle" aria-label="圆圈"></span></span></li>
      <li><span class="method-step-no" aria-hidden="true">3</span><strong>检查定积</strong><span><span class="mini-slot square" aria-label="方框"></span> · <span class="mini-slot circle" aria-label="圆圈"></span> 为定值，再验证取等</span></li>
    </ol>`,

  mount(root, {tip}) {
    const pick = key => {
      for (const button of root.querySelectorAll('[data-mh-tab]')) button.setAttribute('aria-selected', String(button.dataset.mhTab === key));
      for (const panel of root.querySelectorAll('[data-mh-panel]')) panel.hidden = panel.dataset.mhPanel !== key;
    };
    for (const button of root.querySelectorAll('[data-mh-tab]')) button.addEventListener('click', () => pick(button.dataset.mhTab));
    pick(tip?.case === 'local' ? 'local' : 'whole');
  },
};
