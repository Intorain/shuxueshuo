// Extract the current explainer's prose and TeX; no browser globals or mount handlers run.
import fs from 'node:fs';
import {pathToFileURL, fileURLToPath} from 'node:url';
import path from 'node:path';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../site');
const graph=JSON.parse(fs.readFileSync(path.join(root,'data/knowledge/graph.json')));
const display=JSON.parse(fs.readFileSync(path.join(root,'data/knowledge/display.json')));
const result={};
for(const node of graph.nodes){
 const module=await import(pathToFileURL(path.join(root,`assets/explain/${node.kind==='method'?'method':'knowledge'}/${display[node.id].sheet}.js`)));
 result[node.id]=module.default.render({node,tip:null,topic:null});
}
process.stdout.write(JSON.stringify(result));
