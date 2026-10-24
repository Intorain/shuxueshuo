#!/usr/bin/env node
// Rewrite the site header block of hand-written pages from tools/lib/site-header.mjs.
// Usage: node tools/sync-site-header.mjs [--check]
import {readFileSync, readdirSync, writeFileSync, existsSync} from 'node:fs';
import {dirname, join, relative} from 'node:path';
import {fileURLToPath} from 'node:url';
import {BEGIN, END, SITE_HEADER_CSS, TOPICS_TABS, siteChrome} from './lib/site-header.mjs';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const SITE = join(ROOT, 'site');

// Practice chapters under site/<n>/; a new chapter directory must be named here.
export const CHAPTERS = {1: '基本不等式', 2: '恒成立问题'};
const CHAPTER_WIDTH = '928px';
const PRACTICE_WIDTH = '824px';
const RESET = '<button type="button" class="reset-button" id="reset">↺ <span>重新练习</span></button>';
const topicsCrumb = {label: '高中专题', href: '/topics/'};

export function pages() {
  const list = [
    ['index.html', {section: 'home', exact: true}],
    ['lab/search/index.html', {section: 'search', exact: true}],
    ['nav/index.html', {section: 'junior', exact: true}],
    ['problems/tj/24/tj-2026-24-ranking.html', {section: 'junior'}],
    ['problems/tj/25/tj-2026-25-ranking.html', {section: 'junior'}],
    ['mistake-book/index.html', {}],
    ['topics/index.html', {section: 'topics', exact: true, subbar: {tabs: TOPICS_TABS, current: 'practice', tabsLabel: '高中专题', width: CHAPTER_WIDTH}}],
    ['senior-high/index.html', {section: 'topics', subbar: {tabs: TOPICS_TABS, current: 'library', tabsLabel: '高中专题'}}],
  ];
  for (const [n, name] of Object.entries(CHAPTERS)) {
    list.push([`${n}/index.html`, {section: 'topics', subbar: {crumbs: [topicsCrumb, {label: name}], width: CHAPTER_WIDTH}}]);
  }
  for (const dir of readdirSync(SITE, {withFileTypes: true})) {
    if (!dir.isDirectory() || !/^\d+$/.test(dir.name)) continue;
    const name = CHAPTERS[dir.name];
    if (!name) throw new Error(`site/${dir.name}/ 未登记专题名：请在 tools/sync-site-header.mjs 的 CHAPTERS 中添加`);
    for (const q of readdirSync(join(SITE, dir.name)).filter(q => /^q\d+$/.test(q)).sort()) {
      if (!existsSync(join(SITE, dir.name, q, 'index.html'))) continue;
      list.push([`${dir.name}/${q}/index.html`, {section: 'topics', subbar: {
        crumbs: [topicsCrumb, {label: name, href: `/${dir.name}/`}, {label: q.toUpperCase()}],
        tools: RESET, width: PRACTICE_WIDTH,
      }}]);
    }
  }
  return list;
}

const CSS_LINK = /<link rel="stylesheet" href="\/assets\/css\/site-header\.css(?:\?v=[\w.-]+)?">/;

export function render(html, spec, file) {
  const start = html.indexOf(BEGIN);
  const end = html.indexOf(END);
  if (start < 0 || end < start) throw new Error(`${file} 缺少 ${BEGIN} … ${END} 标记块`);
  let out = html.slice(0, start + BEGIN.length) + siteChrome(spec) + html.slice(end);
  const link = `<link rel="stylesheet" href="${SITE_HEADER_CSS}">`;
  if (CSS_LINK.test(out)) out = out.replace(CSS_LINK, link);
  else out = out.replace(/([ \t]*)<\/head>/, (_, indent) => `${indent}  ${link}\n${indent}</head>`);
  return out;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const check = process.argv.includes('--check');
  const stale = [];
  for (const [file, spec] of pages()) {
    const path = join(SITE, file);
    const html = readFileSync(path, 'utf8');
    const next = render(html, spec, file);
    if (next === html) continue;
    stale.push(relative(ROOT, path));
    if (!check) writeFileSync(path, next);
  }
  if (check && stale.length) {
    console.error(`站点头部与 tools/lib/site-header.mjs 不一致，请运行 node tools/sync-site-header.mjs：\n${stale.join('\n')}`);
    process.exit(1);
  }
  console.log(check ? '站点头部一致' : `已更新 ${stale.length} 个页面`);
}
