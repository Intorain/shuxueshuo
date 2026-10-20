// One local decision engine for the student UI, model recorder and replay.
import '../practice/context.js?v=15';

const copy = value => structuredClone(value);
const nodeId = ref => ref.split('#')[0];

export function createState(bundle) {
  return {
    bundleVersion: bundle.bundleVersion,
    introCompleted: [],
    run: {id: 1, route: null, completed: []},
    archives: [],
    nextRun: 2,
    events: [],
    lastFeedback: null,
    done: false,
  };
}

function checkVersion(bundle, state) {
  if (bundle.bundleVersion !== state.bundleVersion) {
    throw new Error('这份记录与当前 Demo 版本不一致，请重新开始。');
  }
}

export function currentDecision(bundle, state) {
  checkVersion(bundle, state);
  if (state.introCompleted.length < bundle.intro.length) {
    return bundle.intro[state.introCompleted.length];
  }
  const route = bundle.routes[state.run.route];
  if (bundle.stream && route?.available === false) return null;
  return route?.steps[state.run.completed.length] || null;
}

export function gradeDecision(decision, answer) {
  if (!decision) return {status: 'wrong', message: '当前没有待作答步骤。'};
  const alternative = typeof answer === 'string' && decision.alternatives?.[answer];
  if (alternative) {
    return {status: 'uncovered', message: alternative.message, href: alternative.href};
  }
  const component = decision.interaction;
  try {
    if (component.type === 'read') {
      if (answer !== 'read') throw new Error('请确认已经读完这一步。');
    } else if (component.type === 'multi') {
      const {required, allowed} = decision.expected_answer;
      if (!Array.isArray(answer) || new Set(answer).size !== answer.length ||
          answer.some(value => !allowed.includes(value)) || !required.every(value => answer.includes(value))) {
        throw new Error(decision.feedback?.answer || '请同时关注成立范围和式子关于哪个字母是二次的。');
      }
    } else if (component.type === 'choice') {
      if (typeof answer !== 'string' || !component.options.some(option => option.value === answer)) {
        throw new Error('请选择当前步骤提供的一个选项。');
      }
      globalThis.PracticeContext.validate(decision, {
        active: 0, pairs: [[]], choices: {[component.field]: answer},
      });
    } else if (['checklist', 'fill'].includes(component.type)) {
      const count = globalThis.PracticeContext.slotCount(component);
      if (!Array.isArray(answer) || answer.length !== count || answer.some(value => typeof value !== 'string')) {
        throw new Error('请按显示顺序完成每一项，再提交。');
      }
      for (const [index, value] of answer.entries()) {
        const available = component.slots
          ? component.slots[index].options.map(option => option.value)
          : component.terms;
        if (!available.includes(value)) throw new Error('请使用当前步骤提供的选项。');
      }
      globalThis.PracticeContext.validate(decision, {active: 0, pairs: [answer], choices: {}});
    } else if (component.type === 'plane') {
      const [x, y, value] = Array.isArray(answer) && answer.length === 3 ? answer : [];
      const method = component.methods.find(item => item.value === value);
      if (!component.x.options.some(option => option.value === x) || !component.y.options.some(option => option.value === y) || !method) {
        throw new Error('请先在坐标图里点一格，再选这一格里的一种方法。');
      }
      const [expectedX, expectedY] = decision.expected_answer.cell;
      if (x !== expectedX) throw new Error(decision.feedback.x);
      if (y !== expectedY) throw new Error(decision.feedback.y);
      if (!method.cells.some(cell => cell[0] === x && cell[1] === y)) throw new Error(decision.feedback.method);
      const alternative = decision.alternatives?.[value];
      if (alternative) return {status: 'uncovered', message: alternative.message, href: alternative.href};
    } else if (component.type === 'grid') {
      const [x, y] = Array.isArray(answer) && answer.length === 2 ? answer : [];
      if (!component.x.options.some(option => option.value === x) || !component.y.options.some(option => option.value === y)) {
        throw new Error('请在图里点一格。');
      }
      const [expectedX, expectedY] = decision.expected_answer.cell;
      if (x !== expectedX) throw new Error(decision.feedback.x);
      if (y !== expectedY) throw new Error(decision.feedback.y);
    } else {
      throw new Error(`尚未支持的交互：${component.type}`);
    }
    return {status: 'passed', message: '判断通过，已记录本步结果。'};
  } catch (error) {
    return {status: 'wrong', message: optionFeedback(decision, answer) || error.message};
  }
}

/* An option may carry its own feedback; a wrong pick then explains itself instead of the step's generic hint. */
function optionFeedback(decision, answer) {
  const component = decision.interaction;
  if (component.type === 'choice') return component.options.find(option => option.value === answer)?.feedback || '';
  if (component.type !== 'checklist' || !Array.isArray(answer)) return '';
  const expected = decision.expected_answer?.terms || [];
  return answer.map((value, index) => value !== expected[index] &&
    component.slots[index]?.options.find(option => option.value === value)?.feedback).filter(Boolean).join(' ');
}

const routeOf = (decision, answer) => decision.route_by_answer?.[answer] ||
  decision.interaction.methods?.find(method => method.value === answer?.[2])?.route;
const methodChoice = bundle => bundle.intro.find(decision => decision.interaction.type === 'plane');

