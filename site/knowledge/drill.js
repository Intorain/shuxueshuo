/* 刷题 on a node's detail page: the author's short questions (site/data/knowledge/drills/<node>.json, embedded
   by tools/build-knowledge-pages.mjs), one at a time in a dialog. Answers are checked here; nothing is sent or saved. */
import {escapeHtml as escape} from '/assets/explain/shared/html.js?v=1';

const closeIcon = '<svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true"><path d="m4 4 8 8M12 4l-8 8" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>';
let dialog = null;
let run = null;

function shell() {
  if (dialog) return dialog;
  dialog = document.createElement('dialog');
  dialog.className = 'kd-sheet';
  dialog.setAttribute('aria-labelledby', 'kd-title');
  dialog.innerHTML = `<div class="kd-inner">
    <header class="kd-head">
      <span class="kd-kicker">刷题</span>
      <h2 id="kd-title" tabindex="-1"></h2>
      <button class="kd-close" type="button" aria-label="关闭刷题">${closeIcon}</button>
    </header>
    <div class="kd-bar" aria-hidden="true"><span></span></div>
    <div class="kd-body"></div>
  </div>`;
  document.body.append(dialog);
  dialog.addEventListener('click', event => {
    if (event.target.closest('.kd-close, [data-kd-close]')) dialog.close();
    else if (event.target.closest('[data-kd-restart]')) { run = fresh(run.data); render(); }
    else if (event.target.closest('.kd-submit')) submit();
    else if (event.target.closest('.kd-option')) choose(event.target.closest('.kd-option'));
  });
  return dialog;
}

const fresh = data => ({data, index: 0, selected: new Set(), tries: data.items.map(() => 0)});
const math = root => {
  if (window.PracticeMath) for (const element of root.querySelectorAll('[data-math-text]')) window.PracticeMath.render(element, element.textContent);
};
const body = () => dialog.querySelector('.kd-body');

function render() {
  const {data, index} = run;
  const done = index >= data.items.length;
  dialog.querySelector('.kd-bar span').style.width = `${Math.min(index, data.items.length) / data.items.length * 100}%`;
  body().innerHTML = done ? summary() : question(data.items[index], index, data.items.length);
  run.selected = new Set();
  math(body());
  dialog.scrollTop = 0;
  (done ? body().querySelector('[data-kd-restart]') : body().querySelector('.kd-option'))?.focus({preventScroll: true});
}

function question(item, index, total) {
  const multi = item.type === 'multi';
  return `<p class="kd-progress" role="status">第 ${index + 1} / ${total} 题${multi ? '<span class="kd-multi">多选</span>' : ''}</p>
    ${item.given ? `<p class="kd-given" data-math-text>${escape(item.given)}</p>` : ''}
    <p class="kd-question" id="kd-question" data-math-text>${escape(item.question)}</p>
    <div class="kd-options" role="${multi ? 'group' : 'radiogroup'}" aria-labelledby="kd-question">
      ${item.options.map(option => `<button type="button" class="kd-option" role="${multi ? 'checkbox' : 'radio'}" aria-checked="false" data-value="${escape(option.value)}"><span class="kd-box" aria-hidden="true"></span><span class="kd-label" data-math-text>${escape(option.label)}</span></button>`).join('')}
    </div>
    <div class="kd-feedback" role="status" aria-live="polite"></div>
    <div class="kd-actions"><button type="button" class="kd-submit" disabled>提交</button></div>`;
}

function summary() {
  const {items} = run.data;
  const clean = run.tries.filter(count => count === 1).length;
  return `<div class="kd-summary">
      <p class="kd-summary-title">${items.length} 题都做完了</p>
      <p class="kd-summary-note">${clean === items.length ? '全部一次答对。' : `一次答对 ${clean} 题，${items.length - clean} 题改过之后答对。`}</p>
      <ol class="kd-review">${items.map((item, index) => `<li class="${run.tries[index] === 1 ? 'is-clean' : 'is-retried'}">
        <span class="kd-review-text" data-math-text>${escape(item.question)}</span>
        <span class="kd-review-mark">${run.tries[index] === 1 ? '一次答对' : `改了 ${run.tries[index] - 1} 次`}</span></li>`).join('')}</ol>
    </div>
    <div class="kd-actions"><button type="button" class="kd-submit" data-kd-restart>再刷一遍</button><button type="button" class="kd-secondary" data-kd-close>回到图解</button></div>`;
}

function choose(button) {
  const item = run.data.items[run.index];
  const value = button.dataset.value;
  if (item.type === 'multi') run.selected.has(value) ? run.selected.delete(value) : run.selected.add(value);
  else run.selected = new Set([value]);
  for (const option of body().querySelectorAll('.kd-option')) {
    option.setAttribute('aria-checked', String(run.selected.has(option.dataset.value)));
    option.classList.remove('is-wrong');
  }
  body().querySelector('.kd-feedback').innerHTML = '';
  body().querySelector('.kd-submit').disabled = !run.selected.size;
}

function submit() {
  const item = run.data.items[run.index];
  const answer = new Set([item.answer].flat());
  const picked = [...run.selected];
  const wrong = picked.filter(value => !answer.has(value));
  const correct = !wrong.length && picked.length === answer.size;
  run.tries[run.index]++;
  if (correct) {
    run.index++;
    render();
    return;
  }
  const feedback = body().querySelector('.kd-feedback');
  const option = value => item.options.find(entry => entry.value === value);
  for (const button of body().querySelectorAll('.kd-option')) button.classList.toggle('is-wrong', wrong.includes(button.dataset.value));
  const notes = wrong.length ? wrong.map(value => option(value).feedback) : ['选对的还不全，还有正确的选项没选上。'];
  feedback.innerHTML = `<div class="kd-wrong">${notes.map(note => `<p data-math-text>${escape(note)}</p>`).join('')}<p class="kd-retry">改一改，再提交。</p></div>`;
  math(feedback);
  feedback.scrollIntoView({block: 'nearest', behavior: 'smooth'});
}

// Reopening the same set mid-way continues where the student stopped; a finished set starts over.
export function openDrill(data) {
  shell();
  if (!run || run.data !== data || run.index >= data.items.length) run = fresh(data);
  dialog.querySelector('#kd-title').textContent = data.label;
  if (!dialog.open) dialog.showModal();
  render();
}
