#!/usr/bin/env node
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {createHash} from 'node:crypto';
import {validateGraph, RESERVED_PATHS} from '../site/assets/knowledge-next/model.mjs';
import {rewriteResourceLinks} from '../site/assets/knowledge-next/resource-links.mjs';
import {buildCity, homeChapters, recorded} from '../site/assets/knowledge-next/city.mjs';
import {makeRenderer, textHtml} from './lib/public-knowledge-html.mjs';
import {loadTeaching} from './lib/public-knowledge-teaching.mjs';
import {teachingOutputs} from './lib/public-knowledge-teaching-html.mjs';
import {exportRows} from './lib/public-knowledge-export.mjs';

import {repoRoot, loadSources} from './lib/public-knowledge-sources.mjs';
export {repoRoot, loadSources};

const decode = text => text.replace(/&(lt|gt|amp|quot|#39);/g,(_s,k)=>({lt:'<',gt:'>',amp:'&',quot:'"','#39':"'"}[k]));
export function renderResourceMath(html) {
  return html.split(/(<[^>]*>)/g).map((part,i)=>i%2 || !part.includes('$') ? part : textHtml(decode(part))).join('');
}

async function fileUnderSite(root, url) {
  if (!url.startsWith('/') || url.startsWith('//') || url.includes('..') || /[?#]/.test(url)) throw new Error(`资源必须是明确的站内文件路径：${url}`);
  const file=path.join(root,'site',url);
  if (!(await fs.stat(file)).isFile()) throw new Error(`资源不是文件：${url}`);
  return file;
}

export async function generate(root = repoRoot) {
  const {nodes,manifest,outline}=await loadSources(root), edges=validateGraph(nodes,manifest);
  const teaching=await loadTeaching(root,nodes,manifest);
  for (const n of nodes) if (RESERVED_PATHS.includes(n.id)) throw new Error(`节点 ID 与页面路径冲突：${n.id}`);
  const city=buildCity(outline,{nodes,edges,defaultScope:manifest.defaultScope}), homes=homeChapters(outline,{nodes,edges});
  const bookShort=new Map(city.books.map(b=>[b.id,b.short]));
  const chapters=city.chapters.map(c=>({id:c.id,book:bookShort.get(c.book),number:c.number,label:c.label,strand:c.strand,recorded:recorded(c),...(c.node?{node:c.node}:{}),sections:c.sections.filter(s=>s.node).map(s=>({id:s.node,number:s.number,label:s.label}))}));
  // Every current example URL must resolve. No problem routes or steps are copied.
  for (const n of nodes) for (const e of n.examples || []) if (e.url) {
    if (!/^\/(1|2)\/q\d{2}\/$/.test(e.url)) throw new Error(`例题地址不符合本站题页格式：${e.url}`);
    await fileUnderSite(root,`${e.url}index.html`);
  }
  const resourceHtml={}, labels=Object.fromEntries(nodes.map(n=>[n.id,n.label]));
  for (const [id,resource] of Object.entries(manifest.resources)) {
    const file=await fileUnderSite(root,resource.module);
    if (!/^[a-z][a-z0-9-]*$/.test(resource.scope)) throw new Error(`非法图解样式作用域 ${id}`);
    const mod=(await import(pathToFileURL(file).href)).default;
    if (resource.part && typeof mod[resource.part]!=='function') throw new Error(`图解 ${id} 的模块没有 ${resource.part}()`);
    const raw=(resource.part ? mod[resource.part] : mod.render).call(mod,{node:null,tip:null,topic:null});
    const rewritten=rewriteResourceLinks(raw,manifest.resourceLinks,labels);
    if (rewritten.includes('data-explain-open') || /href=["']\/knowledge\//.test(rewritten)) throw new Error(`图解仍包含旧导航：${id}`);
    resourceHtml[id]=renderResourceMath(rewritten).replace(/^[ \t]+$/gm,'');
    if (mod.stylesheet) {
      const u=new URL(mod.stylesheet);
      const relative=path.relative(path.dirname(await fs.realpath(file)),fileURLToPath(u)).split(path.sep).join('/');
      resource.stylesheet=path.posix.join(path.posix.dirname(resource.module),relative);
      await fileUnderSite(root,resource.stylesheet);
    }
    const resourceHash=createHash('sha256').update(await fs.readFile(file));
    if(resource.stylesheet) resourceHash.update(await fs.readFile(path.join(root,'site',resource.stylesheet)));
    resource.version=resourceHash.digest('hex').slice(0,12);
  }
  // New drill ownership is not wired to the legacy learning API. Stage 3 enables it.
  manifest.drills=[];
  const release=(await exportRows(root,{nodes,edges,manifest,teaching}))._meta;
  const assetDir=path.join(root,'site/assets/knowledge-next');
  const assetNames=(await fs.readdir(assetDir)).filter(n=>/\.(mjs|css)$/.test(n)).sort();
  const hash=createHash('sha256');
  for (const f of assetNames) hash.update(await fs.readFile(path.join(assetDir,f)));
  const version=hash.digest('hex').slice(0,12);
  const render=makeRenderer(nodes,edges,manifest,version,city,homes,chapters);
  const graph={schemaVersion:1,defaultScope:manifest.defaultScope,chapters,nodes:nodes.map(n=>({id:n.id,kind:n.kind,subtype:n.subtype,label:n.label,summary:n.summary,aliases:n.aliases || [],...(homes.has(n.id)?{home:homes.get(n.id)}:{}),...(n.kind==='method'?{steps:n.steps.map(s=>({id:s.id,title:s.title,calls:(s.calls || []).map(c=>c.ref),...(s.rule?{rule:s.rule}:{})}))}:{})})),edges};
  const outputs=new Map([
    ['index.html',render.overview()],['nodes/index.html',render.list()],['3d/index.html',render.tower()],
    ['graph.json',JSON.stringify(graph,null,2)+'\n'],['city.json',JSON.stringify(city,null,2)+'\n'],
  ]);
  for (const c of chapters.filter(c=>c.recorded)) outputs.set(`chapters/${c.id}/index.html`,render.chapter(c));
  // A versioned directory also versions all relative ES module imports.
  for (const f of assetNames) outputs.set(`assets/${version}/${f}`,await fs.readFile(path.join(assetDir,f),'utf8'));
  for (const n of nodes) outputs.set(`${n.id}/index.html`,render.detail(n,resourceHtml));
  for (const [file,body] of teachingOutputs(teaching,nodes,manifest,resourceHtml,render,version)) outputs.set(file,body);
  outputs.set('teaching/version.json',JSON.stringify(release,null,2)+'\n');
  for (const [name,body] of outputs) if (/^teaching\/problems\/.+\.json$/.test(name)) {
    outputs.set(name,JSON.stringify({...JSON.parse(body),content_version:release.content_version},null,2)+'\n');
  }
  outputs.set('manifest.json',JSON.stringify({contentVersion:release.content_version,generator:'tools/build-public-knowledge-graph.mjs',schemaVersion:1,nodeCounts:manifest.expectedCounts,files:[...outputs.keys()].sort()},null,2)+'\n');
  return {outputs,nodes,edges,manifest,teaching};
}

async function filesBelow(dir, prefix='') {
  let entries; try {entries=await fs.readdir(dir,{withFileTypes:true});} catch(e) {if(e.code==='ENOENT') return []; throw e;}
  const result=[];
  for(const ent of entries) {
    if(ent.isSymbolicLink()) throw new Error(`输出目录不允许符号链接：${ent.name}`);
    const rel=path.posix.join(prefix,ent.name);
    if(ent.isDirectory()) result.push(...await filesBelow(path.join(dir,ent.name),rel));
    else result.push(rel);
  }
  return result;
}

export async function publish({root=repoRoot, check=false}={}) {
  const {outputs,nodes,edges}=await generate(root);
  const out=path.join(root,'site/knowledge-next');
  const existing=await filesBelow(out), stale=[];
  for (const [rel,body] of outputs) {
    const file=path.join(out,rel);
    let old; try {old=await fs.readFile(file,'utf8');} catch(e) {if(e.code!=='ENOENT') throw e;}
    if(old!==body) {
      stale.push(rel);
      if(!check) {await fs.mkdir(path.dirname(file),{recursive:true});await fs.writeFile(file,body);}
    }
  }
  // Only this generator's dedicated preview directory is managed.
  for (const rel of existing) if(!outputs.has(rel)) { stale.push(`obsolete: ${rel}`); if(!check) await fs.unlink(path.join(out,rel)); }
  if(!check) for (const dir of new Set(existing.filter(rel=>!outputs.has(rel)).map(rel=>path.dirname(path.join(out,rel))))) await fs.rmdir(dir).catch(()=>{});
  if(check && stale.length) throw new Error(`生成产物缺失或过期（运行 node tools/build-public-knowledge-graph.mjs）：\n${stale.join('\n')}`);
  return {nodes:nodes.length,edges:edges.length,files:outputs.size,changed:stale.length};
}
if(process.argv[1] && path.resolve(process.argv[1])===fileURLToPath(import.meta.url)) {
  if(process.argv.slice(2).some(a=>a!=='--check')) { console.error('Usage: node tools/build-public-knowledge-graph.mjs [--check]');process.exitCode=1; }
  else try {console.log(JSON.stringify(await publish({check:process.argv.includes('--check')})));} catch(e) {console.error(e.message);process.exitCode=1;}
}