function completeDecision(bundle, next, decision, answer, reason) {
  const entry = {
    decision: decision.id,
    answer: copy(answer),
    reason: typeof reason === 'string' ? reason.slice(0, 6000) : '',
    results: copy(decision.effects?.results || []),
    calls: copy(decision.effects?.calls || []),
    runId: ['page', 'stream'].includes(decision.source) ? next.run.id : null,
    ...(decision.source === 'stream' ? {source: 'stream', stream_steps: copy(decision.stream_steps),
      stream_last_part: decision.stream_last_part} : {}),
  };
  if (next.introCompleted.length < bundle.intro.length) {
    next.introCompleted.push(entry);
    if (decision.interaction.type === 'plane' || decision.route_by_answer) {
      const route = routeOf(decision, answer);
      if (!bundle.routes[route]) throw new Error('此路线尚未提供完整交互。');
      next.run.route = route;
    }
  } else {
    next.run.completed.push(entry);
  }
  if (!bundle.stream) next.done = next.introCompleted.length === bundle.intro.length &&
    Boolean(next.run.route) && !bundle.routes[next.run.route].streaming &&
    next.run.completed.length === bundle.routes[next.run.route].steps.length;
}

export function submitAnswer(bundle, state, action) {
  checkVersion(bundle, state);
  const next = copy(state);
  const decision = currentDecision(bundle, state);
  const feedback = decision && action?.decision === decision.id
    ? gradeDecision(decision, action.answer)
    : {status: 'wrong', message: '作答步骤已改变，请回答当前显示的问题。'};
  next.lastFeedback = {...feedback, decision: decision?.id || null};
  const safeAction = {
    decision: typeof action?.decision === 'string' ? action.decision : '',
    answer: action?.answer === undefined ? null : copy(action.answer),
    ...(typeof action?.reason === 'string' ? {reason: action.reason.slice(0, 6000)} : {}),
  };
  next.events.push({kind: 'answer', action: safeAction, status: feedback.status, runId: next.run.id});
  if (feedback.status === 'passed') completeDecision(bundle, next, decision, action.answer, action.reason);
  if (bundle.stream && feedback.status === 'passed') next.streamDraft = null;
  return bundle.stream ? refreshStreamState(bundle, next) : next;
}

function saveStreamRoute(bundle, state) {
  const intro = new Set(bundle.intro.map(item => item.id));
  state.streamRoutes ||= {};
  state.streamIntroEvents = state.events.filter(event => event.kind === 'answer' && intro.has(event.action.decision));
  if (state.run.route) state.streamRoutes[state.run.route] = {
    run: copy(state.run), events: copy(state.events.filter(event => event.kind === 'answer' && !intro.has(event.action.decision))),
    lastFeedback: copy(state.lastFeedback), draft: copy(state.streamDraft || null),
  };
}

/** Recompute streamed completion without discarding records ahead of an initial snapshot. */
export function refreshStreamState(bundle, state) {
  checkVersion(bundle, state);
  if (!bundle.stream) return copy(state);
  const next = copy(state), route = bundle.routes[next.run.route];
  const decisions = route?.steps || [];
  for (let index = 0; index < Math.min(decisions.length, next.run.completed.length); index++) {
    if (decisions[index].id !== next.run.completed[index].decision) throw new Error('stream.progress_mismatch');
  }
  next.done = next.introCompleted.length === bundle.intro.length && Boolean(route?.math_complete) &&
    route.available !== false && route.interactions_complete && decisions.length > 0 &&
    decisions.length === next.run.completed.length;
  const decision = currentDecision(bundle, next);
  if (next.done || (decision && next.streamDraft?.decision !== decision.id)) next.streamDraft = null;
  // Incomplete startup projections may not contain D3/D4 or the active route yet.
  // Do not reclassify already saved selection events as route answers in that gap.
  if (next.introCompleted.length <= bundle.intro.length) saveStreamRoute(bundle, next);
  return next;
}

export function setStreamDraft(bundle, state, draft) {
  checkVersion(bundle, state);
  if (!bundle.stream) throw new Error('stream.not_streaming');
  const next = copy(state), decision = currentDecision(bundle, next);
  if (draft !== null && (!decision || draft?.decision !== decision.id)) throw new Error('stream.draft_decision_mismatch');
  next.streamDraft = copy(draft);
  saveStreamRoute(bundle, next);
  return next;
}

export function streamDraft(bundle, state) {
  checkVersion(bundle, state);
  const draft = state.streamDraft;
  return bundle.stream && draft?.decision === currentDecision(bundle, state)?.id ? copy(draft) : null;
}

