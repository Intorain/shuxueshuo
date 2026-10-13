/* Discriminant method: the whole parabola against the x-axis, by opening direction and Δ. */
const figure = () => `<div class="method-figure">
      <ul class="method-graphs" aria-label="开口向上时，抛物线与横轴的三种位置">
        <li><svg viewBox="0 0 120 84" aria-hidden="true"><line class="g-axis" x1="6" y1="60" x2="114" y2="60"/><path class="g-curve" d="M14 8 Q60 92 106 8"/></svg><b>Δ &lt; 0</b><span>不相交 <span class="ok-mark">✓</span></span></li>
        <li><svg viewBox="0 0 120 84" aria-hidden="true"><line class="g-axis" x1="6" y1="60" x2="114" y2="60"/><path class="g-curve" d="M14 8 Q60 112 106 8"/><circle class="g-dot" cx="60" cy="60" r="3.6"/></svg><b>Δ = 0</b><span>相切，允许取等时 <span class="ok-mark">✓</span></span></li>
        <li class="bad"><svg viewBox="0 0 120 84" aria-hidden="true"><line class="g-axis" x1="6" y1="60" x2="114" y2="60"/><line class="g-bad" x1="37.7" y1="60" x2="82.3" y2="60"/><path class="g-curve" d="M14 8 Q60 144 106 8"/></svg><b>Δ &gt; 0</b><span>穿过横轴 <span class="bad-mark">✗</span></span></li>
      </ul>
      <p class="method-graph-caption">开口向上时，要 <math><mi>f</mi><mo stretchy="false">(</mo><mi>x</mi><mo stretchy="false">)</mo><mo>≥</mo><mn>0</mn></math> 恒成立，图像不能到横轴下方</p>
      <ul class="method-cases">
        <li><span class="method-case-tag">恒 ≥ 0</span><span>开口向上</span><span class="method-case-arrow" aria-hidden="true">+</span><span>Δ ≤ 0</span></li>
        <li><span class="method-case-tag">恒 ≤ 0</span><span>开口向下</span><span class="method-case-arrow" aria-hidden="true">+</span><span>Δ ≤ 0</span></li>
      </ul>
      <p class="method-pill">不等号不带等号（&gt;、&lt;）时，只取 Δ &lt; 0</p>
    </div>`;

export default {
  figure: () => figure(),

  render: () => `
    <p class="method-core"><span class="method-tag">核心</span><span>对全体实数恒成立，就看整条抛物线与横轴的位置，用开口方向和判别式 Δ 表示出来。</span></p>
    <section class="method-judge" aria-labelledby="method-discriminant-judge">
      <h3 class="method-judge-title" id="method-discriminant-judge"><span class="method-tag">判断</span>两个前提都满足，才用判别式法</h3>
      <div class="method-signal">
        <span class="method-signal-tag">读题信号 · 第 02 题</span>
        已知不等式 <mark><math><mi>k</mi><msup><mi>x</mi><mn>2</mn></msup></math></mark><math><mo>+</mo><mn>2</mn><mi>k</mi><mi>x</mi><mo>−</mo><mo stretchy="false">(</mo><mi>k</mi><mo>+</mo><mn>2</mn><mo stretchy="false">)</mo><mo>&lt;</mo><mn>0</mn></math> <mark>恒成立</mark>，求实数 <var>k</var> 的取值范围。
        <ul class="method-signal-notes">
          <li>没写 <var>x</var> 的范围：<var>x</var> 取全体实数</li>
          <li><var>x</var><sup>2</sup> 的系数是 <var>k</var>：可能为 0，要先单独讨论</li>
        </ul>
      </div>
      <ol class="method-checks">
        <li><span class="method-check-no" aria-hidden="true">1</span><b><var>x</var> 的取值范围：全体实数</b><small>题目没写范围，或写“对任意实数 <var>x</var>”</small></li>
        <li><span class="method-check-no" aria-hidden="true">2</span><b><var>x</var><sup>2</sup> 的系数：确定非零</b><small>含参数、可能为零时，先讨论系数为 0 的情形，再用判别式</small></li>
      </ol>
      <ul class="method-else">
        <li><span class="method-else-tag">不满足</span><span><var>x</var> 只在某个区间上</span><span aria-hidden="true">→</span><button class="method-switch" type="button" data-explain-open="method-interval-extremum"></button><button class="method-switch" type="button" data-explain-open="method-separation"></button></li>
      </ul>
    </section>
    ${figure()}
    <ol class="method-steps" aria-label="解题三步">
      <li><span class="method-step-no" aria-hidden="true">1</span><strong>定开口</strong><span>系数可能为 0 先讨论，再看开口方向</span></li>
      <li><span class="method-step-no" aria-hidden="true">2</span><strong>位置化成 Δ</strong><span>不相交 Δ &lt; 0，允许相切 Δ ≤ 0</span></li>
      <li><span class="method-step-no" aria-hidden="true">3</span><strong>解范围，查边界</strong><span>边界值代回原不等式检验</span></li>
    </ol>`,
};
