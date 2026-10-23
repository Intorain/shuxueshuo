"""Read-only local preview of the authoritative committed event stream.

This development adapter deliberately does not start/restart solvers. The
product WebSocket adapter can consume the same event and snapshot APIs in 1c.
"""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .checkpoint import identity_from_seed
from .contracts import ROOT
from .events import CursorExpired, EventStore


def open_store(directory):
    directory = Path(directory)
    seed = json.loads((directory / "run.json").read_text())
    frozen = json.loads((directory / "frozen.json").read_text())
    identity = {**identity_from_seed(seed), "revisions": frozen["implementation"]}
    return EventStore(directory, identity)


PAGE = """<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>数学步骤实时预览</title>
<style>body{font:17px/1.6 system-ui;background:#f2f7f5;color:#203633;margin:0}main{max-width:900px;margin:24px auto;padding:16px}
article{background:white;border:1px solid #d8e2dd;border-radius:14px;padding:20px;margin:16px 0}small{color:#637770}
[hidden]{display:none!important}math{font-size:1.2em;max-width:100%;overflow-x:auto}p{overflow-wrap:anywhere}
</style><main><h1>数学步骤实时预览</h1><p>计算过程中逐步展示；最终答案须通过完整验证。</p>
<p id="connection">正在读取已提交步骤…</p><div id="steps"></div></main><script src="/katex.min.js"></script>
<script type="module">
import {mountStageThreeStream} from '/stage-three-stream.mjs';
import {createMathCard,attachMathQA,createRouteCompletion} from '/stream-math-dom.mjs';
const status=document.querySelector('#connection');
const host=document.querySelector('#steps'),cards=new Map(),completed=new Map(),routes=new Map();
const key=(target,route,step)=>JSON.stringify([target,route,step]);
const read=async(url)=>{const r=await fetch(url);if(!r.ok&&r.status!==409)throw Error('读取失败');return r.json();};
const snapshot=await read('/snapshot');
function renderMath(root){
  for(const node of root.querySelectorAll('[data-math-formula]:not([data-math-rendered])')){
    katex.render(node.textContent,node,{trust:false,throwOnError:false,output:'mathml'});node.dataset.mathRendered='true';
  }
  for(const node of root.querySelectorAll('[data-math-text]:not([data-math-rendered])')){
    const parts=node.textContent.split(/(\\$[^$]+\\$)/g);node.replaceChildren();
    for(const part of parts){if(part.startsWith('$')&&part.endsWith('$')){
      const span=document.createElement('span');katex.render(part.slice(1,-1),span,{trust:false,throwOnError:false,output:'mathml'});node.append(span);
    }else node.append(document.createTextNode(part));}node.dataset.mathRendered='true';
  }
}
function routeNode(target,route){
 const id=key(target,route);if(routes.has(id))return routes.get(id);
 const node=document.createElement('section');node.className='stage-three-route';
 node.dataset.targetRef=target;node.dataset.routeId=route;
 const title=document.createElement('h2');title.textContent=route;
 const info=document.createElement('p');info.className='stage-three-status';info.textContent='正在计算…';
 node.append(title,info);host.append(node);const value={node,info};routes.set(id,value);return value;
}
function addMath(step){
 const id=key(step.target_ref,step.route_id,step.step_id);if(cards.has(id))return;
 const card=createMathCard(document,step,{renderMath});cards.set(id,card);routeNode(step.target_ref,step.route_id).node.append(card.node);
}
function addQA(chunk){
 const card=cards.get(key(chunk.target_ref,chunk.route_id,chunk.step_id));if(card)attachMathQA(card,chunk,{renderMath});
}
function finish(target,route,payload){
 const id=key(target,route);if(completed.has(id)||payload.available===false)return;
 const card=createRouteCompletion(document,{...payload,target_ref:target},{renderMath});
 completed.set(id,{...card,target});const section=routeNode(target,route);
 section.node.append(card.node);section.info.textContent=card.statusText;
}
function routeStatus(target,route,payload){
 const labels={capability_gap:'详细步骤暂不支持',math_failed:'数学验证未通过',execution_error:'计算中断'};
 const section=routeNode(target,route);section.node.dataset.mathStatus=payload.status;
 if(labels[payload.status])section.info.textContent=labels[payload.status]+'；已完成步骤保留。';
}
function goalStatus(target,payload){
 if(!['conflict','no_verified_route','unavailable'].includes(payload.status)&&payload.available!==false)return;
 for(const section of routes.values())if(section.node.dataset.targetRef===target){
  section.node.dataset.available='false';section.info.textContent='此目标的完整解答暂不可用；已计算步骤保留供检查。';
 }
 for(const card of completed.values())if(card.target===target)card.node.hidden=true;
 for(const card of cards.values())if(card.step.target_ref===target)card.qa.hidden=true;
}
const view=mountStageThreeStream(snapshot,{
 fetchEvents:async(seq)=>read('/events?after_seq='+seq),fetchSnapshot:()=>read('/snapshot'),pollInterval:150,
 onMathStep:addMath,onQA:addQA,onRouteCompletion:finish,onGoalStatus:goalStatus,onRouteStatus:routeStatus,
 onEnrichmentStatus:(target,route,payload)=>{routeNode(target,route).node.dataset.enrichmentStatus=payload.status;},
 onSnapshot:state=>{
  for(const step of state.math_steps)addMath(step);
  for(const value of state.completions)finish(...value.identity,value);
  for(const chunk of state.qa)addQA(chunk);
  for(const [id,value]of state.route_statuses||[])routeStatus(...JSON.parse(id),value);
  for(const [id,value]of state.enrichment_statuses||[])routeNode(...JSON.parse(id)).node.dataset.enrichmentStatus=value.status;
  for(const [target,value]of Object.entries(state.goals))goalStatus(target,value);
 },
 onEvent:event=>{status.textContent='已同步到事件 '+event.seq;},onError:()=>{status.textContent='连接中断，正在重试…';}
});
view.consumer.hydrate(snapshot);view.start();status.textContent='已同步到事件 '+snapshot.last_seq;
window.stageThreePreview=view;
</script></html>"""


