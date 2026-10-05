/* Substitution: treat a whole denominator as a new variable. */
import {problemNote} from '../shared/html.js?v=1';

export default {
  render: ({tip}) => `
    <p class="method-core"><span class="method-tag">核心</span><span>完整分母看成一个整体，令 <var>u</var> 换元，条件、目标、范围一起改写。</span></p>
    ${tip?.note ? `<p class="method-problem"><span class="method-problem-badge">本题</span><span data-math-text>${problemNote(tip.note)}</span></p>` : ''}
    <div class="method-figure">
      <div class="method-template"><span class="method-node"><small>完整分母</small><b><span class="hole-frac"><span>1</span><span class="hole" aria-hidden="true"></span></span></b></span><span class="method-arrow"><small>令</small><i aria-hidden="true">→</i></span><span class="method-node"><small>换元</small><b><var>u</var> = <span class="hole" aria-hidden="true"></span></b></span></div>
      <p class="method-demo"><span class="method-demo-tag">第 12 题</span><span class="method-demo-body"><span class="method-demo-group"><span class="term square"><math><mi>u</mi></math></span><span class="op">=</span><math><mn>2</mn><mi>m</mi><mo>+</mo><mn>1</mn></math><span class="op">，</span></span><span class="method-demo-group"><span class="term circle"><math><mi>v</mi></math></span><span class="op">=</span><math><mi>n</mi><mo>+</mo><mn>1</mn></math></span><span class="method-demo-group"><span class="op">⇒</span><span class="term square"><math><mi>u</mi></math></span><span class="op">+</span><span class="term circle"><math><mi>v</mi></math></span><span class="op">=</span><math><mn>8</mn></math></span></span></p>
      <p class="method-pill">换元后回到定和、配齐次等熟悉结构</p>
    </div>
    <ol class="method-steps" aria-label="解题三步">
      <li><span class="method-step-no" aria-hidden="true">1</span><strong>识别结构</strong><span>完整分母当作一个整体</span></li>
      <li><span class="method-step-no" aria-hidden="true">2</span><strong>同步改写</strong><span>条件、目标、范围一起换</span></li>
      <li><span class="method-step-no" aria-hidden="true">3</span><strong>验证取等</strong><span>回代原变量检验</span></li>
    </ol>`,
};
