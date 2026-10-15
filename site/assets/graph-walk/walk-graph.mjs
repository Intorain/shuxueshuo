/* A local SVG view of a fixed graph snapshot. No graph loader or personal state. */
const NS = 'http://www.w3.org/2000/svg';
export const KIND_LABELS = {knowledge: '知识点', skill: '技能', method: '方法', problem_type: '题型', judgment_rule: '判断规则', entry: '知识条目'};
export const RELATIONS = {involves: '涉及', prerequisite: '前置', method_rule: '选法判断', selects: '条件满足时选择', calls: '调用', uses: '依据', step_rule: '步骤判断', candidate: '可选用', confuse: '易混'};
export const STATUS_LABELS = {idle: '未触达', candidate: '候选', active: '当前', confirmed: '已确认', rejected: '不推荐', skipped: '本次未调用', wrong: '本次尝试', chosen: '已调用'};
const TREE = {nodeW: 152, gapX: 14, gapY: 10, laneGap: 18, gutter: 92, pad: 20, sweeps: 6};

function element(tag, attributes = {}, text) {
  const node = document.createElementNS(NS, tag);
  for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, String(value));
  if (text !== undefined) node.textContent = text;
  return node;
}

function linesOf(text, limit = 22) {
  const lines = [];
  let line = '', width = 0;
  for (const character of text) {
    const size = /[\x00-\xff]/.test(character) ? 1 : 2;
    if (line && width + size > limit) { lines.push(line); line = ''; width = 0; }
    line += character; width += size;
  }
  if (line) lines.push(line);
  return lines;
}

export function nodeHref(node) {
  const ref = node.ref || node.id;
  const [id, entry] = ref.split('#');
  return `/knowledge/${encodeURIComponent(id)}/${entry ? `#${encodeURIComponent(entry)}` : ''}`;
}

/* The snapshot's lanes read left to right. The 2D view stacks them top-down, each lane named in a left gutter,
   so a solution reads downward from the clues like a tree. A long lane wraps into a grid of at most perRow
   columns, filled column by column so left to right still means one order. A few sweeps move each name toward
   the mean x of its neighbours in other lanes, which keeps connected names roughly above one another. */
