/* System assessment is independent from whole-problem self evaluation. */
import {escapeHtml as escape} from '/assets/explain/shared/html.js?v=1';
export const STATUS = {unassessed:'未评估',mastered:'已掌握',needs_review:'待巩固'};
const sheet=document.createElement('link');sheet.rel='stylesheet';sheet.href='/knowledge/personal.css?v=1';document.head.append(sheet);
export function badge(value){return value?`<span class="kn-mastery ${value.status}">${STATUS[value.status]}${value.in_progress?' · 练习中':''}</span>`:'';}
export function block(value){return value?`<section class="kn-personal"><h3>我的节点状态 ${badge(value)}</h3><p>${value.attempt_id?`最近完成五题首答 ${value.correct_count}/5 · ${escape(new Date(value.completed_at).toLocaleDateString())}`:'尚未完成五题检测'}</p><small>依据节点小题首答。新一轮全部完成后重新评估，已掌握也可能变为待巩固。</small></section>`:'';}
export async function states(user){
 if(!user)return null;
 const r=await fetch('/api/learning/nodes',{credentials:'same-origin',cache:'no-store',headers:{'X-Learning-User':user.id},signal:AbortSignal.timeout(15000)});
 if(!r.ok)throw Error('节点状态暂时无法读取');
 return new Map((await r.json()).nodes.map(n=>[n.node_id,n]));
}
export function watch(refresh){
 window.addEventListener('learning-nodes-change',refresh);
 window.addEventListener('storage',e=>{if(e.key==='sss-learning-change')refresh();});
 window.addEventListener('focus',refresh);
}
export async function evidence(node,host,user){
 if(!user){host.replaceChildren();return;}
 const r=await fetch(`/api/learning/nodes/${encodeURIComponent(node)}/evidence`,{credentials:'same-origin',cache:'no-store',headers:{'X-Learning-User':user.id},signal:AbortSignal.timeout(15000)});
 if(window.SiteAuth?.user?.id!==user.id)return;
 if(!r.ok)throw Error('练习记录暂时无法读取');
 const rows=(await r.json()).evidence;
 host.innerHTML=`<details class="kn-personal"><summary>整题练习记录 · ${rows.length} 个步骤</summary><p>这里只记录学习过程，暂不用于节点掌握评估。</p>${rows.length?rows.map(row=>`<details><summary>${escape(row.label)} · ${escape(row.title)} · ${row.passed?'已完成':'进行中'}</summary><p>提交 ${row.submit_count} 次 · 错误 ${row.wrong_count} 次${row.hint_used?' · 使用过提示':''}</p><button type="button" data-record="${row.attempt_id}" data-step="${escape(row.step_id)}">查看原始记录</button><div class="kn-record"></div></details>`).join(''):'<p>暂无记录。</p>'}</details>`;
 host.onclick=async e=>{
  const button=e.target.closest('[data-record]');if(!button)return;
  button.disabled=true;
  try{
   const response=await fetch(`/api/learning/practice/${button.dataset.record}`,{credentials:'same-origin',cache:'no-store',headers:{'X-Learning-User':user.id},signal:AbortSignal.timeout(15000)});
   if(!response.ok)throw Error('记录暂时无法读取');
   const data=await response.json();if(window.SiteAuth?.user?.id!==user.id)return;
   const events=data.events.filter(item=>item.step_id===button.dataset.step),contexts=new Map(events.filter(e=>e.event_type==='context').map(e=>[e.id,e.payload]));
   const label=(answer,context)=>{
    if(!context)return JSON.stringify(answer);
    const c=context.interaction;
    if(c.type==='choice')return c.options.find(o=>o.value===answer.value)?.label||answer.value;
    return answer.terms.map((v,i)=>(c.slots?.[i]?.options||[]).find(o=>o.value===v)?.label||v).join('，');
   };
   button.nextElementSibling.innerHTML=events.map(event=>{
    const p=event.payload;
    const content=event.event_type==='context'?p.question:event.event_type==='answer'?`学生提交：${label(p,contexts.get(event.related_event_id))}`:event.event_type==='grade'?`判定：${{passed:'通过',wrong:'错误',incomplete:'信息不足'}[p.result]}`:`${p.role==='student'?'学生':'老师'}：${p.text}`;
    return `<p data-math-text>${escape(content)}</p>`;
   }).join('');
   button.nextElementSibling.querySelectorAll('[data-math-text]').forEach(el=>window.PracticeMath?.render(el,el.textContent));
  }catch(error){button.nextElementSibling.textContent=error.message;}finally{button.disabled=false;}
 };
}
