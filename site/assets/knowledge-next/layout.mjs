import {KINDS} from './model.mjs';

export const NODE_W = 196;

export function fitGraph(layout, width, height) {
  const k = Math.min(1.1, Math.max(1, width - 48) / layout.width, Math.max(1, height - 48) / layout.height);
  return {k, x: (width - layout.width * k) / 2, y: (height - layout.height * k) / 2};
}

const LINE = 17, PAD = 36, HEAD = 68, GAP_Y = 12, GAP_X = 14, LANE_GAP = 128, SUB_GAP = 72;
const FRAME_PAD = 22, FRAME_GAP = 44, ROW_ORDER = ['knowledge','skill','method','problem_type','judgment_rule'];

// Knowledge sits between the problem types that involve it and the skills that use it;
// the solution view reads left to right as a problem is solved.
const LANES = {
  knowledge: [
    {label: '题型', test: n => n.kind === 'problem_type'},
    {label: '知识点 · 按前置顺序', test: n => n.kind === 'knowledge', rankBy: 'prerequisite'},
    {label: '技能', test: n => n.kind === 'skill'},
  ],
  solution: [
    {label: '题型', test: n => n.kind === 'problem_type'},
    {label: '选法判断', test: n => n.kind === 'judgment_rule' && n.subtype === 'method_selection'},
    {label: '方法', test: n => n.kind === 'method'},
    {label: '步骤判断', test: n => n.kind === 'judgment_rule'},
    {label: '技能', test: n => n.kind === 'skill'},
  ],
};

export function wrapLabel(label, maxWidth = 24) {
  const lines = []; let line = '', width = 0;
  for (const char of label) {
    const w = /[\x00-\xff]/.test(char) ? 1 : 2;
    if (width + w > maxWidth) { lines.push(line); line = ''; width = 0; }
    line += char; width += w;
  }
  if (line) lines.push(line);
  return lines;
}
export const textWidth = (text, size = 13) => [...text].reduce((s, c) => s + (/[\x00-\xff]/.test(c) ? size * .56 : size), 0);
const sized = n => { const lines = wrapLabel(n.label); return {lines, w: NODE_W, h: lines.length > 1 ? 22 + lines.length * LINE : 40}; };
const pill = n => ({lines: [n.label], w: Math.round(50 + textWidth(n.label)), h: 40});
const byLabel = nodes => (a, b) => nodes.get(a).label.localeCompare(nodes.get(b).label, 'zh-Hans-CN') || a.localeCompare(b, 'en');

// Condense strongly connected components before ranking: only knowledge
// prerequisites are guaranteed acyclic, arbitrary projections are not.
function ranks(nodes, edges) {
  const ids = new Set(nodes.map(n => n.id)), adjacency = new Map(nodes.map(n => [n.id, []]));
  for (const e of edges) if (ids.has(e.from) && ids.has(e.to)) adjacency.get(e.from).push(e.to);
  let clock = 0; const index = new Map(), low = new Map(), stack = [], onStack = new Set(), components = [];
  function visit(id) {
    index.set(id, clock); low.set(id, clock++); stack.push(id); onStack.add(id);
    for (const to of adjacency.get(id)) {
      if (!index.has(to)) { visit(to); low.set(id, Math.min(low.get(id), low.get(to))); }
      else if (onStack.has(to)) low.set(id, Math.min(low.get(id), index.get(to)));
    }
    if (low.get(id) === index.get(id)) { const group = []; let v; do { v = stack.pop(); onStack.delete(v); group.push(v); } while (v !== id); components.push(group); }
  }
  nodes.forEach(n => { if (!index.has(n.id)) visit(n.id); });
  const component = new Map(components.flatMap((g, i) => g.map(id => [id, i]))), parents = components.map(() => new Set());
  for (const e of edges) if (ids.has(e.from) && ids.has(e.to) && component.get(e.from) !== component.get(e.to)) parents[component.get(e.to)].add(component.get(e.from));
  const memo = new Map();
  const rank = i => { if (!memo.has(i)) memo.set(i, parents[i].size ? 1 + Math.max(...[...parents[i]].map(rank)) : 0); return memo.get(i); };
  return new Map(nodes.map(n => [n.id, rank(component.get(n.id))]));
}

// Barycenter sweeps: each node moves toward the average height of its neighbours in other columns.
function orderColumns(columns, edges) {
  const column = new Map(), neighbours = new Map();
  columns.forEach((c, i) => c.forEach(id => { column.set(id, i); neighbours.set(id, []); }));
  for (const e of edges) if (column.has(e.from) && column.has(e.to) && column.get(e.from) !== column.get(e.to)) { neighbours.get(e.from).push(e.to); neighbours.get(e.to).push(e.from); }
  const place = new Map();
  const measure = c => c.forEach((id, k) => place.set(id, (k + .5) / c.length));
  columns.forEach(measure);
  for (let pass = 0; pass < 8; pass++) {
    const order = pass % 2 ? [...columns.keys()].reverse() : [...columns.keys()];
    for (const i of order) {
      const score = new Map(columns[i].map(id => { const ns = neighbours.get(id); return [id, ns.length ? ns.reduce((s, o) => s + place.get(o), 0) / ns.length : place.get(id)]; }));
      columns[i].sort((a, b) => score.get(a) - score.get(b));
      measure(columns[i]);
    }
  }
}