export function switchRoute(bundle, state, route) {
  checkVersion(bundle, state);
  if (!bundle.routes[route] || state.introCompleted.length < bundle.intro.length) {
    throw new Error('请先完成题型和选法判断。');
  }
  const next = copy(state);
  if (bundle.stream) {
    if (route === next.run.route) return refreshStreamState(bundle, next);
    const choice = methodChoice(bundle);
    const method = choice?.interaction.methods.find(item => item.route === route);
    const confirmation = bundle.intro.find(item => item.route_by_answer?.[route] === route);
    if (!method || !confirmation || bundle.routes[route].available === false) throw new Error('这条路线暂不支持，请选择可用路线。');
    saveStreamRoute(bundle, next);
    next.introCompleted = next.introCompleted.map(entry => entry.decision === choice.id
      ? {...entry, answer: [...choice.expected_answer.cell, method.value]}
      : entry.decision === confirmation.id ? {...entry, answer: route} : entry);
    next.streamIntroEvents = next.streamIntroEvents.map(event => event.status !== 'passed' ? event
      : event.action.decision === choice.id ? {...event, action: {...event.action, answer: [...choice.expected_answer.cell, method.value]}}
      : event.action.decision === confirmation.id ? {...event, action: {...event.action, answer: route}} : event);
    const saved = next.streamRoutes[route];
    next.run = saved ? copy(saved.run) : {id: next.nextRun++, route, completed: []};
    next.lastFeedback = copy(saved?.lastFeedback || null);
    next.streamDraft = copy(saved?.draft || null);
    next.events = [...copy(next.streamIntroEvents), ...copy(saved?.events || [])];
    return refreshStreamState(bundle, next);
  }
  if (next.run.completed.length) next.archives.push(copy(next.run));
  next.run = {id: next.nextRun++, route: null, completed: []};
  const decision = methodChoice(bundle);
  next.introCompleted = next.introCompleted.filter(entry => entry.decision !== decision.id);
  next.lastFeedback = null;
  next.done = false;
  const method = decision.interaction.methods.find(item => item.route === route);
  completeDecision(bundle, next, decision, [...decision.expected_answer.cell, method.value]);
  next.events.push({kind: 'switch_route', route, status: 'passed', runId: next.run.id});
  return next;
}

export function undo(bundle, state) {
  checkVersion(bundle, state);
  if (bundle.stream && state.introCompleted.length >= bundle.intro.length && state.run.route) {
    const next = copy(state);
    saveStreamRoute(bundle, next);
    const history = next.streamRoutes[next.run.route].events;
    const last = history.findLastIndex(event => event.status === 'passed');
    const retained = last < 0 ? [] : history.slice(0, last);
    next.run.completed = next.run.completed.slice(0, retained.filter(event => event.status === 'passed').length);
    next.events = [...copy(next.streamIntroEvents), ...copy(retained)];
    next.lastFeedback = null;
    next.streamDraft = null;
    return refreshStreamState(bundle, next);
  }
  const last = state.events.findLastIndex(event => event.status === 'passed');
  if (last < 0) return createState(bundle);
  let next = createState(bundle);
  for (const event of state.events.slice(0, last)) {
    next = event.kind === 'switch_route'
      ? switchRoute(bundle, next, event.route)
      : submitAnswer(bundle, next, event.action);
  }
  next.lastFeedback = null;
  return bundle.stream ? refreshStreamState(bundle, next) : next;
}

function publicInteraction(component) {
  const result = {type: component.type};
  for (const key of ['field', 'title', 'terms', 'term_labels', 'slot_labels', 'slot_shapes', 'x', 'y', 'zones']) {
    if (component[key] !== undefined) result[key] = copy(component[key]);
  }
  if (component.methods) {
    result.methods = component.methods.map(({value, label, cells, route, route_plan}) =>
      ({value, label, cells: copy(cells), implemented: Boolean(route) && route_plan !== 'capability_gap'}));
  }
  const options = list => list.map(({value, label}) => ({value, label}));
  if (component.options) result.options = options(component.options);
  if (component.slots) result.slots = component.slots.map(slot => ({label: slot.label, options: options(slot.options)}));
  return result;
}

export function projectDecision(bundle, state) {
  const decision = currentDecision(bundle, state);
  if (!decision) return null;
  const interaction = publicInteraction(decision.interaction);
  const candidates = (decision.candidateNodes || []).map(id => bundle.graph.nodes.find(node => node.id === id)).filter(Boolean).map(node => ({
    id: node.id, label: node.label, kind: node.kind,
    ...(node.conditions ? {conditions: node.conditions} : {}),
    ...(node.features ? {features: copy(node.features)} : {}),
    ...(node.branches ? {branches: node.branches.map(({id, title, condition, target}) => ({id, title, condition, target}))} : {}),
  }));
  return {
    id: decision.id,
    title: decision.title,
    question: decision.question,
    problem: {text: bundle.problem.text, root: copy(bundle.problem.root)},
    results: [...state.introCompleted, ...state.run.completed].flatMap(entry => entry.results.map(value => ({step: entry.decision, value}))),
    interaction,
    candidates,
    answerFormat: interaction.type === 'read' ? {decision: decision.id, answer: 'read'} : interaction.type === 'choice'
      ? {decision: decision.id, answer: '一个选项的 value 字符串', reason: '简短说明'}
      : interaction.type === 'plane'
        ? {decision: decision.id, answer: ['横轴 x 选项的 value', '纵轴 y 选项的 value', '覆盖这一格的一种方法的 value'], reason: '简短说明'}
        : interaction.type === 'grid'
          ? {decision: decision.id, answer: ['横轴 x 选项的 value', '纵轴 y 选项的 value'], reason: '简短说明'}
        : {decision: decision.id, answer: interaction.type === 'multi' ? ['选中选项的 value；无顺序要求'] : ['按位置依次填写每一项的 value'], reason: '简短说明'},
    ...(state.lastFeedback?.decision === decision.id && state.lastFeedback.status !== 'passed'
      ? {previousFeedback: state.lastFeedback.message} : {}),
  };
}

function decisionById(bundle, id) {
  return bundle.intro.find(decision => decision.id === id) ||
    Object.values(bundle.routes).flatMap(route => route.steps).find(decision => decision.id === id);
}

