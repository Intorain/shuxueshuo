import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {HUB, azimuthFacing, distanceForScale, edgeControls, frameFor, grownNodes, layoutRadial, viewDirection} from '../../site/assets/graph-walk/walk-graph-3d.mjs';

const bundle = JSON.parse(fs.readFileSync(new URL('../../site/data/graph-walk/quadratic-always-q01.json', import.meta.url), 'utf8'));
const source = fs.readFileSync(new URL('../../site/assets/graph-walk/walk-graph-3d.mjs', import.meta.url), 'utf8');

test('a stale Three.js import cannot create a renderer or replace the current graph', async () => {
  let resolve;
  const context = vm.createContext({THREEReady: new Promise(done => { resolve = done; })});
  vm.runInContext(source.replace(/^import .*;\n/gm, '').replace(/^export /gm, '').replace('await import(THREE_URL)', 'await THREEReady'), context);
  context.active = true;
  context.host = {replaceChildren() { assert.fail('stale construction must not touch the host'); }};
  const creating = vm.runInContext('createWalkGraph3D(host, {}, {current:()=>active})', context);
  context.active = false;
  resolve({WebGLRenderer: class { constructor() { assert.fail('stale construction must not allocate WebGL'); } }});
  assert.equal(await creating, null);
});

test('destroying an obsolete 3D graph releases its resources but preserves replacement DOM', () => {
  const retained = [{name: 'new-controls'}, {name: 'new-stage'}];
  const host = {children: retained, replaceChildren(...nodes) { this.children = nodes; }};
  const ownNode = () => ({remove() { host.children = host.children.filter(node => node !== this); }});
  let disposed = 0;
  const disposable = {dispose() { disposed++; }};
  const context = {host, destroyed: false, raf: 1, controlsBar: ownNode(), stage: ownNode(),
    cancelAnimationFrame() {}, resizeObserver: {disconnect() {}}, visibility: {disconnect() {}},
    document: {removeEventListener() {}}, onVisibility() {}, controls: disposable,
    scene: {traverse(callback) { callback({geometry: disposable, material: disposable}); }},
    glow: disposable, renderer: {...disposable, forceContextLoss() {}}};
  const callback = source.slice(source.lastIndexOf('    destroy() {'), source.lastIndexOf('    },') + 6);
  const view = vm.runInNewContext(`({${callback}})`, context);
  view.destroy();
  assert.deepEqual(host.children, retained);
  assert.equal(disposed, 5);
  view.destroy();
  assert.equal(disposed, 5);
});

test('radial layout puts each 2D column on its own ring, from the problem outward', () => {
  const {points, rings} = layoutRadial(bundle.graph);
  const bands = bundle.graph.layout.bands;
  assert.deepEqual(rings.map(ring => ring.label), bands.map(band => band.label));
  for (let i = 1; i < rings.length; i++) assert.ok(rings[i].radius > rings[i - 1].radius);
  for (const node of bundle.graph.nodes) {
    const point = points.get(node.id);
    assert.ok(point, node.id);
    assert.ok(Math.abs(Math.hypot(point.x, point.z) - rings[point.ring].radius) < 1e-6);
  }
  bands.forEach((band, ring) => assert.equal([...points.values()].filter(point => point.ring === ring).length, band.count));
});

test('names on one ring keep a minimum gap and the layout is deterministic', () => {
  const first = layoutRadial(bundle.graph), second = layoutRadial(bundle.graph);
  assert.deepEqual([...first.points], [...second.points]);
  first.rings.forEach((ring, index) => {
    const angles = [...first.points.values()].filter(point => point.ring === index).map(point => point.angle).sort((a, b) => a - b);
    if (angles.length < 2) return;
    const gaps = angles.map((angle, i) => (i ? angle - angles[i - 1] : angle + Math.PI * 2 - angles.at(-1)));
    assert.ok(Math.min(...gaps) * ring.radius > 145, `${ring.label} names overlap`);
  });
});

