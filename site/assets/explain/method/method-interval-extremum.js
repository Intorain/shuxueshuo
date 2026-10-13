/* Interval extremum method: only the arc over the interval matters. */
const graph = tag => `<div class="method-figure">
      <svg class="method-graph" viewBox="0 0 300 140" role="img" aria-label="${tag} m 等于负 5.5 时，f(x) 在区间 1 到 2 上的一段全部在横轴下方，左端 f(1) 等于负 0.5 最高">
        <rect class="g-band" x="85" y="6" width="55" height="128" rx="3"/>
        <line class="g-axis" x1="10" y1="70" x2="290" y2="70"/>
        <line class="g-axis" x1="30" y1="4" x2="30" y2="136"/>
        <text class="g-math" x="282" y="64">x</text>
        <text class="g-text" x="85" y="64" text-anchor="middle">1</text>
        <text class="g-text" x="140" y="64" text-anchor="middle">2</text>
        <path class="g-faint" d="M30.0 14.0 L35.5 21.6 L41.0 28.8 L46.5 35.8 L52.0 42.6 L57.5 49.0 L63.0 55.2 L68.5 61.0 L74.0 66.6 L79.5 72.0 L85.0 77.0 M140.0 112.0 L145.5 114.0 L151.0 115.6 L156.5 117.0 L162.0 118.2 L167.5 119.0 L173.0 119.6 L178.5 119.8 L184.0 119.8 L189.5 119.6 L195.0 119.0 L200.5 118.2 L206.0 117.0 L211.5 115.6 L217.0 114.0 L222.5 112.0 L228.0 109.8 L233.5 107.2 L239.0 104.4 L244.5 101.4 L250.0 98.0 L255.5 94.4 L261.0 90.4 L266.5 86.2"/>
        <path class="g-curve" d="M85.0 77.0 L90.5 81.8 L96.0 86.2 L101.5 90.4 L107.0 94.4 L112.5 98.0 L118.0 101.4 L123.5 104.4 L129.0 107.2 L134.5 109.8 L140.0 112.0"/>
        <circle class="g-dot" cx="85" cy="77" r="4"/>
        <circle class="g-dot" cx="140" cy="112" r="4"/>
        <text class="g-text ok" x="78" y="94" text-anchor="end">最高 f(1) = −0.5</text>
        <text class="g-text" x="134" y="130" text-anchor="end">f(2) = −3</text>
      </svg>
      <p class="method-graph-caption">${tag}，<span class="nowrap"><var>m</var> = −5.5</span> 时：区间外有正有负不要紧，区间内最高点 f(1) &lt; 0</p>
      <ul class="method-cases">
        <li><span class="method-case-tag">恒 &lt; 0</span><span>区间上的最大值 &lt; 0</span></li>
        <li><span class="method-case-tag">恒 &gt; 0</span><span>区间上的最小值 &gt; 0</span></li>
      </ul>
      <p class="method-pill">最值在顶点还是端点，看对称轴与区间的位置</p>
    </div>`;

export default {
  figure: () => graph('例'),

  render: () => `
    <p class="method-core"><span class="method-tag">核心</span><span><var>x</var> 只在某个区间上取值，就只看这一段图像：最高点小于 0，整段都小于 0。</span></p>
    <section class="method-judge" aria-labelledby="method-interval-judge">
      <h3 class="method-judge-title" id="method-interval-judge"><span class="method-tag">判断</span>一个前提满足，就能用区间最值法</h3>
      <div class="method-signal">
        <span class="method-signal-tag">读题信号 · 第 04 题</span>
        当 <mark><math><mn>1</mn><mo>≤</mo><mi>x</mi><mo>≤</mo><mn>2</mn></math></mark> 时，不等式 <math><msup><mi>x</mi><mn>2</mn></msup><mo>+</mo><mi>m</mi><mi>x</mi><mo>+</mo><mn>4</mn><mo>&lt;</mo><mn>0</mn></math> 恒成立，求实数 <var>m</var> 的取值范围。
        <ul class="method-signal-notes">
          <li>只要求 <span class="nowrap">1 ≤ <var>x</var> ≤ 2</span>：只看区间上的那一段图像</li>
          <li>判别式管的是整条图像，这里用不上</li>
        </ul>
      </div>
      <ol class="method-checks">
        <li><span class="method-check-no" aria-hidden="true">1</span><b><var>x</var> 的取值范围：某个区间</b><small>如“当 1 ≤ <var>x</var> ≤ 2 时”“∀<var>x</var> &lt; 0”；开口方向不是前提，它决定最值在哪里取到</small></li>
      </ol>
      <ul class="method-else">
        <li><span class="method-else-tag">不满足</span><span><var>x</var> 取全体实数</span><span aria-hidden="true">→</span><button class="method-switch" type="button" data-explain-open="method-discriminant"></button></li>
        <li><span class="method-else-tag alt">也可以</span><span>参数容易单独移到一边</span><span aria-hidden="true">→</span><button class="method-switch" type="button" data-explain-open="method-separation"></button></li>
      </ul>
    </section>
    ${graph('第 04 题')}
    <ol class="method-steps" aria-label="解题三步">
      <li><span class="method-step-no" aria-hidden="true">1</span><strong>转化为最值条件</strong><span>&lt; 0 比最高点，&gt; 0 比最低点</span></li>
      <li><span class="method-step-no" aria-hidden="true">2</span><strong>分类讨论最值</strong><span>对称轴与区间比较，分情况写最值</span></li>
      <li><span class="method-step-no" aria-hidden="true">3</span><strong>合并，查边界</strong><span>情况内取交集，情况间取并集</span></li>
    </ol>`,
};
