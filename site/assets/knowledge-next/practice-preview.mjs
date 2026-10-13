import { select, confirmedChoices, libraryPath, previewTarget } from './teaching-model.mjs';
import { KINDS, splitRef, nodeHref } from './model.mjs';
import { escapeHtml as h } from './resource-links.mjs';
import { stylesheet, mountResource } from './resource-runtime.mjs';

function math(root) {
  root.querySelectorAll('[data-math-text]').forEach((el) => {
    if (!el.querySelector('.katex')) window.PracticeMath?.render(el, el.textContent);
  });
}
async function read(url) {
  const response = await fetch(url, { cache: 'no-cache' });
  if (!response.ok) throw Error(`加载失败（${response.status}）`);
  return response.json();
}
export async function createPreview(lesson, host, {learning = false, onShown = null, getConfirmedChoices = null, getPassedFields = null, expectedContentVersion = null} = {}) {
  const [problem, catalog] = await Promise.all([
    read(`/knowledge-next/teaching/problems/${encodeURIComponent(lesson.id)}.json`),
    read('/knowledge-next/teaching/catalog.json'),
    stylesheet(new URL('./practice-preview.css', import.meta.url).pathname)
  ]);
  if (expectedContentVersion && problem.content_version !== expectedContentVersion) {
    throw Object.assign(Error('本题关联版本已变化，请刷新页面后再保存。'), {code: 'content_version_mismatch'});
  }
  const topic = `/knowledge-next/topics/${problem.topic}/`;
  const modeHref = path => {
    if (!learning) return path;
    const url = new URL(path, location.href);
    url.searchParams.set('learning', '1');
    return url.pathname + url.search + url.hash;
  };
  const label = (ref) => {
    const { id, entry } = splitRef(ref),
      n = catalog[id];
    return `${n.label}${entry ? ` · ${n.entries[entry]}` : ''}`;
  };
  const chip = (ref) =>
    `<a href="${modeHref(nodeHref(ref))}">${h(label(ref))}<small>${KINDS[catalog[splitRef(ref).id].kind]}</small></a>`;
  const choiceSteps = Object.values(lesson.routes)
    .flat()
    .filter((s) => s.interaction.type === 'choice');
  const optionValues = Object.fromEntries(
    choiceSteps.map((s) => [s.interaction.field, s.interaction.options.map((o) => o.value)])
  );
  function selection(tree, choices, passed) {
    const { actual, candidates, withheld } = select(tree, choices, optionValues, passed);
    const refs = [...new Set(actual.flatMap((b) => b.value))];
    return `${refs.map(chip).join('')}${candidates.length ? `<span class="kxp-candidates">候选关联（未确认选择）：${[...new Set(candidates.flatMap((b) => b.value))].map(chip).join('')}</span>` : ''}${withheld ? '<span class="kxp-candidates">作答后显示对应关联</span>' : ''}`;
  }
  const box = document.createElement('section');
  box.className = 'kxp-associations';
  box.setAttribute('aria-label', '新教学关联');
  host.append(box);
  // Preserve the preview on topic/back/adjacent-problem navigation.
  const targets = { paths: problem.problemPaths, library: libraryPath(problem.path), topic, learning };
  for (const a of document.querySelectorAll('a[href]')) {
    const url = new URL(a.href, location.href);
    if (url.origin !== location.origin) continue;
    const href = previewTarget(url, targets);
    if (href) a.href = href;
  }
  const choices = Object.fromEntries(choiceSteps.map((s) => [s.interaction.field, s.interaction.options]));
  const conditionLabel = (conditions) =>
    Object.entries(conditions)
      .map(([field, value]) => choices[field]?.find((o) => o.value === value)?.label || value)
      .join('，');
  const confirmed = (state) => learning ? (getConfirmedChoices?.() || {}) : confirmedChoices(lesson.routes[state.method], state);
  const passedFields = (state) => learning ? (getPassedFields?.() || []) : (lesson.routes[state.method] || [])
    .slice(0, state.active).filter(step => step.interaction.type === 'choice').map(step => step.interaction.field);
  const resources = new Map();
  function readResource(id) {
    if (!resources.has(id)) {
      resources.set(
        id,
        read(`/knowledge-next/teaching/resources/${encodeURIComponent(id)}.json`).catch((error) => {
          resources.delete(id);
          throw error;
        })
      );
    }
    return resources.get(id);
  }
  let dialog = null,
    cleanup = null,
    ticket = 0;
  function update(snapshot) {
    const route = problem.routes[snapshot.state.method],
      picked = confirmed(snapshot.state), passed = passedFields(snapshot.state);
    box.innerHTML = `<nav><a href="${modeHref(topic)}">返回专题</a> · <a href="${modeHref(topic + "review/")}">关联审阅表</a> · <a href="${modeHref("/knowledge-next/")}">新图谱</a></nav><p>公共题型：${problem.types.map(chip).join('')}</p>${route ? `<p>本路线方法：${selection(route.methods, picked, passed)}</p>` : '<p>选择解题路线后查看对应方法。</p>'}`;
    document.querySelectorAll('.kxp-step-refs').forEach((el) => el.remove());
    if (route)
      lesson.routes[snapshot.state.method].forEach((step, i) => {
        const card = document.getElementById(`step-${i}`);
        if (!card) return;
        const refs = document.createElement('div');
        refs.className = 'kxp-step-refs';
        refs.innerHTML = `<span>本步关联</span>${selection(route.steps[step.id].refs, picked, passed)}`;
        card.append(refs);
      });
    // Do not leave a sheet from a previous route/attempt on screen.
    if (dialog?.open) dialog.close();
  }
  function close() {
    ticket++;
    cleanup?.();
    cleanup = null;
  }
  async function openStep(rid, stage, snapshot) {
    const step = problem.routes[rid]?.steps[lesson.routes[rid]?.[stage]?.id];
    if (!step?.tip) return;
    if (!dialog) {
      dialog = document.createElement('dialog');
      dialog.className = 'kxp-sheet';
      dialog.setAttribute('aria-labelledby', 'kxp-sheet-title');
      dialog.innerHTML =
        '<header><h2 id="kxp-sheet-title">学习提示</h2><button type="button" aria-label="关闭学习提示">关闭</button></header><div class="kxp-sheet-body"></div>';
      document.body.append(dialog);
      dialog.querySelector('header button').onclick = () => dialog.close();
      dialog.addEventListener('close', close);
    }
    close();
    if (!dialog.open) dialog.showModal();
    const selection = select(step.tip, confirmed(snapshot.state), optionValues, passedFields(snapshot.state)),
      passed = stage < snapshot.state.active;
    const items = [...selection.actual, ...selection.candidates];
    const body = dialog.querySelector('.kxp-sheet-body');
    if (!items.length) {
      body.textContent = selection.withheld
        ? '这一步的提示和你的选择有关，作答后显示对应提示。'
        : '当前选择未匹配有效关联。可以继续修改答案。';
      return;
    }
    if (selection.candidates.length) {
      body.innerHTML =
        `<p>${passed ? '本步已通过，但没有记录具体选择。' : '尚未选择完整分支。'}下面是候选提示，不代表已采用的方法。</p><div class="kxp-tip-options"></div><div class="kxp-tip-content"></div>`;
      items.forEach((b) => {
        const button = document.createElement('button');
        button.type = 'button';
        button.textContent = label(b.value.ref) + '（' + conditionLabel(b.conditions) + '）';
        button.setAttribute('data-math-text', '');
        button.onclick = () => show(b.value, passed, body.querySelector('.kxp-tip-content'), false, {snapshot, stage});
        body.querySelector('.kxp-tip-options').append(button);
      });
      math(body);
    } else await show(items[0].value, passed, body, false, {snapshot, stage});
  }
  async function show(tip, passed, body, retry = false, evidence = null) {
    close();
    const stamp = ticket;
    const { id, entry } = splitRef(tip.ref),
      n = catalog[id];
    body.innerHTML = `<p class="kxp-kind">${KINDS[n.kind]}</p><h3>${h(label(tip.ref))}</h3><p>${h(n.summary)}</p>${n.conditions ? `<p class="condition" data-math-text>${h(n.conditions)}</p>` : ''}<p><a href="${modeHref(nodeHref(tip.ref))}" target="_blank" rel="noopener">打开完整详情 ↗</a></p><div class="kxp-detail"></div><div class="kxp-resource"></div><p class="kxp-load-status" role="status">正在加载提示…</p><button class="kxp-retry" type="button" hidden>重试加载提示</button>`;
    const retryButton = body.querySelector('.kxp-retry');
    retryButton.onclick = () => show(tip, passed, body, true, evidence);
    math(body);
    const failures = [];
    // Text and diagrams load independently: a failed resource must not hide the text.
    await Promise.all([
      (async () => {
        if (passed) {
          const detail = await read(`/knowledge-next/teaching/nodes/${id}.json`);
          if (stamp !== ticket) return;
          const parsed = new DOMParser().parseFromString(detail.html, 'text/html');
          parsed.querySelectorAll('.resource-section,.entry-users').forEach((el) => el.remove());
          body.querySelector('.kxp-detail').innerHTML =
            (entry ? parsed.getElementById(entry)?.outerHTML : null) || parsed.body.innerHTML;
          if (tip.note)
            body
              .querySelector('.kxp-detail')
              .insertAdjacentHTML('afterbegin', `<p class="kxp-case" data-math-text>${h(tip.note)}</p>`);
        } else {
          body.querySelector('.kxp-detail').textContent = '本步完成后，可查看本题的对应说明和详细例子。';
        }
      })().catch(() => failures.push('正文')),
      (async () => {
        if (!tip.resource) return;
        const resource = await readResource(tip.resource);
        await stylesheet('/assets/explain/explain.css?v=1');
        if (stamp !== ticket) return;
        const root = body.querySelector('.kxp-resource');
        root.className = `kxp-resource explain-inline explain-${resource.scope}`;
        root.innerHTML = `${resource.conditions ? `<p class="condition" data-math-text>${h(resource.conditions)}</p>` : ''}${resource.html}`;
        const unmount = await mountResource(root, resource, { node: n, tip: passed ? tip : null, retry });
        if (stamp !== ticket) {
          unmount?.();
          return;
        }
        cleanup = unmount;
      })().catch(() => {
        failures.push('图解');
      })
    ]);
    if (stamp !== ticket) return;
    body.querySelector('.kxp-load-status').textContent = failures.length
      ? `${failures.join('、')}加载失败，可重试或打开详情；练习仍可继续。`
      : '';
    retryButton.hidden = !failures.length;
    math(body);
    if (!failures.length && evidence && dialog?.open) onShown?.(evidence.snapshot, evidence.stage, tip);
    body.querySelectorAll('a[href^="#"]').forEach((a) =>
      a.addEventListener('click', (event) => {
        const target = body.querySelector(`[id="${CSS.escape(a.hash.slice(1))}"]`);
        if (target) {
          event.preventDefault();
          target.scrollIntoView({ block: 'start' });
        }
      })
    );
  }
  return { update, openStep, contentVersion: problem.content_version };
}
