#!/usr/bin/env node
/* Builds one static detail page per graph node, site/knowledge/<node id>/index.html, from graph.json,
   display.json, the topic files and the 刷题 files under data/knowledge/drills/.
   Usage: node tools/build-knowledge-pages.mjs [--check]   (--check reports stale pages and writes nothing) */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const site = path.join(repoRoot, "site");
const outRoot = path.join(site, "knowledge");
const GENERATOR = "tools/build-knowledge-pages.mjs";
const { detailHref } = await import(pathToFileURL(path.join(site, "assets/explain/links.js")).href);

const readJson = (file) => JSON.parse(fs.readFileSync(path.join(site, file), "utf8"));
const jsonFiles = (dir) => fs.readdirSync(path.join(site, dir)).filter((name) => name.endsWith(".json")).sort();
const escape = (text) => String(text).replace(/[&<>"]/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[ch]);

const graph = readJson("data/knowledge/graph.json");
const display = readJson("data/knowledge/display.json");
const topics = jsonFiles("data/knowledge/topics").map((name) => readJson(`data/knowledge/topics/${name}`));
const nodes = new Map(graph.nodes.map((node) => [node.id, { ...node, ...display[node.id] }]));
const edges = (type, key, id) => graph.edges.filter((edge) => edge.type === type && edge[key] === id);
const before = (id) => edges("prerequisite", "to", id).map((edge) => edge.from);
const after = (id) => edges("prerequisite", "from", id).map((edge) => edge.to);
const usedBy = (id) => edges("uses", "to", id).map((edge) => edge.from);
const usesOf = (id) => edges("uses", "from", id).map((edge) => edge.to);
const kindLabel = (node) => node.subtype === "technique" ? "方法 · 表达式的变形" : node.kind === "method" ? "方法" : "知识点";

const routes = new Map();
function stepsOf(problemId, route) {
  const problem = topics.map((topic) => topic.problems[problemId]).find(Boolean);
  if (!problem) throw new Error(`unknown problem ${problemId}`);
  if (!routes.has(problemId)) {
    const html = fs.readFileSync(path.join(site, problem.path, "index.html"), "utf8");
    const config = html.match(/id="practice-config">\s*([\s\S]*?)<\/script>/)?.[1];
    if (!config) throw new Error(`${problem.path}: missing practice-config`);
    routes.set(problemId, JSON.parse(config).routes);
  }
  return routes.get(problemId)[route] || [];
}

// 刷题 files: short questions an author wrote for one node; checked here so a broken file fails the build.
function checkDrill(name, drill) {
  const fail = (message) => { throw new Error(`data/knowledge/drills/${name}: ${message}`); };
  if (`${drill.node}.json` !== name || !nodes.has(drill.node)) fail("node must be a graph node named like the file");
  if (!drill.items?.length) fail("no items");
  const ids = new Set();
  for (const item of drill.items) {
    const where = `item ${item.id}`;
    if (!item.id || ids.has(item.id)) fail(`${where}: missing or duplicate id`);
    ids.add(item.id);
    if (!item.question) fail(`${where}: question is required`);
    if (!["choice", "multi"].includes(item.type)) fail(`${where}: type must be choice or multi`);
    const values = (item.options || []).map((option) => option.value);
    if (values.length < 2 || new Set(values).size !== values.length || item.options.some((option) => !option.label)) fail(`${where}: needs two or more options with distinct values and labels`);
    const answer = [item.answer].flat();
    const shaped = item.type === "choice" ? typeof item.answer === "string" : Array.isArray(item.answer) && answer.length > 0;
    if (!shaped || new Set(answer).size !== answer.length || answer.some((value) => !values.includes(value))) fail(`${where}: answer must name its options`);
    // A wrong pick is answered with that option's feedback.
    if (item.options.some((option) => !answer.includes(option.value) && !option.feedback)) fail(`${where}: every wrong option needs feedback`);
    if (item.source) {
      const [problemId, route, step] = item.source.split("/");
      if (!stepsOf(problemId, route).some((entry) => entry.id === step)) fail(`${where}: source ${item.source} is not a practice step`);
    }
  }
  return drill;
}
const drills = new Map(jsonFiles("data/knowledge/drills").map((name) => {
  const drill = checkDrill(name, readJson(`data/knowledge/drills/${name}`));
  return [drill.node, drill];
}));

const chip = (id) => `<a class="kn-chip ${nodes.get(id).kind}" href="${detailHref(id)}">${escape(nodes.get(id).label)}</a>`;

function relations(node) {
  const rows = (node.kind === "knowledge"
    ? [["前提", before(node.id)], ["后续", after(node.id)], ["以它为核心依据的方法", usedBy(node.id)]]
    : [["核心知识依据", usesOf(node.id)]]).filter(([, ids]) => ids.length);
  if (!rows.length) return "";
  return `<dl class="kn-relations">${rows.map(([title, ids]) => `<div><dt>${title}</dt><dd>${ids.map(chip).join("")}</dd></div>`).join("")}</dl>`;
}

// A method's steps in each topic that uses it: its first step, then the knowledge points in order.
function flows(node) {
  return topics.flatMap((topic) => topic.methods.filter((method) => method.node === node.id).map((method) => {
    const problemId = Object.keys(topic.problems).find((id) => topic.problems[id].routes[method.route]);
    const basis = stepsOf(problemId, method.route)[0].title;
    return `<article class="kn-topic">
        <h3><a href="${topic.path}">${escape(topic.label)}</a></h3>
        <ol class="kn-flow"><li class="kn-flow-self">${escape(basis)}</li>${method.sequence.map((id) => `<li>${chip(id)}</li>`).join("")}</ol>
      </article>`;
  }));
}

const drillButton = (drill) => `<button type="button" class="kn-drill-open" data-drill-open hidden>刷题 · ${drill.items.length} 题</button>`;
const drillData = (node, drill) => JSON.stringify({ label: node.label, items: drill.items.map(({ source, ...item }) => item) }).replace(/</g, "\\u003c");

function render(node) {
  const url = `https://shuxueshuo.com/knowledge/${node.id}/`;
  const title = `${node.label} · ${kindLabel(node)} · 数学说`;
  const drill = drills.get(node.id);
  const steps = flows(node);
  const sections = [];
  if (node.sheet) sections.push(`<section class="kn-section" aria-labelledby="kn-explain-title">
      <div class="kn-section-head"><h2 id="kn-explain-title">图解</h2>${drill ? drillButton(drill) : ""}</div>
      <div class="kn-explain"><div data-explainer="${node.sheet}"><p class="kn-none">图解加载中…</p></div></div>
    </section>`);
  else if (drill) sections.push(`<section class="kn-section" aria-labelledby="kn-drill-title">
      <div class="kn-section-head"><h2 id="kn-drill-title">刷题</h2>${drillButton(drill)}</div>
    </section>`);
  if (steps.length) sections.push(`<section class="kn-section" aria-labelledby="kn-steps-title">
      <h2 id="kn-steps-title">解题步骤</h2>
      <div class="kn-topics">
      ${steps.join("\n      ")}
      </div>
    </section>`);
  if (!sections.length) sections.push('<p class="kn-none kn-pending">图解和刷题还在整理中。</p>');
  return `<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <meta name="theme-color" content="#f5f7f5">
  <meta name="generator" content="${GENERATOR}">
  <meta name="description" content="${escape(node.summary)}">
  <meta property="og:title" content="${escape(title)}">
  <meta property="og:description" content="${escape(node.summary)}">
  <meta property="og:type" content="article">
  <meta property="og:url" content="${url}">
  <meta property="og:image" content="https://shuxueshuo.com/assets/images/share-default.png">
  <link rel="canonical" href="${url}">
  <link rel="stylesheet" href="/1/chapter.css?v=20261003a">
  <link rel="stylesheet" href="/knowledge/node.css?v=1">
  <link rel="stylesheet" href="/assets/practice/vendor/katex-0.18.9/katex.min.css">
  <title>${escape(title)}</title>
  <script src="/assets/practice/vendor/katex-0.18.9/katex.min.js" defer></script>
  <script src="/assets/practice/vendor/katex-0.18.9/auto-render.min.js" defer></script>
  <script src="/assets/practice/math-text.js?v=12" defer></script>
  <script type="module" src="/assets/auth/site-auth.js?v=4"></script>
  <script type="module" src="/knowledge/node.js?v=1"></script>
</head>
<body class="kn-page">
  <a class="skip-link" href="#main">跳到正文</a>
  <header class="topbar">
    <nav class="topbar-inner" aria-label="站内导航">
      <a class="brand" href="/" aria-label="数学说首页"><span class="brand-mark" aria-hidden="true">数</span>数学说</a>
      <a class="home-link" href="/">首页 <span aria-hidden="true">↗</span></a>
    </nav>
  </header>
  <main class="workspace" id="main">
    <section class="hero kn-hero" aria-labelledby="page-title">
      <p class="eyebrow"><span>高中数学</span><span class="eyebrow-sep" aria-hidden="true">/</span><a href="/knowledge/#${node.id}">知识图谱</a><span class="eyebrow-sep" aria-hidden="true">/</span><span aria-current="page">${kindLabel(node)}</span></p>
      <h1 id="page-title" class="kn-title"><span class="title-mark">${escape(node.label)}</span></h1>
      <p class="lead">${escape(node.summary)}</p>
      ${relations(node)}
    </section>

    ${sections.join("\n\n    ")}
${drill ? `
    <script type="application/json" id="kn-drill-data">${drillData(node, drill)}</script>
` : ""}
    <footer class="chapter-footer">
      <span>数学说 · 知识图谱</span>
      <a href="${url}">shuxueshuo.com/knowledge/${node.id}</a>
    </footer>
  </main>
</body>
</html>
`;
}

const expected = new Map(graph.nodes.map((node) => [path.join(outRoot, node.id, "index.html"), render(nodes.get(node.id))]));
const generated = (dir) => {
  const file = path.join(outRoot, dir, "index.html");
  return fs.existsSync(file) && fs.readFileSync(file, "utf8").includes(`<meta name="generator" content="${GENERATOR}">`);
};
const problems = [];
for (const node of graph.nodes) {
  if (fs.existsSync(path.join(outRoot, node.id)) && !generated(node.id)) problems.push(`site/knowledge/${node.id} exists and was not generated`);
}
const stale = fs.readdirSync(outRoot, { withFileTypes: true })
  .filter((entry) => entry.isDirectory() && !nodes.has(entry.name) && generated(entry.name)).map((entry) => entry.name);
const changed = [...expected].filter(([file, html]) => !fs.existsSync(file) || fs.readFileSync(file, "utf8") !== html).map(([file]) => file);

if (problems.length) {
  console.error(problems.join("\n"));
  process.exit(1);
}
if (process.argv.includes("--check")) {
  const report = [...changed.map((file) => `outdated: ${path.relative(repoRoot, file)}`), ...stale.map((dir) => `stale: site/knowledge/${dir}`)];
  if (report.length) {
    console.error(`${report.join("\n")}\nRun: node ${GENERATOR}`);
    process.exit(1);
  }
  console.log(`${expected.size} knowledge pages are up to date.`);
} else {
  for (const file of changed) {
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, expected.get(file));
  }
  for (const dir of stale) fs.rmSync(path.join(outRoot, dir), { recursive: true });
  console.log(`${expected.size} knowledge pages: ${changed.length} written, ${stale.length} removed.`);
}
