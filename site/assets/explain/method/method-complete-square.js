/* Completing the square: the area picture of x² + 6x gaining its missing corner, step by step. Purely local. */
import {escapeHtml as escape, problemNote} from '../shared/html.js?v=1';

const O = [36, 24], SIDE = 110, HALF = 40;
const STEPS = [
  '先看前两项：$x^2+6x$ 是一个边长为 $x$ 的正方形，加一个 $6\\times x$ 的长方形。',
  '一次项系数分一半：$6x=3x+3x$，两块分别贴到正方形的右边和下边。',
  '缺一个角，补上 $3^2=9$：$x^2+6x+9=(x+3)^2$，所以 $x^2+6x=(x+3)^2-9$。',
  '$x^2+6x+11=(x+3)^2+2\\ge2$，$x=-3$ 时取等，最小值是 $2$。',
];

function picture(step) {
  const [x0, y0] = O, x1 = x0 + SIDE, y1 = y0 + SIDE;
  const box = (x, y, w, h, cls, text) => `<rect x="${x}" y="${y}" width="${w}" height="${h}" class="sq-piece ${cls}"/>${text ? `<text x="${x + w / 2}" y="${y + h / 2 + 5}" text-anchor="middle" class="sq-area">${text}</text>` : ''}`;
  const side = (x, y, text, anchor = 'middle') => `<text x="${x}" y="${y}" text-anchor="${anchor}" class="sq-side">${text}</text>`;
  if (step === 0) {
    return box(x0, y0, SIDE, SIDE, 'square', 'x²') + box(x1, y0, HALF * 2, SIDE, 'strip', '6x')
      + side(x0 + SIDE / 2, y0 - 8, 'x') + side(x1 + HALF, y0 - 8, '6') + side(x0 - 10, y0 + SIDE / 2 + 5, 'x', 'end');
  }
  const corner = step === 1
    ? `<rect x="${x1}" y="${y1}" width="${HALF}" height="${HALF}" class="sq-piece missing"/><text x="${x1 + HALF / 2}" y="${y1 + HALF / 2 + 5}" text-anchor="middle" class="sq-area missing">?</text>`
    : box(x1, y1, HALF, HALF, 'corner', '9');
  const outline = step >= 2 ? `<rect x="${x0}" y="${y0}" width="${SIDE + HALF}" height="${SIDE + HALF}" class="sq-outline"/>${side(x0 + (SIDE + HALF) / 2, y1 + HALF + 20, '边长 x + 3')}` : '';
  return box(x0, y0, SIDE, SIDE, 'square', 'x²') + box(x1, y0, HALF, SIDE, 'strip', '3x') + box(x0, y1, SIDE, HALF, 'strip', '3x') + corner + outline
    + side(x0 + SIDE / 2, y0 - 8, 'x') + side(x1 + HALF / 2, y0 - 8, '3') + side(x0 - 10, y0 + SIDE / 2 + 5, 'x', 'end') + side(x0 - 10, y1 + HALF / 2 + 5, '3', 'end');
}

const explorer = () => `<div class="sq-explorer">
      <p class="sq-ask" data-math-text>例：求 $x^2+6x+11$ 的最小值。</p>
      <div class="sq-stage">
        <svg class="sq-graph" viewBox="0 0 230 214" role="img" aria-label="面积图：边长为 x 的正方形加上 6x 的长方形，补上一角成为边长 x+3 的正方形"><g data-sq-layer></g></svg>
        <ol class="sq-steps" aria-live="polite">${STEPS.map((text, i) => `<li data-sq-text="${i}"${i ? ' hidden' : ''} data-math-text>${text}</li>`).join('')}</ol>
      </div>
      <div class="sq-controls">
        <button type="button" data-sq-move="-1">上一步</button>
        <button type="button" data-sq-move="1" class="sq-next">下一步</button>
        <button type="button" data-sq-all>全部显示</button>
      </div>
    </div>`;

export default {
  stylesheet: new URL('method-complete-square.css?v=1', import.meta.url).href,

  figure: () => explorer(),

  render({tip}) {
    return `<p class="method-core"><span class="method-tag">核心</span><span data-math-text>把二次式配成“平方 + 常数”，由平方 $\\ge0$ 读出它的界，以及取等时的 $x$。</span></p>
    ${tip?.note ? `<p class="sq-problem"><span class="sq-badge">本题</span><span data-math-text>${problemNote(tip.note)}</span></p>` : ''}
    ${explorer()}
    <div class="sq-lead">
      <h3>二次项系数不是 1：先提出来</h3>
      <p class="sq-chain" data-math-text>$-x^2+2x+3=-(x^2-2x)+3=-\\left[(x-1)^2-1\\right]+3=4-(x-1)^2\\le4$</p>
      <p data-math-text>$x=1$ 时取等，最大值是 $4$。提出负号后，括号里减的 $1$ 出来要变号。</p>
    </div>
    <ol class="method-steps" aria-label="配方三步">
      <li><span class="method-step-no" aria-hidden="true">1</span><strong>提系数</strong><span>二次项系数不是 1，先从前两项提出来</span></li>
      <li><span class="method-step-no" aria-hidden="true">2</span><strong>加一半的平方</strong><span>加上再减去一次项系数一半的平方</span></li>
      <li><span class="method-step-no" aria-hidden="true">3</span><strong>读出界</strong><span>写成“平方 + 常数”，由平方 ≥ 0 得界，写出取等的 x</span></li>
    </ol>
    <div class="sq-notes">
      <section class="sq-note">
        <h3>取等的 x 要在范围里</h3>
        <p data-math-text>$x^2-2x=(x-1)^2-1\\ge-1$，但在 $[2,3]$ 上取不到 $x=1$，最小值是 $f(2)=0$。</p>
        <p>范围受限时，见 <button type="button" class="sq-link" data-explain-open="quadratic-interval-extremum"></button>。</p>
      </section>
      <section class="sq-note">
        <h3>判断恒正</h3>
        <p data-math-text>$x^2-x+1=\\left(x-\\frac12\\right)^2+\\frac34\\ge\\frac34&gt;0$，所以它对一切实数都是正的，不用解不等式。</p>
      </section>
      <section class="sq-note">
        <h3>和判别式的关系</h3>
        <p data-math-text>$ax^2+bx+c=a\\left(x+\\frac b{2a}\\right)^2+\\frac{4ac-b^2}{4a}$，常数项的分子就是 $-\\Delta$。</p>
        <p>见 <button type="button" class="sq-link" data-explain-open="method-discriminant"></button>。</p>
      </section>
    </div>`;
  },

  mount(root) {
    const last = STEPS.length - 1;
    let step = 0;
    const show = next => {
      step = Math.max(0, Math.min(last, next));
      root.querySelector('[data-sq-layer]').innerHTML = picture(step);
      for (const item of root.querySelectorAll('[data-sq-text]')) {
        const n = Number(item.dataset.sqText);
        item.hidden = n > step;
        item.classList.toggle('sq-current', n === step);
      }
      root.querySelector('[data-sq-move="-1"]').disabled = step === 0;
      root.querySelector('[data-sq-move="1"]').disabled = step === last;
      root.querySelector('[data-sq-all]').disabled = step === last;
    };
    for (const button of root.querySelectorAll('[data-sq-move]')) button.addEventListener('click', () => show(step + Number(button.dataset.sqMove)));
    root.querySelector('[data-sq-all]').addEventListener('click', () => show(last));
    show(0);
  },
};
