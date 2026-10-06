/* Student-led board. Server owns mathematics and the context; browser owns drafts and selection. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const endpoint = '/api/tutor-demo/explanation/sessions';
  const TWO = ['claim', 'amgm', 'attain'];
  const NO_ARGUMENTS = ['expand', 'combine'];
  const SOURCE = {stated: '你说的', prompted: '提示后说出'};
  // page: only page controls; mixed: page controls plus free explanation.
  const PAGE = document.body.dataset.mode === 'page';
  const LETTERS = ['x', 'y', 'a', 'b', 'u', 'v', 't'];
  const TEMPLATES = {
    claim: [['a'], ' = ', ['b']],
    substitute: ['设 ', ['name'], ' = ', ['a']],
    multiply: ['给整个式子乘 ', ['a']],
    amgm: ['对 ', ['a'], ' 和 ', ['b'], ' 用基本不等式'],
    attain: ['当 ', ['a'], ' = ', ['b'], ' 时取等'],
  };
  const describe = o => ({claim: `${o.a} = ${o.b}`, substitute: `设 ${o.name} = ${o.a}`, multiply: `给当前式子乘 (${o.a})`,
    expand: '展开当前式子', combine: '合并分母相同的项', amgm: `对 ${o.a} 和 ${o.b} 用基本不等式`, attain: `当 ${o.a} = ${o.b} 时取等`})[o.op];
  const INITIAL = {
    steps: [], turns: [], branches: [{id: '', label: '思路 1', steps: 0}], branch_id: '',
    focus: {thread_id: '', step_id: null, step_number: null, turn_ids: [], attempts: [], clarifications: []},
    state: {marked: '', conditions: [], definitions: [], objects: [], symbols: [], complete: false},
    choices: null
  };
  let view = null, busy = false, pending = null, epoch = 0, actor = null;
  let selected = [];
  let loadingChoices = false;
  let template = null, slot = null;   // page mode: the open sentence template and its active blank
  const node = (tag, cls, text) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  };
  const button = (label, onClick, cls = 'explain-quiet') => {
    const b = node('button', cls, label); b.type = 'button'; b.addEventListener('click', onClick); return b;
  };
  const prose = (parent, text, cls) => { const p = node('p', cls); window.PracticeMath.render(p, text); parent.append(p); return p; };
  const tex = (element, latex, display = false) => {
    // Model-authored formulas may never create HTML, links or interactive attributes.
    window.katex.render(latex, element, {displayMode: display, throwOnError: false, strict: 'ignore',
      trust: false});
    return element;
  };
  const formula = (parent, latex) => {
    parent.append(window.ExplanationMath.renderLine(node('div', 'explain-line'), latex));
  };
  const current = () => view || INITIAL;
  const turnsById = () => new Map(current().turns.map(t => [t.id, t]));
  const objectLatex = expression => current().state.objects.find(o => o.expression === expression)?.latex || expression;

  function echo(parent, segments) {
    const p = node('p', 'explain-echo');
    p.append(node('span', 'explain-echo-label', PAGE ? '你的操作：' : '我理解为：'));
    for (const segment of segments) {
      if (segment.math === undefined) { p.append(document.createTextNode(segment.text)); continue; }
      const span = tex(node('span', segment.inferred ? 'explain-inferred' : ''), segment.math);
      if (segment.inferred) span.title = '这是我根据你的指代推断的；不对的话可以追问这一步';
      p.append(span);
    }
    if (segments.some(s => s.inferred)) p.append(node('span', 'explain-echo-note', '（虚线框是我推断的对象）'));
    parent.append(p);
  }

  function dialogue(parent, ids) {
    const turns = turnsById();
    for (const id of ids) {
      const turn = turns.get(id);
      if (!turn) continue;
      const bubble = node('div', `explain-turn ${turn.speaker}`);
      if (turn.speaker === 'student') bubble.textContent = turn.text;
      else window.PracticeMath.render(bubble, turn.text);
      parent.append(bubble);
    }
  }

  function card(step, index) {
    const article = node('article', 'explain-card');
    article.dataset.stepId = step.id;
    const header = node('header');
    header.append(node('span', 'explain-step-number', index + 1), node('h2', '', step.title));
    article.append(header);
    if (step.change && step.action) prose(article, step.action, 'explain-action');
    if (step.change) {
      const change = node('section', 'explain-change');
      change.setAttribute('aria-label', '本次操作带来的数学变化');
      const before = node('div', 'explain-change-before');
      before.append(node('span', 'explain-change-label', '使用的式子'));
      formula(before, step.change.before);
      // This arrow denotes the selected operation, not equality between two
      // possibly different kinds of objects (an expression, condition or bound).
      const direction = node('div', 'explain-change-relation', '→');
      direction.setAttribute('aria-label', '执行所选操作');
      const after = node('div', 'explain-change-after');
      after.append(node('span', 'explain-change-label', '本步结果'));
      formula(after, step.change.after);
      change.append(before, direction, after);
      article.append(change);
    }
    if (step.highlight) {
      const highlight = node('section', step.change ? 'explain-highlight explain-change-summary' : 'explain-highlight');
      highlight.append(node('h3', '', step.highlight.kind === 'problem' ? '当前问题化为' : '本步得到'));
      prose(highlight, step.highlight.content, 'explain-highlight-content');
      article.append(highlight);
    }
    const turns = turnsById();
    const words = step.turn_ids.map(id => turns.get(id)).filter(t => t?.speaker === 'student').map(t => t.text);
    // Page operations have no words of their own; the echo below already shows them.
    if (words.length && !PAGE && !step.change) article.append(node('blockquote', 'explain-source', words.join('\n')));
    if (step.echo && !step.derivation) echo(article, step.echo);
    if (step.component === 'amgm') {
      const visual = node('div');
      // Shared component escapes all label values before producing HTML.
      visual.innerHTML = window.PracticeComponents.completedAmgm(step.visual);
      visual.querySelectorAll('[data-math-text]').forEach(el => window.PracticeMath.render(el, el.textContent));
      article.append(visual);
    }
    const result = node('div', step.highlight ? 'explain-result explain-proof' : 'explain-result');
    if (step.highlight) result.append(node('h3', 'explain-proof-title', '数学推导'));
    if (step.derivation) {
      for (const row of step.derivation) {
        const line = node('div', 'explain-derivation-row');
        if (row.lead) line.append(node('span', 'explain-derivation-lead', row.lead));
        formula(line, row.math);
        result.append(line);
      }
    } else formula(result, step.result);
    article.append(result);
    const said = step.judgments.filter(j => !j.implied);
    if (said.length) {
      const list = node('ul', 'explain-judgments');
      for (const j of said) {
        const item = node('li', j.correct ? 'ok' : 'wrong', `${j.correct ? '✓' : '✗'} ${j.label}`);
        item.append(node('span', 'explain-judgment-source', ` · ${SOURCE[j.source] || ''}：“${j.quote}”`));
        list.append(item);
      }
      article.append(list);
    }
    if (!step.derivation) {
      const details = node('details'); details.append(node('summary', '', '系统代算 · 展开计算依据'));
      step.lines.forEach(line => formula(details, line)); article.append(details);
    }
    const talk = node('details', 'explain-dialogue');
    talk.append(node('summary', '', `对话 ${step.turn_ids.length}`));
    dialogue(talk, step.turn_ids); article.append(talk);
    const actions = node('div', 'explain-card-actions');
    if (!PAGE) actions.append(button('追问这一步', () => send({kind: 'focus', step_id: step.id})));
    actions.append(button('从这里换个思路', () => send({kind: 'fork', step_count: step.step_count ?? index + 1})));
    article.append(actions);
    return article;
  }

  function report(steps) {
    const box = node('section', 'explain-report');
    box.append(node('h2', '', '解题记录'));
    const list = node('ol');
    for (const step of steps) {
      const item = node('li', '', step.title);
      if (step.inferred.length) item.append(node('span', 'explain-report-note', ' · 有对象由系统根据指代推断'));
      const said = step.judgments.filter(j => j.correct && !j.implied).map(j => j.label);
      if (said.length) item.append(node('span', 'explain-report-note', ` · 讲出的理由：${said.join('、')}`));
      if (step.via === 'candidate') item.append(node('span', 'explain-report-note', ' · 从候选中选择'));
      list.append(item);
    }
    box.append(list);
    box.append(node('p', 'explain-note', '以上推导由系统根据你选择的操作生成。'));
    return box;
  }

  function renderBoard() {
    const {state} = current();
    const steps = current().board_steps || current().steps;
    const board = $('board');
    board.replaceChildren();
    steps.forEach((step, index) => board.append(card(step, index)));
    if (state.complete) board.append(report(steps));
  }

  function renderFormula() {
    const {state} = current();
    const host = $('current-expression');
    tex(host, state.marked, true);
    const picks = node('div', 'explain-key-objects');
    for (const object of state.objects) {
      const b = button('', () => toggle(object.expression), 'explain-key explain-key-object');
      tex(b, object.latex); b.disabled = busy || loadingChoices;
      b.setAttribute('aria-pressed', String(selected.includes(object.expression)));
      picks.append(b);
    }
    host.append(picks);
    $('conditions').replaceChildren(...[...(state.definitions || []), ...state.conditions].map(line => tex(node('span'), line)));

  }

  function toggle(expression) {
    if (busy) return;
    if (template && slot) { insert(expression); return; }
    selected = selected.includes(expression) ? selected.filter(v => v !== expression) : [...selected.slice(-1), expression];
    if (!PAGE) {
      $('operand-a').value = selected[0] || '';
      $('operand-b').value = selected[1] || '';
    }
    renderFormula(); renderSelected();
    renderCandidates();
  }

  // ---- page mode: sentence templates with a small math keypad -------------
  function insert(text, raw = false) {
    if (!slot) return;
    // A picked object is one quantity: bracket it unless it fills the blank on its own.
    const piece = raw || !slot.value.trim() || /^[\w.]+$/.test(text) ? text : `(${text})`;
    slot.setRangeText(piece, slot.selectionStart ?? slot.value.length, slot.selectionEnd ?? slot.value.length, 'end');
    slot.focus();
    draftChanged();
  }

  function keypad() {
    const pad = $('keypad');
    pad.replaceChildren();
    const keys = [['7'], ['8'], ['9'], ['+'], ['('], [')'], ['4'], ['5'], ['6'], ['−', '-'],
      ['1'], ['2'], ['3'], ['×', '*'], ['0'], ['÷', '/'], ...(current().state.symbols || []).map(k => [k])];
    for (const [label, text = label] of keys) pad.append(button(label, () => insert(text, true), 'explain-key'));
    pad.append(button('⌫', () => {
      if (!slot) return;
      const at = slot.selectionStart ?? slot.value.length;
      if (at === (slot.selectionEnd ?? at) && at > 0) slot.setRangeText('', at - 1, at, 'end');
      else slot.setRangeText('', slot.selectionStart, slot.selectionEnd, 'end');
      slot.focus(); draftChanged();
    }, 'explain-key'));
    const objects = node('div', 'explain-key-objects');
    objects.append(node('span', 'explain-note', '放入式子里的项：'));
    for (const object of current().state.objects) {
      const b = button('', () => insert(object.expression), 'explain-key explain-key-object');
      tex(b, object.latex); objects.append(b);
    }
    pad.append(objects);
    // Keep the caret in the blank: keypad presses must not take focus.
    pad.querySelectorAll('button').forEach(b => b.addEventListener('pointerdown', e => e.preventDefault()));
  }

  function openTemplate(op, known = {}) {
    if (NO_ARGUMENTS.includes(op)) { send({kind: 'operation', operation: {op, a: '', b: '', name: ''}, text: describe({op}), via: 'template'}); return; }
    $('own').open = true;
    const used = current().state.symbols || [];
    template = {op, name: known.name || LETTERS.find(l => !used.includes(l)) || 'x'};
    const line = $('template-line');
    line.replaceChildren();
    const picks = [known.a || selected[0] || '', known.b || selected[1] || ''];
    for (const part of TEMPLATES[op]) {
      if (typeof part === 'string') { line.append(node('span', 'explain-template-text', part)); continue; }
      if (part[0] === 'name') {
        const names = node('span', 'explain-names');
        for (const letter of LETTERS.filter(l => !used.includes(l))) {
          const b = button(letter, () => { template.name = letter; names.querySelectorAll('button').forEach(x => x.setAttribute('aria-pressed', String(x.textContent === letter))); }, 'explain-name');
          b.setAttribute('aria-pressed', String(letter === template.name));
          names.append(b);
        }
        line.append(names);
        continue;
      }
      const input = node('input', 'explain-slot');
      input.dataset.arg = part[0]; input.maxLength = 120; input.autocomplete = 'off'; input.spellcheck = false;
      input.value = part[0] === 'a' ? picks[0] : picks[1];
      for (const type of ['focus', 'pointerdown']) input.addEventListener(type, () => { slot = input; markSlot(); });
      line.append(input);
    }
    document.querySelectorAll('#actions [data-op]').forEach(b => b.classList.toggle('active', b.dataset.op === op));
    $('template').hidden = false;
    keypad();
    const blanks = [...line.querySelectorAll('.explain-slot')];
    slot = blanks.find(b => !b.value) || blanks[0];
    markSlot(); slot.focus();
    selected = []; renderSelected(); renderFormula();
  }

  function markSlot() { document.querySelectorAll('.explain-slot').forEach(b => b.classList.toggle('active', b === slot)); }

  function closeTemplate() {
    template = null; slot = null;
    if ($('template')) $('template').hidden = true;
    document.querySelectorAll('#actions [data-op]').forEach(b => b.classList.remove('active'));
  }

  function segments(parent, items, blank = null) {
    for (const item of items) {
      if (item.blank) parent.append(blank || node('span', 'explain-blank', '？'));
      else if (item.math === undefined) parent.append(document.createTextNode(item.text));
      else parent.append(tex(node('span'), item.math));
    }
  }

  function renderCandidates() {
    const host = $('candidates');
    if (!host) return;
    host.replaceChildren();
    if (current().state.complete) {
      host.append(node('p', 'explain-note', '本次推导已完成，可以回看或从前面尝试其他思路。'));
      return;
    }
    if (loadingChoices) return;
    const batch = current().choices;
    if (!batch) {
      host.append(button(actor ? '生成可选操作' : '登录后生成可选操作', () => loadChoices(), 'explain-candidate-op'));
      return;
    }
    for (const choice of batch.candidates.slice(0, 3)) {
      const b = button('', () => send({kind: 'candidate', candidate_id: choice.id}), 'explain-candidate-op');
      window.PracticeMath.render(b, choice.label);
      host.append(b);
    }
    if (!batch.candidates.length) {
      host.append(node('p', 'explain-note', '暂未找到可建议的操作，可以自己写一步或回退。'));
      host.append(button('重新生成选项', () => send({kind: 'refresh'}), 'explain-candidate-op'));
    }
  }

  async function loadChoices(promptLogin = true) {
    if (busy || loadingChoices || view?.choices) return;
    loadingChoices = true;
    const ticket = epoch;
    renderCandidates(); controls();
    try {
      const auth = window.SiteAuth;
      if (!auth) throw new Error('登录服务尚未准备好，请稍后重试。');
      const user = promptLogin ? await auth.requireLogin({intro: '登录后生成这道题的可选操作。'}) : auth.user;
      if (!user || ticket !== epoch) return;
      if (!view) view = await request(endpoint, {});
      if (ticket !== epoch) return;
      const response = await request(`${endpoint}/${view.session_id}/candidates`, {});
      if (ticket !== epoch) return;
      view = response;
      $('network-status').textContent = '';
    } catch (error) {
      if (ticket !== epoch) return;
      if ([401, 404].includes(error.status)) { view = null; if (error.status === 401) window.SiteAuth?.refresh(); }
      $('network-status').textContent = error.name === 'AbortError'
        ? '生成时间较长，可以重试；已生成的选项会保留。' : error.message;
    } finally {
      if (ticket === epoch) { loadingChoices = false; render(); }
    }
  }

  function renderSelected() {
    const box = $('selected');
    box.replaceChildren();
    if (!selected.length) return;
    box.append(node('span', 'explain-selected-label', '已选：'));
    for (const expression of selected) {
      const chip = node('span', 'explain-chip');
      chip.append(tex(node('span'), objectLatex(expression)), button('×', () => toggle(expression), 'explain-chip-remove'));
      box.append(chip);
    }
  }

  function prefill(op, known = {}, focusField = null) {
    if (PAGE) { openTemplate(op, known); return; }
    $('tools').open = true;
    $('operation').value = op; fields();
    $('operand-a').value = known.a || selected[0] || '';
    $('operand-b').value = known.b || selected[1] || '';
    $('variable-name').value = known.name || '';
    const target = {a: 'operand-a', b: 'operand-b', name: 'variable-name'}[focusField];
    ($(target) || $('operand-a')).focus();
  }

  function renderFrontier() {
    const {focus} = current();
    const banner = $('focus-banner');
    banner.hidden = !focus.step_id;
    if (focus.step_id) {
      $('focus-text').replaceChildren();
      window.PracticeMath.render($('focus-text'), `正在讨论第 ${focus.step_number} 步，可以就这一步提问。`);
    }
    $('thread').replaceChildren();
    dialogue($('thread'), focus.turn_ids);

    $('attempts').replaceChildren();
    for (const attempt of focus.attempts.slice(-1)) {
      const draft = node('article', 'explain-draft');
      draft.append(node('span', 'explain-draft-label', '这次尝试没有成立，不会进入板书'));
      echo(draft, attempt.echo);
      prose(draft, attempt.reply);
      const actions = node('div', 'explain-card-actions');
      actions.append(button('改一下', () => prefill(attempt.operation.op, attempt.operation)),
        button('换个想法', () => { if (!PAGE) $('message').value = ''; closeTemplate(); send({kind: 'abandon'}); }));
      draft.append(actions); $('attempts').append(draft);
    }

    $('clarify').replaceChildren();
    for (const c of focus.clarifications) {
      const box = node('div', 'explain-clarify');
      prose(box, c.question);
      if (c.kind === 'ambiguous_ref' && c.candidates.length) {
        box.append(node('p', 'explain-note', '在上面的式子里点选，或者直接点下面的候选项：'));
        const row = node('div', 'explain-candidates');
        for (const expression of c.candidates) {
          const b = button('', () => toggle(expression), 'explain-candidate');
          tex(b, objectLatex(expression)); b.setAttribute('aria-pressed', String(selected.includes(expression)));
          row.append(b);
        }
        box.append(row);
        if (c.op) box.append(button('用选中的对象填写这一步', () => prefill(c.op, c.known, c.missing)));
      }
      if (c.kind === 'missing_arg' && c.op) {
        const label = {a: '缺的式子', b: '第二个式子', name: '新变量名'}[c.missing] || '缺的部分';
        box.append(button(`直接填写${label}`, () => prefill(c.op, c.known, c.missing)));
      }
      $('clarify').append(box);
    }
  }

  function renderChrome() {
    const {branches, branch_id: active} = current();
    $('branch-tabs').replaceChildren(...(branches.length > 1 ? branches.map(b => {
      const tab = button(`${b.label} · ${b.steps} 步`, () => { if (b.id !== active) send({kind: 'switch', branch_id: b.id}); }, 'explain-tab');
      tab.setAttribute('role', 'tab'); tab.setAttribute('aria-selected', String(b.id === active));
      return tab;
    }) : []));
  }

  function controls() {
    $('frontier').setAttribute('aria-busy', String(busy || loadingChoices));
    $('generation-status').hidden = !(busy || loadingChoices);
    $('generation-status').textContent = loadingChoices ? '正在生成可选操作…' : busy ? '正在生成本步推导和下一步选项…' : '';
    for (const el of document.querySelectorAll('.workspace button, .workspace select, .workspace input, #restart')) el.disabled = busy || loadingChoices;
    if (!PAGE) {
      $('send').disabled = busy || loadingChoices || !$('message').value.trim();
      $('message').disabled = busy || loadingChoices;
    }
    if ($('undo')) $('undo').disabled = busy || loadingChoices || !current().steps.length;
    $('frontier-title').textContent = busy ? '正在生成推导和下一步选项…' : (PAGE ? '可选对象' : '现在的式子');
  }

  function render() {
    selected = selected.filter(v => current().state.objects.some(o => o.expression === v));
    renderChrome(); renderBoard(); renderFormula(); renderSelected(); renderFrontier();
    renderCandidates();
    controls();
  }

  async function request(url, body) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 115000);
    try {
      const response = await fetch(url, {method: body === undefined ? 'GET' : 'POST', credentials: 'same-origin',
        headers: {'Content-Type': 'application/json'}, body: body === undefined ? undefined : JSON.stringify(body), signal: controller.signal});
      const data = await response.json();
      if (!response.ok) {
        const error = new Error(typeof data.detail === 'string' ? data.detail : '这次输入还不完整，请检查后重试。');
        error.status = response.status; error.snapshot = data.snapshot; throw error;
      }
      return data;
    } finally { clearTimeout(timeout); }
  }

  async function send(input, retry = false) {
    if (busy || loadingChoices) return;
    busy = true; controls(); $('network-status').textContent = ''; $('retry').hidden = true;
    const ticket = epoch;
    try {
      if (!window.SiteAuth) throw new Error('登录服务尚未准备好，请稍后再试。');
      const user = await window.SiteAuth.requireLogin({intro: '登录后开始这次讲解。'});
      if (!user || ticket !== epoch) return;
      if (!view) view = await request(endpoint, {});
      if (ticket !== epoch) return;
      if (!retry || !pending) pending = {event_id: crypto.randomUUID(), revision: view.revision, ...input};
      const response = await request(`${endpoint}/${view.session_id}/events`, pending);
      if (ticket !== epoch) return;
      const accepted = pending;
      view = response; pending = null;
      if (['text', 'operation', 'candidate', 'help'].includes(accepted.kind)) selected = [];
      if (PAGE) {
        if (['undo', 'fork', 'switch', 'operation', 'candidate', 'abandon'].includes(accepted.kind)) { closeTemplate(); $('own').open = false; }
      } else {
        if (['undo', 'fork', 'switch', 'operation'].includes(accepted.kind)) {
          $('operand-a').value = ''; $('operand-b').value = ''; $('variable-name').value = '';
        }
        if (accepted.kind === 'operation') $('tools').open = false;
        if (accepted.kind === 'text' && $('message').value.trim() === accepted.text) $('message').value = '';
      }
      busy = false;
      render();
      if (!PAGE && view.feedback?.reply && ['undo', 'fork', 'switch'].includes(accepted.kind)) $('network-status').textContent = view.feedback.reply;
      if (PAGE) {
        // Shown only when the reply is not already the last message of the visible discussion.
        const last = turnsById().get(view.focus.turn_ids.at(-1));
        const reply = view.feedback?.reply || '';
        $('feedback').replaceChildren();
        if (last?.text !== reply) window.PracticeMath.render($('feedback'), reply);
      }
      if (accepted.kind === 'candidate' || (accepted.kind === 'operation' && view.steps.length)) {
        ($('board').lastElementChild || $('frontier')).scrollIntoView({block: 'start', behavior: 'smooth'});
      } else if (['text', 'operation', 'help', 'focus'].includes(accepted.kind)) {
        $('frontier').scrollIntoView({block: 'start', behavior: 'smooth'});
      }
    } catch (error) {
      if (ticket !== epoch) return;
      if (error.snapshot) { view = error.snapshot; pending = null; busy = false; render(); }
      if (error.status === 404) { view = null; pending = null; }
      if (error.status === 401) { view = null; pending = null; window.SiteAuth?.refresh(); }
      if (error.status === 422) pending = null;
      $('network-status').textContent = error.name === 'AbortError' ? '等待时间较长，输入已保留。重试不会重复添加步骤。' : error.message || '连接失败，输入已保留。';
      $('retry').hidden = !pending;
    } finally { if (ticket === epoch) { busy = false; controls(); renderFormula(); } }
  }

  function fields() {
    const op = $('operation').value;
    $('a-label').hidden = NO_ARGUMENTS.includes(op);
    $('b-label').hidden = !TWO.includes(op);
    $('name-label').hidden = op !== 'substitute';
    $('operand-a').required = !NO_ARGUMENTS.includes(op);
    $('operand-b').required = TWO.includes(op);
    $('variable-name').required = op === 'substitute';
    $('a-label').querySelector('span').textContent = {claim: '等式左边', substitute: '看成整体的式子', multiply: '乘数', amgm: '第一项', attain: '取等关系左边'}[op] || '式子';
    $('b-label').querySelector('span').textContent = op === 'amgm' ? '第二项' : '等式右边';
  }

  $('current-expression').addEventListener('click', event => {
    // KaTeX fraction layers overlap nested parts, so pick the smallest object box under the pointer.
    const hits = [...$('current-expression').querySelectorAll('[data-obj]')].map(el => [el, el.getBoundingClientRect()])
      .filter(([, r]) => r.width && event.clientX >= r.left && event.clientX <= r.right && event.clientY >= r.top && event.clientY <= r.bottom)
      .sort(([, a], [, b]) => a.width * a.height - b.width * b.height);
    const el = hits[0]?.[0] || event.target.closest('[data-obj]');
    const object = el && current().state.objects[Number(el.dataset.obj)];
    if (object) toggle(object.expression);
  });
  $('current-expression').addEventListener('keydown', event => {
    if (event.key !== 'Enter' && event.key !== ' ') return;
    const el = event.target.closest('[data-obj]');
    const object = el && current().state.objects[Number(el.dataset.obj)];
    if (object) { event.preventDefault(); toggle(object.expression); }
  });
  function draftChanged() { pending = null; $('retry').hidden = true; controls(); }
  $('help').addEventListener('click', () => send({kind: 'help', text: '给点提示', selected}));
  $('leave-focus').addEventListener('click', () => send({kind: 'focus', step_id: null}));
  $('undo')?.addEventListener('click', () => send({kind: 'undo'}));
  $('retry').addEventListener('click', () => { if (pending) send(pending, true); });
  if (PAGE) {
    $('actions').addEventListener('click', event => {
      const op = event.target.closest('[data-op]')?.dataset.op;
      if (op && !busy) openTemplate(op);
    });
    $('template').addEventListener('input', draftChanged);
    $('template-cancel').addEventListener('click', closeTemplate);

    $('template').addEventListener('submit', event => {
      event.preventDefault();
      const value = arg => $('template-line').querySelector(`[data-arg="${arg}"]`)?.value.trim() || '';
      const operation = {op: template.op, a: value('a'), b: value('b'), name: template.op === 'substitute' ? template.name : ''};
      const blank = [...$('template-line').querySelectorAll('.explain-slot')].find(b => !b.value.trim());
      if (blank) { slot = blank; markSlot(); blank.focus(); $('network-status').textContent = '还有空没有填。'; return; }
      send({kind: 'operation', operation, text: describe(operation), via: 'template'});
    });
  } else {
    $('operation').addEventListener('change', fields);
    $('message').addEventListener('input', draftChanged);
    $('operation-form').addEventListener('input', draftChanged);
    $('message').addEventListener('keydown', event => {
      if (event.key === 'Enter' && (event.ctrlKey || event.metaKey) && !event.isComposing) { event.preventDefault(); $('send').click(); }
    });
    $('send').addEventListener('click', () => send({kind: 'text', text: $('message').value.trim(), selected}));
    $('operation-form').addEventListener('submit', event => {
      event.preventDefault();
      const op = $('operation').value;
      const operation = {op, a: NO_ARGUMENTS.includes(op) ? '' : $('operand-a').value.trim(), b: TWO.includes(op) ? $('operand-b').value.trim() : '', name: op === 'substitute' ? $('variable-name').value.trim() : ''};
      send({kind: 'operation', operation, text: describe(operation)});
    });
  }
  function clear() {
    epoch++; view = null; pending = null; selected = []; busy = false; loadingChoices = false;
    if (PAGE) { closeTemplate(); $('own').open = false; $('feedback').replaceChildren(); } else $('message').value = '';
    $('retry').hidden = true; $('network-status').textContent = '';
    render();
  }
  $('restart').addEventListener('click', () => { clear(); if (actor) loadChoices(false); });
  window.addEventListener('site-auth-change', event => {
    const next = event.detail.user?.id || null;
    if (actor !== null && actor !== next) clear();
    const changed = actor !== next;
    actor = next;
    if (next && changed) loadChoices(false);
  });
  document.querySelectorAll('[data-math-text]').forEach(el => window.PracticeMath.render(el, el.textContent));
  if (!PAGE) fields();
  render();
  if (window.SiteAuth?.user) { actor = window.SiteAuth.user.id; loadChoices(false); }
})();