export function lanesLayout(nodes, edges, defs) {
  const byId = new Map(nodes.map(n => [n.id, n])), assigned = new Set(), columns = [], bands = [];
  for (const def of defs) {
    const members = nodes.filter(n => !assigned.has(n.id) && def.test(n));
    if (!members.length) continue;
    members.forEach(n => assigned.add(n.id));
    const band = {label: def.label, count: members.length, cols: []};
    if (def.rankBy) {
      const rank = ranks(members, edges.filter(e => e.type === def.rankBy)), levels = new Map();
      for (const n of members) { const r = rank.get(n.id); if (!levels.has(r)) levels.set(r, []); levels.get(r).push(n.id); }
      for (const [, ids] of [...levels].sort((a, b) => a[0] - b[0])) { band.cols.push(columns.length); columns.push(ids); }
    } else { band.cols.push(columns.length); columns.push(members.map(n => n.id)); }
    bands.push(band);
  }
  const rest = nodes.filter(n => !assigned.has(n.id));
  if (rest.length) { bands.push({label: '其他', count: rest.length, cols: [columns.length]}); columns.push(rest.map(n => n.id)); }
  columns.forEach(c => c.sort(byLabel(byId)));
  orderColumns(columns, edges);

  const sizes = new Map(nodes.map(n => [n.id, sized(n)]));
  const heights = columns.map(c => c.reduce((s, id) => s + sizes.get(id).h, 0) + Math.max(0, c.length - 1) * GAP_Y);
  const maxH = Math.max(120, ...heights), colX = [], top = defs.some(d => d.label) ? HEAD : PAD;
  let x = PAD;
  for (const band of bands) {
    band.x = x - 18;
    band.cols.forEach((ci, k) => { colX[ci] = x; x += NODE_W + (k < band.cols.length - 1 ? SUB_GAP : 0); });
    band.w = x - band.x + 18; band.y = top - (band.label ? 50 : 18); band.h = maxH + (band.label ? 68 : 36);
    x += LANE_GAP;
  }
  const positions = new Map();
  columns.forEach((c, ci) => {
    let y = top + (maxH - heights[ci]) / 2;
    for (const id of c) { const s = sizes.get(id); positions.set(id, {x: colX[ci], y, ...s}); y += s.h + GAP_Y; }
  });
  return {
    positions, width: Math.max(320, x - LANE_GAP + PAD), height: top + maxH + PAD, routing: 'lanes', implicit: [],
    bands: bands.map(({label, count, x, y, w, h}) => ({label, count, x, y, w, h})), frames: [], labels: [], notes: [],
  };
}

