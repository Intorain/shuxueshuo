/* A 3D view of the same fixed graph snapshot, with the interface of walk-graph.mjs. The problem sits at the
   center of a tilted disk and the six columns of the 2D layout become rings around it, so a solution reads
   as a ray from the center outward. Names are DOM buttons over the WebGL canvas so they stay sharp,
   clickable and reachable with Tab. */
import {KIND_LABELS, RELATIONS, STATUS_LABELS} from './walk-graph.mjs?v=20261015-view-tabs';

const THREE_URL = '/assets/vendor/three-0.186.1/three-graph.min.js';
export const KIND_COLORS = {knowledge: '#2dd4bf', skill: '#7cb8ff', method: '#f5b54a', problem_type: '#ff8f7a', judgment_rule: '#c4a1ff', entry: '#9fb7c9'};
export const HUB = '__problem__';
const RING_START = 170, RING_GAP = 140, LABEL_ARC = 165, SPREAD = 0.5, BOWL = 70, FOV = 40;
const ELEVATION = 0.8, MIN_POLAR = Math.PI * 0.12, MAX_POLAR = Math.PI * 0.42;
const IDLE_SWAY = 4500, DRAW_MS = 700, STAGGER_MS = 150, RIPPLE_MS = 110;
const NODE_LOOK = {
  idle: {opacity: 0.7, glow: 0.4, scale: 0.88},
  candidate: {opacity: 1, glow: 0.85, scale: 1},
  active: {opacity: 1, glow: 1.7, scale: 1.3},
  confirmed: {opacity: 1, glow: 1.15, scale: 1.08},
  wrong: {opacity: 1, glow: 0.9, scale: 1},
  rejected: {opacity: 0.45, glow: 0.2, scale: 0.8},
  skipped: {opacity: 0.45, glow: 0.2, scale: 0.8},
};
const EDGE_COLORS = {idle: '#56708a', candidate: '#c4b5fd', chosen: '#34d399', archived: '#a78bfa', near: '#9fb7c9'};

const TAU = Math.PI * 2;
const clamp = (value, min, max) => Math.min(max, Math.max(min, value));
const ease = t => t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2;
const backOut = t => 1 + 2.70158 * (t - 1) ** 3 + 1.70158 * (t - 1) ** 2;
const wrap = angle => ((angle % TAU) + TAU) % TAU;
const wrapPi = angle => wrap(angle + Math.PI) - Math.PI;
function circularMean(angles, weights = angles.map(() => 1)) {
  let sin = 0, cos = 0;
  angles.forEach((angle, index) => { sin += Math.sin(angle) * weights[index]; cos += Math.cos(angle) * weights[index]; });
  return Math.hypot(sin, cos) < 1e-9 ? null : Math.atan2(sin, cos);
}
/* Camera azimuth (around +y, measured from +z toward +x) that looks at a disk angle from its own side. */
export const azimuthFacing = angle => Math.atan2(Math.cos(angle), Math.sin(angle));
export const viewDirection = (azimuth, elevation = ELEVATION) =>
  ({x: Math.sin(azimuth) * Math.cos(elevation), y: Math.sin(elevation), z: Math.cos(azimuth) * Math.cos(elevation)});

/* Each 2D column becomes a ring. Nodes start at the angle of their 2D row, then move toward the mean angle of
   their neighbors in other rings for a few sweeps, so connected nodes line up along rays. Every ring keeps a
   minimum gap for its names and spreads over most of the circle. */
export function layoutRadial(graph) {
  const {layout} = graph;
  const positions = layout.positions instanceof Map ? layout.positions : new Map(Object.entries(layout.positions));
  const bands = layout.bands?.length ? layout.bands : [{label: '', x: -Infinity, w: Infinity}];
  const bandOf = x => {
    const index = bands.findIndex(band => x >= band.x && x < band.x + band.w);
    return index < 0 ? bands.length - 1 : index;
  };
  const rings = bands.map((band, index) => ({label: band.label || '', radius: RING_START + index * RING_GAP, ids: []}));
  const ringOf = new Map(), angle = new Map();
  for (const [id, p] of [...positions].sort((a, b) => a[1].y - b[1].y)) {
    const ring = bandOf(p.x + p.w / 2);
    ringOf.set(id, ring);
    rings[ring].ids.push(id);
    angle.set(id, (p.y + p.h / 2) / layout.height * TAU);
  }
  const neighbors = new Map([...ringOf.keys()].map(id => [id, []]));
  for (const edge of graph.edges) {
    if (!ringOf.has(edge.from) || !ringOf.has(edge.to) || ringOf.get(edge.from) === ringOf.get(edge.to)) continue;
    neighbors.get(edge.from).push(edge.to);
    neighbors.get(edge.to).push(edge.from);
  }
  const spread = ring => {
    const {ids, radius} = ring, count = ids.length;
    if (count < 2) return;
    const gap = Math.min(TAU / count, Math.max(LABEL_ARC / radius, SPREAD * TAU / count)) * 0.999;
    const order = [...ids].sort((a, b) => wrap(angle.get(a)) - wrap(angle.get(b)));
    const values = order.map(id => wrap(angle.get(id)));
    for (let pass = 0; pass < 400; pass++) {
      let moved = false;
      for (let i = 0; i < count; i++) {
        const j = (i + 1) % count, space = values[j] + (j === 0 ? TAU : 0) - values[i];
        if (space < gap) { const push = (gap - space) / 2; values[i] -= push; values[j] += push; moved = true; }
      }
      if (!moved) break;
    }
    order.forEach((id, index) => angle.set(id, values[index]));
  };
  rings.forEach(spread);
  for (let sweep = 0; sweep < 8; sweep++) {
    for (const ring of sweep % 2 ? [...rings].reverse() : rings) {
      for (const id of ring.ids) {
        const list = neighbors.get(id);
        const mean = list.length ? circularMean(list.map(other => angle.get(other)), list.map(other => 1 / Math.abs(ringOf.get(other) - ringOf.get(id)))) : null;
        if (mean != null) angle.set(id, mean);
      }
      spread(ring);
    }
  }
  const outer = rings.at(-1).radius;
  const height = radius => BOWL * (radius / outer) ** 2;
  const points = new Map();
  for (const [id, ring] of ringOf) {
    const {radius} = rings[ring], value = wrap(angle.get(id));
    points.set(id, {x: radius * Math.cos(value), y: height(radius), z: radius * Math.sin(value), angle: value, ring});
  }
  return {points, rings: rings.map(({label, radius}) => ({label, radius, y: height(radius)}))};
}

