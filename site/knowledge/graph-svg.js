/* Flat SVG view of the knowledge graph: used without WebGL, with reduced motion, or when chosen. */
import {kindLabel} from '/knowledge/data.js?v=2';
import {NODE_W, NODE_H, wrap, PROGRESS} from '/knowledge/graph-layout.js?v=1';

const SVG_NS = 'http://www.w3.org/2000/svg';
const svg = (tag, attrs = {}) => {
  const element = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs)) element.setAttribute(key, value);
  return element;
};

export function mount({data, box, topicColor, container, select, preview}) {
  const {nodes, prerequisites, uses, topicsOf, practiceOf} = data;
  const root = svg('svg', {
    viewBox: `0 0 ${box.width} ${box.height}`, width: box.width, height: box.height,
    class: 'kg-svg', role: 'group', 'aria-label': '知识点与方法的关系图',
  });
  const edgeLayer = svg('g', {class: 'kg-edges'});
  const nodeLayer = svg('g', {class: 'kg-nodes'});
  const defs = svg('defs');
  const arrow = svg('marker', {id: 'kg-arrow', viewBox: '0 0 8 8', refX: 7, refY: 4, markerWidth: 7, markerHeight: 7, orient: 'auto-start-reverse'});
  arrow.append(svg('path', {d: 'M0 0 8 4 0 8z', class: 'kg-arrow'}));
  defs.append(arrow);
  root.append(defs);

  const knowledgeTitle = svg('text', {x: box.colX(0), y: 22, class: 'kg-col-title'});
  knowledgeTitle.textContent = '知识点 · 前提在左';
  const methodTitle = svg('text', {x: box.colX(box.knowledgeCols), y: 22, class: 'kg-col-title'});
  methodTitle.textContent = '方法';
  root.append(knowledgeTitle, methodTitle, edgeLayer, nodeLayer);

  const edgeElements = [];
  function link(edge, from, to) {
    let x0 = box.x.get(from) + NODE_W;
    let y0 = box.y.get(from) + NODE_H / 2;
    let d = `M${x0} ${y0}`;
    const stops = [...box.via.get(`${from}>${to}`), to];
    stops.forEach((id, index) => {
      const x1 = box.x.get(id);
      const y1 = box.y.get(id) + NODE_H / 2;
      const dx = Math.max(36, (x1 - x0) / 2);
      d += ` C${x0 + dx} ${y0} ${x1 - dx} ${y1} ${x1} ${y1}`;
      x0 = index < stops.length - 1 ? x1 + NODE_W : x1;
      y0 = y1;
      if (x0 !== x1) d += ` H${x0}`;
    });
    const path = svg('path', {d, class: `kg-edge ${edge.type}`});
    if (edge.type === 'prerequisite') path.setAttribute('marker-end', 'url(#kg-arrow)');
    edgeLayer.append(path);
    edgeElements.push({edge, path});
  }
  prerequisites.forEach(edge => link(edge, edge.from, edge.to));
  uses.forEach(edge => link(edge, edge.to, edge.from));

  const nodeElements = new Map();
  const progressLayers = new Map();
  nodes.forEach(node => {
    const practiced = practiceOf(node.id).length > 0;
    const group = svg('g', {
      class: ['kg-node', node.kind, node.subtype, practiced ? '' : 'is-unpracticed'].filter(Boolean).join(' '),
      transform: `translate(${box.x.get(node.id)} ${box.y.get(node.id)})`,
      tabindex: 0, role: 'button', 'data-node': node.id, 'aria-label': `${kindLabel(node)}：${node.label}`,
    });
    group.append(svg('rect', {width: NODE_W, height: NODE_H, rx: node.kind === 'method' ? 12 : 9, class: 'kg-box'}));
    topicsOf(node.id).forEach((topic, index) => {
      const tab = svg('rect', {x: 10 + index * 22, y: -3, width: 18, height: 6, rx: 3, fill: topicColor(topic), class: 'kg-topic-tab'});
      tab.append(Object.assign(svg('title'), {textContent: topic.label}));
      group.append(tab);
    });
    const lines = wrap(node.label);
    const text = svg('text', {x: NODE_W / 2, y: NODE_H / 2 - (lines.length - 1) * 8 + 4.5});
    lines.forEach((line, index) => {
      const span = svg('tspan', {x: NODE_W / 2, dy: index ? 16 : 0});
      span.textContent = line;
      text.append(span);
    });
    group.append(text);
    if (node.sheet) group.append(svg('circle', {cx: NODE_W - 9, cy: 9, r: 4, class: 'kg-sheet-dot'}));
    const bar = svg('g', {class: 'kg-progress', transform: `translate(10 ${NODE_H - 7})`});
    group.append(bar);
    progressLayers.set(node.id, bar);
    nodeLayer.append(group);
    nodeElements.set(node.id, group);
  });
  container.replaceChildren(root);

  root.addEventListener('click', event => {
    const target = event.target.closest('[data-node]');
    select(target ? target.dataset.node : null);
  });
  nodeLayer.addEventListener('keydown', event => {
    const target = event.target.closest('[data-node]');
    if (target && (event.key === 'Enter' || event.key === ' ')) { event.preventDefault(); select(target.dataset.node); }
  });
  nodeLayer.addEventListener('pointerover', event => {
    const target = event.target.closest('[data-node]');
    if (target && event.pointerType === 'mouse') preview(target.dataset.node);
  });
  nodeLayer.addEventListener('pointerleave', () => preview(null));

  return {
    highlight({id, related, edgeState}) {
      nodeElements.forEach((element, key) => {
        element.classList.toggle('is-selected', key === id);
        element.classList.toggle('is-related', Boolean(related?.has(key)) && key !== id);
        element.classList.toggle('is-dim', Boolean(related) && !related.has(key));
      });
      for (const {edge, path} of edgeElements) {
        const state = edgeState(edge);
        path.classList.toggle('is-shown', state !== 'hidden');
        path.classList.toggle('is-strong', state === 'strong');
      }
    },
    filter(test) {
      nodeElements.forEach((element, id) => element.classList.toggle('is-out', !test(id)));
      for (const {edge, path} of edgeElements) path.classList.toggle('is-out', !test(edge.from) || !test(edge.to));
    },
    // A thin bar along the bottom of each box, split by the share of each coverage segment.
    progress(map) {
      progressLayers.forEach((bar, id) => {
        bar.replaceChildren();
        const counts = map?.get(id);
        if (!counts?.total) return;
        let x = 0;
        const width = NODE_W - 20;
        for (const [key] of PROGRESS) {
          if (!counts[key]) continue;
          const w = width * counts[key] / counts.total;
          bar.append(svg('rect', {x: x + 0.5, width: Math.max(1, w - 1), height: 3, rx: 1.5, class: `kg-progress-${key}`}));
          x += w;
        }
      });
    },
    focus(id) {
      nodeElements.get(id)?.scrollIntoView({block: 'nearest', inline: 'center', behavior: 'smooth'});
    },
    destroy() { container.replaceChildren(); },
  };
}
