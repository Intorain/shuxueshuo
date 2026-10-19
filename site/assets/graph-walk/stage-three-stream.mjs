/** Consume committed mathematical fragments without waiting for a complete route.
 * Transport is injected: HTTP polling and WebSocket can feed the same reducer.
 * Reading progress belongs to the view; sequence numbers only order delivery.
 */

const copy = value => structuredClone(value);
const routeKey = (target, route) => JSON.stringify([target, route]);
const stepKey = step => JSON.stringify([step.target_ref, step.route_id, step.step_id]);
const unavailable = goal => Boolean(goal && (goal.status === 'conflict' || goal.available === false || goal.reason === 'route_consistency_undecidable'));
const methodNames = {discriminant: '判别式法', extremum: '分离参数法', interval: '区间最值法', variable: '更换主元法'};
const stoppedLabels = {capability_gap: '暂时无法继续这一步', math_failed: '这条解法未通过数学检查', execution_error: '计算遇到问题'};
const expressionText = value => typeof value === 'string' ? value : value?.latex || value?.display || value?.expression || '';

export function createEventConsumer(identity, hooks = {}) {
  const run = {run_id: identity.run_id, lesson_version: identity.lesson_version, stream_id: identity.stream_id || identity.run_id};
  if (!run.run_id || !run.lesson_version) throw new Error('stream.missing_identity');
  let lastSeq = 0;
  const pending = new Map(), seen = new Map(), steps = new Map(), goals = new Map();
  const completions = new Map(), qa = new Map(), routeStatuses = new Map(), enrichmentStatuses = new Map();
  const selections = new Map(), trajectories = new Map();
  let checkpoints = [];
  const matches = value => value.run_id === run.run_id && value.lesson_version === run.lesson_version;
  const orderedSteps = () => [...steps.values()].sort((left, right) =>
    left.target_ref.localeCompare(right.target_ref) || left.route_id.localeCompare(right.route_id) || left.ordinal - right.ordinal);

  function acceptStep(step) {
    if (!matches(step) || typeof step.target_ref !== 'string' || typeof step.route_id !== 'string' ||
        typeof step.step_id !== 'string' || !step.step_id || !Number.isInteger(step.ordinal) || step.ordinal < 1 ||
        typeof step.math_step_sha256 !== 'string' || step.local_check !== 'passed') throw new Error('stream.invalid_math_step');
    const key = stepKey(step), previous = steps.get(key);
    if (previous && JSON.stringify(previous) !== JSON.stringify(step)) throw new Error('stream.immutable_math_step');
    if (!previous) {
      const siblings = [...steps.values()].filter(value => value.target_ref === step.target_ref && value.route_id === step.route_id);
      if (step.ordinal !== siblings.length + 1) throw new Error('stream.noncontiguous_math_steps');
      steps.set(key, copy(step));
      try { hooks.onMathStep?.(copy(step)); } catch (error) { steps.delete(key); throw error; }
    }
  }

  function acceptQA(chunk) {
    if (!matches(chunk)) throw new Error('stream.qa_identity_mismatch');
    if (unavailable(goals.get(chunk.target_ref))) return;
    const key = stepKey(chunk), step = steps.get(key), completion = completions.get(routeKey(chunk.target_ref, chunk.route_id));
    if (!step || !completion || step.math_step_sha256 !== chunk.math_step_sha256 ||
        completion.verified_route_sha256 !== chunk.verified_route_sha256) throw new Error('stream.qa_hash_mismatch');
    const previous = qa.get(key);
    if (previous && JSON.stringify(previous) !== JSON.stringify(chunk)) throw new Error('stream.immutable_qa');
    if (!previous) {
      hooks.onQA?.(copy(chunk));
      qa.set(key, copy(chunk));
    }
  }

  function acceptSelection(target, kind, chunk) {
    if (!['D1', 'D2', 'D3', 'D4'].includes(kind) || !chunk || typeof target !== 'string') throw new Error('stream.invalid_selection');
    const key = JSON.stringify([target, kind]), previous = selections.get(key);
    if (previous && JSON.stringify(previous.chunk) !== JSON.stringify(chunk)) throw new Error('stream.immutable_selection');
    if (!previous) {
      selections.set(key, {target_ref: target, kind, chunk: copy(chunk)});
      try { hooks.onSelection?.(target, kind, copy(chunk)); } catch (error) { selections.delete(key); throw error; }
    }
  }

  function acceptTrajectory(target, route, values) {
    const key = routeKey(target, route), rows = trajectories.get(key) || new Map();
    for (const value of values || []) rows.set(value.seq, copy(value));
    trajectories.set(key, rows);
  }

  function applyOrdered(event) {
    const payload = event.payload, target = event.target_ref, key = routeKey(target, event.route_id);
    if (!payload || typeof payload !== 'object') throw new Error('stream.invalid_payload');
    if (event.type === 'lesson.chunk_ready' && ['D1', 'D2', 'D3', 'D4'].includes(payload.kind)) {
      acceptSelection(target, payload.kind, payload.chunk);
    } else if (event.type === 'solver.step_completed') {
      acceptTrajectory(target, event.route_id, payload.trajectory);
    } else if (event.type === 'lesson.chunk_ready' && payload.kind === 'math_step') {
      const step = payload.chunk;
      if (!step || step.target_ref !== target || step.route_id !== event.route_id ||
          step.step_id !== payload.step_id || step.math_step_sha256 !== payload.math_step_sha256) throw new Error('stream.math_identity_mismatch');
      acceptStep(step);
    } else if (event.type === 'lesson.goal_status') {
      goals.set(target, copy(payload));
      hooks.onGoalStatus?.(target, copy(payload));
    } else if (event.type === 'lesson.route_status') {
      routeStatuses.set(key, copy(payload));
      hooks.onRouteStatus?.(target, event.route_id, copy(payload));
    } else if (event.type === 'lesson.chunk_ready' && payload.kind === 'route_completion') {
      if (!unavailable(goals.get(target))) {
        completions.set(key, copy(payload));
        hooks.onRouteCompletion?.(target, event.route_id, copy(payload));
      }
    } else if (event.type === 'lesson.chunk_ready' && payload.kind === 'step_qa') {
      const chunk = payload.chunk;
      if (!chunk || chunk.target_ref !== target || chunk.route_id !== event.route_id || chunk.step_id !== payload.step_id ||
          chunk.math_step_sha256 !== payload.math_step_sha256 || chunk.verified_route_sha256 !== payload.verified_route_sha256) throw new Error('stream.qa_identity_mismatch');
      acceptQA(chunk);
    } else if (event.type === 'lesson.enrichment_status') {
      enrichmentStatuses.set(key, copy(payload));
      hooks.onEnrichmentStatus?.(target, event.route_id, copy(payload));
    }
    hooks.onEvent?.(copy(event));
  }

  function accept(event) {
    if (!matches(event) || event.stream_id !== run.stream_id) return {ignored: 'different_run', last_seq: lastSeq};
    if (!Number.isInteger(event.seq) || event.seq < 1 || typeof event.event_id !== 'string' || !event.event_id) throw new Error('stream.invalid_event');
    if (event.seq <= lastSeq) {
      if (seen.has(event.seq) && seen.get(event.seq) !== event.event_id) throw new Error('stream.sequence_conflict');
      return {ignored: 'duplicate', last_seq: lastSeq};
    }
    if (pending.has(event.seq) && JSON.stringify(pending.get(event.seq)) !== JSON.stringify(event)) throw new Error('stream.sequence_conflict');
    pending.set(event.seq, copy(event));
    if (pending.size > 1000) throw new Error('stream.buffer_limit');
    while (pending.has(lastSeq + 1)) {
      const next = pending.get(lastSeq + 1);
      applyOrdered(next);
      pending.delete(next.seq);
      seen.set(next.seq, next.event_id);
      lastSeq = next.seq;
    }
    if (pending.size) hooks.onGap?.(lastSeq);
    return {last_seq: lastSeq, pending: pending.size};
  }

  function hydrate(snapshot) {
    if (!matches(snapshot) || snapshot.stream_id !== run.stream_id) throw new Error('stream.snapshot_identity_mismatch');
    if (!Number.isInteger(snapshot.last_seq) || snapshot.last_seq < lastSeq) throw new Error('stream.stale_snapshot');
    const available = new Map((snapshot.math_steps || []).map(step => [stepKey(step), step]));
    for (const [key, previous] of steps) {
      if (JSON.stringify(available.get(key)) !== JSON.stringify(previous)) throw new Error('stream.snapshot_math_changed');
    }
    goals.clear();
    for (const [target, value] of Object.entries(snapshot.goals || {})) goals.set(target, copy(value));
    checkpoints = copy(snapshot.checkpoints || []);
    for (const checkpoint of checkpoints) acceptTrajectory(checkpoint.target_ref, checkpoint.route_id, checkpoint.driver_state?.trajectory?.steps);
    for (const selection of snapshot.selection_chunks || []) acceptSelection(selection.target_ref, selection.kind, selection.chunk);
    for (const step of (snapshot.math_steps || []).slice().sort((left, right) => left.ordinal - right.ordinal)) acceptStep(step);
    completions.clear();
    for (const task of snapshot.handoffs || []) {
      if (task.available && !unavailable(goals.get(task.target_ref))) completions.set(routeKey(task.target_ref, task.route_id), {
        kind: 'route_completion', status: 'verified', answer: copy(task.answer), feasible_set: copy(task.feasible_set),
        verified_route_sha256: task.verified_route_sha256,
      });
      enrichmentStatuses.set(routeKey(task.target_ref, task.route_id), {status: task.status});
    }
    for (const checkpoint of snapshot.checkpoints || []) routeStatuses.set(routeKey(checkpoint.target_ref, checkpoint.route_id), {status: checkpoint.status});
    for (const chunk of snapshot.qa || []) acceptQA(chunk);
    lastSeq = snapshot.last_seq;
    for (const seq of pending.keys()) if (seq <= lastSeq) pending.delete(seq);
    hooks.onSnapshot?.(view());
    // Events already buffered beyond the snapshot waterline remain usable.
    if (pending.has(lastSeq + 1)) accept(pending.get(lastSeq + 1));
    return view();
  }

  function view() {
    return {...run, last_seq: lastSeq, math_steps: copy(orderedSteps()), goals: Object.fromEntries(copy([...goals])),
      completions: copy([...completions].map(([key, value]) => ({identity: JSON.parse(key), ...value,
        available: !unavailable(goals.get(JSON.parse(key)[0]))}))),
      qa: copy([...qa.values()]), route_statuses: copy([...routeStatuses]), enrichment_statuses: copy([...enrichmentStatuses]),
      selection_chunks: copy([...selections.values()]), checkpoints: copy(checkpoints),
      trajectories: [...trajectories].map(([key, values]) => ({target_ref: JSON.parse(key)[0], route_id: JSON.parse(key)[1],
        steps: copy([...values.values()].sort((a, b) => a.seq - b.seq))}))};
  }

  return {accept, hydrate, view, get last_seq() { return lastSeq; }};
}

