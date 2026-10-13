import {safeGraphReturn,VIEW_KINDS} from './model.mjs';

const config=JSON.parse(document.querySelector('#node-page-config').textContent);
const params=new URLSearchParams(location.search);
const returnTo=safeGraphReturn(params.get('graph'));
if(params.has('graph')) {
  document.querySelectorAll('[data-graph-return]').forEach(a=>a.href=returnTo);
  const locate=new URL(returnTo,location.origin);
  locate.searchParams.set('node',config.id);
  const view=locate.searchParams.get('view') || 'curriculum';
  if(!VIEW_KINDS[view]?.includes(config.kind)) {
    locate.searchParams.set('view',config.kind==='knowledge'?'knowledge':['textbook','chapter','section'].includes(config.kind)?'curriculum':'solution');
    locate.searchParams.delete('relations');
  }
  const kinds=(locate.searchParams.get('kinds') || '').split(',').filter(Boolean);
  if(kinds.length && !kinds.includes(config.kind)) locate.searchParams.delete('kinds');
  const expanded=new Set((locate.searchParams.get('expand') || '').split(',').filter(Boolean));
  expanded.add(config.id);locate.searchParams.set('expand',[...expanded].join(','));
  document.querySelectorAll('[data-graph-locate]').forEach(a=>a.href=locate.pathname+locate.search);
  document.querySelectorAll('[data-node-link]').forEach(a=>{const u=new URL(a.href);u.searchParams.set('graph',returnTo);a.href=u.pathname+u.search+u.hash;});
}
if(matchMedia('(max-width: 760px)').matches) document.querySelector('.detail-toc details').open=false;

async function stylesheet(url) {
  if(!url) return;
  const existing=[...document.querySelectorAll('link[rel="stylesheet"]')].find(l=>l.getAttribute('href')===url);
  if(existing?.sheet) return;
  if(existing) existing.remove();
  await new Promise((resolve,reject)=>{
    const link=document.createElement('link');link.rel='stylesheet';link.href=url;
    link.onload=resolve;link.onerror=()=>{link.remove();reject(new Error('样式加载失败'));};document.head.append(link);
  });
}
const script=src=>new Promise((resolve,reject)=>{
  const el=document.createElement('script');el.src=src;el.onload=resolve;el.onerror=()=>{el.remove();reject(new Error('脚本加载失败'));};document.head.append(el);
});
// Drill questions arrive as LaTeX text and are rendered in the browser by PracticeMath.
async function drillDeps() {
  await stylesheet('/knowledge/node.css?v=1');
  if(window.PracticeMath) return;
  await script('/assets/practice/vendor/katex-0.18.9/katex.min.js');
  await script('/assets/practice/vendor/katex-0.18.9/auto-render.min.js');
  await script('/assets/practice/math-text.js?v=12');
}
const drillButton=document.querySelector('[data-drill-open]');
if(drillButton && config.drill) {
  let drill=null;
  drillButton.hidden=false;
  drillButton.addEventListener('click',()=>{
    drill||=drillDeps().then(()=>import('/knowledge/drill.js?v=2'));
    drill.then(m=>m.openDrill({node:config.id,label:config.label})).catch(()=>{drill=null;drillButton.textContent='刷题暂时打不开，请重试';});
  });
}

for (const resource of config.resources) {
  const root=document.querySelector(`[data-resource="${resource.id}"]`);
  const status=document.querySelector(`[data-resource-status="${resource.id}"]`), retry=document.querySelector(`[data-resource-retry="${resource.id}"]`);
  let busy=false, cleanup;
  async function mount(force=false) {
    if(busy) return;busy=true;retry.hidden=true;status.textContent='正在加载图解交互…';
    root.querySelectorAll('button,input').forEach(el=>el.disabled=true);
    try {
      const moduleUrl=`${resource.module}?v=${resource.version}${force?`&retry=${Date.now()}`:''}`;
      const mod=(await import(moduleUrl)).default;
      await stylesheet(resource.stylesheet ? `${resource.stylesheet}?v=${resource.version}` : null);
      cleanup?.();cleanup=mod.mount?.(root,{node:config,tip:null,topic:null});
      root.querySelectorAll('button,input').forEach(el=>el.disabled=false);
      status.textContent=root.querySelector('button,input,select') ? '图解已加载，可操作控件观察变化。' : '';
    } catch(error) {
      status.textContent='图解交互加载失败，正文、公式和普通链接仍可阅读。';retry.hidden=false;
    } finally {busy=false;}
  }
  retry.addEventListener('click',()=>mount(true));
  mount();
}
