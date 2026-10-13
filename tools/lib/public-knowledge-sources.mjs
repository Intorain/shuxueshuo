import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

export const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
export async function loadSources(root = repoRoot) {
  const dir = path.join(root,'site/data/knowledge-next');
  const manifest = JSON.parse(await fs.readFile(path.join(dir,'catalog.json'),'utf8'));
  const names = (await fs.readdir(path.join(dir,'nodes'))).filter(f=>f.endsWith('.json')).sort();
  const nodes = await Promise.all(names.map(async name=>{
    const node=JSON.parse(await fs.readFile(path.join(dir,'nodes',name),'utf8'));
    if (`${node.id}.json`!==name) throw new Error(`文件名与 ID 不一致：${name}`);
    return node;
  }));
  const outline = JSON.parse(await fs.readFile(path.join(dir,'outline.json'),'utf8'));
  return {nodes,manifest,outline};
}