export function mountStageThreeStream(container, identity, options = {}) {
  const document = container.ownerDocument, cards = new Map(), routeNodes = new Map();
  let stopped = false, started = false, polling = false, timer = null;
  let mode = options.mode || 'explain';
  const reached = new Map();
  let selectedTarget = options.targetRef || null, selectedRoute = null, readingEnabled = options.readingEnabled !== false;
  const storageKey = `graph-stage-three-reading:${identity.run_id}:${identity.lesson_version}`;
  let storage = options.storage;
  if (storage === undefined) try { storage = globalThis.localStorage; } catch { storage = null; }
  try {
    const saved = JSON.parse(storage?.getItem(storageKey) || 'null');
    for (const [key, ordinal] of saved?.reached || []) if (Number.isInteger(ordinal) && ordinal > 0) reached.set(key, ordinal);
  } catch { /* Storage is optional, including private browsing. */ }
  const persist = () => { try { storage?.setItem(storageKey, JSON.stringify({reached: [...reached]})); } catch {} };
  const text = (tag, value, className) => { const node = document.createElement(tag); node.textContent = value; if (className) node.className = className; return node; };
  const routeTabs = options.routeControls ? text('nav', '', 'stage-three-route-tabs') : null;
  if (routeTabs) { routeTabs.setAttribute?.('aria-label', '解题路线'); container.append(routeTabs); }

  function routeNode(target, route) {
    const key = routeKey(target, route);
    if (!routeNodes.has(key)) {
      const section = document.createElement('section');
      section.dataset.targetRef = target; section.dataset.routeId = route;
      section.className = 'stage-three-route';
      const status = text('p', '正在计算，已完成的步骤可先阅读。', 'stage-three-route-status');
      const steps = document.createElement('div'), completion = text('p', '', 'stage-three-completion');
      completion.hidden = true;
      const label = options.routeLabel?.(target, route) || methodNames[route] || '解题路线';
      const next = text('button', '下一步 →', 'stage-three-next');
      next.type = 'button'; next.dataset.streamNext = route;
      next.addEventListener?.('click', () => revealThrough(target, route, (reached.get(key) || 1) + 1));
      section.append(text('h2', label), status, steps, next, completion);
      container.append(section);
      let tab;
      if (routeTabs) {
        tab = text('button', label); tab.type = 'button'; tab.dataset.streamRoute = route; tab.dataset.targetRef = target;
        tab.addEventListener?.('click', () => options.onRouteSelect?.(target, route));
        routeTabs.append(tab);
      }
      routeNodes.set(key, {section, status, steps, completion, next, tab, complete: false});
    }
    return routeNodes.get(key);
  }

  function reveal() {
    const visible = [];
    for (const {step, node} of cards.values()) {
      const limit = reached.get(routeKey(step.target_ref, step.route_id)) ?? 1;
      node.hidden = mode === 'practice' && step.ordinal > limit;
      if (!node.hidden && readingEnabled && (!selectedTarget || selectedTarget === step.target_ref) &&
          (!selectedRoute || selectedRoute === step.route_id)) visible.push(copy(step));
    }
    for (const [key, nodes] of routeNodes) {
      const [target, route] = JSON.parse(key);
      const sameTarget = !selectedTarget || selectedTarget === target;
      nodes.section.hidden = !readingEnabled || !sameTarget || Boolean(selectedRoute && selectedRoute !== route);
      const count = [...cards.values()].filter(({step}) => step.target_ref === target && step.route_id === route).length;
      const ordinal = Math.min(reached.get(key) || 1, count);
      nodes.next.hidden = mode !== 'practice' || count === 0;
      nodes.next.disabled = ordinal >= count;
      nodes.next.textContent = ordinal < count ? '下一步 →' : nodes.complete ? '本路线已读完' : '等待下一步…';
      nodes.completion.hidden = !nodes.complete || unavailable(consumer.view().goals[target]) || (mode === 'practice' && ordinal < count);
      if (nodes.tab) { nodes.tab.hidden = !sameTarget || !readingEnabled; nodes.tab.setAttribute?.('aria-pressed', String(route === selectedRoute)); }
    }
    options.onReading?.({target_ref: selectedTarget, route_id: selectedRoute, steps: visible, mode, enabled: readingEnabled});
  }

  function revealThrough(target, route, ordinal) {
    if (!Number.isInteger(ordinal) || ordinal < 1) throw new Error('stream.invalid_reading_position');
    const count = [...cards.values()].filter(({step}) => step.target_ref === target && step.route_id === route).length;
    const key = routeKey(target, route);
    reached.set(key, Math.max(Math.min(ordinal, count || 1), reached.get(key) || 1));
    persist(); reveal();
  }

  function addMath(step) {
    const key = stepKey(step);
    if (cards.has(key)) return;
    const card = document.createElement('article');
    card.className = 'stage-three-math-step'; card.dataset.stepId = step.step_id;
    card.dataset.mathStepSha256 = step.math_step_sha256; card.dataset.ordinal = String(step.ordinal);
    card.append(text('h3', step.title));
    for (const expression of step.before || []) { const node = text('p', expression.display, 'stage-three-before'); node.dataset.mathFormula = 'true'; card.append(node); }
    for (const expression of step.after || []) { const node = text('p', expression.display, 'stage-three-after'); node.dataset.mathFormula = 'true'; card.append(node); }
    const explanation = text('p', step.explanation || '', 'stage-three-explanation'); explanation.dataset.mathText = 'true'; card.append(explanation);
    const supplementary = document.createElement('aside');
    supplementary.className = 'stage-three-qa'; supplementary.hidden = true;
    card.append(supplementary);
    // Render before publishing this card so a transient renderer failure can retry.
    options.renderMath?.(card);
    cards.set(key, {node: card, qa: supplementary, step: copy(step)});
    routeNode(step.target_ref, step.route_id).steps.append(card);
    reveal();
    const goal = consumer.view().goals[step.target_ref];
    if (goal) updateGoal(step.target_ref, goal);
  }

  function addQA(chunk) {
    const card = cards.get(stepKey(chunk));
    if (!card) return;
    // Only the separate QA region changes; no card replacement or scrolling.
    const pieces = [];
    const labels = {questions: '想一想', possible_questions: '你可能会问', hints: '提示', common_errors: '常见错误', feedback: '反馈'};
    for (const [key, value] of Object.entries(chunk.qa)) {
      const values = Array.isArray(value) ? value : [value];
      const lines = values.map(item => typeof item === 'string' ? item : item?.text || item?.question || item?.message || '').filter(Boolean);
      if (lines.length) pieces.push(text('strong', labels[key] || '补充说明'), ...lines.map(line => text('p', line)));
    }
    card.qa.replaceChildren(...pieces);
    card.qa.hidden = false;
    options.renderMath?.(card.qa);
  }

  function updateGoal(target, goal) {
    const blocked = unavailable(goal);
    for (const [key, nodes] of routeNodes) if (JSON.parse(key)[0] === target) {
      nodes.section.dataset.available = String(!blocked);
      if (blocked) {
        nodes.completion.hidden = true;
        nodes.status.textContent = '此目标的完整解答暂不可用；已计算步骤保留供检查。';
      }
    }
    if (blocked) for (const {step, qa: node} of cards.values()) if (step.target_ref === target) node.hidden = true;
  }

  function completed(target, route, payload) {
    const nodes = routeNode(target, route);
    const answer = payload.answer || {};
    const formula = answer.status === 'set' ? expressionText(answer.set) : expressionText(answer.value);
    const label = answer.status === 'set' ? '参数范围：' : answer.kind === 'find_minimum' ? '最小值：' : '最大值：';
    const statuses = {not_attained: '最值不存在：边界没有取得。', unbounded_below: '最小值不存在：没有下界。',
      unbounded_above: '最大值不存在：没有上界。', empty_feasible_set: '没有满足题设的参数。'};
    nodes.completion.replaceChildren(text('span', formula ? label : statuses[answer.status] || '答案已通过数学验证。'));
    if (formula) { const node = text('span', formula, 'stage-three-answer'); node.dataset.mathFormula = 'true'; nodes.completion.append(node); }
    nodes.complete = true;
    nodes.status.textContent = '本路线已完成数学验证。';
    options.renderMath?.(nodes.completion);
    reveal();
  }

  const consumer = createEventConsumer(identity, {
    onMathStep: addMath, onQA: addQA, onGoalStatus: updateGoal, onRouteCompletion: completed,
    onSelection: (...args) => options.onSelection?.(...args),
    onRouteStatus(target, route, payload) {
      const nodes = routeNode(target, route);
      nodes.section.dataset.mathStatus = payload.status;
      if (['capability_gap', 'math_failed', 'execution_error'].includes(payload.status)) {
        nodes.status.textContent = `${stoppedLabels[payload.status]}；已完成步骤保留。`;
      }
    },
    onEnrichmentStatus(target, route, payload) { routeNode(target, route).section.dataset.enrichmentStatus = payload.status; },
    onSnapshot(state) {
      for (const step of state.math_steps) addMath(step);
      for (const value of state.completions) if (value.available) completed(...value.identity, value);
      for (const chunk of state.qa) if (!unavailable(state.goals[chunk.target_ref])) addQA(chunk);
      for (const [key, value] of state.route_statuses) {
        const nodes = routeNode(...JSON.parse(key));
        nodes.section.dataset.mathStatus = value.status;
        if (['capability_gap', 'math_failed', 'execution_error'].includes(value.status)) nodes.status.textContent = `${stoppedLabels[value.status]}；已完成步骤保留。`;
      }
      for (const [key, value] of state.enrichment_statuses) routeNode(...JSON.parse(key)).section.dataset.enrichmentStatus = value.status;
      for (const [target, goal] of Object.entries(state.goals)) updateGoal(target, goal);
      reveal();
      options.onSnapshot?.(state);
    },
    onGap: cursor => options.onGap?.(cursor), onEvent: event => options.onEvent?.(event),
  });

  async function pollOnce() {
    if (stopped || polling || !options.fetchEvents) return;
    polling = true;
    try {
      const result = await options.fetchEvents(consumer.last_seq);
      if (stopped) return;
      if (result?.cursor_expired || result?.error === 'events.cursor_expired') {
        if (!options.fetchSnapshot) throw new Error('stream.snapshot_required');
        const snapshot = await options.fetchSnapshot();
        if (!stopped) consumer.hydrate(snapshot);
      } else for (const event of Array.isArray(result) ? result : result.events || []) consumer.accept(event);
    } catch (error) {
      if (!stopped) options.onError?.(error);
      throw error;
    } finally { polling = false; }
  }

  async function schedule() {
    try { await pollOnce(); } catch { /* Preserve the current cards while the transport reconnects. */ }
    if (!stopped) timer = setTimeout(schedule, options.pollInterval ?? 500);
  }

  return {consumer, pollOnce, start() { if (!started && !stopped) { started = true; schedule(); } },
    stop() { stopped = true; if (timer) clearTimeout(timer); },
    setMode(value) { if (!['explain', 'practice'].includes(value)) throw new Error('stream.invalid_mode'); mode = value; reveal(); },
    revealThrough,
    setSelection(target, route, enabled = true) { selectedTarget = target; selectedRoute = route; readingEnabled = enabled; reveal(); },
    readingPosition(target, route) { return reached.get(routeKey(target, route)) || 1; },
  };
}