export function treeLayout(graph, {perRow = 4, ...options} = {}) {
  const {nodeW, gapX, gapY, laneGap, gutter, pad, sweeps} = {...TREE, ...options};
  const {layout} = graph;
  const source = layout.positions instanceof Map ? layout.positions : new Map(Object.entries(layout.positions));
  const byId = new Map([...graph.nodes, ...(graph.entries || [])].map(node => [node.id, node]));
  const sizes = new Map([...source.keys()].map(id => {
    const lines = linesOf(byId.get(id)?.label || id, Math.floor((nodeW - 26) / 6.5));
    return [id, {lines, w: nodeW, h: lines.length > 1 ? 22 + lines.length * 17 : 40}];
  }));
  const bands = [...(layout.bands?.length ? layout.bands : [{label: '', x: -Infinity, w: Infinity}])].sort((a, b) => a.x - b.x);
  const lanes = bands.map(() => []), laneOf = new Map();
  for (const [id, p] of [...source].sort((a, b) => a[1].y - b[1].y)) {
    const center = p.x + p.w / 2, found = bands.findIndex(band => center >= band.x && center < band.x + band.w);
    const index = found < 0 ? bands.length - 1 : found;
    lanes[index].push(id); laneOf.set(id, index);
  }
  const neighbours = new Map([...laneOf.keys()].map(id => [id, []]));
  for (const edge of graph.edges) {
    if (!laneOf.has(edge.from) || !laneOf.has(edge.to) || laneOf.get(edge.from) === laneOf.get(edge.to)) continue;
    neighbours.get(edge.from).push(edge.to); neighbours.get(edge.to).push(edge.from);
  }
  const labelled = bands.some(band => band.label), left = pad + (labelled ? gutter : 0);
  const shape = lane => { const rows = Math.ceil(lane.length / perRow); return {rows, cols: Math.ceil(lane.length / rows)}; };
  const gridWidth = cols => cols * nodeW + (cols - 1) * gapX;
  const inner = Math.max(...lanes.filter(lane => lane.length).map(lane => gridWidth(shape(lane).cols)));
  const width = left + inner + pad;
  function place() {
    const positions = new Map(), out = [];
    let y = pad;
    lanes.forEach((lane, index) => {
      if (!lane.length) return;
      const {rows, cols} = shape(lane), top = y, x0 = left + (inner - gridWidth(cols)) / 2;
      const heights = Array.from({length: rows}, (_, r) => Math.max(...lane.filter((_, i) => i % rows === r).map(id => sizes.get(id).h)));
      const rowTop = heights.map((_, r) => y + heights.slice(0, r).reduce((sum, h) => sum + h + gapY, 0));
      lane.forEach((id, i) => {
        const size = sizes.get(id), r = i % rows, c = Math.floor(i / rows);
        positions.set(id, {...size, x: x0 + c * (nodeW + gapX), y: rowTop[r] + (heights[r] - size.h) / 2});
      });
      y += heights.reduce((sum, h) => sum + h, 0) + (rows - 1) * gapY;
      out.push({label: bands[index].label || '', count: lane.length, x: pad, y: top, w: width - pad * 2, h: y - top});
      y += laneGap;
    });
    return {positions, bands: out, height: y - laneGap + pad};
  }
  let placed = place();
  for (let sweep = 0; sweep < sweeps; sweep++) {
    for (const lane of sweep % 2 ? [...lanes].reverse() : lanes) {
      const center = id => { const p = placed.positions.get(id); return p.x + p.w / 2; };
      const score = new Map(lane.map(id => {
        const list = neighbours.get(id);
        return [id, list.length ? list.reduce((sum, other) => sum + center(other), 0) / list.length : center(id)];
      }));
      lane.sort((a, b) => score.get(a) - score.get(b) || center(a) - center(b));
      placed = place();
    }
  }
  return {direction: 'down', perRow, width, ...placed};
}

/* The panorama is the point of the 2D view, so pick the row width whose whole tree is largest in this panel. */
export function panoramaLayout(graph, width, height) {
  const {bands, positions} = graph.layout;
  const longest = bands?.length ? Math.max(...bands.map(band => band.count || 0)) : Object.keys(positions instanceof Map ? Object.fromEntries(positions) : positions).length;
  let best = null;
  for (let perRow = 2; perRow <= Math.max(2, longest); perRow++) {
    const layout = treeLayout(graph, {perRow});
    const k = Math.min((width - 16) / layout.width, (height - 16) / layout.height);
    if (!best || k > best.k + 1e-6) best = {k, layout};
  }
  return best.layout;
}

function edgePath(start, end) {
  if (end.y >= start.y + start.h || end.y + end.h <= start.y) {
    const down = end.y >= start.y + start.h;
    const x1 = start.x + start.w / 2, y1 = down ? start.y + start.h : start.y;
    const x2 = end.x + end.w / 2, y2 = down ? end.y : end.y + end.h;
    const bend = Math.max(24, Math.abs(y2 - y1) * .45) * (down ? 1 : -1);
    return {d: `M${x1},${y1} C${x1},${y1 + bend} ${x2},${y2 - bend} ${x2},${y2}`, x: (x1 + x2) / 2, y: (y1 + y2) / 2 + 3};
  }
  const forward = end.x >= start.x;
  const x1 = start.x + (forward ? start.w : 0), y1 = start.y + start.h / 2;
  const x2 = end.x + (forward ? 0 : end.w), y2 = end.y + end.h / 2;
  const bend = Math.max(30, Math.abs(x2 - x1) * .45) * (forward ? 1 : -1);
  return {d: `M${x1},${y1} C${x1 + bend},${y1} ${x2 - bend},${y2} ${x2},${y2}`, x: (x1 + x2) / 2, y: (y1 + y2) / 2 - 6};
}

