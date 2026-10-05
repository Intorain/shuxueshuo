/* Sum and product: symmetric conditions in s = x + y and p = xy. */
export default {
  render: () => `
    <p class="method-core"><span class="method-tag">核心</span><span>交换 <var>x</var>、<var>y</var> 后条件和目标都不变，就只研究和 <var>s</var> 与积 <var>p</var>，再用 <span class="nowrap"><var>s</var><sup>2</sup> ≥ 4<var>p</var></span> 消元。</span></p>
    <div class="method-figure">
      <div class="method-template"><span class="method-node"><small>交换</small><b><span class="nowrap"><var>x</var> ↔ <var>y</var></span></b></span><span class="method-arrow"><i aria-hidden="true">→</i></span><span class="method-node"><small>条件、目标</small><b>都不变</b></span><span class="method-arrow"><i aria-hidden="true">→</i></span><span class="method-node"><small>和积换元</small><b class="wrap"><span class="nowrap"><var>s</var> = <var>x</var> + <var>y</var>，</span><span class="nowrap"><var>p</var> = <var>xy</var></span></b></span></div>
      <p class="method-demo"><span class="method-demo-tag">第 28 题</span><span class="method-demo-body"><span class="method-demo-group"><span class="term plain"><math><msup><mi>s</mi><mn>2</mn></msup><mo>−</mo><mn>3</mn><mi>p</mi><mo>=</mo><mn>1</mn></math></span><span class="op">＋</span><span class="term plain"><math><msup><mi>s</mi><mn>2</mn></msup><mo>≥</mo><mn>4</mn><mi>p</mi></math></span></span><span class="method-demo-group"><span class="op">⇒</span><math><msup><mi>s</mi><mn>2</mn></msup><mo>≤</mo><mn>4</mn></math></span></span></p>
      <p class="method-pill"><span class="nowrap"><var>s</var><sup>2</sup> ≥ 4<var>p</var></span> 来自 <span class="nowrap">(<var>x</var> − <var>y</var>)<sup>2</sup> ≥ 0</span></p>
    </div>
    <ol class="method-steps" aria-label="解题三步">
      <li><span class="method-step-no" aria-hidden="true">1</span><strong>交换检验</strong><span>条件、目标分别交换 <var>x</var>、<var>y</var></span></li>
      <li><span class="method-step-no" aria-hidden="true">2</span><strong>和积换元</strong><span><span class="nowrap"><var>s</var> = <var>x</var> + <var>y</var></span>，<span class="nowrap"><var>p</var> = <var>xy</var></span></span></li>
      <li><span class="method-step-no" aria-hidden="true">3</span><strong>验证取等</strong><span>取等时 <var>x</var> = <var>y</var> 能否成立</span></li>
    </ol>`,
};
