/* Shared by both renderers: knowledge points layered by prerequisite, methods in the last column. */
export const NODE_W = 150;
export const NODE_H = 46;
const COL_GAP = 62;
const ROW_GAP = 12;
export const PAD = {top: 44, right: 64, bottom: 24, left: 24};
const LINE_UNITS = 10.5;
export const TOPIC_COLORS = ['#0f8f86', '#d08a1e', '#5b6fd6', '#c2547a'];

/* A knowledge point sits as far right as its successors allow, so points without prerequisite
   links end up next to the methods that use them. */
export function layout({nodes, prerequisites, uses, after}) {
  const knowledge = [...nodes.values()].filter(node => node.kind === 'knowledge');
  const depth = new Map();
  const toSink = id => {
    if (!depth.has(id)) depth.set(id, Math.max(-1, ...after(id).map(toSink)) + 1);
    return depth.get(id);
  };
  knowledge.forEach(node => toSink(node.id));
  const knowledgeCols = Math.max(...depth.values()) + 1;
  const columns = Array.from({length: knowledgeCols + 1}, () => []);
  knowledge.forEach(node => columns[knowledgeCols - 1 - depth.get(node.id)].push(node.id));
  nodes.forEach(node => { if (node.kind === 'method') columns[knowledgeCols].push(node.id); });

  // Edges run left to right. One that skips columns gets an empty slot in every column it
  // crosses, so it passes through a gap instead of behind other nodes.
  const columnOf = new Map(columns.flatMap((ids, index) => ids.map(id => [id, index])));
  const adjacent = new Map();
  const connect = (a, b) => [[a, b], [b, a]].forEach(([p, q]) => adjacent.set(p, [...(adjacent.get(p) || []), q]));
  const via = new Map();
  [...prerequisites.map(edge => [edge.from, edge.to]), ...uses.map(edge => [edge.to, edge.from])].forEach(([left, right]) => {
    const slots = [];
    for (let col = columnOf.get(left) + 1; col < columnOf.get(right); col += 1) {
      slots.push(`${left}>${right}@${col}`);
      columns[col].push(slots.at(-1));
    }
    [left, ...slots, right].reduce((a, b) => { connect(a, b); return b; });
    via.set(`${left}>${right}`, slots);
  });
  const neighbours = id => adjacent.get(id) || [];
  const height = Math.max(...columns.map(column => column.length)) * (NODE_H + ROW_GAP) - ROW_GAP;
  const y = new Map();
  const place = () => columns.forEach(column => {
    const top = PAD.top + (height - (column.length * (NODE_H + ROW_GAP) - ROW_GAP)) / 2;
    column.forEach((id, index) => y.set(id, top + index * (NODE_H + ROW_GAP)));
  });
  place();
  // A few barycentre sweeps keep related nodes at similar heights.
  for (let sweep = 0; sweep < 8; sweep += 1) {
    const order = sweep % 2 ? [...columns].reverse() : columns;
    for (const column of order) {
      const centre = id => {
        const ys = neighbours(id).map(other => y.get(other));
        return ys.length ? ys.reduce((sum, value) => sum + value, 0) / ys.length : y.get(id);
      };
      const keys = new Map(column.map(id => [id, centre(id)]));
      column.sort((a, b) => keys.get(a) - keys.get(b));
      place();
    }
  }
  const x = new Map();
  columns.forEach((column, index) => column.forEach(id => x.set(id, PAD.left + index * (NODE_W + COL_GAP))));
  return {
    x, y, via, columns, knowledgeCols,
    colX: col => PAD.left + col * (NODE_W + COL_GAP),
    width: PAD.left + columns.length * (NODE_W + COL_GAP) - COL_GAP + PAD.right,
    height: PAD.top + height + PAD.bottom,
  };
}

/* Two lines at most: break after punctuation or a space when both halves fit, otherwise
   at the visual middle. Widths are in CJK characters. */
export function wrap(label) {
  const chars = [...label];
  const widths = chars.map(ch => ch.charCodeAt(0) > 255 ? 1 : 0.55);
  const total = widths.reduce((sum, value) => sum + value, 0);
  if (total <= LINE_UNITS) return [label];
  const prefix = widths.map((_, index) => widths.slice(0, index + 1).reduce((sum, value) => sum + value, 0));
  const fits = index => prefix[index] <= LINE_UNITS && total - prefix[index] <= LINE_UNITS;
  const breaks = chars.map((ch, index) => index).filter(index => '：，、／→ '.includes(chars[index]) && fits(index));
  const nearest = list => list.reduce((best, index) => Math.abs(prefix[index] - total / 2) < Math.abs(prefix[best] - total / 2) ? index : best, list[0]);
  const index = breaks.length ? nearest(breaks) : nearest(chars.map((_, i) => i));
  return [chars.slice(0, index + 1).join('').trim(), chars.slice(index + 1).join('').trim()];
}

// Personal coverage segments, in drawing order.
export const PROGRESS = [
  ['mastered', '自评掌握'],
  ['practiced', '练过未自评'],
  ['review', '需再练'],
  ['unpracticed', '未练'],
];