def make_server(directory, *, host="127.0.0.1", port=0):
    store = open_store(directory)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            target = urlsplit(self.path)
            content_type = "application/json; charset=utf-8"
            code = 200
            try:
                if target.path == "/snapshot":
                    value = store.snapshot()
                elif target.path == "/events":
                    cursor = int(parse_qs(target.query).get("after_seq", ["0"])[0])
                    events = store.events(cursor)
                    value = {"run_id": store.identity["run_id"], "events": events,
                             "last_seq": events[-1]["seq"] if events else cursor}
                elif target.path in {"/", "/index.html"}:
                    value, content_type = PAGE, "text/html; charset=utf-8"
                elif target.path in {"/stage-three-stream.mjs", "/stream-math-dom.mjs", "/original-choice.mjs"}:
                    value = (ROOT / "site/assets/graph-walk" / target.path[1:]).read_text()
                    content_type = "text/javascript; charset=utf-8"
                elif target.path == "/katex.min.js":
                    value = (ROOT / "site/assets/practice/vendor/katex-0.18.9/katex.min.js").read_text()
                    content_type = "text/javascript; charset=utf-8"
                else:
                    value, code = {"error": "not_found"}, 404
            except CursorExpired:
                value, code = {"error": "events.cursor_expired", "cursor_expired": True}, 409
            except ValueError:
                value, code = {"error": "invalid_cursor"}, 400
            raw = (value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)).encode()
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *_args):
            pass

    return ThreadingHTTPServer((host, port), Handler)


def serve(directory, *, port=8783):
    with make_server(directory, port=port) as server:
        print(f"数学步骤预览：http://127.0.0.1:{server.server_port}/", flush=True)
        server.serve_forever()
