/* Changing the main variable: the letter with the given range becomes the variable, usually linear. */
const figure = tag => `<div class="method-figure">
      <svg class="method-graph" viewBox="0 0 280 150" role="img" aria-label="${tag}，x 等于 0 时 f(m) 等于 m 减 6 在 m 属于 1 到 3 上两端都在横轴下方；x 等于 2 时 f(m) 等于 3m 减 6 右端在横轴上方">
        <rect class="g-band" x="90" y="4" width="100" height="142" rx="3"/>
        <line class="g-axis" x1="20" y1="60" x2="264" y2="60"/>
        <line class="g-axis" x1="40" y1="4" x2="40" y2="146"/>
        <text class="g-math" x="256" y="54">m</text>
        <text class="g-text" x="90" y="54" text-anchor="middle">1</text>
        <text class="g-text" x="190" y="54" text-anchor="middle">3</text>
        <line class="g-faint" x1="65" y1="131.5" x2="210" y2="93.8"/>
        <line class="g-curve" x1="90" y1="125" x2="190" y2="99"/>
        <circle class="g-dot" cx="90" cy="125" r="4"/>
        <circle class="g-dot" cx="190" cy="99" r="4"/>
        <line class="g-alt" x1="65" y1="118.5" x2="210" y2="5.4"/>
        <circle class="g-dot-alt" cx="90" cy="99" r="3.6"/>
        <circle class="g-dot-bad" cx="190" cy="21" r="4.4"/>
        <text class="g-text ok" x="196" y="128">x = 0 ✓</text>
        <text class="g-text bad" x="200" y="30">x = 2 ✗</text>
      </svg>
      <p class="method-graph-caption">${tag}：<span class="nowrap"><var>x</var> = 0</span> 时 <span class="nowrap"><var>f</var>(<var>m</var>) = <var>m</var> − 6</span>，两端都在横轴下方；<span class="nowrap"><var>x</var> = 2</span> 时 <span class="nowrap"><var>f</var>(<var>m</var>) = 3<var>m</var> − 6</span>，右端跑到上方</p>
      <ul class="method-cases">
        <li><span class="method-case-tag">斜率恒正／恒负</span><span class="method-case-arrow" aria-hidden="true">→</span><span>最值在确定的一端</span></li>
        <li><span class="method-case-tag">斜率符号不定</span><span class="method-case-arrow" aria-hidden="true">→</span><span>两端都要看</span></li>
      </ul>
      <p class="method-pill">一次函数在区间上恒 &lt; 0 ⇔ 两个端点值都 &lt; 0</p>
    </div>`;

export default {
  figure: () => figure('例'),

  render: () => `
    <p class="method-core"><span class="method-tag">核心</span><span>对哪个字母恒成立，就把它当自变量（主元）；另一个字母当常数，常常变成一次函数，只看两端。</span></p>
    <section class="method-judge" aria-labelledby="method-variable-judge">
      <h3 class="method-judge-title" id="method-variable-judge"><span class="method-tag">判断</span>两个前提都满足，才用更换主元法</h3>
      <div class="method-signal">
        <span class="method-signal-tag">读题信号 · 第 08 题</span>
        已知函数 <math><mi>y</mi><mo>=</mo><mi>m</mi><msup><mi>x</mi><mn>2</mn></msup><mo>−</mo><mi>m</mi><mi>x</mi><mo>−</mo><mn>6</mn><mo>+</mo><mi>m</mi></math>，若对于 <mark><math><mn>1</mn><mo>≤</mo><mi>m</mi><mo>≤</mo><mn>3</mn></math></mark>，<span class="nowrap"><var>y</var> &lt; 0</span> 恒成立，求实数 <mark><var>x</var></mark> 的取值范围。
        <ul class="method-signal-notes">
          <li>给出范围的是 <var>m</var>，要求的是 <var>x</var>：把 <var>m</var> 当作主元</li>
          <li><span class="nowrap"><var>y</var> = (<var>x</var><sup>2</sup> − <var>x</var> + 1)<var>m</var> − 6</span>：关于 <var>m</var> 是一次函数</li>
        </ul>
      </div>
      <ol class="method-checks">
        <li><span class="method-check-no" aria-hidden="true">1</span><b>恒成立针对的是给出范围的字母</b><small>它不是要求范围的那个字母，就把它当作主元</small></li>
        <li><span class="method-check-no" aria-hidden="true">2</span><b>固定另一个字母后，关于主元是一次形式</b><small>可退化为常数；最值都在区间端点取到</small></li>
      </ol>
      <ul class="method-else">
        <li><span class="method-else-tag">不满足</span><span>恒成立针对的就是 <var>x</var></span><span aria-hidden="true">→</span><button class="method-switch" type="button" data-explain-open="method-discriminant"></button><button class="method-switch" type="button" data-explain-open="method-interval-extremum"></button><button class="method-switch" type="button" data-explain-open="method-separation"></button></li>
      </ul>
    </section>
    ${figure('第 08 题')}
    <ol class="method-steps" aria-label="解题三步">
      <li><span class="method-step-no" aria-hidden="true">1</span><strong>定主元，整理</strong><span>写成 f(主元) = (…)·主元 + (…)</span></li>
      <li><span class="method-step-no" aria-hidden="true">2</span><strong>看斜率定端点</strong><span>恒正、恒负看一端，不定看两端</span></li>
      <li><span class="method-step-no" aria-hidden="true">3</span><strong>解不等式，查边界</strong><span>解关于原来字母的不等式</span></li>
    </ol>`,
};
