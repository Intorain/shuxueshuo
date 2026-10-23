/* On the real line, quantifier, opening and discriminant determine each sign condition. */
const positionGraphs = negative => {
  const positions = [
    {delta: 'Δ &lt; 0', control: 92, text: negative ? '处处为负' : '处处为正'},
    {delta: 'Δ = 0', control: 112, text: negative ? '最高点为 0' : '最低点为 0', tangent: true},
    {delta: 'Δ &gt; 0', control: 144, text: '既有正值，也有负值'},
  ];
  return `<p class="md-opening">${negative ? 'a &lt; 0：开口向下' : 'a &gt; 0：开口向上'}</p>
    <ul class="method-graphs" aria-label="${negative ? '开口向下' : '开口向上'}时，抛物线与横轴的三种位置">
      ${positions.map(item => `<li><svg viewBox="0 0 120 84" aria-hidden="true"><g${negative ? ' transform="translate(0 84) scale(1 -1)"' : ''}>
        <line class="g-axis" x1="6" y1="60" x2="114" y2="60"/>
        <path class="g-curve" d="M14 8 Q60 ${item.control} 106 8"/>
        ${item.tangent ? '<circle class="g-dot" cx="60" cy="60" r="3.6"/>' : ''}
      </g></svg><b>${item.delta}</b><span>${item.text}</span></li>`).join('')}
    </ul>`;
};

const signTable = () => `<div class="md-table-wrap"><table class="md-sign-table">
      <caption>设 f(x) = ax² + bx + c，a ≠ 0，x ∈ ℝ</caption>
      <thead><tr><th scope="col">要求</th><th scope="col">a &gt; 0</th><th scope="col">a &lt; 0</th></tr></thead>
      <tbody>
        <tr><th scope="row">恒 &gt; 0</th><td>Δ &lt; 0</td><td>不成立</td></tr>
        <tr><th scope="row">恒 ≥ 0</th><td>Δ ≤ 0</td><td>不成立</td></tr>
        <tr><th scope="row">恒 &lt; 0</th><td>不成立</td><td>Δ &lt; 0</td></tr>
        <tr><th scope="row">恒 ≤ 0</th><td>不成立</td><td>Δ ≤ 0</td></tr>
        <tr><th scope="row">存在 &gt; 0</th><td>总有解</td><td>Δ &gt; 0</td></tr>
        <tr><th scope="row">存在 ≥ 0</th><td>总有解</td><td>Δ ≥ 0</td></tr>
        <tr><th scope="row">存在 &lt; 0</th><td>Δ &gt; 0</td><td>总有解</td></tr>
        <tr><th scope="row">存在 ≤ 0</th><td>Δ ≥ 0</td><td>总有解</td></tr>
      </tbody>
    </table></div>`;

const figure = () => `<div class="method-figure md-figure">
      <p class="md-meaning"><b>恒成立</b>看整条图像；<b>存在成立</b>只需找到一个点。</p>
      ${positionGraphs(false)}
      ${positionGraphs(true)}
      <p class="method-graph-caption">Δ 只表示交点情况，不能单独决定原不等式是否成立；还要看开口、量词与关系。</p>
      ${signTable()}
      <p class="md-note">“总有解”表示在该开口下不需要额外限制 Δ。例如 x² + 1 &gt; 0 有解，虽然 Δ &lt; 0。</p>
      <p class="md-note">a = 0 时另看一次式或常数：b ≠ 0 的一次式取遍 ℝ，四种关系都有解、都不恒成立；b = 0 时直接检查常数 c 是否满足原关系。</p>
      <p class="method-pill">这些条件针对全体实数；限定区间时先看该区间上的取值。</p>
    </div>`;

export default {
  stylesheet: new URL('method-discriminant.css?v=1', import.meta.url).href,
  figure,

  render: () => `
    <p class="method-core"><span class="method-tag">核心</span><span>变量取全体实数时，用开口方向和判别式判断二次不等式恒成立，或至少有一个实数解。</span></p>
    <section class="method-judge" aria-labelledby="method-discriminant-judge">
      <h3 class="method-judge-title" id="method-discriminant-judge"><span class="method-tag">判断</span>先读清范围、量词，再检查次数</h3>
      <div class="method-signal">
        <span class="method-signal-tag">两个量词，条件不同</span>
        <var>x</var> 取全体实数，研究 <var>x</var><sup>2</sup> − 2<var>x</var> + <var>m</var> ≤ 0。
        <ul class="method-signal-notes">
          <li>对所有 <var>x</var> 成立：开口向上，两端值越来越大，不可能恒 ≤ 0</li>
          <li>存在 <var>x</var> 成立：图像碰到或穿过横轴即可，Δ = 4 − 4<var>m</var> ≥ 0，得 <var>m</var> ≤ 1</li>
        </ul>
      </div>
      <ol class="method-checks">
        <li><span class="method-check-no" aria-hidden="true">1</span><b>量词变量的范围：全体实数</b><small>只在某个区间内取值时，不能直接使用下表</small></li>
        <li><span class="method-check-no" aria-hidden="true">2</span><b>要求：恒成立，还是至少有一个解</b><small>保留 &gt;、≥、&lt;、≤ 的方向与是否允许等号</small></li>
        <li><span class="method-check-no" aria-hidden="true">3</span><b>二次项系数：先处理可能为 0 的情况</b><small>非零时才按开口与 Δ 判断；为零时看一次式或常数</small></li>
      </ol>
      <ul class="method-else">
        <li><span class="method-else-tag">限定区间</span><span>先研究区间上的值域</span><span aria-hidden="true">→</span><button class="method-switch" type="button" data-explain-open="method-interval-extremum"></button><button class="method-switch" type="button" data-explain-open="method-separation"></button></li>
      </ul>
    </section>
    ${figure()}
    <ol class="method-steps" aria-label="解题三步">
      <li><span class="method-step-no" aria-hidden="true">1</span><strong>分清次数与量词</strong><span>先处理退化，再读清全称或存在</span></li>
      <li><span class="method-step-no" aria-hidden="true">2</span><strong>把位置化成条件</strong><span>开口、Δ 与关系一起看，区分“且”和“或”</span></li>
      <li><span class="method-step-no" aria-hidden="true">3</span><strong>解范围，查边界</strong><span>存在型边界只需找到一个符合条件的点</span></li>
    </ol>`,
};
