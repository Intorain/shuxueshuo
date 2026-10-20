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
const status=document.querySelector('#connection');
const read=async(url)=>{const r=await fetch(url);if(!r.ok&&r.status!==409)throw Error('读取失败');return r.json();};
const snapshot=await read('/snapshot');
function renderMath(root){
  for(const node of root.querySelectorAll('.stage-three-before,.stage-three-after,.stage-three-answer')){
    katex.render(node.textContent,node,{trust:false,throwOnError:false,output:'mathml'});
  }
  for(const node of root.querySelectorAll('h3,.stage-three-explanation')){
    const parts=node.textContent.split(/(\\$[^$]+\\$)/g);node.replaceChildren();
    for(const part of parts){if(part.startsWith('$')&&part.endsWith('$')){
      const span=document.createElement('span');katex.render(part.slice(1,-1),span,{trust:false,throwOnError:false,output:'mathml'});node.append(span);
    }else node.append(document.createTextNode(part));}
  }
}
const view=mountStageThreeStream(document.querySelector('#steps'),snapshot,{
 fetchEvents:async(seq)=>read('/events?after_seq='+seq),fetchSnapshot:()=>read('/snapshot'),pollInterval:150,renderMath,
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
                elif target.path == "/stage-three-stream.mjs":
                    value = (ROOT / "site/assets/graph-walk/stage-three-stream.mjs").read_text()
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