function curriculumLayout(nodes, edges, structure, {perRow = Infinity, cols: frameCols = 0} = {}) {
  const byId = new Map(nodes.map(n => [n.id, n])), positions = new Map(), frames = [], labels = [], notes = [];
  const sections = structure.sections, home = new Map();
  for (const relation of ['contains', 'extends']) for (const s of sections) for (const m of s.members) {
    if (byId.has(m.id) && m.relation === relation && !home.has(m.id)) home.set(m.id, {section: s.id, tag: relation === 'extends' ? '拓展' : ''});
  }
  // Judgment rules are not section members; they sit with the node that enters them.
  for (const e of edges) if (['method_rule','step_rule'].includes(e.type) && byId.has(e.to) && !home.has(e.to) && home.has(e.from)) home.set(e.to, {section: home.get(e.from).section, tag: ''});
  const org = new Set([...structure.crumbs, ...sections.map(s => s.id)]);
  const related = nodes.filter(n => !org.has(n.id) && !home.has(n.id)).map(n => n.id);

  let x = PAD, y = PAD;
  const crumbs = structure.crumbs.filter(id => byId.has(id));
  crumbs.forEach((id, i) => {
    const s = pill(byId.get(id)); positions.set(id, {x, y, ...s}); x += s.w;
    if (i < crumbs.length - 1) { labels.push({x: x + 15, y: y + 26, text: '›', cls: 'crumb-sep'}); x += 30; }
  });
  if (crumbs.length) y += 40 + 30;

  let fx = PAD, bottom = y, right = x, inRow = 0;
  const place = (id, ids, {cols, title = '', header = '', dashed = false, shared = []}) => {
    if (inRow >= perRow) { fx = PAD; y = bottom + FRAME_GAP; inRow = 0; }
    inRow++;
    const inner = cols * NODE_W + (cols - 1) * GAP_X;
    let cy = y + FRAME_PAD;
    if (header && byId.has(header)) { const s = pill(byId.get(header)); positions.set(header, {x: fx + FRAME_PAD, y: cy, ...s, w: Math.min(inner, s.w)}); cy += 40 + 20; }
    else if (title) { labels.push({x: fx + FRAME_PAD, y: cy + 18, text: title, cls: 'frame-title'}); cy += 38; }
    const kinds = [...ROW_ORDER, ...Object.keys(KINDS).filter(k => !ROW_ORDER.includes(k))];
    for (const kind of kinds) {
      const row = ids.filter(id => byId.get(id).kind === kind).sort(byLabel(byId));
      if (!row.length) continue;
      labels.push({x: fx + FRAME_PAD + 2, y: cy + 12, text: `${KINDS[kind]} · ${row.length}`, cls: 'row-label', kind});
      cy += 24;
      for (let i = 0; i < row.length; i += cols) {
        const line = row.slice(i, i + cols), lineH = Math.max(...line.map(id => sized(byId.get(id)).h));
        line.forEach((rid, k) => positions.set(rid, {x: fx + FRAME_PAD + k * (NODE_W + GAP_X), y: cy, ...sized(byId.get(rid)), tag: home.get(rid)?.tag || ''}));
        cy += lineH + GAP_Y;
      }
      cy += 12;
    }
    if (shared.length) {
      labels.push({x: fx + FRAME_PAD + 2, y: cy + 12, text: '本节也包含（位于其他节）', cls: 'row-label'});
      cy += 22;
      const items = []; let nx = 0;
      for (const sid of shared) {
        const w = Math.round(textWidth(byId.get(sid).label, 12) + 26);
        if (nx && nx + w > inner) { nx = 0; cy += 32; }
        items.push({id: sid, label: byId.get(sid).label, x: fx + FRAME_PAD + nx, y: cy, w, h: 26}); nx += w + 8;
      }
      notes.push({items}); cy += 26 + 16;
    }
    const w = inner + FRAME_PAD * 2, h = Math.max(cy - y + FRAME_PAD - 12, 120);
    frames.push({id, x: fx, y, w, h, dashed});
    fx += w + FRAME_GAP; bottom = Math.max(bottom, y + h); right = Math.max(right, fx - FRAME_GAP);
  };
  const widest = Math.max(1, ...ROW_ORDER.map(k => [...home].filter(([id]) => byId.get(id).kind === k).length));
  const cols = frameCols || (sections.length > 1 ? 3 : Math.min(5, Math.max(3, widest)));
  for (const s of sections) {
    const own = [...home].filter(([, v]) => v.section === s.id).map(([id]) => id);
    const shared = s.members.filter(m => byId.has(m.id) && home.get(m.id)?.section !== s.id).map(m => m.id);
    place(s.id, own, {cols, header: s.id, title: s.label, shared});
  }
  if (related.length) place('related', related, {cols: 2, title: '按需展开的相关内容', dashed: true});
  return {positions, width: right + PAD, height: bottom + PAD, routing: 'frames', implicit: ['contains', 'extends'], bands: [], frames, labels, notes, perRow, cols};
}

// With a canvas size, section frames wrap (and narrow) into whichever arrangement
// shows them largest. The first view never drops below canvas.minScale, so among
// arrangements clamped to it the one showing the most of the graph wins.
export function layoutGraph(nodes, edges, {view, structure, canvas} = {}) {
  if (view === 'curriculum' && structure) {
    let best = curriculumLayout(nodes, edges, structure);
    if (!canvas?.width || !canvas?.height) return best;
    const {width, height, minScale = 0} = canvas;
    const score = l => {
      const k = Math.max(fitGraph(l, width, height).k, minScale);
      return [k, Math.min(1, width / (l.width * k)) * Math.min(1, height / (l.height * k))];
    };
    const better = ([k, seen], [bestK, bestSeen]) => k > bestK + 1e-6 || (k > bestK - 1e-6 && seen > bestSeen + 1e-6);
    let bestScore = score(best);
    const colsOptions = [...new Set([best.cols, Math.min(best.cols, 3), 2])];
    for (const cols of colsOptions) for (let perRow = best.frames.length; perRow >= 1; perRow--) {
      if (cols === best.cols && perRow === best.frames.length) continue;
      const next = curriculumLayout(nodes, edges, structure, {perRow, cols}), s = score(next);
      if (better(s, bestScore)) { best = next; bestScore = s; }
    }
    return best;
  }
  if (LANES[view]) return lanesLayout(nodes, edges, LANES[view]);
  const rank = ranks(nodes, edges), levels = [...new Set(rank.values())].sort((a, b) => a - b);
  return lanesLayout(nodes, edges, levels.map(r => ({label: '', test: n => rank.get(n.id) === r})));
}
