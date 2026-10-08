/* Five fixed questions per server attempt. Only first submissions affect mastery. */
import {escapeHtml as escape} from '/assets/explain/shared/html.js?v=1';
let dialog, run, source, selected=new Set(), busy=false, owner=null, pending=null, epoch=0;
const math=root=>root.querySelectorAll('[data-math-text]').forEach(el=>window.PracticeMath?.render(el,el.textContent));
async function api(path,body){
 const response=await fetch(`/api/learning${path}`,{method:body===undefined?'GET':'POST',credentials:'same-origin',cache:'no-store',headers:{'Content-Type':'application/json','X-Learning-User':owner},body:body===undefined?undefined:JSON.stringify(body),signal:AbortSignal.timeout(20000)});
 const result=await response.json();if(!response.ok)throw Error(result.detail||'暂时无法保存，请重试。');return result;
}
function shell(){
 if(dialog)return;
 dialog=document.createElement('dialog');dialog.className='kd-sheet';dialog.setAttribute('aria-label','节点五题检测');
 dialog.innerHTML='<div class="kd-inner"><header class="kd-head"><h2></h2><button class="kd-close" aria-label="关闭">×</button></header><div class="kd-bar"><span></span></div><div class="kd-body"></div><p class="kd-network" role="status"></p><button class="kd-secondary" data-retry hidden>重试保存</button></div>';
 document.body.append(dialog);
 dialog.addEventListener('click',e=>{
  if(e.target.closest('.kd-close')){dialog.close();return;}
  if(busy)return;
  if(e.target.closest('[data-retry]')){perform();return;}
  if(e.target.closest('[data-restart]')){pending={path:'/drills',body:{id:crypto.randomUUID(),node_id:source.node,previous_attempt_id:run.id}};perform();return;}
  if(e.target.closest('[data-next]')){run.showPosition=null;render();return;}
  if(pending)return;
  const opt=e.target.closest('.kd-option');const item=current();
  if(opt && !item.answered_at){
   const v=opt.dataset.value;if(item.question_type==='multi')selected.has(v)?selected.delete(v):selected.add(v);else selected=new Set([v]);
   dialog.querySelectorAll('.kd-option').forEach(b=>b.setAttribute('aria-checked',String(selected.has(b.dataset.value))));
   dialog.querySelector('[data-submit]').disabled=!selected.size;
  }
  if(e.target.closest('[data-submit]')){pending={path:`/drills/${run.id}/answers/${item.position}`,body:{selected:[...selected]},position:item.position};perform();}
 });
 window.addEventListener('site-auth-change',e=>{if(owner && e.detail.user?.id!==owner){epoch++;run=null;pending=null;owner=null;busy=false;dialog.close();}});
}
function current(){return run?.items.find(i=>i.position===run.showPosition)||run?.items.find(i=>!i.answered_at);}
function render(){
 const body=dialog.querySelector('.kd-body');dialog.querySelector('h2').textContent=source.label;
 const count=run.items.filter(i=>i.answered_at).length;dialog.querySelector('.kd-bar span').style.width=`${count/5*100}%`;
 const item=current();selected=new Set(item?.selected||[]);
 if(!item){
  const correct=run.items.filter(i=>i.is_correct).length;
  body.innerHTML=`<div class="kd-summary"><p class="kd-summary-title">本轮首答 ${correct} / 5</p><p>${correct===5?'已掌握':'待巩固'} · 依据本轮五题首答</p><ol>${run.items.map(i=>`<li data-math-text>${escape(i.statement_md)} · ${i.is_correct?'答对':'答错'}</li>`).join('')}</ol><p>下一轮完成后会重新评估，掌握状态可以变化。</p></div><button class="kd-submit" data-restart>再练五题</button>`;
 }else{
  body.innerHTML=`<p class="kd-progress">第 ${item.position} / 5 题${item.question_type==='multi'?' · 多选':''}</p><p class="kd-question" data-math-text>${escape(item.statement_md)}</p><div class="kd-options">${item.options.map(o=>`<button class="kd-option" role="${item.question_type==='multi'?'checkbox':'radio'}" aria-checked="${selected.has(o.value)}" data-value="${escape(o.value)}" ${item.answered_at?'disabled':''}><span class="kd-box"></span><span data-math-text>${escape(o.label)}</span></button>`).join('')}</div>${item.answered_at?`<div class="kd-feedback"><p>${item.is_correct?'首答正确':'首答已记录，本题需巩固。'}</p>${(item.feedback||[]).map(t=>`<p data-math-text>${escape(t)}</p>`).join('')}<p data-math-text>正确选择：${escape(item.options.filter(o=>item.answer.includes(o.value)).map(o=>o.label).join('；'))}</p></div><button class="kd-submit" data-next>${run.status==='completed'?'查看本轮结果':'下一题'}</button>`:'<button class="kd-submit" data-submit disabled>提交首答</button>'}`;
 }
 math(body);
}
async function perform(){
 if(!pending||busy)return;busy=true;const ticket=epoch,request=pending;
 dialog.querySelector('.kd-network').textContent='正在保存…';dialog.querySelector('[data-retry]').hidden=true;
 try{
  const next=await api(request.path,request.body);if(ticket!==epoch)return;
  run={...next,showPosition:request.position};pending=null;render();
  dialog.querySelector('.kd-network').textContent='已保存';
  window.dispatchEvent(new CustomEvent('learning-nodes-change'));
  try{localStorage.setItem('sss-learning-change',String(Date.now()));}catch{}
 }catch(error){if(ticket!==epoch)return;dialog.querySelector('.kd-network').textContent=error.message+'，原首答已保留，请重试。';dialog.querySelector('[data-retry]').hidden=false;}
 finally{if(ticket===epoch)busy=false;}
}
export async function openDrill(data){
 shell();await window.SiteAuth?.ready;
 const user=await window.SiteAuth?.requireLogin({title:'登录后开始五题检测',intro:'保存首答记录，并更新你的节点掌握状态。'});
 if(!user)return;
 owner=user.id;source=data;if(!dialog.open)dialog.showModal();
 if(run?.node_id===data.node){render();return;}
 pending={path:'/drills',body:{id:crypto.randomUUID(),node_id:data.node}};await perform();
}
