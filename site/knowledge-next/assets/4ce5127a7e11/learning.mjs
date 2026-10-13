import {ABILITY_KINDS, STATUS_LABELS, learningHref, learningVersion, learningApi, learningDirectoryHref, progressScope, practiceEventView, renderLearningMath, preserveLearningLink} from './learning-model.mjs';
import {escapeHtml as h} from './resource-links.mjs';

const params = new URLSearchParams(location.search);
const enabled = params.get('learning') === '1';
const nodeConfig = document.querySelector('#node-page-config');
const config = nodeConfig ? JSON.parse(nodeConfig.textContent) : null;
if (config?.redirectHref) {
  location.replace(enabled ? learningDirectoryHref(config, location.href) : config.redirectHref);
} else {
  const hero = document.querySelector('main .hero');
  const mode = document.createElement('p');
  mode.className = 'kx-learning-entry';
  if (!enabled) {
    if (/^(localhost|127(?:\.\d{1,3}){3}|\[?::1\]?)$/i.test(location.hostname)) {
      mode.innerHTML = `<a href="${h(learningHref(location.href))}">进入登录联调 · 查看个人状态与五题检测 →</a>`;
      hero?.append(mode);
    }
  } else {
    mode.textContent = '登录联调 · 正在确认内容版本…';
    document.querySelectorAll('[data-teaching-mode]').forEach(el => el.textContent = '教学内容 · 登录联调');
    document.querySelectorAll('a[href]').forEach(a => {
      if (a.textContent === '专题预览') a.textContent = '专题练习';
      else if (a.textContent === '打开原题 · 关联预览') a.textContent = '打开原题 · 登录联调';
    });
    document.querySelectorAll('[data-preview-notice]').forEach(el => el.textContent = '登录联调：进入题页后，练习记录保存到当前账号。');
    hero?.append(mode);
    const preserveLink = a => preserveLearningLink(a, location.href);
    document.querySelectorAll('a[href]').forEach(preserveLink);
    // Graph drawers and topic tables add links after the initial page load.
    for (const type of ['click', 'auxclick', 'contextmenu']) document.addEventListener(type, e => preserveLink(e.target.closest('a[href]')), true);
    const graphConfig = document.querySelector('#graph-config');
    const graph = graphConfig ? JSON.parse(graphConfig.textContent) : null;
    const panel = document.createElement('section');
    panel.className = 'kx-learning-panel';
    panel.setAttribute('aria-label', '个人学习记录');
    panel.setAttribute('aria-live', 'polite');
    hero?.after(panel);
    let ticket = 0, contentVersion = null;
    const stateConfig = config;
    const scope = () => progressScope(location.search, graph);
    // Formula rendering is an enhancement; a failed script must not hide evidence.
    const renderMath = async target => {
      try { await renderLearningMath(target); }
      catch {
        const retry = document.createElement('button');
        retry.type = 'button';
        retry.textContent = '公式排版暂不可用，重试';
        retry.onclick = () => { retry.remove(); renderMath(target); };
        target.append(retry);
      }
    };
    const read = async path => {
      if (path.startsWith('/api/')) return learningApi(path);
      const response = await fetch(path, {cache: 'no-cache', signal: AbortSignal.timeout(15000)});
      if (!response.ok) throw Error('内容版本暂不可用，请重试。');
      return response.json();
    };
    const aggregate = (name, value) => {
      if (!value) return '';
      const counts = value.statuses;
      const byKind = Object.entries(value.by_kind || {}).map(([kind, row]) =>
        `<li>${h({knowledge:'知识点',skill:'技能',method:'方法',problem_type:'题型'}[kind] || kind)}：${row.total} 个，已掌握 ${row.statuses?.mastered || 0}，待巩固 ${row.statuses?.needs_review || 0}，未评估 ${row.statuses?.unassessed || 0}</li>`).join('');
      return `<article><h3>${name} · ${value.total} 个能力节点</h3><p>已掌握 ${counts.mastered} · 待巩固 ${counts.needs_review} · 未评估 ${counts.unassessed} · 可检测 ${value.eligible}</p>${byKind ? `<ul>${byKind}</ul>` : ''}</article>`;
    };
    async function refresh() {
      const stamp = ++ticket;
      panel.replaceChildren();
      try {
        contentVersion = await learningVersion(read);
        if (stamp !== ticket) return;
        mode.textContent = '登录联调 · 学习记录保存到当前账号';
        await window.SiteAuth?.ready;
        const user = window.SiteAuth?.user;
        if (!user) {
          panel.innerHTML = '<p>登录后查看个人学习状态与练习证据。</p><button type="button" data-login>登录并继续</button>';
          panel.querySelector('[data-login]').onclick = async () => {
            await window.SiteAuth?.requireLogin({title:'登录后查看学习记录', intro:'五题全部完成后更新节点状态。'});
            refresh();
          };
          return;
        }
        if (config && ABILITY_KINDS.includes(config.kind)) {
          const result = await learningApi('/nodes', {user: user.id});
          if (stamp !== ticket) return;
          const state = result.nodes.find(n => n.node_id === config.id);
          if (!state) throw Error('当前节点尚未发布到学习服务。');
          panel.innerHTML = `<h2>我的状态 <span class="kx-status ${h(state.status)}">${STATUS_LABELS[state.status]}</span>${state.in_progress ? ' · 练习中' : ''}</h2><p>${state.attempt_id ? `最近完成的五题首答 ${state.correct_count} / 5 · ${h(new Date(state.completed_at).toLocaleString())}` : '尚无本节点的有效评测证据。'}</p><p>五题全部完成后更新状态。新一轮答错，完成后可变为待巩固。</p>${state.eligible ? '<button type="button" data-start-drill>刷题 · 5 题</button>' : `<p>当前 ${state.item_count} 道有效小题，暂未开放五题检测。</p>`}${state.attempt_id ? '<button type="button" data-drill-evidence>查看评估依据</button><div class="kx-drill-evidence"></div>' : ''}<div class="kx-evidence"></div>`;
          const showDrill = panel.querySelector('[data-drill-evidence]');
          if (showDrill) showDrill.onclick = async () => {
            showDrill.disabled = true;
            try {
              const run = await learningApi(`/drills/${state.attempt_id}`, {user:user.id});
              if (stamp !== ticket) return;
              const target = panel.querySelector('.kx-drill-evidence');
              target.innerHTML = `<p>最近完成的五题首答记录</p><ol>${run.items.map(item => `<li><p data-math-text>${h(item.statement_md)} · ${item.is_correct ? '答对' : '答错'}</p><p data-math-text>所选答案：${h(item.options.filter(option => item.selected?.includes(option.value)).map(option => option.label).join('；'))}</p></li>`).join('')}</ol>`;
              await renderMath(target);
            } catch (error) { panel.querySelector('.kx-drill-evidence').textContent = error.message; }
            finally { showDrill.disabled = false; }
          };
          const start = panel.querySelector('[data-start-drill]');
          if (start) start.onclick = async () => {
            start.disabled = true;
            try {
              const {openDrill} = await import('./learning-drill.mjs');
              await openDrill({node:config.id, label:config.label, contentVersion});
            } catch (error) { start.after(document.createTextNode(error.message)); }
            finally { start.disabled = false; }
          };
          await evidence(panel.querySelector('.kx-evidence'), config.id, user.id, stamp);
        } else if (config?.kind === 'judgment_rule') {
          panel.innerHTML = '<h2>判断记录</h2><p>只记录实际发生的判断与选择，不设置掌握状态。</p><div class="kx-evidence"></div>';
          await evidence(panel.querySelector('.kx-evidence'), config.id, user.id, stamp);
        } else if (scope()) {
          const result = await learningApi(`/progress?scope=${encodeURIComponent(scope())}`, {user:user.id});
          if (stamp !== ticket) return;
          panel.innerHTML = `<h2>学习进度</h2>${aggregate('包含', result.contains)}${aggregate('拓展', result.extends)}<p>每组内按节点去重；这些计数不表示教材、章或节的掌握概率。</p>`;
        } else panel.innerHTML = '<p>进入具体章节查看学习进度，或打开节点详情进行五题检测。</p>';
      } catch (error) {
        if (stamp !== ticket) return;
        mode.textContent = '登录联调 · 学习记录暂不可用';
        panel.innerHTML = `<p>${h(error.message)} 公共正文仍可阅读。</p><button type="button" data-retry>重试读取</button>`;
        panel.querySelector('[data-retry]').onclick = refresh;
      }
    }
    async function evidence(host, id, user, stamp) {
      const anchor = location.hash.slice(1);
      const entry = stateConfig.entryIds?.includes(anchor) ? anchor : '';
      const query = entry ? `?entry=${encodeURIComponent(entry)}` : '';
      const result = await learningApi(`/nodes/${encodeURIComponent(id)}/evidence${query}`, {user});
      if (stamp !== ticket) return;
      const rows = result.evidence;
      const drills = result.drills || [];
      const runLabels = {completed:'已完成', in_progress:'进行中', closed:'已关闭'};
      host.innerHTML = `<details><summary>小题首答 · 最近 ${drills.length} 条${entry ? ' · 当前条目' : ''}</summary><p>保留每次遇到这道题时的首答；进行中或已关闭的轮次不更新掌握状态。</p>${drills.length ? drills.map(row => `<details><summary>${h(new Date(row.answered_at).toLocaleString())} · 第 ${row.position} 题 · ${row.is_correct ? '答对' : '答错'} · ${h(runLabels[row.status] || row.status)}</summary><button type="button" data-drill-record="${h(row.attempt_id)}" data-position="${row.position}">查看当时题目与首答</button><div class="kx-record"></div></details>`).join('') : '<p>暂无首答记录。</p>'}</details><details><summary>整题过程 · 最近 ${rows.length} 条${entry ? ' · 当前条目' : ''}</summary><p>整题过程仅作证据，暂不用于掌握评估。</p>${rows.length ? rows.map(row => `<details><summary>${h(row.label || row.problem_id || '练习')} · ${h(row.title || row.step_id || '')} · ${row.passed ? '已完成' : '进行中'}</summary><p>提交 ${row.submit_count || 0} 次 · 错误 ${row.wrong_count || 0} 次${row.hint_used ? ' · 使用过提示' : ''}</p><button type="button" data-record="${h(row.attempt_id)}" data-step="${h(row.step_id || '')}">查看原始记录</button><div class="kx-record"></div></details>`).join('') : '<p>暂无记录。</p>'}</details>`;
      host.onclick = async event => {
        const button = event.target.closest('[data-record], [data-drill-record]');
        if (!button) return;
        button.disabled = true;
        try {
          if (button.dataset.drillRecord) {
            const run = await learningApi(`/drills/${button.dataset.drillRecord}`, {user});
            if (stamp !== ticket) return;
            const item = run.items.find(item => item.position === Number(button.dataset.position));
            if (!item) throw Error('未找到该首答题目。');
            button.nextElementSibling.innerHTML = `<p data-math-text>${h(item.statement_md)}</p><p data-math-text>所选答案：${h(item.options.filter(option => item.selected?.includes(option.value)).map(option => option.label).join('；'))}</p>`;
            await renderMath(button.nextElementSibling);
            return;
          }
          const history = await learningApi(`/practice/${button.dataset.record}`, {user});
          if (stamp !== ticket) return;
          const contexts = new Map(history.events.filter(e => e.event_type === 'context').map(e => [e.id, e.payload]));
          button.nextElementSibling.innerHTML = history.events.filter(e => e.step_id === button.dataset.step).map(e => {
            const view = practiceEventView(e, contexts);
            return `<p><strong>${h(view.title)}</strong> · ${h(e.created_at || '')}</p><p data-math-text>${h(view.text)}</p>${view.details.map(detail => `<p data-math-text>${h(detail)}</p>`).join('')}`;
          }).join('');
          await renderMath(button.nextElementSibling);
        } catch (error) { button.nextElementSibling.textContent = error.message; }
        finally { button.disabled = false; }
      };
    }
    window.addEventListener('site-auth-change', refresh);
    window.addEventListener('learning-nodes-change', refresh);
    window.addEventListener('knowledge-scope-change', refresh);
    window.addEventListener('popstate', refresh);
    window.addEventListener('hashchange', refresh);
    window.addEventListener('storage', e => {if (e.key === 'sss-learning-change') refresh();});
    refresh();
  }
}
