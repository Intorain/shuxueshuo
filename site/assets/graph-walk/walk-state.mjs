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
  return bundle.routes[state.run.route]?.steps[state.run.completed.length] || null;
}

export function gradeDecision(decision, answer) {
  if (!decision) return {status: 'wrong', message: '当前没有待作答步骤。'};
  const alternative = typeof answer === 'string' && decision.alternatives?.[answer];
  if (alternative) {
    return {status: 'uncovered', message: alternative.message, href: alternative.href};
  }
  const component = decision.interaction;
  try {
    if (component.type === 'multi') {
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

const routeOf = (decision, answer) => decision.interaction.methods?.find(method => method.value === answer?.[2])?.route;
const methodChoice = bundle => bundle.intro.find(decision => decision.interaction.type === 'plane');

function completeDecision(bundle, next, decision, answer, reason) {
  const entry = {
    decision: decision.id,
    answer: copy(answer),
    reason: typeof reason === 'string' ? reason.slice(0, 6000) : '',
    results: copy(decision.effects?.results || []),
    calls: copy(decision.effects?.calls || []),
    runId: decision.source === 'page' ? next.run.id : null,
  };
  if (next.introCompleted.length < bundle.intro.length) {
    next.introCompleted.push(entry);
    if (decision.interaction.type === 'plane') {
      const route = routeOf(decision, answer);
      if (!bundle.routes[route]) throw new Error('此路线尚未提供完整交互。');
      next.run.route = route;
    }
  } else {
    next.run.completed.push(entry);
  }
  next.done = next.introCompleted.length === bundle.intro.length &&
    Boolean(next.run.route) && next.run.completed.length === bundle.routes[next.run.route].steps.length;
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
  return next;
}

export function switchRoute(bundle, state, route) {
  checkVersion(bundle, state);
  if (!bundle.routes[route] || state.introCompleted.length < bundle.intro.length) {
    throw new Error('请先完成题型和选法判断。');
  }
  const next = copy(state);
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
  const last = state.events.findLastIndex(event => event.status === 'passed');
  if (last < 0) return createState(bundle);
  let next = createState(bundle);
  for (const event of state.events.slice(0, last)) {
    next = event.kind === 'switch_route'
      ? switchRoute(bundle, next, event.route)
      : submitAnswer(bundle, next, event.action);
  }
  next.lastFeedback = null;
  return next;
}

function publicInteraction(component) {
  const result = {type: component.type};
  for (const key of ['field', 'title', 'terms', 'term_labels', 'slot_labels', 'slot_shapes', 'x', 'y', 'zones']) {
    if (component[key] !== undefined) result[key] = copy(component[key]);
  }
  if (component.methods) {
    result.methods = component.methods.map(({value, label, cells, route}) => ({value, label, cells: copy(cells), implemented: Boolean(route)}));
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
    answerFormat: interaction.type === 'choice'
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
  const realEdges = new Set(bundle.graph.edges.map(edge => edge.id));
  const edge = id => { if (realEdges.has(id)) edges.add(id); };
  for (const entry of entries) {
    const decision = decisionById(bundle, entry.decision);
    const effects = decision?.effects || {};
    for (const id of effects.nodes || []) nodes.add(id);
    for (const id of effects.edges || []) edge(id);
    if (effects.log) logs.push({decision: entry.decision, text: effects.log});
    if (decision?.interaction.type === 'plane' && route) {
      logs.push({decision: entry.decision, text: `作答判断：选择「${bundle.routes[route].label}」，执行本路线的方法步骤。`});
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
  if (route) {
    const method = bundle.routes[route].method;
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
  const focus = current?.candidateNodes?.length ? current.candidateNodes : state.run.route ? [bundle.routes[state.run.route].method] : [];
  for (const id of focus) if (id in nodes && nodes[id] === 'idle') nodes[id] = 'candidate';
  if (current?.interaction.type === 'plane') {
    nodes['rule-quadratic-method'] = 'active';
    for (const edge of bundle.graph.edges.filter(edge => edge.from === 'rule-quadratic-method' && edge.type === 'selects')) {
      if (edges[edge.id] !== 'chosen') edges[edge.id] = 'candidate';
    }
  } else if (current?.source === 'page' && state.run.route) {
    nodes[bundle.routes[state.run.route].method] = 'active';
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