/* Unlike the 3D view, the 2D view never moves on its own: it shows the whole tree, and only the student zooms
   or drags it. Each resize lays the tree out again to fill the new panel. */
export function createWalkGraph(host, graph, {onSelect = () => {}, onSwitch = null} = {}) {
  if (!graph.layout?.positions) throw new Error('图谱快照缺少布局信息。');
  const nodes = [...graph.nodes, ...(graph.entries || [])];
  const byId = new Map(nodes.map(node => [node.id, node]));
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const controls = document.createElement('div');
  controls.className = 'gw-graph-controls';
  controls.innerHTML = '<button type="button" data-graph-action="out" aria-label="缩小图谱">−</button><button type="button" data-graph-action="in" aria-label="放大图谱">＋</button><button type="button" data-graph-action="fit">全景</button>'
    + (onSwitch ? '<button type="button" data-graph-action="switch" aria-pressed="false" aria-label="切换为三维图">3D</button>' : '')
    + '<button type="button" aria-pressed="true" aria-label="平面图">平面图</button>';
  const svg = element('svg', {class: 'gw-svg', role: 'group', tabindex: 0, 'aria-label': '解题关系图，显示全景。方向键移动，加减键缩放，0 回到全景。节点可用 Tab 选择。'});
  const defs = element('defs');
  const marker = element('marker', {id: 'gw-arrow', viewBox: '0 0 10 10', refX: 9, refY: 5, markerWidth: 7, markerHeight: 7, orient: 'auto-start-reverse'});
  marker.append(element('path', {d: 'M0 0 10 5 0 10z', fill: 'context-stroke'}));
  defs.append(marker);
  const viewport = element('g');
  const laneLayer = element('g', {class: 'gw-lane-layer'});
  const edgeLayer = element('g', {class: 'gw-edge-layer'});
  const nodeLayer = element('g');
  svg.append(defs, viewport);
  viewport.append(laneLayer, edgeLayer, nodeLayer);
  host.replaceChildren(controls, svg);

  let layout, transform = {x: 0, y: 0, k: 1}, size = '';
  let lastState, selected = '', animation = 0, drag = null;
  const nodeElements = new Map(), edgeElements = new Map();
  const dimensions = () => ({width: svg.clientWidth || 500, height: svg.clientHeight || 480});
  const applyTransform = () => viewport.setAttribute('transform', `translate(${transform.x},${transform.y}) scale(${transform.k})`);

  function move(next, animate = false) {
    cancelAnimationFrame(animation);
    if (!animate || reduced.matches) { transform = next; applyTransform(); return; }
    const start = performance.now(), from = {...transform};
    function frame(now) {
      const fraction = Math.min(1, (now - start) / 320), eased = 1 - (1 - fraction) ** 3;
      transform = Object.fromEntries(['x', 'y', 'k'].map(key => [key, from[key] + (next[key] - from[key]) * eased]));
      applyTransform();
      if (fraction < 1) animation = requestAnimationFrame(frame);
    }
    animation = requestAnimationFrame(frame);
  }

  function fit(animate = true) {
    const {width, height} = dimensions();
    const k = Math.min(1.15, (width - 16) / layout.width, (height - 16) / layout.height);
    // Top-aligned, so a caption growing by a line under the panel never nudges the tree.
    move({k, x: (width - layout.width * k) / 2, y: 8}, animate);
  }

  function zoom(factor, origin) {
    const {width, height} = dimensions();
    const p = origin || {x: width / 2, y: height / 2};
    const k = Math.min(2.5, Math.max(.16, transform.k * factor)), ratio = k / transform.k;
    move({k, x: p.x - (p.x - transform.x) * ratio, y: p.y - (p.y - transform.y) * ratio});
  }

  for (const edge of graph.edges) {
    if (!byId.has(edge.from) || !byId.has(edge.to)) continue;
    const group = element('g', {'data-edge': edge.id, class: 'gw-edge', 'data-state': 'idle'});
    group.append(element('title', {}, `${byId.get(edge.from).label} → ${RELATIONS[edge.type] || edge.type} → ${byId.get(edge.to).label}`), element('path', {'marker-end': edge.type === 'confuse' ? '' : 'url(#gw-arrow)'}));
    if (edge.type !== 'confuse') group.append(element('text', {'text-anchor': 'middle'}, RELATIONS[edge.type] || edge.type));
    edgeLayer.append(group); edgeElements.set(edge.id, {group, edge});
  }
  for (const node of nodes) {
    if (!(graph.layout.positions instanceof Map ? graph.layout.positions.has(node.id) : node.id in graph.layout.positions)) continue;
    const group = element('g', {class: 'gw-node', 'data-node': node.id, 'data-kind': node.kind, 'data-state': 'idle', role: 'button', tabindex: 0});
    group.append(element('rect', {rx: 11}), element('text', {class: 'gw-node-label'}), element('text', {y: -6, class: 'gw-node-status', 'text-anchor': 'end'}, ''));
    function select() {
      selected = node.id;
      for (const [id, item] of nodeElements) item.classList.toggle('is-selected', id === selected);
      onSelect(node, lastState);
    }
    group.addEventListener('click', select);
    group.addEventListener('keydown', event => {
      if (['Enter', ' '].includes(event.key)) { event.preventDefault(); select(); }
    });
    group.addEventListener('focus', () => {
      const position = layout.positions.get(node.id), {width, height} = dimensions();
      const x = transform.x + position.x * transform.k, y = transform.y + position.y * transform.k;
      if (x < 10 || y < 10 || x + position.w * transform.k > width - 10 || y + position.h * transform.k > height - 10) {
        move({...transform, x: width / 2 - (position.x + position.w / 2) * transform.k, y: height / 2 - (position.y + position.h / 2) * transform.k}, true);
      }
    });
    nodeLayer.append(group); nodeElements.set(node.id, group);
  }

  function arrange() {
    const {width, height} = dimensions();
    layout = panoramaLayout(graph, width, height);
    laneLayer.replaceChildren();
    layout.bands.forEach((band, index) => {
      if (index) laneLayer.append(element('line', {x1: band.x, x2: band.x + band.w, y1: band.y - 9, y2: band.y - 9, class: 'gw-lane-rule'}));
      if (band.label) laneLayer.append(element('text', {x: band.x, y: band.y + 25, class: 'gw-lane-title'}, band.label));
    });
    for (const [id, group] of nodeElements) {
      const p = layout.positions.get(id);
      group.setAttribute('transform', `translate(${p.x},${p.y})`);
      const [rect, label, status] = group.children;
      rect.setAttribute('width', p.w); rect.setAttribute('height', p.h);
      label.setAttribute('x', 12); label.setAttribute('y', Math.max(20, (p.h - p.lines.length * 17) / 2 + 13));
      label.replaceChildren(...p.lines.map((line, index) => element('tspan', {x: 12, dy: index ? 17 : 0}, line)));
      status.setAttribute('x', p.w - 8);
    }
    for (const {group, edge} of edgeElements.values()) {
      const route = edgePath(layout.positions.get(edge.from), layout.positions.get(edge.to));
      group.children[1].setAttribute('d', route.d);
      group.children[2]?.setAttribute('x', route.x); group.children[2]?.setAttribute('y', route.y);
    }
    fit(false);
  }

  function render(state) {
    lastState = state;
    const archive = new Set(state.archivedEdges || []);
    for (const [id, item] of nodeElements) {
      const value = state.nodes[id] || 'idle', node = byId.get(id);
      item.dataset.state = value;
      item.querySelector('.gw-node-status').textContent = value === 'idle' ? '' : STATUS_LABELS[value] || value;
      item.setAttribute('aria-label', `${node.label}，${KIND_LABELS[node.kind] || '条目'}，${STATUS_LABELS[value] || value}`);
      item.setAttribute('aria-pressed', String(id === selected));
    }
    for (const [id, {group}] of edgeElements) {
      group.dataset.state = state.edges[id] || 'idle';
      group.classList.toggle('is-archived', archive.has(id));
    }
  }

  controls.addEventListener('click', event => {
    const action = event.target.closest('[data-graph-action]')?.dataset.graphAction;
    if (action === 'in') zoom(1.25);
    if (action === 'out') zoom(.8);
    if (action === 'fit') fit();
    if (action === 'switch') onSwitch?.();
  });
  svg.addEventListener('wheel', event => {
    event.preventDefault();
    const box = svg.getBoundingClientRect();
    zoom(Math.exp(-event.deltaY * .0015), {x: event.clientX - box.left, y: event.clientY - box.top});
  }, {passive: false});
  /* One finger or the mouse drags; two fingers pinch around their midpoint. A press that starts on a name is not
     captured unless it becomes a pinch, so a tap still reaches the name as a click. */
  const pointers = new Map();
  let pinch = null;
  const local = event => { const box = svg.getBoundingClientRect(); return {x: event.clientX - box.left, y: event.clientY - box.top}; };
  const spread = () => { const [a, b] = [...pointers.values()]; return {d: Math.hypot(a.x - b.x, a.y - b.y) || 1, x: (a.x + b.x) / 2, y: (a.y + b.y) / 2}; };
  svg.addEventListener('pointerdown', event => {
    pointers.set(event.pointerId, local(event));
    if (pointers.size === 2) {
      cancelAnimationFrame(animation); drag = null;
      for (const id of pointers.keys()) if (!svg.hasPointerCapture?.(id)) svg.setPointerCapture(id);
      pinch = {...spread(), from: {...transform}};
      return;
    }
    if (pointers.size > 2 || event.target.closest('[data-node]')) return;
    cancelAnimationFrame(animation);
    drag = {id: event.pointerId, x: event.clientX, y: event.clientY, fromX: transform.x, fromY: transform.y};
    svg.setPointerCapture(event.pointerId);
  });
  svg.addEventListener('pointermove', event => {
    if (pointers.has(event.pointerId)) pointers.set(event.pointerId, local(event));
    if (pinch && pointers.size >= 2) {
      const now = spread(), {from} = pinch;
      const k = Math.min(2.5, Math.max(.16, from.k * now.d / pinch.d));
      transform = {k, x: now.x - (pinch.x - from.x) / from.k * k, y: now.y - (pinch.y - from.y) / from.k * k};
      applyTransform();
      return;
    }
    if (drag?.id !== event.pointerId) return;
    transform.x = drag.fromX + event.clientX - drag.x; transform.y = drag.fromY + event.clientY - drag.y;
    applyTransform();
  });
  const endDrag = event => {
    pointers.delete(event.pointerId);
    if (pointers.size < 2) pinch = null;
    drag = null;
  };
  svg.addEventListener('pointerup', endDrag); svg.addEventListener('pointercancel', endDrag);
  svg.addEventListener('keydown', event => {
    if (event.target !== svg) return;
    const offset = {ArrowLeft: [45, 0], ArrowRight: [-45, 0], ArrowUp: [0, 45], ArrowDown: [0, -45]}[event.key];
    if (offset) { event.preventDefault(); move({...transform, x: transform.x + offset[0], y: transform.y + offset[1]}); }
    else if (['+', '='].includes(event.key)) { event.preventDefault(); zoom(1.25); }
    else if (event.key === '-') { event.preventDefault(); zoom(.8); }
    else if (event.key === '0') { event.preventDefault(); fit(); }
  });
  arrange();
  const resizeObserver = new ResizeObserver(() => {
    const {width, height} = dimensions(), next = `${width}x${height}`;
    if (svg.clientWidth && next !== size) { size = next; arrange(); }
  });
  resizeObserver.observe(svg);
  return {render, focus: () => fit(false), fit, destroy() { cancelAnimationFrame(animation); resizeObserver.disconnect(); host.replaceChildren(); }};
}
