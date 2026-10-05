/* Direct AM-GM: two whole positive terms in the square and circle slots. */
export default {
  render: () => `
    <p class="method-core"><span class="method-tag">核心</span><span>比较的不是两个特定字母，而是两个完整的正项，整体放进方框、圆圈。</span></p>
    <div class="method-figure">
      <ul class="method-kinds" aria-label="可以作为完整正项的量">
        <li><span class="method-kind-label">正变量</span><math><mi>x</mi><mo>&gt;</mo><mn>0</mn></math></li>
        <li><span class="method-kind-label">正常数</span><math><mn>3</mn><mo>&gt;</mo><mn>0</mn></math></li>
        <li><span class="method-kind-label">完整表达式</span><math><mi>x</mi><mo>+</mo><mn>1</mn><mo>&gt;</mo><mn>0</mn></math></li>
        <li><span class="method-kind-label">函数值</span><math><msup><mn>2</mn><mi>a</mi></msup><mo>&gt;</mo><mn>0</mn></math></li>
      </ul>
      <p class="method-kinds-note">都可以整体放进 <span class="mini-slot square" aria-label="方框"></span> 和 <span class="mini-slot circle" aria-label="圆圈"></span></p>
      <div class="method-formula" role="img" aria-label="方框加圆圈，大于等于 2 倍根号下方框乘圆圈">
        <span class="slot square"></span><span class="op">+</span><span class="slot circle"></span><span class="op">≥</span><span class="op coef">2</span><span class="radical"><svg class="radical-sign" viewBox="0 0 20 60" preserveAspectRatio="none" aria-hidden="true"><path d="M1 36 7 31 13 58 19.5 1.2" fill="none" stroke="currentColor" stroke-width="2.4" vector-effect="non-scaling-stroke" stroke-linejoin="round"/></svg><span class="radicand"><span class="slot square small"></span><span class="op dot">·</span><span class="slot circle small"></span></span></span>
      </div>
      <ul class="method-cases">
        <li><span class="method-case-tag">定积</span><span><span class="mini-slot square" aria-label="方框"></span> · <span class="mini-slot circle" aria-label="圆圈"></span> 为定值</span><span class="method-case-arrow" aria-hidden="true">→</span><span>和有最小值</span></li>
        <li><span class="method-case-tag">定和</span><span><span class="mini-slot square" aria-label="方框"></span> + <span class="mini-slot circle" aria-label="圆圈"></span> 为定值</span><span class="method-case-arrow" aria-hidden="true">→</span><span>积有最大值</span></li>
      </ul>
      <p class="method-pill">取等 <span aria-hidden="true">⇔</span><span class="visually-hidden">当且仅当</span> <span class="mini-slot square" aria-label="方框"></span> = <span class="mini-slot circle" aria-label="圆圈"></span></p>
    </div>
    <ol class="method-steps" aria-label="解题三步">
      <li><span class="method-step-no" aria-hidden="true">1</span><strong>识别正项</strong><span>正变量、正常数、完整表达式或函数值，<span class="nowrap">整体 &gt; 0</span></span></li>
      <li><span class="method-step-no" aria-hidden="true">2</span><strong>代入基本不等式</strong><span><span class="mini-slot square" aria-label="方框"></span> 与 <span class="mini-slot circle" aria-label="圆圈"></span> 同步替换</span></li>
      <li><span class="method-step-no" aria-hidden="true">3</span><strong>验证取等</strong><span><span class="mini-slot square" aria-label="方框"></span> = <span class="mini-slot circle" aria-label="圆圈"></span> 能否成立</span></li>
    </ol>`,
};