function confirmedGraph(bundle, entries, route, runId) {
  const nodes = new Set(), edges = new Set(), usedBasis = new Set(), calls = [], logs = [];
  const selectedRoute = bundle.routes[route];
  const realEdges = new Set(bundle.graph.edges.map(edge => edge.id));
  const edge = id => { if (realEdges.has(id)) edges.add(id); };
  for (const entry of entries) {
    const decision = decisionById(bundle, entry.decision);
    const effects = decision?.effects || {};
    for (const id of effects.nodes || []) nodes.add(id);
    for (const id of effects.edges || []) edge(id);
    if (effects.log) logs.push({decision: entry.decision, text: effects.log});
    if (decision?.interaction.type === 'plane' && selectedRoute) {
      logs.push({decision: entry.decision, text: `作答判断：选择「${selectedRoute.label}」，执行本路线的方法步骤。`});
    }
    for (const [index, call] of entry.calls.entries()) {
      const ref = nodeId(call.ref);
      nodes.add(call.method); nodes.add(ref);
      edge(`${call.method}|calls|${ref}`);
      calls.push({...copy(call), runId, decision: entry.decision, executionIndex: index});
      for (const basis of call.usedBasis || []) {
        usedBasis.add(basis);
        nodes.add(nodeId(basis));
        edge(`${ref}|uses|${nodeId(basis)}`);
      }
    }
  }
  if (selectedRoute) {
    const method = selectedRoute.method;
    nodes.add(method);
    edge(`rule-quadratic-method|selects|${method}`);
  }
  return {nodes, edges, usedBasis, calls, logs};
}

export function graphState(bundle, state) {
  checkVersion(bundle, state);
  const current = currentDecision(bundle, state);
  const confirmed = confirmedGraph(bundle, [...state.introCompleted, ...state.run.completed], state.run.route, state.run.id);
  const nodes = Object.fromEntries(bundle.graph.nodes.map(node => [node.id, 'idle']));
  const edges = Object.fromEntries(bundle.graph.edges.map(edge => [edge.id, 'idle']));
  for (const id of confirmed.nodes) if (id in nodes) nodes[id] = 'confirmed';
  for (const id of confirmed.edges) edges[id] = 'chosen';
  const selectedRoute = bundle.routes[state.run.route];
  const focus = current?.candidateNodes?.length ? current.candidateNodes : selectedRoute ? [selectedRoute.method] : [];
  for (const id of focus) if (id in nodes && nodes[id] === 'idle') nodes[id] = 'candidate';
  if (current?.interaction.type === 'plane') {
    nodes['rule-quadratic-method'] = 'active';
    for (const edge of bundle.graph.edges.filter(edge => edge.from === 'rule-quadratic-method' && edge.type === 'selects')) {
      if (edges[edge.id] !== 'chosen') edges[edge.id] = 'candidate';
    }
  } else if (current?.source === 'page' && selectedRoute) {
    nodes[selectedRoute.method] = 'active';
  }
  const archivedEdges = new Set();
  for (const run of state.archives) {
    for (const id of confirmedGraph(bundle, run.completed, run.route, run.id).edges) archivedEdges.add(id);
  }
  return {
    nodes, edges, focus,
    usedBasis: [...confirmed.usedBasis].sort(), calls: confirmed.calls,
    logs: confirmed.logs,
    archivedEdges: [...archivedEdges],
  };
}

const streamStepKey = step => JSON.stringify([step.route_id, step.step_id]);
const sameStream = (identity, value) => identity.run_id === value.run_id &&
  identity.lesson_version === value.lesson_version && identity.target_ref === value.target_ref;

/** Preserve work done before the server could expose its stage-three identity.
 * Only a genuine D1/D2 state from this exact base bundle may enter the new run.
 */
export function migrateStageTwoState(baseBundle, streamBundle, state) {
  const invalid = () => { throw new Error('stream.invalid_stage_two_progress'); };
  if (!streamBundle.stream || baseBundle.stream || state?.bundleVersion !== baseBundle.bundleVersion ||
      streamBundle.stream.base_bundle_version !== baseBundle.bundleVersion ||
      baseBundle.problemId !== streamBundle.problemId || !baseBundle.intro.every(item => ['D1', 'D2'].includes(item.id)) ||
      state.run?.route !== null || state.run?.completed?.length !== 0 || state.archives?.length !== 0 ||
      !Array.isArray(state.events)) invalid();
  let verified = createState(baseBundle);
  for (const event of state.events) {
    if (event.kind !== 'answer' || !['D1', 'D2'].includes(event.action?.decision)) invalid();
    verified = submitAnswer(baseBundle, verified, event.action);
  }
  // Undo intentionally removes the feedback while preserving its event prefix.
  if (state.lastFeedback === null) verified.lastFeedback = null;
  const normalize = value => Array.isArray(value) ? value.map(normalize)
    : value && typeof value === 'object' ? Object.fromEntries(Object.keys(value).sort().map(key => [key, normalize(value[key])])) : value;
  if (JSON.stringify(normalize(verified)) !== JSON.stringify(normalize(state))) invalid();
  return {...copy(state), bundleVersion: streamBundle.bundleVersion};
}

