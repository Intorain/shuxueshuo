/* Separation of the parameter: a horizontal line y = parameter against h(x). */
export default {
  render: () => `
    <p class="method-core"><span class="method-tag">核心</span><span>把参数单独放到一边，问题就变成水平线 <span class="nowrap"><var>y</var> = 参数</span> 与函数 <var>h</var>(<var>x</var>) 比高低。</span></p>
    <section class="method-judge" aria-labelledby="method-separation-judge">
      <h3 class="method-judge-title" id="method-separation-judge"><span class="method-tag">判断</span>两个前提都满足，才用分离参数法</h3>
      <div class="method-signal">
        <span class="method-signal-tag">读题信号 · 第 06 题</span>
        “<math><mo>∀</mo></math><mark><math><mi>x</mi><mo>&lt;</mo><mn>0</mn></math></mark><math><mo separator="true">,</mo><mspace width="0.3em"/><msup><mi>x</mi><mn>2</mn></msup><mo>+</mo></math><mark><math><mi>a</mi><mi>x</mi></math></mark><math><mo>+</mo><mn>2</mn><mo>≥</mo><mn>0</mn></math>”为真命题，求实数 <var>a</var> 的取值范围。
        <ul class="method-signal-notes">
          <li>参数只出现在 <var>ax</var> 中：移项后除以 <var>x</var>，就能把 <var>a</var> 单独放到一边</li>
          <li><var>x</var> &lt; 0：除数符号确定，除以负数时不等号变向</li>
        </ul>
      </div>
      <ol class="method-checks">
        <li><span class="method-check-no" aria-hidden="true">1</span><b>参数能单独放到一边</b><small>已经分离，或移项后可以分离</small></li>
        <li><span class="method-check-no" aria-hidden="true">2</span><b>要除的式子，符号确定</b><small>不需要除，或需要除但符号确定；符号不定就不能直接除</small></li>
      </ol>
      <ul class="method-else">
        <li><span class="method-else-tag">不满足</span><span>除数符号不定（如第 02 题的 <span class="nowrap"><var>x</var><sup>2</sup> + 2<var>x</var> − 1</span>）</span><span aria-hidden="true">→</span><button class="method-switch" type="button" data-explain-open="method-discriminant"></button><button class="method-switch" type="button" data-explain-open="method-interval-extremum"></button></li>
      </ul>
    </section>
    <div class="method-figure">
      <svg class="method-graph" viewBox="0 0 300 160" role="img" aria-label="第 06 题 h(x) 等于负 x 减 x 分之 2 在 x 小于 0 时的图像，最低点为负根号 2、2 倍根号 2，水平线 y 等于 a 在最低点下方">
        <line class="g-axis" x1="20" y1="140" x2="290" y2="140"/>
        <line class="g-axis" x1="262" y1="6" x2="262" y2="146"/>
        <text class="g-math" x="282" y="134">x</text>
        <text class="g-math" x="268" y="16">y</text>
        <path class="g-curve" d="M46.0 32.3 L50.3 34.3 L54.6 36.2 L59.0 38.1 L63.3 40.0 L67.6 41.9 L71.9 43.8 L76.2 45.7 L80.6 47.6 L84.9 49.4 L89.2 51.3 L93.5 53.2 L97.8 55.0 L102.2 56.9 L106.5 58.7 L110.8 60.5 L115.1 62.3 L119.4 64.1 L123.8 65.9 L128.1 67.6 L132.4 69.4 L136.7 71.1 L141.0 72.8 L145.4 74.4 L149.7 76.1 L154.0 77.7 L158.3 79.2 L162.6 80.8 L167.0 82.2 L171.3 83.7 L175.6 85.0 L179.9 86.3 L184.2 87.5 L188.6 88.7 L192.9 89.7 L197.2 90.5 L201.5 91.2 L205.8 91.7 L210.2 91.9 L214.5 91.8 L218.8 91.3 L223.1 90.2 L227.4 88.3 L231.8 85.2 L236.1 80.5 L240.4 73.1 L244.7 61.0 L249.0 39.4"/>
        <line class="g-guide" x1="211.1" y1="92" x2="211.1" y2="140"/>
        <line class="g-alt" x1="30" y1="106" x2="256" y2="106"/>
        <circle class="g-dot" cx="211.1" cy="91.9" r="4"/>
        <text class="g-text ok" x="211" y="124" text-anchor="middle">最低点 2√2</text>
        <text class="g-text" x="211" y="155" text-anchor="middle">−√2</text>
        <text class="g-text alt" x="34" y="100">y = a，不高于最低点</text>
      </svg>
      <p class="method-graph-caption">第 06 题，<span class="nowrap"><var>h</var>(<var>x</var>) = −<var>x</var> − 2/<var>x</var></span>（<var>x</var> &lt; 0）：<span class="nowrap"><var>a</var> ≤ <var>h</var>(<var>x</var>)</span> 恒成立 ⇔ <span class="nowrap"><var>a</var> ≤ 2√2</span></p>
      <ul class="method-cases">
        <li><span class="method-case-tag">参数 ≤ <var>h</var>(<var>x</var>)</span><span class="method-case-arrow" aria-hidden="true">→</span><span>比 <var>h</var>(<var>x</var>) 的最小值</span></li>
        <li><span class="method-case-tag">参数 ≥ <var>h</var>(<var>x</var>)</span><span class="method-case-arrow" aria-hidden="true">→</span><span>比 <var>h</var>(<var>x</var>) 的最大值</span></li>
      </ul>
      <p class="method-pill">除以负数，不等号要变向</p>
    </div>
    <ol class="method-steps" aria-label="解题三步">
      <li><span class="method-step-no" aria-hidden="true">1</span><strong>分离参数</strong><span>看除数符号，定不等号方向</span></li>
      <li><span class="method-step-no" aria-hidden="true">2</span><strong>转化为最值条件</strong><span>≤ 比最小值，≥ 比最大值</span></li>
      <li><span class="method-step-no" aria-hidden="true">3</span><strong>求最值，查边界</strong><span>用图像、单调性或基本不等式</span></li>
    </ol>`,
};
