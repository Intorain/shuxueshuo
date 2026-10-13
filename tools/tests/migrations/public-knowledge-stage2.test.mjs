// One-time migration acceptance. This suite intentionally needs the legacy sources;
// the regular builder and regression suites do not read them.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import { repoRoot, loadSources } from '../../build-public-knowledge-graph.mjs';
import { loadTeaching } from '../../lib/public-knowledge-teaching.mjs';
import { branches } from '../../../site/assets/knowledge-next/teaching-model.mjs';

const json = async (file) => JSON.parse(await fs.readFile(path.join(repoRoot, file), 'utf8'));
const { nodes, manifest } = await loadSources();
const teaching = await loadTeaching(repoRoot, nodes, manifest);

test('stage 2 baseline retains all legacy problem identities and hint branches', async () => {
  assert.deepEqual(teaching.counts, { problems: 39, routes: 50, steps: 259, tips: 219 });
  const legacy = await json('site/data/knowledge/graph.json');
  assert.deepEqual(
    teaching.migration.nodes.map((n) => n.legacy).sort(),
    legacy.nodes.map((n) => n.id).sort()
  );
  const hintContract = (tree) =>
    branches(tree).map((b) => ({
      conditions: b.conditions,
      case: b.value.case,
      note: b.value.note
    }));
  for (const topic of teaching.topics) {
    const old = await json(`site/data/knowledge/topics/${topic.id}.json`);
    assert.deepEqual(Object.keys(topic.problems), Object.keys(old.problems));
    for (const [pid, problem] of Object.entries(topic.problems)) {
      assert.equal(problem.path, old.problems[pid].path, pid);
      for (const [rid, steps] of Object.entries(teaching.lessons.get(pid).routes)) {
        for (const step of steps) {
          assert.deepEqual(
            hintContract(problem.routes[rid].steps[step.id].tip),
            hintContract(step.tip),
            `${pid}/${rid}/${step.id}`
          );
        }
      }
    }
  }
});

test('stage 2 baseline accounts for every legacy drill and preserves unedited questions', async () => {
  const base = 'server/shuxueshuo_server/learning';
  const originals = new Map(),
    migrated = new Map();
  for (const file of await fs.readdir(path.join(repoRoot, base, 'drills'))) {
    if (!file.endsWith('.json')) continue;
    const set = await json(`${base}/drills/${file}`);
    for (const item of set.items) originals.set(`${set.node}--${item.id}`, item);
  }
  for (const file of await fs.readdir(path.join(repoRoot, base, 'drills-next/sets'))) {
    if (!file.endsWith('.json')) continue;
    const set = await json(`${base}/drills-next/sets/${file}`);
    for (const item of set.items) migrated.set(item.id, item);
  }
  for (const item of (await json(`${base}/drills-next/retired.json`)).items) migrated.set(item.id, item);
  assert.equal(originals.size, 180);
  assert.deepEqual([...migrated.keys()].sort(), [...originals.keys()].sort());
  assert.deepEqual(teaching.drills.records.map((r) => r.id).sort(), [...originals.keys()].sort());
  assert.equal(teaching.drills.active, 177);
  assert.equal(teaching.drills.retired, 3);
  assert.equal(teaching.drills.sets.length, 29);
  assert.equal(teaching.drills.sets.filter((s) => s.eligible).length, 16);
  for (const row of teaching.drills.records) {
    if (!['keep', 'reassign', 'retire'].includes(row.action)) continue;
    const item = migrated.get(row.id),
      copy = { ...item, id: item.origin.item };
    delete copy.origin;
    delete copy.entry;
    assert.deepEqual(copy, originals.get(row.id), `小题已修订但未记录：${row.id}`);
  }
});