function sourceCalls(view, step) {
  const trajectory = view.trajectories?.find(item => item.target_ref === step.target_ref && item.route_id === step.route_id);
  // Public v2 snapshots own a compact evidence view. Only legacy saved input
  // falls back to execution checkpoints; never mix old and new source sets.
  const legacy = !trajectory && view.checkpoints?.find(item => item.target_ref === step.target_ref && item.route_id === step.route_id)
    ?.driver_state?.trajectory;
  const records = trajectory?.steps || legacy?.steps || [];
  const calls = [];
  for (const source of step.source_refs || []) {
    const match = /^\/steps\/(\d+)\/calls\/(\d+)$/.exec(source);
    const final = /^\/finalization\/(\d+)$/.exec(source);
    if (!match && !final) continue;
    // Streaming solver events carry a one-based seq, even if earlier records
    // have not arrived. Snapshot trajectories use the same sequence identity.
    const record = match ? records.find(item => item.seq === Number(match[1]) + 1) : null;
    const call = match ? record?.calls?.[Number(match[2])]
      : trajectory?.finalization?.find(item => item.index === Number(final[1]))?.record ||
        (!trajectory ? legacy?.finalization?.[Number(final[1])] : undefined);
    if (!Array.isArray(call?.postconditions) || !call.postconditions.length ||
        !call.postconditions.every(check => check.passed === true) ||
        JSON.stringify(record?.case_path || []) !== JSON.stringify(step.case_path || []) ||
        (call.case_path && JSON.stringify(call.case_path) !== JSON.stringify(step.case_path || []))) continue;
    const [method, methodStep] = (step.method_ref || '').split('#');
    calls.push({method: record?.method || method, step: record?.step || methodStep, ref: call.public_ref || null,
      ...('rule_ref' in call ? {rule_ref: call.rule_ref} : {}), ...('branch' in call ? {branch: call.branch} : {}),
      usedBasis: (Array.isArray(call.used_basis) ? call.used_basis : []).filter(ref => typeof ref === 'string' && ref), source});
  }
  return calls;
}

// A traced public call must follow a real graph occurrence. A rule-directed
// skill is connected by method -> step rule -> selected skill, not a made-up
// method -> calls edge. Malformed rule metadata never falls back to that edge.
function publicCallPath(call, nodes, edges) {
  if (typeof call.ref !== 'string' || !nodes.has(call.ref) || !nodes.has(call.method)) return null;
  if ('rule_ref' in call || 'branch' in call) {
    if (typeof call.rule_ref !== 'string' || typeof call.branch !== 'string' ||
        !call.branch || nodes.get(call.rule_ref)?.kind !== 'judgment_rule') return null;
    const stepRule = [...edges.values()].find(item => item.type === 'step_rule' &&
      item.from === call.method && item.to === call.rule_ref && item.occurrences?.some(part => part.step === call.step));
    const selection = [...edges.values()].find(item => item.type === 'selects' &&
      item.from === call.rule_ref && item.to === call.ref);
    const occurrence = selection?.occurrences?.findIndex(part => part.branch === call.branch) ?? -1;
    if (!stepRule || !selection || occurrence < 0) return null;
    return {edge: selection.id, occurrence, edges: [stepRule.id, selection.id], rule: call.rule_ref};
  }
  const direct = [...edges.values()].find(item => item.type === 'calls' && item.from === call.method && item.to === call.ref);
  const occurrence = direct?.occurrences?.findIndex(part => part.step === call.step) ?? -1;
  return direct && occurrence >= 0 ? {edge: direct.id, occurrence, edges: [direct.id]} : null;
}

const failedStreamRoute = status => ['capability_gap', 'math_failed', 'execution_error', 'conflict', 'unavailable'].includes(status);
const unavailableStreamGoal = goal => Boolean(goal && (goal.status === 'conflict' || goal.available === false ||
  goal.reason === 'route_consistency_undecidable'));

function streamDecisions(cards, states, chunks, enabled) {
  const result = [], covered = new Set(), chunkById = new Map(chunks.map(chunk => [chunk.interaction_id, chunk]));
  const byId = new Map(cards.map(card => [card.step_id, card]));
  const read = (card, interactionId = null) => ({id: card.step_id, source: 'stream', title: card.title,
    question: '', interaction: {type: 'read'}, expected_answer: 'read', submit_label: '读完了，下一步',
    stream_steps: [{step_id: card.step_id, math_step_sha256: card.math_step_sha256}],
    stream_last_part: true, stream_interaction_id: interactionId,
    effects: {nodes: [], edges: [], calls: [], results: [], log: `已阅读：${card.title}`}});
  for (const card of cards) {
    if (covered.has(card.step_id)) continue;
    if (!enabled) { result.push(read(card)); continue; }
    const state = states.find(row => row.route_id === card.route_id && row.step_id === card.step_id);
    if (!state || state.status === 'pending') break;
    if (state.math_step_sha256 !== card.math_step_sha256) throw new Error('stream.interaction_hash_mismatch');
    const chunk = chunkById.get(state.interaction_id);
    if (!chunk || chunk.status !== state.status || chunk.route_id !== card.route_id || chunk.target_ref !== card.target_ref) {
      throw new Error('stream.invalid_interaction');
    }
    if (!Array.isArray(chunk.steps) || !chunk.steps.length || chunk.steps.length > 2 ||
        !Array.isArray(chunk.parts) || (chunk.status === 'interactive' ? !chunk.parts.length : chunk.parts.length)) {
      throw new Error('stream.invalid_interaction');
    }
    const members = chunk.steps.map((ref, index) => {
      const member = byId.get(ref.step_id);
      const decision = states.find(row => row.route_id === card.route_id && row.step_id === ref.step_id);
      if (!member || member.ordinal !== card.ordinal + index || member.math_step_sha256 !== ref.math_step_sha256 ||
          decision?.interaction_id !== chunk.interaction_id || decision.status !== chunk.status ||
          decision.math_step_sha256 !== ref.math_step_sha256) throw new Error('stream.invalid_interaction');
      return member;
    });
    for (const member of members) covered.add(member.step_id);
    if (chunk.status === 'readonly') {
      result.push(...members.map(member => read(member, chunk.interaction_id)));
    } else if (chunk.status === 'interactive') {
      result.push(...chunk.parts.map((part, index) => ({...copy(part), source: 'stream',
        stream_steps: copy(chunk.steps), stream_last_part: index === chunk.parts.length - 1,
        stream_interaction_id: chunk.interaction_id,
        effects: {nodes: [], edges: [], calls: [], results: [], log: part.effects?.log || `完成判断：${part.title || card.title}`}})));
    } else throw new Error('stream.invalid_interaction');
  }
  if (result.some(item => typeof item.id !== 'string' || !item.id) || new Set(result.map(item => item.id)).size !== result.length) {
    throw new Error('stream.invalid_decision');
  }
  return result;
}

