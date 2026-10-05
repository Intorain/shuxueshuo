/* 3D star map of the knowledge graph. The flat layout keeps its columns (prerequisites left, methods
   right) and gains depth by topic. Names are DOM buttons laid over the WebGL canvas, so they stay sharp,
   clickable and reachable with Tab. */
import * as THREE from '/assets/vendor/three-0.186.1/three-graph.min.js';
import {kindLabel} from '/knowledge/data.js?v=2';
import {NODE_W, NODE_H, PROGRESS} from '/knowledge/graph-layout.js?v=1';

const COLORS = {
  knowledge: {core: '#b4fff4', glow: '#22d3c5'},
  method: {core: '#ffe0a3', glow: '#f5a524'},
  prerequisite: '#5eead4',
  uses: '#fbbf24',
  stars: '#d7ecff',
  progress: {mastered: '#34d399', practiced: '#60a5fa', review: '#fbbf24', unpracticed: '#4b5b70'},
};
const FOV = 36;
const ORB_X = 14;            // the star sits at the left of its old box; the name follows it
const TOPIC_DEPTH = 70;
const HOP_DELAY = 150;       // ms between rings of the lit chain
const SWAY_RESUME = 15000;   // ms of quiet before the idle sway comes back
const NODE_TARGET = {
  rest: {glow: 0.85, opacity: 1, scale: 1},
  selected: {glow: 1.9, opacity: 1, scale: 1.4},
  related: {glow: 1.35, opacity: 1, scale: 1.12},
  dim: {glow: 0.12, opacity: 0.2, scale: 0.85},
  out: {glow: 0, opacity: 0.04, scale: 0.7},
};
const EDGE_OPACITY = {hidden: 0, shown: 0.32, strong: 0.95};

