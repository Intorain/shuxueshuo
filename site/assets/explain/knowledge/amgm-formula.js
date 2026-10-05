/* The AM–GM inequality: the half-chord √(ab) never exceeds the radius (a+b)/2, and the three conditions for using it. Purely local. */
import {escapeHtml as escape, problemNote} from '../shared/html.js?v=1';

// Diameter a + b = 8 drawn 280 px wide, so one unit is 35 px.
const SUM = 8, UNIT = 35, LEFT = 30, BASE = 168;
const A = {min: 0.5, max: 7.5, step: 0.1, value: 2};

// A finished step's tip.case opens the matching tab.
const TABS = [
  {key: 'apply', label: '套公式', title: '两种用法：看哪个是定值', body: `
    <ul class="ag-uses">
      <li><span class="ag-use-tag">定积求和</span><span data-math-text>$a,b&gt;0$，$ab=P$ 为定值 $\\Rightarrow a+b\\ge2\\sqrt P$，和有最小值</span></li>
      <li><span class="ag-use-tag">定和求积</span><span data-math-text>$a+b=S$ 为定值 $\\Rightarrow ab\\le\\left(\\frac S2\\right)^2$，积有最大值</span></li>
    </ul>
    <p data-math-text>$a$、$b$ 换成两个完整的式子：$x&gt;1$ 时 $2(x-1)$ 与 $\\frac2{x-1}$ 的积是 $4$，所以 $2(x-1)+\\frac2{x-1}\\ge2\\sqrt4=4$。</p>`},
  {key: 'positive', label: '一正', title: '一正：两项都要是正数', body: `
    <p class="ag-wrong" data-math-text>$x&lt;0$ 时写 $x+\\frac1x\\ge2$ 是错的：$x=-1$ 时它等于 $-2$。</p>
    <p data-math-text>先提出负号，对两个正数 $-x$、$-\\frac1x$ 用公式：$x+\\frac1x=-\\left[(-x)+\\left(-\\frac1x\\right)\\right]\\le-2$。</p>
    <p data-math-text>和为正不代表两项都正：$2a+3b=1$ 时 $a$、$b$ 仍可能一正一负，要另外说明。</p>`},
  {key: 'fixed', label: '二定', title: '二定：和或积要是定值', body: `
    <p class="ag-wrong" data-math-text>$x&gt;1$ 时，$x\\cdot\\frac1{x-1}$ 不是定值，$x+\\frac1{x-1}\\ge2\\sqrt{\\frac x{x-1}}$ 的右边还在变，求不出最小值。</p>
    <p data-math-text>先凑成积为定值的两项，$x-1&gt;0$：$x+\\frac1{x-1}=(x-1)+\\frac1{x-1}+1\\ge2+1=3$。</p>`,
    link: 'method-matching'},
  {key: 'equal', label: '三相等', title: '三相等：取等的条件要能成立', body: `
    <p class="ag-wrong" data-math-text>$\\sqrt{x^2+2}+\\frac1{\\sqrt{x^2+2}}\\ge2$ 本身没错，但取等要 $\\sqrt{x^2+2}=1$，做不到，所以 $2$ 不是最小值。</p>
    <p data-math-text>令 $t=\\sqrt{x^2+2}\\ge\\sqrt2$，$t+\\frac1t$ 在 $[\\sqrt2,+\\infty)$ 上递增，最小值在 $t=\\sqrt2$ 处取到，是 $\\frac{3\\sqrt2}2$。</p>`,
    link: 'reciprocal-sum-function'},
];

function figure() {
  return `<svg class="ag-graph" viewBox="0 0 340 196" role="img" aria-labelledby="ag-graph-title">
    <title id="ag-graph-title">半圆：直径分成长 a 和 b 的两段，分点处向上的半弦长 √(ab)，半径长 (a+b)/2</title>
    <path d="M${LEFT} ${BASE}A${SUM / 2 * UNIT} ${SUM / 2 * UNIT} 0 0 1 ${LEFT + SUM * UNIT} ${BASE}" class="ag-arc"/>
    <path d="M${LEFT - 6} ${BASE}H${LEFT + SUM * UNIT + 6}" class="ag-diameter"/>
    <g data-ag-layer></g>
  </svg>`;
}