function streamRouteState(view, target, route, previous = {}) {
  const completion = view.completions?.find(item => item.identity?.[0] === target && item.identity?.[1] === route) ||
    view.handoffs?.find(item => item.target_ref === target && item.route_id === route);
  const routeStatus = view.route_statuses?.find(([key]) => key === JSON.stringify([target, route]))?.[1];
  const checkpoint = view.checkpoints?.find(item => item.target_ref === target && item.route_id === route);
  const status = routeStatus?.status || checkpoint?.status || previous.status || 'running';
  const available = !unavailableStreamGoal(view.goals?.[target]) && completion?.available !== false && !failedStreamRoute(status) &&
    (view.goals === undefined && !completion && !routeStatus && !checkpoint ? previous.available !== false : true);
  return {status: available && (completion?.status === 'verified' || checkpoint?.status === 'verified') ? 'verified' : status,
    available, math_complete: available && (completion?.status === 'verified' || checkpoint?.status === 'verified' ||
      (!completion && !checkpoint && previous.math_complete === true))};
}

/** Add selection and graph evidence without changing the mathematical DOM.
 * The version includes the run identity from the first snapshot; later chunks
 * cannot reset D1/D2 answers, route answers or drafts.
 */
export function extendStreamBundle(base, view, targetRef, fullGraph = base.graph) {
  const identity = {run_id: view.run_id, lesson_version: view.lesson_version,
    stream_id: view.stream_id || view.run_id, target_ref: targetRef};
  if (!identity.run_id || !identity.lesson_version || !targetRef) throw new Error('stream.missing_identity');
  if (base.stream && (!sameStream(identity, base.stream) || identity.stream_id !== base.stream.stream_id)) {
    throw new Error('stream.bundle_identity_mismatch');
  }
  const bundle = copy(base);
  const baseVersion = base.stream?.base_bundle_version || base.bundleVersion;
  bundle.bundleVersion = JSON.stringify(['stream', baseVersion, identity.lesson_version, identity.run_id, targetRef]);
  const chunks = (view.selection_chunks || []).filter(item => item.target_ref === targetRef);
  const d3 = chunks.find(item => item.kind === 'D3')?.chunk || base.stream?.d3;
  const d4 = chunks.find(item => item.kind === 'D4')?.chunk || base.stream?.d4;
  for (const [kind, chunk] of [['d3', d3], ['d4', d4]]) {
    if (base.stream?.[kind] && JSON.stringify(base.stream[kind]) !== JSON.stringify(chunk)) {
      throw new Error('stream.immutable_selection');
    }
  }
  const mathSteps = (view.math_steps || []).filter(step => sameStream(identity, step) && step.local_check === 'passed');
  const knownSteps = new Map(mathSteps.map(step => [streamStepKey(step), step]));
  for (const previous of base.stream?.math_steps || []) {
    const current = knownSteps.get(streamStepKey(previous));
    if (current && JSON.stringify(current) !== JSON.stringify(previous)) throw new Error('stream.immutable_math_step');
    if (!current) { mathSteps.push(copy(previous)); knownSteps.set(streamStepKey(previous), previous); }
  }
  const nodes = new Map((fullGraph?.nodes || []).map(node => [node.id, node]));
  for (const node of base.graph.nodes) if (!nodes.has(node.id)) nodes.set(node.id, node);
  const edges = new Map([...(fullGraph?.edges || []), ...base.graph.edges].map(edge => [edge.id, edge]));
  const stepCalls = copy(base.stream?.step_calls || {});
  for (const step of mathSteps) {
    const calls = sourceCalls(view, step);
    if (calls.length) stepCalls[streamStepKey(step)] = calls.filter(call => !call.ref || !nodes.has(call.ref) || publicCallPath(call, nodes, edges));
  }
  const interactionStates = (view.interaction_states || base.stream?.interaction_states || []).filter(row => row.target_ref === targetRef);
  const interactions = (view.interactions || base.stream?.interactions || []).filter(chunk => chunk.target_ref === targetRef);
  const declaredProtocol = view.interaction_protocol === undefined ? base.stream?.interaction_protocol || null : view.interaction_protocol;
  if (declaredProtocol !== null && declaredProtocol !== 'graph-step-interaction/v1') throw new Error('stream.invalid_interaction_protocol');
  // A first math event can precede a fresh protocol-bearing snapshot. Its
  // explicit pending state must never be mistaken for a legacy read-only card.
  const interactionProtocol = declaredProtocol || (interactionStates.length || interactions.length ? 'graph-step-interaction/v1' : null);
  bundle.stream = {...identity, base_bundle_version: baseVersion, d3: copy(d3 || null), d4: copy(d4 || null),
    math_steps: copy(mathSteps), step_calls: stepCalls, interaction_protocol: interactionProtocol,
    interaction_states: copy(interactionStates), interactions: copy(interactions)};

  const ids = new Set(base.graph.nodes.map(node => node.id));
  for (const step of mathSteps) {
    if (step.method_ref && nodes.has(nodeId(step.method_ref))) ids.add(nodeId(step.method_ref));
    for (const call of stepCalls[streamStepKey(step)] || []) {
      for (const ref of [call.method, call.ref, call.rule_ref, ...call.usedBasis]) if (ref && nodes.has(nodeId(ref))) ids.add(nodeId(ref));
    }
  }
  if (d3 && d4) {
    const ruleEdges = [...edges.values()].filter(edge => edge.type === 'method_rule' && edge.from === d3.query.from);
    const rules = new Set(ruleEdges.map(edge => edge.to));
    const selectedByBranch = new Map();
    for (const edge of edges.values()) if (edge.type === 'selects' && rules.has(edge.from)) {
      for (const occurrence of edge.occurrences || []) selectedByBranch.set(occurrence.branch, edge.to);
    }
    const options = d4.options || [];
    const methods = Object.entries(d3.interaction.coverage).map(([branch, cells]) => {
      const option = options.find(item => item.branch === branch);
      const target = option?.method || selectedByBranch.get(branch);
      if (!target || !nodes.has(target)) throw new Error('stream.unknown_method');
      ids.add(target);
      return {value: branch, label: nodes.get(target).label, target, cells: copy(cells),
        ...(option ? {route: option.route_id, route_plan: option.route_plan} : {})};
    });
    for (const id of rules) ids.add(id);
    const alternatives = {};
    for (const method of methods) if (!method.route) alternatives[method.value] = {
      message: options.find(item => item.branch === method.value)?.message ||
        d3.verdicts?.[method.value]?.message || '这条思路本次不展开。', href: `/knowledge/${method.target}/`,
    };
    const selection = {...copy(d3), source: 'authored', interaction: {...copy(d3.interaction), methods}, alternatives,
      candidateNodes: [...rules, ...methods.map(method => method.target)],
      effects: {nodes: [...rules], edges: ruleEdges.map(edge => edge.id), calls: [], results: [], log: '根据本题条件选择解题方法。'}};
    const routeChoices = options.map(option => ({value: option.route_id, label: nodes.get(option.method)?.label || option.method}));
    const routeByAnswer = Object.fromEntries(options.filter(option => option.route_plan === 'planned').map(option => [option.route_id, option.route_id]));
    const confirmation = {id: 'D4', title: d4.title, source: 'authored', question: '选择这一轮要阅读的解题路线。',
      submit_label: '开始阅读解题步骤', interaction: {type: 'choice', field: 'route', options: routeChoices},
      expected_answer: {one_of: Object.keys(routeByAnswer)}, route_by_answer: routeByAnswer,
      alternatives: Object.fromEntries(options.filter(option => option.route_plan !== 'planned').map(option =>
        [option.route_id, {message: option.message || '详细步骤暂不支持', href: `/knowledge/${option.method}/`}])),
      feedback: {answer: '请选择一条当前可以展开的路线。'}, candidateNodes: options.map(option => option.method),
      effects: {nodes: [], edges: [], calls: [], results: [], log: '已确认本轮解题路线。'}};
    bundle.intro = [...bundle.intro.filter(item => !['D3', 'D4'].includes(item.id)), selection, confirmation];
    bundle.routes = Object.fromEntries(options.map(option => [option.route_id, {
      id: option.route_id, method: option.method, label: nodes.get(option.method)?.label || option.method,
      streaming: true, route_plan: option.route_plan, steps: [], takeaway: '',
    }]));
    bundle.pending = {title: '解题步骤', status: '准备中', text: '正在准备这一步的练习'};
  }
  for (const [id, route] of Object.entries(bundle.routes)) if (route.streaming) {
    const cards = mathSteps.filter(card => card.route_id === id).sort((left, right) => left.ordinal - right.ordinal);
    const decisions = streamDecisions(cards, interactionStates, interactions, interactionProtocol !== null);
    const previous = base.routes[id];
    for (let index = 0; index < (previous?.steps.length || 0); index++) {
      if (JSON.stringify(previous.steps[index]) !== JSON.stringify(decisions[index])) throw new Error('stream.immutable_decision');
    }
    const resolved = new Set(decisions.flatMap(decision => decision.stream_steps.map(ref => ref.step_id)));
    Object.assign(route, streamRouteState(view, targetRef, id, previous), {steps: decisions,
      interactions_complete: cards.length > 0 && resolved.size === cards.length,
      pending_count: cards.length - resolved.size});
  }
  bundle.graph = {...bundle.graph, nodes: [...ids].map(id => copy(nodes.get(id))),
    edges: [...edges.values()].filter(edge => ids.has(edge.from) && ids.has(edge.to)).map(copy)};
  // Newly encountered skills/bases use the same public lane layout as D1/D2.
  if (bundle.graph.lanes) {
    const covered = new Set(bundle.graph.lanes.flatMap(lane => lane.ids || []));
    for (const lane of bundle.graph.lanes) for (const node of bundle.graph.nodes) if (node.kind === lane.kind) covered.add(node.id);
    const extra = bundle.graph.nodes.filter(node => !covered.has(node.id)).map(node => node.id);
    if (extra.length) bundle.graph.lanes.push({label: '本步调用与依据', ids: extra});
  }
  return bundle;
}

