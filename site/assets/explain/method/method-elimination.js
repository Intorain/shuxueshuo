/* Elimination: solve the condition for one variable and substitute. */
export default {
  render: () => `
    <p class="method-core"><span class="method-tag">核心</span><span>用条件把一个变量表示成另一个，代入目标，二元变一元。</span></p>
    <div class="method-figure">
      <div class="method-template"><span class="method-node"><small>条件</small><b>二元等式</b></span><span class="method-arrow"><small>解出</small><i aria-hidden="true">→</i></span><span class="method-node"><small>表示</small><b><var>y</var> = <span class="hole" aria-hidden="true"></span></b></span><span class="method-arrow"><small>代入</small><i aria-hidden="true">→</i></span><span class="method-node"><small>目标</small><b>一元式</b></span></div>
      <p class="method-demo"><span class="method-demo-tag">第 16 题</span><span class="method-demo-body"><span class="method-demo-group"><math><mi>y</mi><mo>=</mo><mfrac><mrow><mn>7</mn><mo>−</mo><mi>x</mi></mrow><mrow><mi>x</mi><mo>+</mo><mn>2</mn></mrow></mfrac></math></span><span class="method-demo-group"><span class="op">⇒</span><math><mi>x</mi><mo>+</mo><mi>y</mi></math></span><span class="method-demo-group"><span class="op">=</span><span class="term square"><math><mi>x</mi><mo>+</mo><mn>2</mn></math></span><span class="op">+</span><span class="term circle"><math><mfrac><mrow><mn>9</mn></mrow><mrow><mi>x</mi><mo>+</mo><mn>2</mn></mrow></mfrac></math></span><span class="op">−</span><math><mn>3</mn></math></span></span></p>
      <p class="method-pill">消元后，剩下变量的范围跟着改写</p>
    </div>
    <ol class="method-steps" aria-label="解题三步">
      <li><span class="method-step-no" aria-hidden="true">1</span><strong>整理条件</strong><span>化简条件，解出一个变量</span></li>
      <li><span class="method-step-no" aria-hidden="true">2</span><strong>表示代入</strong><span>目标化成一元式，写出新范围</span></li>
      <li><span class="method-step-no" aria-hidden="true">3</span><strong>验证取等</strong><span>回代另一个变量检验</span></li>
    </ol>`,
};
