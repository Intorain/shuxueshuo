/* Matching: add and subtract constants until the product or sum is fixed. */
import {problemNote} from '../shared/html.js?v=1';

const figure = tag => `<div class="method-figure">
      <div class="method-template"><span class="method-word">原式</span><span class="op">=</span><span class="slot square"></span><span class="op">+</span><span class="slot circle"></span><span class="op">+</span><span class="method-word">常数</span></div>
      <p class="method-demo"><span class="method-demo-tag">${tag}</span><span class="method-demo-body"><span class="method-demo-group"><math><mn>2</mn><mi>x</mi><mo>+</mo><mfrac><mrow><mn>2</mn></mrow><mrow><mi>x</mi><mo>−</mo><mn>1</mn></mrow></mfrac></math></span><span class="method-demo-group"><span class="op">=</span><span class="term square"><math><mn>2</mn><mo>(</mo><mi>x</mi><mo>−</mo><mn>1</mn><mo>)</mo></math></span><span class="op">+</span><span class="term circle"><math><mfrac><mrow><mn>2</mn></mrow><mrow><mi>x</mi><mo>−</mo><mn>1</mn></mrow></mfrac></math></span><span class="op">+</span><math><mn>2</mn></math></span></span></p>
      <p class="method-pill">补进的常数要在式外减回</p>
    </div>`;

export default {
  figure: () => figure('例'),

  render: ({tip}) => `
    <p class="method-core"><span class="method-tag">核心</span><span>积、和都不是定值时，先加减常数或拆项，凑出定积或定和。</span></p>
    ${tip?.note ? `<p class="method-problem"><span class="method-problem-badge">本题</span><span data-math-text>${problemNote(tip.note)}</span></p>` : ''}
    ${figure('第 06 题')}
    <ol class="method-steps" aria-label="解题三步">
      <li><span class="method-step-no" aria-hidden="true">1</span><strong>定配凑目标</strong><span>看分母、根号，定出 <span class="mini-slot square" aria-label="方框"></span>、<span class="mini-slot circle" aria-label="圆圈"></span></span></li>
      <li><span class="method-step-no" aria-hidden="true">2</span><strong>加减配凑</strong><span>补项再减回，原式保持不变</span></li>
      <li><span class="method-step-no" aria-hidden="true">3</span><strong>验证取等</strong><span><span class="mini-slot square" aria-label="方框"></span> = <span class="mini-slot circle" aria-label="圆圈"></span> 且在范围内</span></li>
    </ol>`,
};