function glowTexture() {
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = 128;
  const context = canvas.getContext('2d');
  const gradient = context.createRadialGradient(64, 64, 0, 64, 64, 64);
  gradient.addColorStop(0, 'rgba(255,255,255,1)');
  gradient.addColorStop(0.18, 'rgba(255,255,255,.55)');
  gradient.addColorStop(0.45, 'rgba(255,255,255,.14)');
  gradient.addColorStop(1, 'rgba(255,255,255,0)');
  context.fillStyle = gradient;
  context.fillRect(0, 0, 128, 128);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

const lerp = (a, b, t) => a + (b - a) * t;
const ease = t => t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2;

export function mount({data, box, topicColor, container, select, preview}) {
  const {nodes, prerequisites, uses, topicsOf, practiceOf} = data;
  const touch = matchMedia('(pointer: coarse)').matches;
  // Reduced motion: no sway, sparks, spin, pulse or breathing; states and camera jump instead of easing.
  const calm = matchMedia('(prefers-reduced-motion: reduce)').matches;

  const root = document.createElement('div');
  root.className = 'kg-3d';
  const renderer = new THREE.WebGLRenderer({antialias: true, alpha: true, powerPreference: 'high-performance'});
  renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
  renderer.domElement.setAttribute('aria-hidden', 'true');
  const labels = new THREE.CSS2DRenderer();
  labels.domElement.className = 'kg-3d-labels';
  labels.domElement.setAttribute('role', 'group');
  labels.domElement.setAttribute('aria-label', '知识点与方法的关系图');
  const hint = document.createElement('p');
  hint.className = 'kg-3d-hint';
  hint.textContent = touch ? '单指拖动 · 双指缩放和旋转 · 点星星看关系' : '拖动旋转 · 右键拖动平移 · 按住 Ctrl/⌘ 滚动缩放';
  root.append(renderer.domElement, labels.domElement, hint);
  container.replaceChildren(root);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(FOV, 1, 10, 8000);
  const graph = new THREE.Group();
  scene.add(graph);
  const glow = glowTexture();

  /* Positions: layout pixels become world units, centred; single-topic nodes step forward or back. */
  const cx = box.width / 2;
  const cy = box.height / 2;
  const depthOf = id => {
    const owners = topicsOf(id);
    if (owners.length !== 1) return 0;
    const index = data.topics.indexOf(owners[0]);
    return TOPIC_DEPTH * Math.ceil((index + 1) / 2) * (index % 2 ? -1 : 1);
  };
  const orb = id => new THREE.Vector3(box.x.get(id) + ORB_X - cx, -(box.y.get(id) + NODE_H / 2 - cy), 0);
  const position = new Map();
  nodes.forEach((node, id) => position.set(id, orb(id).setZ(depthOf(id))));

  /* Background: a field of stars and two faint nebula clouds behind the graph. */
  const starCount = 1400;
  const starPositions = new Float32Array(starCount * 3);
  for (let i = 0; i < starCount; i += 1) {
    starPositions[i * 3] = (Math.random() - 0.5) * box.width * 3.2;
    starPositions[i * 3 + 1] = (Math.random() - 0.5) * box.height * 3.2;
    starPositions[i * 3 + 2] = -150 - Math.random() * 1500;
  }
  const starGeometry = new THREE.BufferGeometry();
  starGeometry.setAttribute('position', new THREE.Float32BufferAttribute(starPositions, 3));
  const stars = new THREE.Points(starGeometry, new THREE.PointsMaterial({
    color: COLORS.stars, size: 3.2, map: glow, transparent: true, opacity: 0.8, depthWrite: false, blending: THREE.AdditiveBlending,
  }));
  scene.add(stars);
  for (const [color, x, y, size] of [['#1fb5a8', -0.28, 0.12, 1.3], ['#6d5bd6', 0.3, -0.18, 1.5], ['#c2547a', 0.05, 0.35, 0.9]]) {
    const cloud = new THREE.Sprite(new THREE.SpriteMaterial({map: glow, color, transparent: true, opacity: 0.11, depthWrite: false, blending: THREE.AdditiveBlending}));
    cloud.position.set(x * box.width, y * box.height, -700);
    cloud.scale.setScalar(box.width * size);
    scene.add(cloud);
  }

  /* Nodes: a star (sphere for knowledge, octahedron for methods, wire octahedron for techniques),
     a glow, one halo per topic, an optional coverage ring and a hit sphere larger than the star. */
  const items = new Map();
  const hitTargets = [];
  const column = id => [...box.columns.keys()].find(index => box.columns[index].includes(id));
  const order = [...nodes.keys()].sort((a, b) => column(a) - column(b) || box.y.get(a) - box.y.get(b));
  for (const id of order) {
    const node = nodes.get(id);
    const palette = COLORS[node.kind];
    const group = new THREE.Group();
    group.position.copy(position.get(id));
    let body;
    if (node.subtype === 'technique') {
      body = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.OctahedronGeometry(8.5)), new THREE.LineBasicMaterial({color: palette.core, transparent: true}));
    } else if (node.kind === 'method') {
      body = new THREE.Mesh(new THREE.OctahedronGeometry(8.5), new THREE.MeshBasicMaterial({color: palette.core, transparent: true}));
    } else {
      body = new THREE.Mesh(new THREE.SphereGeometry(6.5, 24, 16), new THREE.MeshBasicMaterial({color: palette.core, transparent: true}));
    }
    const halo = new THREE.Sprite(new THREE.SpriteMaterial({map: glow, color: palette.glow, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending}));
    halo.scale.setScalar(54);
    group.add(halo, body);
    const rings = topicsOf(id).map((topic, index) => {
      const color = new THREE.Color(topicColor(topic)).lerp(new THREE.Color('#ffffff'), 0.3);
      const ring = new THREE.Mesh(new THREE.TorusGeometry(13 + index * 3.2, 0.55, 6, 56), new THREE.MeshBasicMaterial({color, transparent: true, opacity: 0.85}));
      ring.rotation.set(1.15 + index * 0.55, index * 0.8, 0);
      group.add(ring);
      return ring;
    });
    const coverage = new THREE.Group();
    group.add(coverage);
    const hit = new THREE.Mesh(new THREE.SphereGeometry(22, 8, 6), new THREE.MeshBasicMaterial({visible: false}));
    hit.userData.id = id;
    group.add(hit);
    hitTargets.push(hit);

    const practiced = practiceOf(id).length > 0;
    const element = document.createElement('div');
    element.className = `kg-star ${node.kind}${node.subtype ? ` ${node.subtype}` : ''}${practiced ? '' : ' is-unpracticed'}`;
    element.innerHTML = `<button type="button" data-node="${id}" aria-label="${kindLabel(node)}：${node.label}" title="${node.label}"><span>${node.label}</span>${node.sheet ? '<i class="kg-star-sheet" aria-hidden="true"></i>' : ''}</button>`;
    const label = new THREE.CSS2DObject(element);
    label.center.set(0, 0.5);
    label.position.set(ORB_X + 2, 0, 0);
    group.add(label);
    graph.add(group);

    const rest = practiced ? NODE_TARGET.rest : {...NODE_TARGET.rest, glow: 0.45, opacity: 0.7};
    items.set(id, {
      node, group, body, halo, rings, coverage, element, rest, spin: node.kind === 'method' ? 0.4 + Math.random() * 0.3 : 0,
      current: {...rest}, target: {...rest}, startAt: 0, out: false,
    });
  }

  for (const [col, text] of [[0, '知识点 · 前提在左'], [box.knowledgeCols, '方法']]) {
    const element = document.createElement('div');
    element.className = 'kg-3d-column';
    element.textContent = text;
    const title = new THREE.CSS2DObject(element);
    title.center.set(0, 0.5);
    title.position.set(box.colX(col) - cx, cy - 18, 0);
    graph.add(title);
  }

  /* Edges: the flat view's bezier route through the empty column slots, as a thin glowing tube. */
  const slotPoint = (key, from, to) => {
    const point = orb(key);
    const [a, b] = [position.get(from), position.get(to)];
    return point.setZ(lerp(a.z, b.z, (point.x - a.x) / ((b.x - a.x) || 1)));
  };
  const edges = [];
  const link = (edge, from, to) => {
    const stops = [position.get(from), ...box.via.get(`${from}>${to}`).map(key => slotPoint(key, from, to)), position.get(to)];
    const path = new THREE.CurvePath();
    for (let index = 1; index < stops.length; index += 1) {
      const [a, b] = [stops[index - 1], stops[index]];
      const dx = Math.max(40, (b.x - a.x) / 2);
      path.add(new THREE.CubicBezierCurve3(a, a.clone().add(new THREE.Vector3(dx, 0, 0)), b.clone().sub(new THREE.Vector3(dx, 0, 0)), b));
    }
    const color = COLORS[edge.type];
    const tube = new THREE.Mesh(new THREE.TubeGeometry(path, 24 * stops.length, 1.1, 6), new THREE.MeshBasicMaterial({
      color, transparent: true, opacity: 0, depthWrite: false, blending: THREE.AdditiveBlending,
    }));
    graph.add(tube);
    const length = path.getLength();
    let arrow = null;
    if (edge.type === 'prerequisite') {
      const t = 1 - 16 / length;
      arrow = new THREE.Mesh(new THREE.ConeGeometry(3.6, 9, 12), new THREE.MeshBasicMaterial({color, transparent: true, opacity: 0, depthWrite: false}));
      arrow.position.copy(path.getPointAt(t));
      arrow.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), path.getTangentAt(t));
      graph.add(arrow);
    }
    const sparks = Array.from({length: 3}, (_, index) => {
      const spark = new THREE.Sprite(new THREE.SpriteMaterial({map: glow, color: '#ffffff', transparent: true, opacity: 0, depthWrite: false, blending: THREE.AdditiveBlending}));
      spark.scale.setScalar(16);
      spark.userData.offset = index / 3;
      graph.add(spark);
      return spark;
    });
    edges.push({edge, path, length, tube, arrow, sparks, state: 'shown', current: 0, target: EDGE_OPACITY.shown, startAt: 0, out: false});
  };
  prerequisites.forEach(edge => link(edge, edge.from, edge.to));
  uses.forEach(edge => link(edge, edge.to, edge.from));

  const pulse = new THREE.Mesh(new THREE.RingGeometry(9, 11, 48), new THREE.MeshBasicMaterial({color: '#ffffff', transparent: true, opacity: 0, depthWrite: false, side: THREE.DoubleSide}));
  graph.add(pulse);

  /* Camera and controls: rotation stays near the front so "left to right" still reads. */
  const controls = new THREE.OrbitControls(camera, renderer.domElement);
  Object.assign(controls, {
    enableDamping: !calm, dampingFactor: 0.08, rotateSpeed: 0.5, screenSpacePanning: true,
    minAzimuthAngle: -0.6, maxAzimuthAngle: 0.6, minPolarAngle: Math.PI / 2 - 0.35, maxPolarAngle: Math.PI / 2 + 0.35,
  });
  controls.touches = {ONE: THREE.TOUCH.PAN, TWO: THREE.TOUCH.DOLLY_ROTATE};
  controls.mouseButtons = {LEFT: THREE.MOUSE.ROTATE, MIDDLE: THREE.MOUSE.DOLLY, RIGHT: THREE.MOUSE.PAN};
  // A plain wheel scrolls the page; Ctrl/⌘ (and trackpad pinch, which sets ctrlKey) zooms the graph.
  const onWheel = event => { if (!event.ctrlKey && !event.metaKey) event.stopPropagation(); };
  root.addEventListener('wheel', onWheel, {capture: true});

  let size = {width: 1, height: 1};
  let fitDistance = 1000;
  const distanceFor = (width, height) => {
    const tan = Math.tan(THREE.MathUtils.degToRad(FOV / 2));
    return Math.max((height / 2) / tan, (width / 2) / (tan * camera.aspect)) * 1.06;
  };
  function resize() {
    const rect = root.getBoundingClientRect();
    size = {width: Math.max(1, rect.width), height: Math.max(1, rect.height)};
    renderer.setSize(size.width, size.height, false);
    labels.setSize(size.width, size.height);
    camera.aspect = size.width / size.height;
    camera.updateProjectionMatrix();
    fitDistance = distanceFor(box.width, box.height);
    controls.minDistance = fitDistance * 0.18;
    controls.maxDistance = fitDistance * 1.5;
  }
  resize();
  camera.position.set(0, 0, fitDistance);
  controls.target.set(0, 0, 0);
  controls.update();

  let tween = null;
  function moveTo(target, distance) {
    const offset = camera.position.clone().sub(controls.target).normalize();
    tween = {
      start: performance.now(), duration: calm ? 1 : 700,
      fromTarget: controls.target.clone(), toTarget: target,
      fromDistance: camera.position.distanceTo(controls.target), toDistance: THREE.MathUtils.clamp(distance, controls.minDistance, controls.maxDistance),
      offset,
    };
  }
  const worldOf = id => items.get(id).group.getWorldPosition(new THREE.Vector3());

  /* Idle sway: a slow drift that stops as soon as the reader touches the graph. */
  let lastInteraction = -Infinity;
  let sway = 0;
  controls.addEventListener('start', () => { lastInteraction = performance.now(); tween = null; });
  const clampTarget = () => {
    controls.target.x = THREE.MathUtils.clamp(controls.target.x, -box.width / 2, box.width / 2);
    controls.target.y = THREE.MathUtils.clamp(controls.target.y, -box.height / 2, box.height / 2);
  };
  controls.addEventListener('change', clampTarget);

  /* Picking: a short click on a star selects it, on empty space clears; hover previews with the mouse. */
  const raycaster = new THREE.Raycaster();
  const pointer = new THREE.Vector2();
  const pick = event => {
    const rect = renderer.domElement.getBoundingClientRect();
    pointer.set(((event.clientX - rect.left) / rect.width) * 2 - 1, -((event.clientY - rect.top) / rect.height) * 2 + 1);
    raycaster.setFromCamera(pointer, camera);
    const hit = raycaster.intersectObjects(hitTargets.filter(target => !items.get(target.userData.id).out), false)[0];
    return hit?.object.userData.id || null;
  };
  // On phones the sheet hides most of the sky, so picking a star also brings it above the sheet.
  const choose = id => { select(id); if (id && size.width < 720) focus(id); };
  let down = null;
  let hovered = null;
  const setHover = id => {
    if (id === hovered) return;
    if (hovered) items.get(hovered)?.element.classList.remove('is-hover');
    hovered = id;
    if (id) items.get(id).element.classList.add('is-hover');
    renderer.domElement.style.cursor = id ? 'pointer' : '';
    preview(id);
  };
  const onDown = event => { down = {x: event.clientX, y: event.clientY}; lastInteraction = performance.now(); };
  const onUp = event => {
    if (!down || Math.hypot(event.clientX - down.x, event.clientY - down.y) > 6) { down = null; return; }
    down = null;
    choose(pick(event));
  };
  const onMove = event => { if (event.pointerType === 'mouse' && !event.buttons) setHover(pick(event)); };
  const onLeave = () => setHover(null);
  renderer.domElement.addEventListener('pointerdown', onDown);
  renderer.domElement.addEventListener('pointerup', onUp);
  renderer.domElement.addEventListener('pointermove', onMove);
  renderer.domElement.addEventListener('pointerleave', onLeave);
  const labelNode = event => event.target.closest?.('[data-node]')?.dataset.node || null;
  const onLabelClick = event => { const id = labelNode(event); if (id) choose(id); };
  const onLabelOver = event => { if (event.pointerType === 'mouse') { const id = labelNode(event); if (id) setHover(id); } };
  const onLabelOut = event => { if (event.pointerType === 'mouse' && labelNode(event) && !event.relatedTarget?.closest?.(`[data-node="${labelNode(event)}"]`)) setHover(null); };
  const onFocus = event => { const id = labelNode(event); if (id) setHover(id); };
  const onBlur = () => setHover(null);
  const labelLayer = labels.domElement;
  labelLayer.addEventListener('click', onLabelClick);
  labelLayer.addEventListener('pointerover', onLabelOver);
  labelLayer.addEventListener('pointerout', onLabelOut);
  labelLayer.addEventListener('focusin', onFocus);
  labelLayer.addEventListener('focusout', onBlur);

  /* Highlight state: nodes and edges ease toward their targets, ring by ring away from the selection. */
  let selectedId = null;
  let lastState = null;
  function highlight(state) {
    lastState = state;
    const {id, related, hops, edgeState, preview: previewing} = state;
    const now = performance.now();
    const delay = calm ? 0 : previewing ? HOP_DELAY * 0.5 : HOP_DELAY;
    if (!previewing) selectedId = id;
    items.forEach((item, key) => {
      const state = item.out ? 'out' : !related ? 'rest' : key === id ? 'selected' : related.has(key) ? 'related' : 'dim';
      item.target = state === 'rest' ? {...item.rest} : {...NODE_TARGET[state]};
      item.startAt = now + (related?.has(key) ? (hops.get(key) ?? 0) * delay : 0);
      item.element.classList.toggle('is-selected', key === id);
      item.element.classList.toggle('is-related', Boolean(related?.has(key)) && key !== id);
      item.element.classList.toggle('is-dim', state === 'dim');
    });
    for (const entry of edges) {
      entry.state = entry.out ? 'hidden' : edgeState(entry.edge);
      entry.target = EDGE_OPACITY[entry.state];
      const reach = Math.max(hops?.get(entry.edge.from) ?? 0, hops?.get(entry.edge.to) ?? 0);
      entry.startAt = now + (entry.state === 'strong' ? reach * delay : 0);
    }
  }

  function filter(test) {
    items.forEach((item, id) => {
      item.out = !test(id);
      item.element.classList.toggle('is-out', item.out);
    });
    for (const entry of edges) entry.out = items.get(entry.edge.from).out || items.get(entry.edge.to).out;
    if (lastState) highlight(lastState);
    const visible = [...items.keys()].filter(id => !items.get(id).out);
    if (visible.length && visible.length < items.size) {
      const xs = visible.map(id => position.get(id).x), ys = visible.map(id => position.get(id).y);
      const [minX, maxX, minY, maxY] = [Math.min(...xs), Math.max(...xs) + NODE_W, Math.min(...ys), Math.max(...ys)];
      moveTo(new THREE.Vector3((minX + maxX) / 2, (minY + maxY) / 2, 0), distanceFor(maxX - minX + 120, maxY - minY + 160));
    } else if (visible.length === items.size && tween === null && camera.position.distanceTo(controls.target) !== fitDistance) {
      moveTo(new THREE.Vector3(0, 0, 0), fitDistance);
    }
  }

  // Ring segments around each star, split by the share of each coverage segment; "needs review" breathes.
  function progress(map) {
    items.forEach((item, id) => {
      item.coverage.clear();
      const counts = map?.get(id);
      if (!counts?.total) return;
      let start = Math.PI / 2;
      for (const [key] of PROGRESS) {
        if (!counts[key]) continue;
        const length = Math.PI * 2 * counts[key] / counts.total;
        const gap = counts[key] === counts.total ? 0 : 0.08;
        const segment = new THREE.Mesh(new THREE.RingGeometry(17.5, 20.5, 40, 1, start + gap / 2, Math.max(0.05, length - gap)),
          new THREE.MeshBasicMaterial({color: COLORS.progress[key], transparent: true, opacity: key === 'unpracticed' ? 0.7 : 0.95, depthWrite: false, side: THREE.DoubleSide}));
        segment.userData.breathe = key === 'review';
        segment.userData.base = segment.material.opacity;
        item.coverage.add(segment);
        start -= length;
      }
    });
  }

  function focus(id) {
    if (!items.has(id)) return;
    const narrow = size.width < 720;
    let distance = Math.min(camera.position.distanceTo(controls.target), fitDistance * (narrow ? 0.45 : 0.85));
    const target = worldOf(id).setZ(0);
    if (narrow) {
      // Phones: frame the lit chain across the width, and keep the star a quarter of the way down,
      // above the detail sheet that covers the lower half.
      const chain = [...(lastState?.id === id && lastState.related || [])].filter(key => items.has(key) && !items.get(key).out);
      if (chain.length > 1) {
        const xs = chain.map(key => worldOf(key).x);
        const [minX, maxX] = [Math.min(...xs), Math.max(...xs) + NODE_W * 0.8];
        target.x = (minX + maxX) / 2;
        distance = THREE.MathUtils.clamp(distanceFor(maxX - minX + 40, 0), distance, fitDistance);
      }
      target.y -= distance * Math.tan(THREE.MathUtils.degToRad(FOV / 2)) * 0.5;
    }
    moveTo(target, distance);
  }

  /* Frame loop: runs only while the graph is on screen and the tab is visible. */
  let visible = true;
  let frame = 0;
  let last = performance.now();
  const observer = new IntersectionObserver(([entry]) => { visible = entry.isIntersecting; if (visible) start(); });
  observer.observe(root);
  const resizeObserver = new ResizeObserver(() => resize());
  resizeObserver.observe(root);
  const onVisibility = () => { if (!document.hidden) start(); };
  document.addEventListener('visibilitychange', onVisibility);

  let labelScale = -1;
  let far = null;
  function tick(now) {
    frame = 0;
    if (!visible || document.hidden) return;
    const dt = Math.min(0.05, (now - last) / 1000);
    last = now;
    const k = calm ? 1 : 1 - Math.exp(-dt * 9);

    if (tween) {
      const t = Math.min(1, (now - tween.start) / tween.duration);
      const e = ease(t);
      controls.target.lerpVectors(tween.fromTarget, tween.toTarget, e);
      camera.position.copy(controls.target).addScaledVector(tween.offset, lerp(tween.fromDistance, tween.toDistance, e));
      if (t === 1) tween = null;
    }
    const idle = !calm && now - lastInteraction > SWAY_RESUME && !tween;
    sway = lerp(sway, idle ? 1 : 0, 1 - Math.exp(-dt * (idle ? 0.6 : 6)));
    graph.rotation.y = sway * 0.13 * Math.sin(now / 16000 * Math.PI * 2);
    graph.rotation.x = sway * 0.05 * Math.sin(now / 23000 * Math.PI * 2);
    const seconds = calm ? 0 : now / 1000;
    stars.rotation.z = seconds / 400;
    controls.update();

    items.forEach(item => {
      if (now >= item.startAt) for (const key of ['glow', 'opacity', 'scale']) item.current[key] = lerp(item.current[key], item.target[key], k);
      const {glow: g, opacity, scale} = item.current;
      item.body.material.opacity = opacity;
      item.body.scale.setScalar(scale);
      item.halo.material.opacity = Math.min(1, g * 0.55);
      item.halo.scale.setScalar(40 + g * 18);
      item.rings.forEach((ring, index) => { ring.material.opacity = 0.85 * opacity; ring.rotation.z = seconds * (0.25 + index * 0.1); });
      if (item.spin) { item.body.rotation.y = seconds * item.spin; item.body.rotation.x = 0.35; }
      item.coverage.quaternion.copy(camera.quaternion);
      item.coverage.children.forEach(segment => {
        const base = segment.userData.breathe && !calm ? 0.55 + 0.4 * Math.sin(seconds * 2.6) : segment.userData.base;
        segment.material.opacity = base * opacity;
      });
    });
    for (const entry of edges) {
      if (now >= entry.startAt) entry.current = lerp(entry.current, entry.target, k);
      entry.tube.material.opacity = entry.current;
      if (entry.arrow) entry.arrow.material.opacity = entry.current;
      const flowing = !calm && entry.state === 'strong' && entry.current > 0.2;
      entry.sparks.forEach(spark => {
        spark.visible = flowing;
        if (!flowing) return;
        const t = (seconds * 110 / entry.length + spark.userData.offset) % 1;
        spark.position.copy(entry.path.getPointAt(t));
        spark.material.opacity = Math.sin(t * Math.PI) * entry.current;
        spark.material.color.set(COLORS[entry.edge.type]).lerp(new THREE.Color('#ffffff'), 0.5);
      });
    }
    if (!calm && selectedId && items.has(selectedId)) {
      const phase = (seconds % 1.6) / 1.6;
      pulse.position.copy(items.get(selectedId).group.position);
      pulse.quaternion.copy(camera.quaternion);
      pulse.scale.setScalar(1 + phase * 2.6);
      pulse.material.opacity = 0.55 * (1 - phase);
    } else {
      pulse.material.opacity = 0;
    }

    // Names scale with the zoom within limits; far away only the lit chain keeps its names.
    const reference = (size.height / 2) / Math.tan(THREE.MathUtils.degToRad(FOV / 2));
    const pixels = reference / camera.position.distanceTo(controls.target);
    const nextScale = Math.round(THREE.MathUtils.clamp(pixels * 1.25, 0.72, 1.05) * 100) / 100;
    if (nextScale !== labelScale) { labelScale = nextScale; root.style.setProperty('--kg-label-scale', String(labelScale)); }
    const nextFar = pixels < 0.42;
    if (nextFar !== far) { far = nextFar; root.classList.toggle('is-far', far); }

    renderer.render(scene, camera);
    labels.render(scene, camera);
    frame = requestAnimationFrame(tick);
  }
  function start() {
    if (!frame && visible && !document.hidden) { last = performance.now(); frame = requestAnimationFrame(tick); }
  }
  start();

  return {
    highlight, filter, progress, focus,
    destroy() {
      cancelAnimationFrame(frame);
      observer.disconnect();
      resizeObserver.disconnect();
      document.removeEventListener('visibilitychange', onVisibility);
      controls.dispose();
      scene.traverse(object => {
        object.geometry?.dispose();
        (Array.isArray(object.material) ? object.material : [object.material]).forEach(material => material?.dispose());
      });
      glow.dispose();
      renderer.dispose();
      container.replaceChildren();
    },
  };
}