/** Checked graph evidence for one exact committed card; independent of reading state. */
export function streamStepGraph(bundle, passed) {
  const result = {nodes: [], edges: [], usedBasis: [], calls: [], logs: []};
  if (!bundle.stream || !passed || !sameStream(bundle.stream, passed)) return result;
  const key = streamStepKey(passed), step = bundle.stream.math_steps.find(value => streamStepKey(value) === key);
  if (!step || passed.math_step_sha256 !== step.math_step_sha256) return result;
  const nodes = new Set(), edges = new Set(), used = new Set();
  const graphNodes = new Map(bundle.graph.nodes.map(node => [node.id, node]));
  const graphEdges = new Map(bundle.graph.edges.map(edge => [edge.id, edge]));
  const light = ref => { if (typeof ref === 'string' && graphNodes.has(nodeId(ref))) nodes.add(nodeId(ref)); };
  const edge = ref => { if (graphEdges.has(ref)) edges.add(ref); };
  for (const [index, call] of (bundle.stream.step_calls[key] || []).entries()) {
    if (!graphNodes.has(call.method)) continue;
    const publicRef = typeof call.ref === 'string' && graphNodes.has(call.ref);
    const path = publicRef ? publicCallPath(call, graphNodes, graphEdges) : null;
    if (publicRef && !path) continue;
    light(call.method);
    for (const basis of call.usedBasis) if (graphNodes.has(nodeId(basis))) {
      light(basis); used.add(basis);
      if (publicRef) edge(`${nodeId(call.ref)}|uses|${nodeId(basis)}`);
    }
    // Internal operations expose checked bases without inventing public calls.
    if (!publicRef) continue;
    light(call.ref);
    if (path.rule) light(path.rule);
    for (const reference of path.edges) edge(reference);
    result.calls.push({...copy(call), edge: path.edge, occurrence: path.occurrence,
      ...(path.rule ? {rule_edges: path.edges} : {}), decision: step.step_id, executionIndex: index});
  }
  result.nodes = [...nodes]; result.edges = [...edges]; result.usedBasis = [...used].sort();
  result.logs.push({decision: step.step_id, text: `已阅读：${step.title}`});
  return result;
}

