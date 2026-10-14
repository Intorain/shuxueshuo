#!/usr/bin/env node
import { realpath } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { loadSources, repoRoot } from './lib/public-knowledge-sources.mjs';
import { validateGraph } from '../site/assets/knowledge-next/model.mjs';
import { loadTeaching } from './lib/public-knowledge-teaching.mjs';
import { exportRows } from './lib/public-knowledge-export.mjs';

export async function exportContent(root = repoRoot) {
  const { nodes, manifest } = await loadSources(root);
  const edges = validateGraph(nodes, manifest);
  const teaching = await loadTeaching(root, nodes, manifest);
  return exportRows(root, { nodes, edges, manifest, teaching });
}
if (process.argv[1] && await realpath(process.argv[1]) === await realpath(fileURLToPath(import.meta.url))) {
  try {
    if (process.argv.slice(2).some((arg) => arg !== '--check')) throw Error('Usage: node tools/export-public-knowledge.mjs [--check]');
    const data = await exportContent();
    console.log(JSON.stringify(process.argv.includes('--check') ? data._meta : data));
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}
