import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {CALL_LANE, extendStreamBundle} from '../../site/assets/graph-walk/walk-state.mjs';
import {laneMembers, treeLayout} from '../../site/assets/graph-walk/walk-graph.mjs';
import {layoutRadial} from '../../site/assets/graph-walk/walk-graph-3d.mjs';
import {lanesLayout} from '../../site/assets/knowledge-next/layout.mjs';

const read = path => JSON.parse(fs.readFileSync(new URL(path, import.meta.url), 'utf8'));
const base = read('../../site/lab/search/demo-lesson-q01.json').goals[0].walk.bundle;
const publicGraph = read('../../site/knowledge/graph.json');
const identity = {run_id: 'stream-lanes', lesson_version: 'stream-lanes-version'};
const target = '/root/goals/0', route = 'discriminant';
const records = [
  {seq: 1, method: 'method-discriminant', step: 'normalize', calls: [
    {public_ref: 'skill-inequality-transform', used_basis: ['inequality-properties#addition'], postconditions: [{passed: true}]},
  ]},
  {seq: 2, method: 'method-discriminant', step: 'conditions', calls: [
    {public_ref: 'skill-quadratic-sign', used_basis: ['quadratic-function-properties#definition'], postconditions: [{passed: true}]},
  ]},
];
const cards = records.map(record => ({...identity, target_ref: target, route_id: route,
  step_id: `math-${record.seq}`, ordinal: record.seq, math_step_sha256: `math-hash-${record.seq}`,
  local_check: 'passed', method_ref: `${record.method}#${record.step}`,
  source_refs: [`/steps/${record.seq - 1}/calls/0`], title: `步骤 ${record.seq}`}));
const view = count => ({...identity, math_steps: cards.slice(0, count),
  trajectories: [{target_ref: target, route_id: route, steps: records.slice(0, count)}]});

function positioned(graph) {
  const defs = graph.lanes.map(lane => ({label: lane.label,
    test: node => lane.ids?.includes(node.id) || lane.kind === node.kind}));
  return {...graph, layout: lanesLayout(graph.nodes, graph.edges, defs)};
}

test('successive calculation arrivals keep one calls lane in both flat and 3D graphs', () => {
  const original = structuredClone(base);
  const first = extendStreamBundle(base, view(1), target, publicGraph);
  const firstCopy = structuredClone(first);
  const incremental = extendStreamBundle(first, view(2), target, publicGraph);
  const snapshot = extendStreamBundle(base, view(2), target, publicGraph);
  assert.deepEqual(base, original, 'stream updates do not mutate the base bundle');
  assert.deepEqual(first, firstCopy, 'later calls do not mutate an earlier bundle');
  assert.deepEqual(incremental.graph.lanes, snapshot.graph.lanes);
  assert.equal(incremental.graph.lanes.filter(lane => lane.label === CALL_LANE).length, 1);
  const graph = positioned(incremental.graph);
  const members = laneMembers(graph, CALL_LANE);
  assert.deepEqual([...members].sort(), ['inequality-properties', 'skill-inequality-transform', 'skill-quadratic-sign']);
  assert.equal(treeLayout(graph).bands.filter(band => band.label === CALL_LANE).length, 1);
  assert.equal(layoutRadial(graph).rings.filter(ring => ring.label === CALL_LANE).length, 1);
  assert.deepEqual(graph.layout, positioned(snapshot.graph).layout, 'initial replay and refresh have the same layout');
  assert.deepEqual(extendStreamBundle(incremental, view(2), target, publicGraph), incremental,
    'duplicate HTTP/WS delivery does not add a lane or change graph evidence');
});

test('existing repeated calls lanes are consolidated without losing skills or basis nodes', () => {
  const snapshot = extendStreamBundle(base, view(2), target, publicGraph);
  const old = structuredClone(snapshot);
  const members = old.graph.lanes.find(lane => lane.label === CALL_LANE).ids;
  old.graph.lanes = [...old.graph.lanes.filter(lane => lane.label !== CALL_LANE),
    ...members.map(id => ({label: CALL_LANE, ids: [id]}))];
  const recovered = extendStreamBundle(old, view(2), target, publicGraph);
  assert.deepEqual(recovered.graph.lanes, snapshot.graph.lanes);
  assert.deepEqual(recovered.stream.step_calls, snapshot.stream.step_calls);
  assert.deepEqual(recovered.graph.nodes, snapshot.graph.nodes);
  assert.deepEqual(recovered.graph.edges, snapshot.graph.edges);
});
