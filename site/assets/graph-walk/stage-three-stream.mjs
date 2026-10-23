/** Consume committed mathematical fragments without waiting for a complete route.
 * Transport is injected: HTTP polling and WebSocket can feed the same reducer.
 * Reading progress belongs to the view; sequence numbers only order delivery.
 */

const copy = value => structuredClone(value);
const routeKey = (target, route) => JSON.stringify([target, route]);
const stepKey = step => JSON.stringify([step.target_ref, step.route_id, step.step_id]);
const unavailable = goal => Boolean(goal && (goal.status === 'conflict' || goal.available === false || goal.reason === 'route_consistency_undecidable'));
const pick = (value, fields) => Object.fromEntries(fields.filter(key => Object.hasOwn(value, key)).map(key => [key, copy(value[key])]));
const INTERACTION_PROTOCOL = 'graph-step-interaction/v1';
const routeSummary = value => pick(value, ['target_ref', 'route_id', 'status', 'phase', 'commit_id', 'last_seq']);

// Normalize legacy/full event records and compact snapshots to the same public
// evidence. Array positions remain the source_refs identities of checked calls.
function sourceEvidence(value) {
  const result = pick(value, ['public_ref', 'rule_ref', 'branch', 'used_basis', 'case_path']);
  if (Object.hasOwn(value, 'postconditions')) result.postconditions = Array.isArray(value.postconditions)
    ? value.postconditions.map(check => check && typeof check === 'object' ? pick(check, ['passed']) : {}) : [];
  return result;
}

function trajectoryEvidence(value) {
  return {...pick(value, ['seq', 'method', 'step', 'case_path']), calls: (value.calls || []).map(sourceEvidence)};
}

/** Adapt saved legacy math values once at the stream read boundary. */
function readMathValues(value) {
  if (Array.isArray(value)) return value.map(readMathValues);
  if (!value || typeof value !== 'object') return value;
  const legacy = typeof value.expression === 'string' && typeof value.display === 'string'
    && Object.keys(value).every(key => ['expression', 'display', 'exact'].includes(key));
  return Object.fromEntries(Object.entries(value).map(([key, child]) =>
    [legacy && key === 'display' ? 'latex' : key, key === 'decision' ? copy(child) : readMathValues(child)]));
}