/** One cursor and reducer for both WebSocket delivery and HTTP recovery. */
export function connectStageThreeStream(consumer, stream, options = {}) {
  let stopped = false, socket = null, timer = null, polling = null, starting = null;
  const base = options.baseURL || globalThis.location?.href || 'http://localhost/';
  const fetcher = options.fetch || globalThis.fetch;
  const WebSocketClass = options.WebSocket === undefined ? globalThis.WebSocket : options.WebSocket;
  const onError = error => { if (!stopped) options.onError?.(error); };
  const url = (source, parameter, value) => {
    const result = new URL(source, base);
    if (parameter) result.searchParams.set(parameter, value);
    return result;
  };
  async function read(source) {
    const response = await fetcher(source, {cache: 'no-store'});
    const value = await response.json();
    if (!response.ok && !value.cursor_expired) throw new Error(value.error || `stream.http_${response.status}`);
    return value;
  }
  async function snapshot() {
    const value = await read(url(stream.snapshot_url));
    if (!stopped) { consumer.hydrate(value); options.onUpdate?.(consumer.view()); }
  }
  async function deliver(value) {
    if (stopped) return;
    if (value?.cursor_expired || value?.error === 'events.cursor_expired') { await snapshot(); return; }
    for (const event of Array.isArray(value) ? value : value.events || []) consumer.accept(event);
    options.onUpdate?.(consumer.view());
  }
  async function pollOnce() {
    if (stopped) return;
    if (polling) return polling;
    polling = (async () => {
      try { await deliver(await read(url(stream.events_url, 'after_seq', consumer.last_seq))); }
      catch (error) { onError(error); throw error; }
      finally { polling = null; }
    })();
    return polling;
  }
  function openSocket() {
    if (stopped || !WebSocketClass || !stream.websocket_url) return;
    const address = url(stream.websocket_url, 'after', consumer.last_seq);
    if (address.protocol === 'http:') address.protocol = 'ws:';
    if (address.protocol === 'https:') address.protocol = 'wss:';
    try { socket = new WebSocketClass(address.href); }
    catch {
      // WebSocket is optional. The polling attempt reports connection failure
      // only when the fallback itself cannot deliver the committed stream.
      socket = null; return;
    }
    const current = socket;
    current.onmessage = event => {
      if (stopped || socket !== current) return;
      Promise.resolve().then(() => deliver(JSON.parse(event.data))).catch(onError);
    };
    current.onerror = () => { if (!stopped && socket === current) { current.close(); void pollOnce().catch(() => {}); } };
    current.onclose = event => {
      if (stopped || socket !== current) return;
      socket = null;
      const recover = event.code === 4009 ? snapshot() : pollOnce();
      void recover.catch(onError);
    };
  }
  async function tick() {
    if (stopped) return;
    // Polling also repairs a missing WebSocket sequence without resetting DOM.
    try { await pollOnce(); } catch { /* Keep the committed prefix visible. */ }
    if (!socket) openSocket();
    if (!stopped) timer = setTimeout(tick, options.pollInterval ?? 1000);
  }
  return {
    start() {
      if (starting) return starting;
      starting = (async () => {
        try { await snapshot(); } catch (error) { onError(error); }
        if (!stopped) { openSocket(); await tick(); }
      })();
      return starting;
    }, pollOnce, refresh: snapshot,
    stop() { stopped = true; if (timer) clearTimeout(timer); socket?.close(); socket = null; },
  };
}
