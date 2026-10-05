/* Square non-negativity: four a×b rectangles inside the (a+b)-square leave a hole of side |a−b|, so (a+b)² ≥ 4ab. Purely local. */
import {escapeHtml as escape, problemNote} from '../shared/html.js?v=1';

// The big square has side a + b = 8, drawn 192 px wide.
const SUM = 8, UNIT = 24, O = [14, 14];
const A = {min: 0.5, max: 7.5, step: 0.1, value: 2.5};

const RULES = [
  ['$a^2+b^2\\ge2ab$', '展开 $(a-b)^2\\ge0$'],
  ['$ab\\le\\left(\\frac{a+b}2\\right)^2$', '即和积换元里的 $p\\le\\frac{s^2}4$'],
  ['$x^2+\\frac1{x^2}\\ge2$', '$x^2+\\frac1{x^2}=\\left(x-\\frac1x\\right)^2+2$'],
];

function layer(a) {
  const b = SUM - a, [x0, y0] = O, u = v => v * UNIT;
  const rect = (x, y, w, h) => `<rect x="${x0 + u(x)}" y="${y0 + u(y)}" width="${u(w)}" height="${u(h)}" class="sn-rect"/>`
    + (Math.min(w, h) >= 1 ? `<text x="${x0 + u(x + w / 2)}" y="${y0 + u(y + h / 2) + 4}" text-anchor="middle" class="sn-rect-label">ab</text>` : '');
  const lo = Math.min(a, b), hi = Math.max(a, b);
  const hole = hi - lo > 0.05
    ? `<rect x="${x0 + u(lo)}" y="${y0 + u(lo)}" width="${u(hi - lo)}" height="${u(hi - lo)}" class="sn-hole"/>`
      + (hi - lo > 1.2 ? `<text x="${x0 + u((lo + hi) / 2)}" y="${y0 + u((lo + hi) / 2) + 4}" text-anchor="middle" class="sn-hole-label">(a−b)²</text>` : '')
    : '';
  return rect(0, 0, a, b) + rect(a, 0, b, a) + rect(b, a, a, b) + rect(0, b, b, a) + hole
    + `<text x="${x0 + u(a / 2)}" y="${y0 - 3}" text-anchor="middle" class="sn-side">a</text>`
    + `<text x="${x0 + u(a + b / 2)}" y="${y0 - 3}" text-anchor="middle" class="sn-side">b</text>`;
}

export default {
  stylesheet: new URL('square-nonnegative.css?v=1', import.meta.url).href,

  render({tip}) {
    return `<p class="sn-core" data-math-text>任何实数的平方都不小于 $0$。由 $(a-b)^2\\ge0$ 得 $a^2+b^2\\ge2ab$，也就是 $ab\\le\\left(\\frac{a+b}2\\right)^2$；对任意实数 $a$、$b$ 都成立，$a=b$ 时取等。</p>
    ${tip?.note ? `<p class="sn-problem"><span class="sn-badge">本题</span><span data-math-text>${problemNote(tip.note)}</span></p>` : ''}
    <div class="sn-explorer">
      <p class="sn-ask">四个 a × b 的长方形拼进边长 a + b 的正方形，拖动 a，看中间空出的部分：</p>
      <svg class="sn-graph" viewBox="0 0 220 220" role="img" aria-labelledby="sn-graph-title">
        <title id="sn-graph-title">边长 a+b 的正方形里放四个 a×b 的长方形，中间空出边长 |a−b| 的小正方形</title>
        <rect x="${O[0]}" y="${O[1]}" width="${SUM * UNIT}" height="${SUM * UNIT}" class="sn-frame"/>
        <g data-sn-layer></g>
      </svg>
      <input class="sn-slider" type="range" data-sn-slider min="${A.min}" max="${A.max}" step="${A.step}" value="${A.value}" aria-label="a 的长度">
      <p class="sn-readout" aria-live="polite" data-sn-readout></p>
      <p class="sn-result" data-math-text>$(a+b)^2=4ab+(a-b)^2\\ge4ab$，中间的小正方形缩成一个点时（$a=b$）取等。</p>
    </div>
    <table class="sn-table">
      <caption>常用的几种写法</caption>
      <thead><tr><th scope="col">结论</th><th scope="col">由来</th></tr></thead>
      <tbody>${RULES.map(([rule, why]) => `<tr><td data-math-text>${rule}</td><td data-math-text>${why}</td></tr>`).join('')}</tbody>
    </table>
    <div class="sn-notes">
      <section class="sn-note">
        <h3>和基本不等式的区别</h3>
        <p data-math-text>这里不要求 $a$、$b$ 为正。$x$、$y$ 可能是负数时，只能用 $xy\\le\\left(\\frac{x+y}2\\right)^2$，不能用 $x+y\\ge2\\sqrt{xy}$。</p>
        <p>见 <button type="button" class="sn-link" data-explain-open="amgm-formula"></button>。</p>
      </section>
      <section class="sn-note">
        <h3>取等：平方项等于 0</h3>
        <p data-math-text>$\\left(x-\\frac1x\\right)^2+2\\ge2$，取等要 $x=\\frac1x$，即 $x=\\pm1$。先写出平方项，再让它等于 $0$。</p>
      </section>
      <section class="sn-note">
        <h3>和与积的范围</h3>
        <p data-math-text>令 $s=x+y$、$p=xy$，实数 $x$、$y$ 一定满足 $s^2\\ge4p$；由条件解出 $s$ 的范围时要用上它。</p>
        <p>见 <button type="button" class="sn-link" data-explain-open="method-sum-product"></button>。</p>
      </section>
    </div>`;
  },

  mount(root) {
    const slider = root.querySelector('[data-sn-slider]');
    const draw = () => {
      const a = Number(slider.value), b = SUM - a;
      root.querySelector('[data-sn-layer]').innerHTML = layer(a);
      root.querySelector('[data-sn-readout]').textContent = Math.abs(a - b) < 0.05
        ? 'a = b = 4：(a+b)² = 64 = 4ab，中间没有空隙'
        : `a = ${a.toFixed(1)}，b = ${b.toFixed(1)}：(a+b)² = 64，4ab = ${(4 * a * b).toFixed(2)}，(a−b)² = ${((a - b) ** 2).toFixed(2)}`;
    };
    slider.addEventListener('input', draw);
    draw();
  },
};