/* Cubic control points: every relation arches above the disk, higher for longer spans. */
export function edgeControls(a, b) {
  const lift = 26 + Math.hypot(b.x - a.x, b.z - a.z) * 0.2;
  const at = t => ({x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t + lift, z: a.z + (b.z - a.z) * t});
  return [a, at(1 / 3), at(2 / 3), b];
}

export const distanceForScale = (scale, height, fov = FOV) => height / 2 / (scale * Math.tan(fov * Math.PI / 360));

/* Camera target and distance that keep the points and their names (drawn above each point) in view when
   looking from `direction` (unit vector from target to camera). Works in camera space so perspective
   depth is counted. `inset` and `top` are the shares of the view height covered at the bottom (by a subtitle)
   and top (by a legend), which the points avoid. When even the farthest allowed distance cannot hold them,
   center the first point. */
export function frameFor(points, {width, height, fov = FOV, min = 0, max = Infinity, direction = {x: 0, y: 0, z: 1}, inset = 0, top = 0}) {
  const f = direction, rLength = Math.hypot(f.z, f.x) || 1;
  const r = {x: f.z / rLength, y: 0, z: -f.x / rLength};
  const u = {x: f.y * r.z - f.z * r.y, y: f.z * r.x - f.x * r.z, z: f.x * r.y - f.y * r.x};
  const dot = (p, axis) => p.x * axis.x + p.y * axis.y + p.z * axis.z;
  const padded = points.flatMap(p => [[-100, 60], [100, 60], [-100, -30], [100, -30]].map(([dx, dy]) => ({x: p.x + dx * r.x, y: p.y + dy, z: p.z + dx * r.z})));
  const cam = padded.map(p => [dot(p, r), dot(p, u), dot(p, f)]);
  const mid = index => (Math.min(...cam.map(c => c[index])) + Math.max(...cam.map(c => c[index]))) / 2;
  const [cu, cv, cw] = [0, 1, 2].map(mid);
  const tanV = Math.tan(fov * Math.PI / 360), tanH = tanV * width / height, open = tanV * (1 - inset - top);
  const need = Math.max(...cam.map(([a, b, c]) => c - cw + Math.max(Math.abs(a - cu) / tanH, Math.abs(b - cv) / open))) * 1.06;
  const distance = clamp(need, min, max);
  const center = need <= max ? {x: cu * r.x + cv * u.x + cw * f.x, y: cu * r.y + cv * u.y + cw * f.y, z: cu * r.z + cv * u.z + cw * f.z}
    : {x: points[0].x, y: points[0].y + 20, z: points[0].z};
  const drop = distance * tanV * (inset - top);
  return {target: {x: center.x - u.x * drop, y: center.y - u.y * drop, z: center.z - u.z * drop}, distance, fits: need <= max};
}

/* Nodes shown in growth mode: everything the walk has reached or offered, plus the problem itself. */
export function grownNodes(state) {
  const shown = new Set([HUB, ...(state?.seen || [])]);
  for (const [id, value] of Object.entries(state?.nodes || {})) if (value !== 'idle') shown.add(id);
  return shown;
}