/** Only completed final parts contribute their covered mathematical cards. */
export function streamGraphState(bundle, state) {
  const view = graphState(bundle, state);
  if (!bundle.stream || state.introCompleted.length < bundle.intro.length) return view;
  const route = bundle.routes[state.run.route];
  if (!route) return view;
  const used = new Set(view.usedBasis), seen = new Set();
  for (const entry of state.run.completed) {
    const decision = route.steps.find(item => item.id === entry.decision);
    if (entry.source !== 'stream' || !entry.stream_last_part || decision?.source !== 'stream' ||
        !decision.stream_last_part || JSON.stringify(entry.stream_steps) !== JSON.stringify(decision.stream_steps)) continue;
    for (const ref of entry.stream_steps) {
      const passed = {...bundle.stream, route_id: state.run.route, ...ref};
      const key = streamStepKey(passed);
      if (seen.has(key)) continue;
      seen.add(key);
      const evidence = streamStepGraph(bundle, passed);
      for (const node of evidence.nodes) view.nodes[node] = 'confirmed';
      for (const edge of evidence.edges) view.edges[edge] = 'chosen';
      for (const basis of evidence.usedBasis) used.add(basis);
      view.calls.push(...evidence.calls.map(call => ({...call, runId: state.run.id})));
    }
  }
  view.usedBasis = [...used].sort();
  return view;
}

// A replay walks `routes` in order: the AI picks the first route itself at the method plane,
// then a {switch_route} action restarts the method steps with the next route. A failed replay
// may end before any route was picked, so only a completed one must name a route.
export function replayState(bundle, replay, count = replay.actions?.length) {
  const routes = replay.routes;
  if (replay.schemaVersion !== 2 || replay.bundleVersion !== bundle.bundleVersion || replay.problemId !== bundle.problemId ||
      !Array.isArray(routes) || (!routes.length && replay.status === 'completed') || new Set(routes).size !== routes.length ||
      !routes.every(route => bundle.routes[route]) || !Array.isArray(replay.actions)) {
    throw new Error('AI 回放与当前题目或版本不一致，请重新录制。');
  }
  if (!Number.isInteger(count) || count < 0 || count > replay.actions.length) throw new Error('回放位置无效。');
  let state = createState(bundle), leg = 0;
  for (const action of replay.actions.slice(0, count)) {
    if (action?.switch_route !== undefined) {
      if (!state.done || action.switch_route !== routes[leg + 1]) throw new Error('AI 回放的换路线位置不一致。');
      state = switchRoute(bundle, state, routes[++leg]);
      continue;
    }
    if (action?.decision !== currentDecision(bundle, state)?.id) throw new Error('AI 回放的步骤顺序不一致。');
    state = submitAnswer(bundle, state, action);
    if (state.run.route && state.run.route !== routes[leg]) throw new Error('AI 回放的路线不一致。');
  }
  if (count === replay.actions.length && replay.status === 'completed' && (!state.done || leg !== routes.length - 1)) {
    throw new Error('AI 回放未完成全部步骤。');
  }
  return state;
}
