/* Taking the reciprocal: y = 2x/(x²+4) and 1/y on two linked number lines move in opposite directions. Purely local. */
import {escapeHtml as escape, problemNote} from '../shared/html.js?v=1';

const X = {min: 0.8, max: 5, step: 0.05, value: 1};
const LEFT = 70, RIGHT = 326;
const ROWS = [
  {key: 'y', y: 40, name: 'y', domain: [0.3, 0.56], ticks: [[0.35, '0.35'], [0.5, '1/2']], value: x => 2 * x / (x * x + 4)},
  {key: 'r', y: 118, name: '1/y', domain: [1.8, 3.1], ticks: [[2, '2'], [3, '3']], value: x => x / 2 + 2 / x},
];
const at = (row, v) => LEFT + (v - row.domain[0]) / (row.domain[1] - row.domain[0]) * (RIGHT - LEFT);

function figure() {
  const rows = ROWS.map(row => `<text x="10" y="${row.y + 4}" class="rc-name">${row.name}</text>
    <path d="M${LEFT - 6} ${row.y}H${RIGHT + 6}" class="rc-line"/>
    ${row.ticks.map(([v, text]) => `<path d="M${at(row, v)} ${row.y - 5}V${row.y + 5}" class="rc-tick"/><text x="${at(row, v)}" y="${row.y + 21}" text-anchor="middle" class="rc-tick-label">${text}</text>`).join('')}`).join('');
  return `<svg class="rc-graph" viewBox="0 0 340 146" role="img" aria-labelledby="rc-graph-title">
    <title id="rc-graph-title">两条数轴：x 变化时 y 与 1/y 反向移动，y 最大时 1/y 最小</title>
    <path d="M${at(ROWS[0], 0.5)} ${ROWS[0].y - 12}V${ROWS[0].y + 12}" class="rc-extreme"/>
    <path d="M${at(ROWS[1], 2)} ${ROWS[1].y - 12}V${ROWS[1].y + 12}" class="rc-extreme"/>
    ${rows}
    <g data-rc-layer></g>
  </svg>`;
}

function layer(x) {
  const [top, bottom] = ROWS.map(row => at(row, row.value(x)));
  return `<path d="M${top} ${ROWS[0].y + 7}L${bottom} ${ROWS[1].y - 7}" class="rc-connector"/>
    <circle cx="${top}" cy="${ROWS[0].y}" r="6.5" class="rc-dot"/><circle cx="${bottom}" cy="${ROWS[1].y}" r="6.5" class="rc-dot"/>`;
}

export default {
  stylesheet: new URL('method-reciprocal.css?v=1', import.meta.url).href,

  render({tip}) {
    return `<p class="method-core"><span class="method-tag">核心</span><span data-math-text>$y$ 恒为正（或恒为负）时，$y$ 越大，$\\frac1y$ 越小：求 $y$ 的最大值，改求 $\\frac1y$ 的最小值，最后再取倒数换回。</span></p>
    ${tip?.note ? `<p class="rc-problem"><span class="rc-badge">本题</span><span data-math-text>${problemNote(tip.note)}</span></p>` : ''}
    <div class="rc-explorer">
      <p class="rc-ask" data-math-text>例：$x&gt;0$，$y=\\frac{2x}{x^2+4}$，$\\frac1y=\\frac x2+\\frac2x$。拖动 $x$，看两个点怎样走：</p>
      ${figure()}
      <input class="rc-slider" type="range" data-rc-slider min="${X.min}" max="${X.max}" step="${X.step}" value="${X.value}" aria-label="x 的值">
      <p class="rc-readout" aria-live="polite" data-rc-readout></p>
      <p class="rc-result" data-math-text>$\\frac1y=\\frac x2+\\frac2x\\ge2$，$x=2$ 时取等，所以 $y\\le\\frac12$，最大值是 $\\frac12$。</p>
    </div>
    <ol class="method-steps" aria-label="取倒数三步">
      <li><span class="method-step-no" aria-hidden="true">1</span><strong>判断符号</strong><span>y 恒正或恒负，且不等于 0</span></li>
      <li><span class="method-step-no" aria-hidden="true">2</span><strong>转化目标</strong><span>最大值改求 1/y 的最小值，最小值反过来</span></li>
      <li><span class="method-step-no" aria-hidden="true">3</span><strong>取倒数换回</strong><span>求出 1/y 的最值后，再取倒数</span></li>
    </ol>
    <div class="rc-notes">
      <section class="rc-note">
        <h3>什么时候想到取倒数</h3>
        <p data-math-text>分子次数比分母低，如 $\\frac{2x}{x^2+4}$。取倒数后分子次数高，就能分式分离成 $t+\\frac kt$ 的形式。</p>
        <p>见 <button type="button" class="rc-link" data-explain-open="method-fraction-split"></button>。</p>
      </section>
      <section class="rc-note">
        <h3>y 能等于 0：先单独看</h3>
        <p data-math-text>$x\\ge0$ 时 $y=\\frac{2x}{x^2+4}$ 在 $x=0$ 处为 $0$，不能取倒数。先说明 $x=0$ 时 $y=0$，再对 $x&gt;0$ 取倒数。</p>
      </section>
      <section class="rc-note">
        <h3>有正有负：不能直接取倒数</h3>
        <p data-math-text>两个数同号，取倒数后大小顺序才颠倒；$-1&lt;2$，取倒数后仍是 $-1&lt;\\frac12$。</p>
        <p>见 <button type="button" class="rc-link" data-explain-open="inequality-properties"></button>。</p>
      </section>
    </div>`;
  },

  mount(root) {
    const slider = root.querySelector('[data-rc-slider]');
    const draw = () => {
      const x = Number(slider.value), y = ROWS[0].value(x), r = ROWS[1].value(x);
      root.querySelector('[data-rc-layer]').innerHTML = layer(x);
      root.querySelector('[data-rc-readout]').textContent = Math.abs(x - 2) < 0.03
        ? 'x = 2：1/y = 2 最小，y = 1/2 最大'
        : `x = ${x.toFixed(2)}：1/y ≈ ${r.toFixed(3)}，y ≈ ${y.toFixed(3)}`;
    };
    slider.addEventListener('input', draw);
    draw();
  },
};
