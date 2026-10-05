/* Fraction splitting: divide by the denominator, or take the reciprocal first. */
import {problemNote} from '../shared/html.js?v=1';

export default {
  render: ({tip}) => `
    <p class="method-core"><span class="method-tag">核心</span><span>分子次数高，就按分母整体拆项；分子次数低，先取倒数再拆。</span></p>
    ${tip?.note ? `<p class="method-problem"><span class="method-problem-badge">本题</span><span data-math-text>${problemNote(tip.note)}</span></p>` : ''}
    <div class="method-figure">
      <p class="method-demo"><span class="method-demo-tag">分子次数高</span><span class="method-demo-body"><span class="method-demo-group"><math><mfrac><mrow><msup><mi>x</mi><mn>2</mn></msup><mo>+</mo><mn>3</mn><mi>x</mi><mo>+</mo><mn>6</mn></mrow><mrow><mi>x</mi><mo>+</mo><mn>1</mn></mrow></mfrac></math></span><span class="method-demo-group"><span class="op">=</span><span class="term square"><math><mi>x</mi><mo>+</mo><mn>1</mn></math></span><span class="op">+</span><span class="term circle"><math><mfrac><mrow><mn>4</mn></mrow><mrow><mi>x</mi><mo>+</mo><mn>1</mn></mrow></mfrac></math></span><span class="op">+</span><math><mn>1</mn></math></span></span></p>
      <p class="method-demo"><span class="method-demo-tag">分子次数低</span><span class="method-demo-body"><span class="method-demo-group"><math><mfrac><mrow><mn>1</mn></mrow><mrow><mi>y</mi></mrow></mfrac></math><span class="op">=</span><math><mfrac><mrow><msup><mi>x</mi><mn>2</mn></msup><mo>+</mo><mn>4</mn></mrow><mrow><mn>2</mn><mi>x</mi></mrow></mfrac></math></span><span class="method-demo-group"><span class="op">=</span><span class="term square"><math><mfrac><mrow><mi>x</mi></mrow><mrow><mn>2</mn></mrow></mfrac></math></span><span class="op">+</span><span class="term circle"><math><mfrac><mrow><mn>2</mn></mrow><mrow><mi>x</mi></mrow></mfrac></math></span></span></span></p>
      <p class="method-pill">拆出的两项 <span class="nowrap"><span class="mini-slot square" aria-label="方框"></span> · <span class="mini-slot circle" aria-label="圆圈"></span></span> 为定值</p>
    </div>
    <ol class="method-steps" aria-label="解题三步">
      <li><span class="method-step-no" aria-hidden="true">1</span><strong>比较次数</strong><span>分子高就分离，低则先取倒数</span></li>
      <li><span class="method-step-no" aria-hidden="true">2</span><strong>按分母拆项</strong><span>拆成 <span class="nowrap"><span class="mini-slot square" aria-label="方框"></span> + <span class="mini-slot circle" aria-label="圆圈"></span> + 常数</span></span></li>
      <li><span class="method-step-no" aria-hidden="true">3</span><strong>验证取等</strong><span><span class="mini-slot square" aria-label="方框"></span> = <span class="mini-slot circle" aria-label="圆圈"></span> 且在范围内</span></li>
    </ol>`,
};
