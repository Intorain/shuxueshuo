"""Exercise the recording queue as a JS unit, without a browser or network."""

import subprocess
from pathlib import Path


def test_recorder_error_recovery_and_route_choices():
    suite = (
        Path(__file__).resolve().parents[3] / "tools/tests/practice-records.test.mjs"
    )
    result = subprocess.run(
        ["node", "--test", str(suite)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_pending_queue_retries_and_restores_without_double_submission():
    script = r"""
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const code=fs.readFileSync(process.argv[1],'utf8').replace('export function','function');
const store=new Map(),posted=[],listeners={};let fail=true,serial=0;
const user={id:'student'},el=()=>({textContent:'',hidden:false,onclick:null});
const span=el(),button=el();
const scope={console,URL,AbortSignal,Error,JSON,Set,Map,crypto:{randomUUID:()=>`uuid-${++serial}`},
 window:{SiteAuth:{user},PracticeContext:{slotCount:()=>2},addEventListener:(name,fn)=>listeners[name]=fn},
 document:{createElement:()=>({setAttribute(){},querySelector:s=>s==='span'?span:button}),querySelector:()=>({append(){}})},
 sessionStorage:{setItem:(k,v)=>store.set(k,v),getItem:k=>store.get(k)},
 fetch:async(url,options)=>{const body=options.body&&JSON.parse(options.body);posted.push({url,body});
   if(url.endsWith('/practice'))return{ok:true,json:async()=>({id:body.id,route_id:body.route_id,steps:[]})};
   if(fail)throw Error('offline');
   return{ok:true,json:async()=>({saved:true})};},
};
vm.createContext(scope);vm.runInContext(code,scope);
const lesson={id:'basic-inequality-q01',routes:{direct:[{id:'structure',interaction:{type:'structure'}}]}};
const before={state:{method:'direct',active:0,pairs:[['m','n']],swapped:false}};
const recorder=scope.createRecorder(lesson);
recorder.action({state:{method:null}}, {event_id:'method-id',action:{kind:'method'}},before);
recorder.action(before,{event_id:'answer-id',action:{kind:'submit'}},before);
(async()=>{
 try{await recorder.flush();}catch{}
 assert.equal(JSON.parse(store.values().next().value).queue[0].id,'answer-id');
 assert.equal(button.hidden,false);
 fail=false;await recorder.flush();
 const answers=posted.filter(p=>p.url.endsWith('/answers'));
 assert.equal(answers.length,2);assert.deepEqual(answers[0],answers[1]);
 assert.deepEqual(answers[1].body.answer,{terms:['m','n'],fixed:'sum'});
 assert.equal(JSON.parse(store.values().next().value).queue.length,0);
 assert.equal(button.hidden,true);
 listeners['site-auth-change']({detail:{user:{id:'other'}}});
 assert.equal((await recorder.dialogue({state:{method:null}})).practice_attempt_id,undefined);
})().catch(e=>{console.error(e);process.exitCode=1;});
"""
    path = (
        Path(__file__).resolve().parents[3] / "site/assets/learning/practice-records.js"
    )
    result = subprocess.run(
        ["node", "-e", script, str(path)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


def test_refresh_replays_pending_before_resume_and_drops_old_account_reply():
    script = r"""
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const code=fs.readFileSync(process.argv[1],'utf8').replace('export function','function');
async function scenario(changeAccount){
 const events=[],listeners={},el={textContent:'',hidden:false};let release,confirmed=false;
 const stored=JSON.stringify({aid:'old-attempt',route:'direct',queue:[{kind:'answer',id:'stable-answer',step:'structure',answer:{terms:['m','n'],fixed:'sum'}}]});
 const scope={console,URL,AbortSignal,Error,JSON,crypto:{randomUUID:()=> 'new-id'},
  window:{SiteAuth:{user:{id:'first'}},addEventListener:(n,f)=>listeners[n]=f},
  document:{createElement:()=>({setAttribute(){},querySelector:()=>el}),querySelector:()=>({append(){}})},
  sessionStorage:{getItem:()=>stored,setItem(){}},
  fetch:async(url,options)=>{
   if(url.endsWith('/answers')){assert.equal(JSON.parse(options.body).id,'stable-answer');confirmed=true;return{ok:true,json:async()=>({})};}
   assert(confirmed);await new Promise(resolve=>release=resolve);
   return{ok:true,json:async()=>({id:'old-attempt',route_id:'direct',status:'in_progress',active_step:'amgm'})};
  }
 };
 vm.createContext(scope);vm.runInContext(code,scope);
 scope.createRecorder({id:'basic-inequality-q01'},history=>events.push(history));
 while(!release)await new Promise(resolve=>setImmediate(resolve));
 if(changeAccount)listeners['site-auth-change']({detail:{user:{id:'second'}}});
 release();await new Promise(resolve=>setImmediate(resolve));
 assert.equal(events.length,changeAccount?0:1);
 if(!changeAccount)assert.equal(events[0].active_step,'amgm');
}
(async()=>{await scenario(false);await scenario(true);})().catch(e=>{console.error(e);process.exitCode=1;});
"""
    path = (
        Path(__file__).resolve().parents[3] / "site/assets/learning/practice-records.js"
    )
    result = subprocess.run(
        ["node", "-e", script, str(path)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