test('connected nodes lean toward each other instead of scattering around the disk', () => {
  const {points} = layoutRadial(bundle.graph);
  const spread = edge => {
    const a = points.get(edge.from), b = points.get(edge.to);
    return Math.abs(Math.atan2(Math.sin(a.angle - b.angle), Math.cos(a.angle - b.angle)));
  };
  const crossRing = bundle.graph.edges.filter(edge => points.get(edge.from).ring !== points.get(edge.to).ring);
  const mean = crossRing.reduce((sum, edge) => sum + spread(edge), 0) / crossRing.length;
  assert.ok(mean < Math.PI / 3, `mean angular span ${mean.toFixed(2)} rad`);
});

test('edge curves start and end on their nodes and arch above the disk', () => {
  const a = {x: 170, y: 2, z: 0}, b = {x: -100, y: 20, z: 300};
  const curve = edgeControls(a, b);
  assert.equal(curve[0], a);
  assert.equal(curve[3], b);
  assert.ok(curve[1].y > Math.max(a.y, b.y) && curve[2].y > Math.max(a.y, b.y));
});

test('the camera faces a disk angle from its own side', () => {
  for (const angle of [0, 1, 2.5, 4, 5.8]) {
    const direction = viewDirection(azimuthFacing(angle));
    const length = Math.hypot(direction.x, direction.z);
    assert.ok(Math.abs(direction.x / length - Math.cos(angle)) < 1e-9);
    assert.ok(Math.abs(direction.z / length - Math.sin(angle)) < 1e-9);
  }
});

for (const [inset, top] of [[0, 0], [0.25, 0], [0.25, 0.08]]) test(`framing keeps padded points inside the view from a tilted camera (inset ${inset}, top ${top})`, () => {
  const {points} = layoutRadial(bundle.graph);
  const list = [...points.values()], width = 650, height = 540, fov = 40;
  const direction = viewDirection(azimuthFacing(1.2));
  const {target, distance} = frameFor(list, {width, height, fov, direction, inset, top});
  const camera = {x: target.x + direction.x * distance, y: target.y + direction.y * distance, z: target.z + direction.z * distance};
  const length = Math.hypot(direction.z, direction.x);
  const right = {x: direction.z / length, y: 0, z: -direction.x / length};
  const up = {x: direction.y * right.z - direction.z * right.y, y: direction.z * right.x - direction.x * right.z, z: direction.x * right.y - direction.y * right.x};
  const dot = (p, axis) => p.x * axis.x + p.y * axis.y + p.z * axis.z;
  const tanV = Math.tan(fov * Math.PI / 360), tanH = tanV * width / height;
  for (const point of list) {
    const relative = {x: point.x - camera.x, y: point.y - camera.y, z: point.z - camera.z};
    const depth = -dot(relative, direction);
    assert.ok(depth > 0);
    assert.ok(Math.abs(dot(relative, right)) / depth <= tanH + 1e-9);
    assert.ok(Math.abs(dot(relative, up)) / depth <= tanV + 1e-9);
    assert.ok(dot(relative, up) / depth >= tanV * (2 * inset - 1) - 0.02, 'points stay above the subtitle');
    assert.ok(dot(relative, up) / depth <= tanV * (1 - 2 * top) + 0.02, 'points stay below the legend');
  }
});

test('framing centers the first point when the allowed distance cannot hold the set', () => {
  const list = [{x: -800, y: 0, z: 0}, {x: 800, y: 0, z: 0}];
  const view = frameFor(list, {width: 400, height: 400, max: 500});
  assert.equal(view.distance, 500);
  assert.equal(view.target.x, -800);
  assert.equal(frameFor(list, {width: 400, height: 400, min: 9000}).distance, 9000);
});

test('growth shows the problem, reached nodes and nodes offered earlier', () => {
  const shown = grownNodes({nodes: {a: 'idle', b: 'candidate', c: 'confirmed', d: 'idle'}, seen: ['d']});
  assert.deepEqual([...shown].sort(), [HUB, 'b', 'c', 'd'].sort());
  assert.deepEqual([...grownNodes(undefined)], [HUB]);
});

test('distance for a screen scale shrinks as the scale grows', () => {
  assert.ok(distanceForScale(1, 500) < distanceForScale(0.5, 500));
  assert.equal(Math.round(distanceForScale(2, 500) * 2), Math.round(distanceForScale(1, 500)));
});