function layer(a) {
  const b = SUM - a, x = LEFT + a * UNIT, h = Math.sqrt(a * b) * UNIT, cx = LEFT + SUM / 2 * UNIT, r = SUM / 2 * UNIT;
  const equal = Math.abs(a - b) < 0.05;
  return `<path d="M${cx} ${BASE}V${BASE - r}" class="ag-radius"/>
    <text x="${cx + (x < cx ? 6 : -6)}" y="${BASE - r / 2}" text-anchor="${x < cx ? 'start' : 'end'}" class="ag-radius-label">(a+b)/2</text>
    <path d="M${x} ${BASE}V${BASE - h}" class="ag-chord${equal ? ' equal' : ''}"/>
    <circle cx="${x}" cy="${BASE - h}" r="4.5" class="ag-top${equal ? ' equal' : ''}"/>
    <text x="${x + (x < cx ? -6 : 6)}" y="${BASE - h / 2}" text-anchor="${x < cx ? 'end' : 'start'}" class="ag-chord-label">√ab</text>
    <circle cx="${x}" cy="${BASE}" r="3.5" class="ag-split"/>
    <text x="${(LEFT + x) / 2}" y="${BASE + 18}" text-anchor="middle" class="ag-part">a</text>
    <text x="${(x + LEFT + SUM * UNIT) / 2}" y="${BASE + 18}" text-anchor="middle" class="ag-part">b</text>`;
}

export default {
  stylesheet: new URL('amgm-formula.css?v=1', import.meta.url).href,

  render({tip}) {
    return `<p class="ag-core" data-math-text>$a,b&gt;0$ 时，$\\sqrt{ab}\\le\\frac{a+b}2$，即 $a+b\\ge2\\sqrt{ab}$，当且仅当 $a=b$ 时取等。用之前检查三件事：一正、二定、三相等。</p>
    ${tip?.note ? `<p class="ag-problem"><span class="ag-badge">本题</span><span data-math-text>${problemNote(tip.note)}</span></p>` : ''}
    <div class="ag-explorer">
      <p class="ag-ask">直径长 a + b = 8，拖动分点，比较半弦和半径：</p>
      ${figure()}
      <input class="ag-slider" type="range" data-ag-slider min="${A.min}" max="${A.max}" step="${A.step}" value="${A.value}" aria-label="a 的长度">
      <p class="ag-readout" aria-live="polite" data-ag-readout></p>
      <p class="ag-legend">半弦总不超过半径，分点在圆心（a = b）时两者相等。</p>
    </div>
    <div class="ag-tabs" role="tablist" aria-label="使用条件">
      ${TABS.map(tab => `<button type="button" role="tab" data-ag-tab="${tab.key}" aria-selected="false">${tab.label}</button>`).join('')}
    </div>
    ${TABS.map(tab => `<section class="ag-panel" role="tabpanel" data-ag-panel="${tab.key}" hidden>
      <h3>${tab.title}</h3>${tab.body}
      ${tab.link ? `<p>见 <button type="button" class="ag-link" data-explain-open="${tab.link}"></button>。</p>` : ''}
    </section>`).join('')}
    <div class="ag-notes">
      <section class="ag-note">
        <h3>为什么成立</h3>
        <p data-math-text>$(\\sqrt a-\\sqrt b)^2\\ge0$ 展开就是 $a+b\\ge2\\sqrt{ab}$。$ab\\le\\left(\\frac{a+b}2\\right)^2$ 这个写法对任意实数都成立。</p>
        <p>见 <button type="button" class="ag-link" data-explain-open="square-nonnegative"></button>。</p>
      </section>
      <section class="ag-note">
        <h3>取等：写出取到时的值</h3>
        <p data-math-text>$x,y&gt;0$，$xy=4$ 时 $x+2y\\ge4\\sqrt2$。取等要 $x=2y$，与 $xy=4$ 联立得 $x=2\\sqrt2$，$y=\\sqrt2$，确实取得到。</p>
      </section>
      <section class="ag-note">
        <h3>用了两次：取等要同时成立</h3>
        <p data-math-text>一个式子里两次用基本不等式，两次的取等条件要能同时满足，否则两个下界相加取不到。</p>
      </section>
    </div>`;
  },

  mount(root, {tip}) {
    const slider = root.querySelector('[data-ag-slider]');
    const draw = () => {
      const a = Number(slider.value), b = SUM - a;
      root.querySelector('[data-ag-layer]').innerHTML = layer(a);
      root.querySelector('[data-ag-readout]').textContent = Math.abs(a - b) < 0.05
        ? 'a = b = 4：√ab = (a+b)/2 = 4，取等'
        : `a = ${a.toFixed(1)}，b = ${b.toFixed(1)}：√ab ≈ ${Math.sqrt(a * b).toFixed(2)} < (a+b)/2 = 4`;
    };
    slider.addEventListener('input', draw);
    draw();
    const pick = key => {
      for (const button of root.querySelectorAll('[data-ag-tab]')) button.setAttribute('aria-selected', String(button.dataset.agTab === key));
      for (const panel of root.querySelectorAll('[data-ag-panel]')) panel.hidden = panel.dataset.agPanel !== key;
    };
    for (const button of root.querySelectorAll('[data-ag-tab]')) button.addEventListener('click', () => pick(button.dataset.agTab));
    pick(TABS.some(tab => tab.key === tip?.case) ? tip.case : 'apply');
  },
};
