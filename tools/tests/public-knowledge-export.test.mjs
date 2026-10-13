import test from 'node:test';
import assert from 'node:assert/strict';
import { exportContent } from '../export-public-knowledge.mjs';
import { contentDigest } from '../lib/public-knowledge-export.mjs';
import { generate } from '../build-public-knowledge-graph.mjs';

const data = await exportContent();

test('structured export contains current ontology and private drills without HTML rendering', () => {
  assert.equal(data.knowledge_nodes.length, 67);
  assert.equal(new Set(data.knowledge_nodes.map((n) => n.kind)).size, 8);
  assert.equal(new Set(data.knowledge_edges.map((e) => e.relation_type)).size, 10);
  assert.equal(data.practice_routes.length, 50);
  assert.equal(data.practice_steps.length, 259);
  assert.equal(data.knowledge_drill_items.length, 177);
  assert.equal(new Set(data.knowledge_drill_items.map((q) => q.item_id)).size, 177);
  assert.equal(data.knowledge_drill_items.filter((q) => q.node_id === 'amgm-formula').length, 1);
  assert.ok(data.knowledge_drill_items.every((q) => q.answer_spec.selected.length));
  assert.ok(data.knowledge_entries.some((e) => e.entry_type === 'branch'));
  assert.ok(data.knowledge_edges.some((e) => e.occurrences.length > 1));
});

test('exports are reproducible and preserve conditional route associations', async () => {
  assert.deepEqual(await exportContent(), data);
  const { _meta, ...rows } = data;
  assert.equal(_meta.content_version, contentDigest(rows));
  const route = data.practice_routes.find((r) => r.problem_id === 'basic-inequality-q01' && r.route_id === 'elimination');
  assert.equal(route.methods.field, 'technique');
  const text = JSON.stringify(route.methods);
  assert.ok(text.includes('method-quadratic-extremum'));
  assert.ok(text.includes('method-square-extremum'));
});

test('static and database content versions agree, static outputs never carry drill answers', async () => {
  const { outputs } = await generate();
  const version = JSON.parse(outputs.get('teaching/version.json'));
  assert.deepEqual(version, data._meta);
  assert.equal(JSON.parse(outputs.get('teaching/problems/basic-inequality-q01.json')).content_version, version.content_version);
  for (const [name, output] of outputs) if (name.endsWith('.json')) {
    assert.ok(!output.includes('"answer_spec"'), name);
    assert.ok(!output.includes('"item_snapshot"'), name);
    assert.ok(!output.includes('"_lesson"'), name);
    assert.ok(!output.includes('"required_evidence"'), name);
  }
});