export function createEventConsumer(identity, hooks = {}) {
  const run = {run_id: identity.run_id, lesson_version: identity.lesson_version, stream_id: identity.stream_id || identity.run_id};
  if (!run.run_id || !run.lesson_version) throw new Error('stream.missing_identity');
  let lastSeq = 0;
  const pending = new Map(), seen = new Map(), steps = new Map(), goals = new Map();
  const completions = new Map(), qa = new Map(), routeStatuses = new Map(), enrichmentStatuses = new Map();
  const selections = new Map(), trajectories = new Map(), finalizations = new Map();
  // Per-card interaction state (pending → interactive | readonly) and final chunks by interaction_id.
  const interactionStates = new Map(), interactions = new Map();
  let checkpoints = [], interactionProtocol = null;
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

  function openInteraction(step, status) {
    const key = stepKey(step);
    if (!['pending', 'readonly'].includes(status)) throw new Error('stream.invalid_interaction_status');
    // A snapshot may predate enable_interactions. The first annotated card is
    // itself proof of the protocol; pending must never fall back to legacy read.
    interactionProtocol ??= INTERACTION_PROTOCOL;
    if (!interactionStates.has(key)) interactionStates.set(key, {status});
  }

  function validInteractionShape(chunk) {
    return Boolean(chunk && matches(chunk) && chunk.contract === INTERACTION_PROTOCOL &&
      typeof chunk.interaction_id === 'string' && chunk.interaction_id &&
      ['interactive', 'readonly'].includes(chunk.status) && Array.isArray(chunk.steps) &&
      chunk.steps.length >= 1 && chunk.steps.length <= 2 && chunk.steps.every(value => value && typeof value === 'object') &&
      Array.isArray(chunk.parts) && (chunk.status === 'interactive' ? chunk.parts.length > 0 : chunk.parts.length === 0));
  }

  /** A final interaction resolves its contiguous cards once; it never changes their mathematics. */
  function acceptInteraction(chunk) {
    if (!validInteractionShape(chunk)) throw new Error('stream.invalid_interaction');
    const previous = interactions.get(chunk.interaction_id);
    if (previous) {
      if (JSON.stringify(previous) !== JSON.stringify(chunk)) throw new Error('stream.immutable_interaction');
      return;
    }
    const covered = chunk.steps.map(value => {
      const key = stepKey({target_ref: chunk.target_ref, route_id: chunk.route_id, step_id: value.step_id});
      const step = steps.get(key);
      if (!step || step.math_step_sha256 !== value.math_step_sha256) throw new Error('stream.interaction_hash_mismatch');
      const state = interactionStates.get(key);
      if (state?.interaction_id && state.interaction_id !== chunk.interaction_id) throw new Error('stream.interaction_conflict');
      return {key, step};
    });
    if (covered.some(({step}, index) => step.ordinal !== covered[0].step.ordinal + index)) {
      throw new Error('stream.interaction_noncontiguous');
    }
    const prior = covered.map(({key}) => interactionStates.get(key)), priorProtocol = interactionProtocol;
    interactionProtocol ??= INTERACTION_PROTOCOL;
    interactions.set(chunk.interaction_id, copy(chunk));
    for (const {key} of covered) interactionStates.set(key, {status: chunk.status, interaction_id: chunk.interaction_id});
    try { hooks.onInteraction?.(copy(chunk)); } catch (error) {
      interactions.delete(chunk.interaction_id);
      covered.forEach(({key}, index) => prior[index] ? interactionStates.set(key, prior[index]) : interactionStates.delete(key));
      interactionProtocol = priorProtocol;
      throw error;
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

  function acceptTrajectory(target, route, values, finalization = []) {
    const key = routeKey(target, route), rows = trajectories.get(key) || new Map();
    for (const value of values || []) rows.set(value.seq, trajectoryEvidence(value));
    trajectories.set(key, rows);
    const operations = finalizations.get(key) || new Map();
    for (const value of finalization) {
      if (!Number.isInteger(value.index) || value.index < 0 || !value.record || typeof value.record !== 'object') {
        throw new Error('stream.invalid_finalization_source');
      }
      const record = sourceEvidence(value.record), previous = operations.get(value.index);
      if (previous && JSON.stringify(previous) !== JSON.stringify(record)) throw new Error('stream.immutable_finalization_source');
      operations.set(value.index, record);
    }
    finalizations.set(key, operations);
  }

  function applyOrdered(event) {
    const payload = event.payload, target = event.target_ref, key = routeKey(target, event.route_id);
    if (!payload || typeof payload !== 'object') throw new Error('stream.invalid_payload');
    if (event.type === 'lesson.chunk_ready' && ['D1', 'D2', 'D3', 'D4'].includes(payload.kind)) {
      acceptSelection(target, payload.kind, payload.chunk);
    } else if (event.type === 'solver.step_completed') {
      acceptTrajectory(target, event.route_id, payload.trajectory, payload.finalization);
    } else if (event.type === 'lesson.chunk_ready' && payload.kind === 'math_step') {
      const step = payload.chunk;
      if (!step || step.target_ref !== target || step.route_id !== event.route_id ||
          step.step_id !== payload.step_id || step.math_step_sha256 !== payload.math_step_sha256) throw new Error('stream.math_identity_mismatch');
      acceptStep(step);
      if (payload.interaction_status !== undefined) openInteraction(step, payload.interaction_status);
    } else if (event.type === 'lesson.chunk_ready' && payload.kind === 'step_interaction') {
      const chunk = payload.chunk;
      if (!chunk || chunk.target_ref !== target || chunk.route_id !== event.route_id ||
          chunk.interaction_id !== payload.interaction_id || chunk.status !== payload.status) throw new Error('stream.interaction_identity_mismatch');
      acceptInteraction(chunk);
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
    event = readMathValues(event);
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

  /** Check the complete interaction projection before hydrate mutates any state or DOM. */
  function validateInteractionSnapshot(snapshot, available) {
    const reject = () => { throw new Error('stream.snapshot_interaction_changed'); };
    const protocol = snapshot.interaction_protocol ?? null;
    const rows = snapshot.interaction_states ?? [], values = snapshot.interactions ?? [];
    if (!Array.isArray(rows) || !Array.isArray(values) || (protocol !== null && protocol !== INTERACTION_PROTOCOL)) reject();
    if (protocol === null && (rows.length || values.length || interactionStates.size || interactions.size)) reject();
    const states = new Map(), chunks = new Map(), covered = new Set();
    for (const row of rows) {
      if (!row || typeof row !== 'object') reject();
      const key = stepKey(row), step = available.get(key);
      if (!step || states.has(key) || step.ordinal !== row.ordinal || step.math_step_sha256 !== row.math_step_sha256 ||
          !['pending', 'interactive', 'readonly'].includes(row.status)) reject();
      if (row.status === 'pending' ? Object.hasOwn(row, 'interaction_id')
        : typeof row.interaction_id !== 'string' || !row.interaction_id) reject();
      const previous = interactionStates.get(key);
      if (previous?.interaction_id && (previous.interaction_id !== row.interaction_id || previous.status !== row.status)) reject();
      states.set(key, row);
    }
    // Enabled snapshots describe every card, including those still awaiting a result.
    if (protocol === INTERACTION_PROTOCOL && states.size !== available.size) reject();
    for (const chunk of values) {
      if (!validInteractionShape(chunk) || chunks.has(chunk.interaction_id)) reject();
      let ordinal;
      for (const value of chunk.steps) {
        const key = stepKey({target_ref: chunk.target_ref, route_id: chunk.route_id, step_id: value.step_id});
        const step = available.get(key), state = states.get(key);
        if (!step || !state || covered.has(key) || step.math_step_sha256 !== value.math_step_sha256 ||
            state.interaction_id !== chunk.interaction_id || state.status !== chunk.status ||
            (ordinal !== undefined && step.ordinal !== ordinal + 1)) reject();
        ordinal = step.ordinal;
        covered.add(key);
      }
      chunks.set(chunk.interaction_id, chunk);
    }
    for (const [key, row] of states) if (row.status !== 'pending' && !covered.has(key)) reject();
    for (const [identifier, previous] of interactions) {
      if (JSON.stringify(chunks.get(identifier)) !== JSON.stringify(previous)) reject();
    }
    return {protocol, states, chunks};
  }

  /** Apply only a projection already validated against all snapshot cards. */
  function hydrateInteractions({protocol, states, chunks}) {
    const priorStates = new Map(interactionStates), priorChunks = new Map(interactions), priorProtocol = interactionProtocol;
    try {
      for (const [key, row] of states) {
        const previous = interactionStates.get(key);
        if (!previous?.interaction_id) {
          interactionStates.set(key, row.interaction_id ? {status: row.status, interaction_id: row.interaction_id} : {status: row.status});
        }
      }
      if (protocol) interactionProtocol = protocol;
      for (const chunk of chunks.values()) acceptInteraction(chunk);
    } catch (error) {
      // A later hook may fail after earlier chunks were accepted. Restore the
      // whole interaction projection so retrying also redelivers those chunks.
      interactionStates.clear();
      for (const [key, value] of priorStates) interactionStates.set(key, value);
      interactions.clear();
      for (const [key, value] of priorChunks) interactions.set(key, value);
      interactionProtocol = priorProtocol;
      throw error;
    }
  }

  function hydrate(snapshot) {
    snapshot = readMathValues(snapshot);
    if (!matches(snapshot) || snapshot.stream_id !== run.stream_id) throw new Error('stream.snapshot_identity_mismatch');
    if (!Number.isInteger(snapshot.last_seq) || snapshot.last_seq < lastSeq) throw new Error('stream.stale_snapshot');
    const available = new Map((snapshot.math_steps || []).map(step => [stepKey(step), step]));
    for (const [key, previous] of steps) {
      if (JSON.stringify(available.get(key)) !== JSON.stringify(previous)) throw new Error('stream.snapshot_math_changed');
    }
    const interactionSnapshot = validateInteractionSnapshot(snapshot, available);
    goals.clear();
    for (const [target, value] of Object.entries(snapshot.goals || {})) goals.set(target, copy(value));
    checkpoints = (snapshot.checkpoints || []).map(routeSummary);
    if (snapshot.trajectories) {
      for (const trajectory of snapshot.trajectories) {
        acceptTrajectory(trajectory.target_ref, trajectory.route_id, trajectory.steps, trajectory.finalization);
      }
    } else {
      // Saved v1 snapshots still carry their evidence inside full checkpoints.
      for (const checkpoint of snapshot.checkpoints || []) {
        const trajectory = checkpoint.driver_state?.trajectory;
        acceptTrajectory(checkpoint.target_ref, checkpoint.route_id, trajectory?.steps,
          (trajectory?.finalization || []).map((record, index) => ({index, record})));
      }
    }
    for (const selection of snapshot.selection_chunks || []) acceptSelection(selection.target_ref, selection.kind, selection.chunk);
    for (const step of (snapshot.math_steps || []).slice().sort((left, right) => left.ordinal - right.ordinal)) acceptStep(step);
    hydrateInteractions(interactionSnapshot);
    completions.clear();
    for (const task of snapshot.handoffs || []) {
      if (task.available && !unavailable(goals.get(task.target_ref))) completions.set(routeKey(task.target_ref, task.route_id), {
        kind: 'route_completion', status: 'verified', answer: copy(task.answer), feasible_set: copy(task.feasible_set),
        verified_route_sha256: task.verified_route_sha256,
        ...(task.original_choice ? {original_choice: copy(task.original_choice)} : {}),
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
      interaction_protocol: interactionProtocol,
      interaction_states: orderedSteps().filter(step => interactionStates.has(stepKey(step))).map(step => ({
        target_ref: step.target_ref, route_id: step.route_id, step_id: step.step_id,
        ordinal: step.ordinal, math_step_sha256: step.math_step_sha256, ...copy(interactionStates.get(stepKey(step)))})),
      interactions: copy([...interactions.values()]),
      trajectories: [...trajectories].map(([key, values]) => ({target_ref: JSON.parse(key)[0], route_id: JSON.parse(key)[1],
        steps: copy([...values.values()].sort((a, b) => a.seq - b.seq)),
        finalization: [...(finalizations.get(key) || [])].map(([index, record]) => ({index, record: copy(record)}))}))};
  }

  return {accept, hydrate, view, get last_seq() { return lastSeq; }};
}

/** Subscribe to committed data. The walk engine owns cards and student progress. */
export function mountStageThreeStream(identity, options = {}) {
  let stopped = false, started = false, polling = false, timer = null;
  const consumer = createEventConsumer(identity, {
    onMathStep: value => options.onMathStep?.(value),
    onQA: value => options.onQA?.(value),
    onInteraction: value => options.onInteraction?.(value),
    onSelection: (...args) => options.onSelection?.(...args),
    onGoalStatus: (...args) => options.onGoalStatus?.(...args),
    onRouteCompletion: (...args) => options.onRouteCompletion?.(...args),
    onRouteStatus: (...args) => options.onRouteStatus?.(...args),
    onEnrichmentStatus: (...args) => options.onEnrichmentStatus?.(...args),
    onSnapshot(state) {
      // The attachment entry point is idempotent. Replay saved QA even when the
      // consumer already knows it, so a remounted engine restores its asides.
      for (const chunk of state.qa) if (!unavailable(state.goals[chunk.target_ref])) options.onQA?.(copy(chunk));
      options.onSnapshot?.(state);
    },
    onGap: cursor => options.onGap?.(cursor),
    onEvent: event => options.onEvent?.(event),
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
    try { await pollOnce(); } catch { /* Preserve committed data while the transport reconnects. */ }
    if (!stopped) timer = setTimeout(schedule, options.pollInterval ?? 500);
  }

  return {consumer, pollOnce, start() { if (!started && !stopped) { started = true; schedule(); } },
    stop() { stopped = true; if (timer) clearTimeout(timer); },
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
