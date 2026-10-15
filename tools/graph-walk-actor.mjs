#!/usr/bin/env node
import fs from 'node:fs/promises';
import readline from 'node:readline';
import {createState, submitAnswer, switchRoute, projectDecision, replayState} from '../site/assets/graph-walk/walk-state.mjs';

let bundle, state;
// The AI picks its first route at the method plane; once that route is done, the recorder
// switches to each remaining route in turn, like a student's "再用另一种方法做一遍".
const walked = () => [...state.archives.map(run => run.route), state.run.route].filter(Boolean);
const nextRoute = () => state.done ? Object.keys(bundle.routes).find(route => !walked().includes(route)) || null : null;
function snapshot() {
  const next = nextRoute(), done = state.done && !next;
  return {
    bundleVersion: bundle.bundleVersion, problemId: bundle.problemId,
    decision: projectDecision(bundle, state), done, nextRoute: next, routes: walked(),
    status: done ? 'completed' : 'in_progress', feedback: state.lastFeedback,
  };
}

const input = readline.createInterface({input: process.stdin, crlfDelay: Infinity});
for await (const line of input) {
  try {
    const request = JSON.parse(line);
    if (request.op === 'init') {
      bundle = JSON.parse(await fs.readFile(request.bundle, 'utf8'));
      state = createState(bundle);
      process.stdout.write(JSON.stringify(snapshot()) + '\n');
    } else if (!state) {
      throw new Error('请先初始化录制');
    } else if (request.op === 'answer') {
      state = submitAnswer(bundle, state, request.action);
      process.stdout.write(JSON.stringify(snapshot()) + '\n');
    } else if (request.op === 'switch') {
      const next = nextRoute();
      if (!next) throw new Error('当前路线未完成或没有其他路线');
      state = switchRoute(bundle, state, next);
      process.stdout.write(JSON.stringify(snapshot()) + '\n');
    } else if (request.op === 'validate_replay') {
      const replay = request.replay;
      const replayed = replayState(bundle, replay);
      const valid = replay.status === 'completed' && replayed.done &&
        Object.keys(bundle.routes).every(route => replay.routes.includes(route));
      process.stdout.write(JSON.stringify({valid}) + '\n');
    } else if (request.op === 'export') {
      const actions = state.events.filter(event => ['answer', 'switch_route'].includes(event.kind))
        .map(event => event.kind === 'switch_route' ? {switch_route: event.route} : event.action);
      process.stdout.write(JSON.stringify({schemaVersion: 2, bundleVersion: bundle.bundleVersion, problemId: bundle.problemId,
        routes: walked(), actions, status: snapshot().status}) + '\n');
    } else throw new Error('未知操作');
  } catch (error) {
    process.stdout.write(JSON.stringify({error: error.message}) + '\n');
  }
}
