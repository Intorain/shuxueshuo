import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {createState, currentDecision, submitAnswer, graphState, replayState} from '../../site/assets/graph-walk/walk-state.mjs';
import {lanesLayout} from '../../site/assets/knowledge-next/layout.mjs';

// Written by server/tools/build_demo_lessons.py from recorded stage-two runs.
const lessons = ['q01', 'q10'].map(name => JSON.parse(fs.readFileSync(new URL(`../../site/lab/search/demo-lesson-${name}.json`, import.meta.url), 'utf8')));
const walks = lessons.flatMap(lesson => lesson.goals.map(goal => goal.walk).filter(Boolean));

test('every resolved part ships a bundle and replay the engine accepts', () => {
  assert.equal(walks.length, 3);
  assert.equal(new Set(walks.map(walk => walk.bundle.problemId)).size, walks.length);
  for (const {bundle, replay} of walks) {
    const state = replayState(bundle, replay);
    assert.equal(state.introCompleted.length, bundle.intro.length);
    assert.equal(currentDecision(bundle, state), null);
    assert.equal(state.done, false);
    assert.ok(bundle.pending.title);
  }
});

test('the AI replay answers with the same values the student is graded against', () => {
  for (const {bundle, replay} of walks) {
    let state = createState(bundle);
    for (const action of replay.actions) {
      state = submitAnswer(bundle, state, action);
      assert.equal(state.lastFeedback.status, 'passed', action.decision);
    }
  }
});

test('a wrong option explains itself with its own feedback', () => {
  const {bundle} = walks[0];
  const [d1, d2] = bundle.intro;
  const right = d1.expected_answer.terms;
  const slot = d1.interaction.slots[0];
  const wrong = slot.options.find(option => option.value !== right[0]);
  let state = submitAnswer(bundle, createState(bundle), {decision: 'D1', answer: [wrong.value, ...right.slice(1)]});
  assert.equal(state.lastFeedback.status, 'wrong');
  assert.equal(state.lastFeedback.message, wrong.feedback);
  state = submitAnswer(bundle, createState(bundle), {decision: 'D1', answer: right});
  const conflict = d2.interaction.options.find(option => option.feedback);
  if (conflict) {
    const next = submitAnswer(bundle, state, {decision: 'D2', answer: conflict.value});
    assert.deepEqual([next.lastFeedback.status, next.lastFeedback.message], ['wrong', conflict.feedback]);
  }
  for (const [value, alternative] of Object.entries(d2.alternatives)) {
    const next = submitAnswer(bundle, state, {decision: 'D2', answer: value});
    assert.deepEqual([next.lastFeedback.status, next.lastFeedback.message], ['uncovered', alternative.message]);
  }
});

test('lit nodes and edges exist in the subgraph, and the lanes lay every node out', () => {
  for (const {bundle} of walks) {
    const ids = new Set(bundle.graph.nodes.map(node => node.id));
    const edges = new Set(bundle.graph.edges.map(edge => edge.id));
    for (const decision of bundle.intro) {
      for (const id of [...decision.effects.nodes, ...decision.candidateNodes]) assert.ok(ids.has(id), id);
      for (const id of decision.effects.edges) assert.ok(edges.has(id), id);
    }
    const view = graphState(bundle, replayStateOf(bundle));
    assert.ok(Object.values(view.nodes).includes('confirmed'));
    const defs = bundle.graph.lanes.map(lane => ({label: lane.label, test: node => (lane.ids || []).includes(node.id) || node.kind === lane.kind}));
    const layout = lanesLayout(bundle.graph.nodes, bundle.graph.edges, defs);
    assert.equal(layout.positions.size, ids.size);
    assert.ok(!layout.bands.some(band => band.label === '其他'));
  }
});

function replayStateOf(bundle) {
  return replayState(bundle, walks.find(walk => walk.bundle === bundle).replay);
}