function glowTexture(THREE) {
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = 128;
  const context = canvas.getContext('2d'), gradient = context.createRadialGradient(64, 64, 0, 64, 64, 64);
  gradient.addColorStop(0, 'rgba(255,255,255,1)');
  gradient.addColorStop(0.2, 'rgba(255,255,255,.5)');
  gradient.addColorStop(0.5, 'rgba(255,255,255,.12)');
  gradient.addColorStop(1, 'rgba(255,255,255,0)');
  context.fillStyle = gradient;
  context.fillRect(0, 0, 128, 128);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

export async function createWalkGraph3D(host, graph, {onSelect = () => {}, onSwitch = null} = {}) {
  const THREE = await import(THREE_URL);
  const renderer = new THREE.WebGLRenderer({antialias: true, alpha: true, powerPreference: 'high-performance'});
  const calm = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const coarse = matchMedia('(pointer: coarse)').matches;
  const nodes = [...graph.nodes, ...(graph.entries || [])];
  const byId = new Map(nodes.map(node => [node.id, node]));
  const {points, rings} = layoutRadial(graph);
  const hubPoint = {x: 0, y: 8, z: 0, angle: null, ring: -1};
  points.set(HUB, hubPoint);
  const V = p => new THREE.Vector3(p.x, p.y, p.z);

  const controlsBar = document.createElement('div');
  controlsBar.className = 'gw-graph-controls';
  controlsBar.innerHTML = '<button type="button" data-graph-action="out" aria-label="缩小图谱">−</button><button type="button" data-graph-action="in" aria-label="放大图谱">＋</button><button type="button" data-graph-action="current">回到当前</button><button type="button" data-graph-action="fit">查看全图</button>'
    + '<span class="gw-mode-switch" role="group" aria-label="图谱视图"><button type="button" aria-pressed="true" aria-label="三维图">3D</button>'
    + (onSwitch ? '<button type="button" data-graph-action="switch" aria-pressed="false" aria-label="切换为平面图">平面图</button>' : '') + '</span>';
  const stage = document.createElement('div');
  stage.className = 'gw3-stage';
  stage.tabIndex = 0;
  stage.setAttribute('role', 'group');
  stage.setAttribute('aria-label', '三维解题关系图：题目在中心，由内向外依次是知识线索、题型、选法判断、方法、技能与数学依据。方向键旋转，加减键缩放，0 查看全图。节点可用 Tab 选择。');
  renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
  renderer.domElement.setAttribute('aria-hidden', 'true');
  const labels = new THREE.CSS2DRenderer();
  labels.domElement.className = 'gw3-labels';
  const hint = document.createElement('p');
  hint.className = 'gw3-hint';
  hint.textContent = coarse ? '单指旋转 · 双指缩放和平移' : '拖动旋转 · 滚轮缩放 · 右键平移';
  const legend = document.createElement('p');
  legend.className = 'gw3-legend';
  legend.setAttribute('aria-hidden', 'true');
  legend.innerHTML = [['knowledge', '知识点'], ['problem_type', '题型'], ['judgment_rule', '选法判断'], ['method', '方法'], ['skill', '技能']]
    .map(([kind, label]) => `<span style="--c:${KIND_COLORS[kind]}">${label}</span>`).join('');
  stage.append(renderer.domElement, labels.domElement, legend, hint);
  host.replaceChildren(controlsBar, stage);

  const scene = new THREE.Scene(), camera = new THREE.PerspectiveCamera(FOV, 1, 10, 20000);
  const glow = glowTexture(THREE);
  const additive = (color, opacity, extra = {}) => ({color, transparent: true, opacity, depthWrite: false, blending: THREE.AdditiveBlending, ...extra});
  const css2d = (element, position, center = [0.5, 0.5]) => {
    const object = new THREE.CSS2DObject(element);
    object.center.set(...center);
    object.position.copy(position);
    scene.add(object);
    return object;
  };

  /* Backdrop: faint stars, terraced ring bands with a circle line each, and a ring name that follows the camera. */
  const starPositions = [];
  for (let i = 0; i < 420; i++) {
    const r = 2600 + Math.random() * 2600, theta = Math.random() * TAU, phi = Math.acos(2 * Math.random() - 1);
    starPositions.push(r * Math.sin(phi) * Math.cos(theta), r * Math.cos(phi), r * Math.sin(phi) * Math.sin(theta));
  }
  const starGeometry = new THREE.BufferGeometry();
  starGeometry.setAttribute('position', new THREE.Float32BufferAttribute(starPositions, 3));
  const stars = new THREE.Points(starGeometry, new THREE.PointsMaterial({color: '#9fb7c9', size: 1.6, sizeAttenuation: false, transparent: true, opacity: 0.55, depthWrite: false}));
  scene.add(stars);
  const ringTitles = [];
  rings.forEach((ring, index) => {
    const band = new THREE.Mesh(new THREE.RingGeometry(ring.radius - RING_GAP / 2, ring.radius + RING_GAP / 2, 128),
      new THREE.MeshBasicMaterial({color: '#1d3a50', transparent: true, opacity: index % 2 ? 0.1 : 0.18, depthWrite: false, side: THREE.DoubleSide}));
    band.rotation.x = -Math.PI / 2;
    band.position.y = ring.y - 3;
    const circle = [];
    for (let i = 0; i < 160; i++) {
      const a = i / 160 * TAU, b = (i + 1) / 160 * TAU;
      circle.push(ring.radius * Math.cos(a), ring.y - 2, ring.radius * Math.sin(a), ring.radius * Math.cos(b), ring.y - 2, ring.radius * Math.sin(b));
    }
    const circleGeometry = new THREE.BufferGeometry();
    circleGeometry.setAttribute('position', new THREE.Float32BufferAttribute(circle, 3));
    scene.add(band, new THREE.LineSegments(circleGeometry, new THREE.LineBasicMaterial({color: '#3d6178', transparent: true, opacity: 0.5, depthWrite: false})));
    if (ring.label) {
      const title = document.createElement('div');
      title.className = 'gw3-band';
      title.textContent = ring.label;
      ringTitles.push({ring, element: title, object: css2d(title, new THREE.Vector3(0, ring.y, ring.radius), [0.5, 0])});
    }
  });

  /* The problem at the center. */
  const hub = new THREE.Group();
  hub.position.copy(V(hubPoint));
  const hubHalo = new THREE.Sprite(new THREE.SpriteMaterial({map: glow, ...additive('#5eead4', 0.75)}));
  hubHalo.scale.setScalar(150);
  const orbitA = new THREE.Mesh(new THREE.TorusGeometry(28, 1.1, 8, 72), new THREE.MeshBasicMaterial(additive('#99f6e4', 0.7)));
  const orbitB = new THREE.Mesh(new THREE.TorusGeometry(38, 0.8, 8, 72), new THREE.MeshBasicMaterial(additive('#5eead4', 0.4)));
  hub.add(hubHalo, new THREE.Mesh(new THREE.SphereGeometry(15, 28, 20), new THREE.MeshBasicMaterial({color: '#e6fffa'})), orbitA, orbitB);
  scene.add(hub);
  const hubLabel = document.createElement('div');
  hubLabel.className = 'gw3-hub';
  hubLabel.innerHTML = '<strong>本题</strong><span>从这里出发</span>';
  css2d(hubLabel, V(hubPoint).add(new THREE.Vector3(0, 30, 0)), [0.5, 1]);

  /* Nodes. */
  const sphere = new THREE.SphereGeometry(7, 20, 14), diamond = new THREE.OctahedronGeometry(10);
  const hitGeometry = new THREE.SphereGeometry(20, 8, 6), ringGeometry = new THREE.RingGeometry(12, 14.5, 40);
  const grey = new THREE.Color('#6d8092');
  const items = new Map(), hits = [];
  for (const node of nodes) {
    const point = points.get(node.id);
    if (!point) continue;
    const color = new THREE.Color(KIND_COLORS[node.kind] || KIND_COLORS.entry);
    const group = new THREE.Group();
    group.position.copy(V(point));
    const spinning = ['method', 'judgment_rule'].includes(node.kind);
    const core = new THREE.Mesh(spinning ? diamond : sphere, new THREE.MeshBasicMaterial({color, transparent: true}));
    const halo = new THREE.Sprite(new THREE.SpriteMaterial({map: glow, ...additive(color, 0.3)}));
    const ring = new THREE.Mesh(ringGeometry, new THREE.MeshBasicMaterial(additive(color, 0, {side: THREE.DoubleSide})));
    const burst = new THREE.Mesh(ringGeometry, new THREE.MeshBasicMaterial(additive(color, 0, {side: THREE.DoubleSide})));
    const marker = new THREE.Mesh(ringGeometry, new THREE.MeshBasicMaterial({color: '#ffffff', transparent: true, opacity: 0, depthWrite: false, side: THREE.DoubleSide}));
    const hit = new THREE.Mesh(hitGeometry, new THREE.MeshBasicMaterial({transparent: true, opacity: 0, depthWrite: false}));
    hit.userData.id = node.id;
    group.add(halo, core, ring, burst, marker, hit);
    scene.add(group);
    hits.push(hit);
    const anchor = document.createElement('div');
    anchor.className = 'gw3-anchor';
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'gw3-node';
    button.dataset.node = node.id;
    button.dataset.kind = node.kind;
    button.dataset.state = 'idle';
    button.innerHTML = '<span class="gw3-status"></span><span class="gw3-name"></span>';
    button.querySelector('.gw3-name').textContent = node.label || node.id;
    anchor.append(button);
    const label = css2d(anchor, V(point).add(new THREE.Vector3(0, 13, 0)), [0.5, 1]);
    const look = {...NODE_LOOK.idle};
    items.set(node.id, {node, point, color, group, core, halo, ring, burst, marker, button, label, spinning,
      state: 'idle', current: {...look}, target: look, startAt: 0, burstAt: -1, far: null, scale: -1,
      shown: true, appear: 1, appearAt: 0});
  }
  const appearOf = id => id === HUB ? 1 : items.get(id)?.appear ?? 0;

  /* Edges: a thin line for every relation, a dashed line for candidates and previous routes, and a glowing
     tube that draws itself when the relation joins the current route. The problem links to every clue. */
  const edges = [];
  const cone = new THREE.ConeGeometry(4.5, 12, 10), up = new THREE.Vector3(0, 1, 0);
  const firstRing = [...points].filter(([, point]) => point.ring === 0).map(([id]) => id);
  const relations = [...graph.edges, ...firstRing.map(id => ({id: `${HUB}|${id}`, from: HUB, to: id, type: 'problem'}))];
  for (const edge of relations) {
    const from = points.get(edge.from), to = points.get(edge.to);
    if (!from || !to) continue;
    const curve = new THREE.CubicBezierCurve3(...edgeControls(from, to).map(V));
    const samples = curve.getPoints(40), solid = [], dashed = [];
    samples.slice(1).forEach((point, index) => {
      const pair = [samples[index].x, samples[index].y, samples[index].z, point.x, point.y, point.z];
      solid.push(...pair);
      if (index % 2 === 0) dashed.push(...pair);
    });
    const lineGeometry = new THREE.BufferGeometry(), dashGeometry = new THREE.BufferGeometry();
    lineGeometry.setAttribute('position', new THREE.Float32BufferAttribute(solid, 3));
    dashGeometry.setAttribute('position', new THREE.Float32BufferAttribute(dashed, 3));
    const line = new THREE.LineSegments(lineGeometry, new THREE.LineBasicMaterial({color: EDGE_COLORS.idle, transparent: true, opacity: 0, depthWrite: false}));
    const dash = new THREE.LineSegments(dashGeometry, new THREE.LineBasicMaterial({color: EDGE_COLORS.candidate, transparent: true, opacity: 0, depthWrite: false}));
    const tangent = curve.getTangent(0.985).normalize();
    const arrow = new THREE.Mesh(cone, new THREE.MeshBasicMaterial({color: EDGE_COLORS.chosen, transparent: true, opacity: 0, depthWrite: false}));
    arrow.position.copy(V(to)).addScaledVector(tangent, -15);
    arrow.quaternion.setFromUnitVectors(up, tangent);
    arrow.visible = edge.type !== 'confuse';
    const sparks = [0, 1, 2].map(() => new THREE.Sprite(new THREE.SpriteMaterial({map: glow, ...additive('#a7f3d0', 0)})));
    sparks.forEach(spark => spark.scale.setScalar(18));
    scene.add(line, dash, arrow, ...sparks);
    let text = null, tag = null;
    if (RELATIONS[edge.type]) {
      text = document.createElement('div');
      text.className = 'gw3-edge';
      text.textContent = RELATIONS[edge.type];
      tag = css2d(text, curve.getPoint(0.5));
      tag.visible = false;
    }
    edges.push({edge, curve, line, dash, arrow, sparks, text, tag, tube: null, state: 'idle', archived: false,
      opacity: 0, drawAt: 0, phase: Math.random()});
  }
  const edgeColor = new THREE.Color();

  /* Camera and controls. Camera moves are tweened in spherical coordinates around the target so a turn to
     another side of the disk orbits instead of cutting through it. */
  const controls = new THREE.OrbitControls(camera, renderer.domElement);
  Object.assign(controls, {enableDamping: !calm, dampingFactor: 0.08, rotateSpeed: 0.5, zoomSpeed: 0.9, panSpeed: 0.8,
    screenSpacePanning: true, minPolarAngle: MIN_POLAR, maxPolarAngle: MAX_POLAR, minDistance: 220, maxDistance: 5200});
  controls.touches = {ONE: THREE.TOUCH.ROTATE, TWO: THREE.TOUCH.DOLLY_PAN};
  controls.mouseButtons = {LEFT: THREE.MOUSE.ROTATE, MIDDLE: THREE.MOUSE.DOLLY, RIGHT: THREE.MOUSE.PAN};
  const sphericalOf = offset => {
    const length = offset.length() || 1;
    return {radius: length, theta: Math.atan2(offset.x, offset.z), phi: Math.acos(clamp(offset.y / length, -1, 1))};
  };
  const fromSpherical = ({radius, theta, phi}) => new THREE.Vector3(radius * Math.sin(phi) * Math.sin(theta), radius * Math.cos(phi), radius * Math.sin(phi) * Math.cos(theta));
  camera.position.copy(fromSpherical({radius: 2600, theta: 0, phi: Math.PI / 2 - ELEVATION}));
  controls.update();

  let size = {width: 0, height: 0}, tween = null, lastInteraction = -Infinity, sway = 0;
  let lastFocus = [], lastState, selected = '', hovered = '', initialized = false;
  let raf = 0, visible = true, destroyed = false;

  const currentAzimuth = () => sphericalOf(camera.position.clone().sub(controls.target)).theta;
  const overlay = () => clamp((stage.querySelector('[data-stage-overlay]')?.offsetHeight || 0) * 0.8 / (size.height || 1), 0, 0.4);
  const legendInset = () => clamp((legend.offsetTop + legend.offsetHeight + 24) / (size.height || 1), 0, 0.2);
  const insets = () => ({inset: overlay(), top: legendInset()});
  function flyTo(target, distance, azimuth, animate = true) {
    const from = sphericalOf(camera.position.clone().sub(controls.target));
    tween = {start: performance.now(), duration: animate && !calm ? 1100 : 0, fromTarget: controls.target.clone(), toTarget: V(target),
      from, to: {radius: distance, theta: from.theta + wrapPi(azimuth - from.theta), phi: Math.PI / 2 - ELEVATION}};
    wake();
  }
  function shownPoints() {
    return [...points].filter(([id]) => id === HUB || items.get(id)?.shown).map(([, point]) => point);
  }
  function fit(animate = true) {
    if (!size.height) return;
    const list = shownPoints(), mean = circularMean(list.map(point => point.angle).filter(angle => angle != null));
    const azimuth = mean == null ? currentAzimuth() : azimuthFacing(mean);
    const view = frameFor(list, {...size, direction: viewDirection(azimuth), ...insets()});
    flyTo(view.target, view.distance, azimuth, animate);
  }
  function focus(ids = lastFocus, animate = true) {
    const related = new Set(ids);
    for (const edge of graph.edges) {
      if (ids.includes(edge.from) && lastState?.nodes[edge.to] === 'confirmed') related.add(edge.to);
      if (ids.includes(edge.to) && lastState?.nodes[edge.from] === 'confirmed') related.add(edge.from);
    }
    const toPoints = set => [...set].map(id => points.get(id)).filter(Boolean);
    const list = toPoints(related);
    if (!list.length || !size.height) { fit(animate); return; }
    const mean = circularMean(list.map(point => point.angle).filter(angle => angle != null));
    const azimuth = mean == null ? currentAzimuth() : azimuthFacing(mean);
    const options = {...size, direction: viewDirection(azimuth), ...insets(),
      min: distanceForScale(1.1, size.height), max: distanceForScale(0.55, size.height)};
    let view = frameFor(list, options);
    if (!view.fits && toPoints(ids).length) view = frameFor(toPoints(ids), options);
    flyTo(view.target, view.distance, azimuth, animate);
  }
  function zoom(factor) {
    const from = sphericalOf(camera.position.clone().sub(controls.target));
    tween = {start: performance.now(), duration: calm ? 0 : 260, fromTarget: controls.target.clone(), toTarget: controls.target.clone(),
      from, to: {...from, radius: clamp(from.radius / factor, controls.minDistance, controls.maxDistance)}};
    wake();
  }
  function orbit(azimuth, polar) {
    const spherical = sphericalOf(camera.position.clone().sub(controls.target));
    camera.position.copy(controls.target).add(fromSpherical({radius: spherical.radius, theta: spherical.theta + azimuth,
      phi: clamp(spherical.phi + polar, MIN_POLAR, MAX_POLAR)}));
    lastInteraction = performance.now(); tween = null; wake();
  }

  function select(id) {
    selected = id;
    for (const [key, item] of items) {
      item.button.classList.toggle('is-selected', key === id);
      item.button.setAttribute('aria-pressed', String(key === id));
    }
    onSelect(byId.get(id), lastState);
    wake();
  }

  /* Which nodes are on stage. Newly shown nodes pop up in a ripple from the center, or when the route
     drawing reaches them. */
  function applyGrowth(now, arrivals = new Map()) {
    const shown = grownNodes(lastState);
    const entering = [];
    for (const [id, item] of items) {
      const next = shown.has(id) || id === selected;
      if (next && !item.shown) entering.push(item);
      item.shown = next;
    }
    if (!initialized) {
      for (const item of items.values()) item.appear = item.shown ? 1 : 0;
      return;
    }
    const innermost = Math.min(...entering.map(item => item.point.ring));
    for (const item of entering) item.appearAt = calm ? 0 : arrivals.get(item.node.id) ?? now + (item.point.ring - innermost) * RIPPLE_MS;
  }

  function render(state, {center = true} = {}) {
    const now = performance.now(), previous = lastState;
    lastState = state;
    const archive = new Set(state.archivedEdges || []);
    const fresh = [];
    for (const entry of edges) {
      const target = entry.edge.to;
      const value = entry.edge.from === HUB
        ? {confirmed: 'chosen', candidate: 'candidate', active: 'candidate'}[state.nodes[target]] || 'idle'
        : state.edges[entry.edge.id] || 'idle';
      if (value === 'chosen' && entry.state !== 'chosen' && initialized) fresh.push(entry);
      if (value === 'chosen' && (entry.state !== 'chosen' || !initialized)) entry.drawAt = initialized ? Infinity : -Infinity;
      entry.state = value;
      entry.archived = archive.has(entry.edge.id);
    }
    const order = id => points.get(id)?.ring ?? -1;
    fresh.sort((a, b) => order(a.edge.from) - order(b.edge.from) || order(a.edge.to) - order(b.edge.to));
    const arrivals = new Map();
    fresh.forEach((entry, index) => {
      entry.drawAt = calm ? -Infinity : now + index * STAGGER_MS;
      arrivals.set(entry.edge.to, Math.max(arrivals.get(entry.edge.to) || 0, entry.drawAt + DRAW_MS * 0.85));
    });
    for (const [id, item] of items) {
      const value = state.nodes[id] || 'idle';
      const becameConfirmed = initialized && value === 'confirmed' && previous?.nodes[id] !== 'confirmed';
      item.startAt = becameConfirmed && !calm ? arrivals.get(id) || now : now;
      if (becameConfirmed && !calm) item.burstAt = item.startAt;
      item.state = value;
      item.target = {...(NODE_LOOK[value] || NODE_LOOK.idle)};
      item.button.dataset.state = value;
      item.button.querySelector('.gw3-status').textContent = value === 'idle' ? '' : STATUS_LABELS[value] || value;
      item.button.setAttribute('aria-label', `${item.node.label}，${KIND_LABELS[item.node.kind] || '条目'}，${STATUS_LABELS[value] || value}`);
      item.button.setAttribute('aria-pressed', String(id === selected));
    }
    applyGrowth(now, arrivals);
    const nextFocus = state.focus || [];
    if (center && (!initialized || JSON.stringify(nextFocus) !== JSON.stringify(lastFocus))) {
      lastFocus = nextFocus;
      if (size.height) focus(nextFocus, initialized);
    }
    lastFocus = nextFocus; initialized = true;
    wake();
  }

  function ensureTube(entry) {
    if (entry.tube) return entry.tube;
    const geometry = new THREE.TubeGeometry(entry.curve, 48, 2.1, 6, false);
    entry.tube = new THREE.Mesh(geometry, new THREE.MeshBasicMaterial(additive(EDGE_COLORS.chosen, 0)));
    entry.tubeCount = geometry.index.count;
    scene.add(entry.tube);
    return entry.tube;
  }

  /* Frame loop. */
  let last = performance.now();
  const toCamera = new THREE.Vector3(), tanV = Math.tan(FOV * Math.PI / 360);
  const pixelsAt = position => size.height / 2 / (toCamera.copy(position).sub(camera.position).length() * tanV);
  function tick(now) {
    raf = 0;
    if (destroyed || !visible || document.hidden || !size.height) return;
    const dt = Math.min(0.05, (now - last) / 1000), k = calm ? 1 : 1 - Math.exp(-dt * 8), seconds = calm ? 0 : now / 1000;
    last = now;
    if (tween) {
      const t = tween.duration ? Math.min(1, (now - tween.start) / tween.duration) : 1, e = ease(t);
      controls.target.lerpVectors(tween.fromTarget, tween.toTarget, e);
      const lerp = key => tween.from[key] + (tween.to[key] - tween.from[key]) * e;
      camera.position.copy(controls.target).add(fromSpherical({radius: lerp('radius'), theta: lerp('theta'), phi: lerp('phi')}));
      if (t === 1) { tween = null; lastInteraction = now; }
    } else if (!calm && now - lastInteraction > IDLE_SWAY) {
      const next = Math.sin((now - lastInteraction - IDLE_SWAY) / 4200) * 0.12;
      const offset = camera.position.clone().sub(controls.target).applyAxisAngle(up, next - sway);
      camera.position.copy(controls.target).add(offset);
      sway = next;
    } else sway = 0;
    controls.update(dt);
    stars.rotation.y = seconds / 400;
    orbitA.rotation.set(Math.PI / 2 + Math.sin(seconds * 0.7) * 0.35, seconds * 0.6, 0);
    orbitB.rotation.set(Math.PI / 2 + Math.cos(seconds * 0.5) * 0.45, -seconds * 0.4, 0);
    hubHalo.material.opacity = 0.62 + Math.sin(seconds * 1.6) * 0.12;

    const emphasis = selected || hovered;
    const appearStep = calm ? 1 : dt / 0.5;
    for (const item of items.values()) {
      if (now >= item.appearAt) item.appear = clamp(item.appear + (item.shown ? appearStep : -appearStep * 1.6), 0, 1);
      const pop = item.shown ? backOut(item.appear) : item.appear;
      item.group.visible = item.appear > 0;
      item.group.scale.setScalar(Math.max(pop, 0.001));
      item.label.visible = item.appear > 0.35;
      if (now >= item.startAt) for (const key of ['glow', 'opacity', 'scale']) item.current[key] += (item.target[key] - item.current[key]) * k;
      const {glow: g, opacity, scale} = item.current;
      item.core.scale.setScalar(scale);
      item.core.material.opacity = opacity;
      item.core.material.color.copy(item.color).lerp(grey, clamp(1 - g, 0, 0.75));
      if (item.spinning) item.core.rotation.y = seconds * 0.8;
      item.halo.material.opacity = Math.min(1, g * 0.55);
      item.halo.scale.setScalar(54 * (0.7 + g * 0.35) * scale);
      for (const part of [item.ring, item.burst, item.marker]) part.quaternion.copy(camera.quaternion);
      const pulse = item.state === 'active' && !calm ? (Math.sin(seconds * 3) + 1) / 2 : item.state === 'active' ? 0.5 : 0;
      item.ring.material.opacity = item.state === 'active' ? 0.45 + pulse * 0.45 : item.state === 'candidate' ? 0.22 : 0;
      item.ring.scale.setScalar(item.state === 'active' ? 1.1 + pulse * 0.55 : 0.9);
      const burst = item.burstAt >= 0 && now >= item.burstAt ? (now - item.burstAt) / 750 : -1;
      item.burst.material.opacity = burst >= 0 && burst < 1 ? 1 - burst : 0;
      item.burst.scale.setScalar(1 + Math.max(0, burst) * 2.6);
      if (burst >= 1) item.burstAt = -1;
      item.marker.material.opacity = item.node.id === selected ? 0.9 : 0;
      item.marker.scale.setScalar(1.35);

      if (!item.label.visible) continue;
      const pixels = pixelsAt(item.group.position);
      const labelScale = Math.round(clamp(pixels * 1.1, 0.5, 1.08) * 50) / 50;
      if (labelScale !== item.scale) { item.scale = labelScale; item.button.style.setProperty('--s', labelScale); }
      const far = pixels < 0.28 && item.state === 'idle' && item.node.id !== emphasis;
      if (far !== item.far) { item.far = far; item.button.toggleAttribute('data-far', far); }
    }
    for (const entry of edges) {
      const {edge, state} = entry, touching = Boolean(emphasis) && (edge.from === emphasis || edge.to === emphasis);
      const presence = Math.min(appearOf(edge.from), appearOf(edge.to));
      const chosen = state === 'chosen', dashed = state === 'candidate' || (entry.archived && state === 'idle');
      const target = chosen ? 0.35 : state === 'candidate' ? 0 : entry.archived ? 0 : touching ? 0.5 : 0.18;
      entry.opacity += (target - entry.opacity) * k;
      entry.line.material.opacity = entry.opacity * presence;
      entry.line.material.color.set(touching && !chosen ? EDGE_COLORS.near : chosen ? EDGE_COLORS.chosen : EDGE_COLORS.idle);
      entry.dash.material.opacity = (dashed ? (state === 'candidate' ? 0.8 : 0.55) : 0) * presence;
      entry.dash.material.color.set(state === 'candidate' ? EDGE_COLORS.candidate : EDGE_COLORS.archived);
      const progress = chosen ? clamp((now - entry.drawAt) / DRAW_MS, 0, 1) : 0;
      if (chosen || entry.tube) {
        const tube = ensureTube(entry);
        tube.visible = chosen && progress > 0 && presence > 0;
        tube.geometry.setDrawRange(0, Math.floor(entry.tubeCount * ease(progress) / 3) * 3);
        tube.material.opacity = 0.9 * presence;
      }
      edgeColor.set(chosen ? EDGE_COLORS.chosen : state === 'candidate' ? EDGE_COLORS.candidate : EDGE_COLORS.archived);
      entry.arrow.material.color.copy(edgeColor);
      entry.arrow.material.opacity = (chosen ? progress : state === 'candidate' ? 0.7 : entry.archived ? 0.45 : touching ? 0.35 : 0) * presence;
      entry.sparks.forEach((spark, index) => {
        const flowing = !calm && presence > 0.9 && ((chosen && progress === 1) || (state === 'candidate' && index === 0));
        spark.material.opacity = flowing ? (chosen ? 0.85 : 0.7) : 0;
        if (!flowing) return;
        spark.material.color.set(chosen ? '#a7f3d0' : '#ddd6fe');
        const t = chosen ? (seconds / 1.6 + index / 3 + entry.phase) % 1 : (seconds / 2.4 + entry.phase) % 1;
        spark.position.copy(entry.curve.getPoint(t));
      });
      if (!entry.tag) continue;
      const current = lastFocus.includes(edge.from) || lastFocus.includes(edge.to);
      const showTag = presence > 0.9 && ((chosen && progress === 1 && current) || touching);
      entry.tag.visible = showTag && pixelsAt(entry.tag.position) > 0.55;
      if (entry.tag.visible) entry.text.dataset.state = state;
    }
    const behind = currentAzimuth() + Math.PI * 0.78;
    for (const title of ringTitles) {
      const {radius, y} = title.ring;
      title.object.position.set(radius * Math.sin(behind), y, radius * Math.cos(behind));
      title.element.style.setProperty('--s', clamp(pixelsAt(title.object.position) * 1.2, 0.6, 1.05).toFixed(2));
    }
    renderer.render(scene, camera);
    labels.render(scene, camera);
    wake();
  }
  function wake() { if (!raf && !destroyed) raf = requestAnimationFrame(tick); }

  function resize() {
    const width = stage.clientWidth, height = stage.clientHeight;
    if (!width || !height || (width === size.width && height === size.height)) return;
    const first = !size.height;
    size = {width, height};
    renderer.setSize(width, height, false);
    labels.setSize(width, height);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    if (first || !tween) focus(lastFocus, false);
    wake();
  }

  /* Input. */
  controls.addEventListener('start', () => { lastInteraction = performance.now(); tween = null; sway = 0; wake(); });
  controls.addEventListener('change', wake);
  controlsBar.addEventListener('click', event => {
    const action = event.target.closest('[data-graph-action]')?.dataset.graphAction;
    if (action === 'in') zoom(1.25);
    if (action === 'out') zoom(0.8);
    if (action === 'fit') fit();
    if (action === 'current') focus();
    if (action === 'switch') onSwitch?.();
  });
  labels.domElement.addEventListener('click', event => {
    const button = event.target.closest('[data-node]');
    if (button) select(button.dataset.node);
  });
  labels.domElement.addEventListener('pointerover', event => {
    const button = event.target.closest?.('[data-node]');
    if (button && event.pointerType === 'mouse') { hovered = button.dataset.node; wake(); }
  });
  labels.domElement.addEventListener('pointerout', event => {
    const button = event.target.closest?.('[data-node]');
    if (button && !button.contains(event.relatedTarget)) { hovered = ''; wake(); }
  });
  labels.domElement.addEventListener('focusin', event => {
    const id = event.target.closest?.('[data-node]')?.dataset.node;
    if (!id) return;
    hovered = id;
    const projected = V(points.get(id)).project(camera);
    if (Math.abs(projected.x) > 0.85 || Math.abs(projected.y) > 0.8 || projected.z > 1) focus([id]);
    wake();
  });
  labels.domElement.addEventListener('focusout', () => { hovered = ''; wake(); });
  const raycaster = new THREE.Raycaster(), pointer = new THREE.Vector2();
  let press = null;
  const pick = event => {
    const box = renderer.domElement.getBoundingClientRect();
    pointer.set((event.clientX - box.left) / box.width * 2 - 1, -(event.clientY - box.top) / box.height * 2 + 1);
    raycaster.setFromCamera(pointer, camera);
    const visibleHits = hits.filter(hit => items.get(hit.userData.id)?.appear > 0.5);
    return raycaster.intersectObjects(visibleHits, false)[0]?.object.userData.id || '';
  };
  renderer.domElement.addEventListener('pointerdown', event => { press = {x: event.clientX, y: event.clientY}; });
  renderer.domElement.addEventListener('pointerup', event => {
    if (press && Math.hypot(event.clientX - press.x, event.clientY - press.y) < 5) {
      const id = pick(event);
      if (id) select(id);
    }
    press = null;
  });
  renderer.domElement.addEventListener('pointermove', event => {
    if (event.buttons || event.pointerType !== 'mouse') return;
    const id = pick(event);
    renderer.domElement.style.cursor = id ? 'pointer' : '';
    if (id !== hovered) { hovered = id; wake(); }
  });
  stage.addEventListener('keydown', event => {
    if (event.target !== stage) return;
    const turn = {ArrowLeft: [-0.15, 0], ArrowRight: [0.15, 0], ArrowUp: [0, -0.08], ArrowDown: [0, 0.08]}[event.key];
    if (turn) { event.preventDefault(); orbit(...turn); }
    else if (['+', '='].includes(event.key)) { event.preventDefault(); zoom(1.25); }
    else if (event.key === '-') { event.preventDefault(); zoom(0.8); }
    else if (event.key === '0') { event.preventDefault(); fit(); }
  });
  const resizeObserver = new ResizeObserver(resize);
  resizeObserver.observe(stage);
  const visibility = new IntersectionObserver(([entry]) => { visible = entry.isIntersecting; wake(); });
  visibility.observe(stage);
  const onVisibility = () => { if (!document.hidden) { last = performance.now(); wake(); } };
  document.addEventListener('visibilitychange', onVisibility);
  resize();

  return {
    render, fit, focus: (ids, animate) => focus(ids, animate), stage,
    destroy() {
      destroyed = true;
      cancelAnimationFrame(raf);
      resizeObserver.disconnect(); visibility.disconnect();
      document.removeEventListener('visibilitychange', onVisibility);
      controls.dispose();
      scene.traverse(object => {
        object.geometry?.dispose();
        for (const material of [object.material].flat()) material?.dispose();
      });
      glow.dispose();
      renderer.dispose();
      renderer.forceContextLoss();
      host.replaceChildren();
    },
  };
}
