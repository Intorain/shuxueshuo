"""Read-only, offline reports for successful, partial and failed stage-one runs.

This module neither evaluates candidates nor creates providers. Malformed JSON is
presented verbatim so a broken model response cannot break the debugging report.
"""

from __future__ import annotations

import base64
import json
import math
import os
import shutil
import statistics
from hashlib import sha256
from html import escape
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[4]
CORPUS = ROOT / "server/tests/solver/fixtures/graph-guided-stage-one/quadratic-always"
TITLE = "图谱课程 · 阶段①调试报告"
CSS = """
:root{color-scheme:light;--ink:#172c35;--muted:#64757c;--line:#dce6e7;--teal:#087f79}
*{box-sizing:border-box}body{margin:0;background:#f3f7f7;color:var(--ink);font:15px/1.65 system-ui,-apple-system,'PingFang SC',sans-serif}
main{max-width:1500px;margin:auto;padding:30px}h1{font-size:28px;margin:4px 0 12px}h2{font-size:19px;margin:0 0 14px}h3{font-size:16px}
header{padding:0 0 22px}.eyebrow{font-size:12px;letter-spacing:.12em;color:var(--teal)}a{color:#087772}a:hover{text-decoration:none}
section,.card{background:white;border:1px solid var(--line);border-radius:12px;padding:22px;margin-bottom:20px}details{margin:12px 0;border:1px solid var(--line);border-radius:8px;padding:10px 14px}
summary{cursor:pointer;font-weight:600}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f5f8f8;padding:14px;border-radius:8px;font:13px/1.65 ui-monospace,SFMono-Regular,monospace;max-height:600px;overflow:auto}
.grid{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:22px}.source{position:sticky;top:15px;align-self:start}.source img{width:100%;height:auto;border:1px solid var(--line)}.original{white-space:pre-wrap;overflow-wrap:anywhere;padding:14px;border:1px dashed #bdcfd0;border-radius:8px;min-height:70px}
.math-text{overflow-wrap:anywhere;font-size:17px}.katex{font-size:1.05em}.muted{color:var(--muted)}.badge{display:inline-block;padding:3px 10px;border-radius:20px;background:#e3f4ed;color:#23664c;font-size:12px}.bad{background:#fff0ed;color:#a23d29}.unknown{background:#fff8dc;color:#806500}
button{border:1px solid #a8cfcb;border-radius:7px;padding:8px 12px;background:#f0faf8;color:#086c66;cursor:pointer;text-align:left;font:inherit}button:hover,button:focus{background:#d9f1ed;outline:2px solid #91bfb7}mark{background:#ffdb7b;color:#172c35;border-radius:2px}.entry{border-bottom:1px solid var(--line);padding:12px 0}.entry:last-child{border:0}.entry pre{margin-bottom:0}
table{border-collapse:collapse;width:100%;background:white}th,td{text-align:left;padding:11px;border-bottom:1px solid var(--line);vertical-align:top}th{font-size:12px;color:var(--muted)}.table-wrap{overflow:auto}.metrics{display:flex;gap:12px;flex-wrap:wrap;margin:18px 0}.metric{background:white;border:1px solid var(--line);border-radius:9px;padding:12px 20px}.metric b{display:block;font-size:24px}.small{font-size:12px}.error{color:#a23d29}.anchor-note{font-size:12px;color:var(--muted)}.raw{max-height:340px}.two{display:grid;grid-template-columns:1fr 1fr;gap:14px}.missing{padding:16px;border:1px dashed #c8d4d5;color:var(--muted)}code{overflow-wrap:anywhere}.call{scroll-margin-top:20px}
@media(max-width:850px){main{padding:16px}.grid,.two{grid-template-columns:1fr}.source{position:static}h1{font-size:23px}section,.card{padding:16px}}
"""
JS = r"""
(() => {
 if(typeof katex!=='undefined') document.querySelectorAll('.math-text').forEach(node=>{
   const value=node.textContent;node.replaceChildren();
   value.split(/(\$[^$]+\$)/g).filter(Boolean).forEach(part=>{
     const span=document.createElement('span');
     if(part.startsWith('$')){try{katex.render(part.slice(1,-1),span,{throwOnError:false,strict:false})}catch{span.textContent=part;}}
     else span.textContent=part;
     node.append(span);
   });
 });
})();
"""


def _read(path: Path):
    """Return parsed data, raw text and diagnostics without raising on bad input."""
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return None, "", f"未产出或无法读取：{exc}"
    try:
        return json.loads(raw), raw, None
    except (ValueError, RecursionError) as exc:
        return None, raw, f"无效 JSON：{exc}"


def _pretty(value):
    return escape(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def _pre(value):
    return "<pre>" + _pretty(value) + "</pre>"


def _file(path, label=None, *, opened=False):
    _data, raw, error = _read(path)
    heading = escape(label or path.name)
    contents = (f'<p class="error">{escape(error)}</p>' if error else "")
    contents += '<pre class="raw">' + escape(raw) + "</pre>" if raw else '<p class="missing">未产出</p>'
    return f'<details{" open" if opened else ""}><summary>{heading}</summary>{contents}</details>'


def _dict(path):
    value = _read(path)[0]
    return value if isinstance(value, dict) else {}


def _first(directory, names):
    return next((directory / name for name in names if (directory / name).is_file()), directory / names[0])


def _path_link(path, output, label):
    relative = quote(os.path.relpath(path, output), safe="/")
    return f'<a href="{escape(relative, quote=True)}">{escape(label)}</a>'


def _badge(passed, status):
    cls = "" if passed is True else " bad" if passed is False else " unknown"
    return f'<span class="badge{cls}">{escape(str(status))}</span>'


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _seconds(row, sample):
    for value in (row.get("elapsed_seconds"), row.get("total_seconds"), _dict(sample / "summary.json").get("elapsed_seconds")):
        if _number(value):
            return value
    return None


def _safe_child(parent: Path, raw, fallback: str) -> Path:
    """Do not follow arbitrary paths from a corrupted ledger or summary."""
    path = (parent / str(raw or fallback)).resolve()
    if not path.is_relative_to(parent.resolve()):
        return parent / fallback
    return path


def _calls(sample):
    workflow = sample / "workflow"
    ledger = _dict(workflow / "ledger.json")
    rows = ledger.get("calls", [])
    rows = [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
    known = {str(row.get("directory", "")) for row in rows}
    if (workflow / "calls").is_dir():
        for folder in sorted((workflow / "calls").iterdir()):
            if folder.is_dir() and str(folder.relative_to(workflow)) not in known:
                rows.append({"directory": str(folder.relative_to(workflow)), "stage": "账本未登记的调用材料", "status": "unknown"})
    sections = []
    for index, call in enumerate(rows, 1):
        folder = _safe_child(workflow, call.get("directory"), f"calls/{index:02}-unknown")
        number, stage = call.get("number", index), str(call.get("stage", "unknown"))
        duration = call.get("elapsed_seconds")
        timing = f" · {duration:.3f}s" if _number(duration) else " · 耗时未记录"
        title = f"调用 {number} · {stage} · {call.get('status', 'unknown')}{timing}"
        body = _pre(call)
        request = folder / "request.json"
        body += _file(request, "完整脱敏请求", opened=False)
        response = _safe_child(workflow, call.get("response_file"), str((folder / "response.json").relative_to(workflow)))
        body += _file(response, "原始响应（含未解析文本）", opened=call.get("status") == "failed")
        saved = _dict(response)
        if isinstance(saved.get("text"), str):
            body += '<h4>模型输出原文</h4><pre>' + escape(saved["text"]) + "</pre>"
        if folder.is_dir():
            for path in sorted(folder.rglob("*")):
                if path.is_file() and path not in {request, response} and path.suffix in {".json", ".txt", ".log", ".md"}:
                    body += _file(path, str(path.relative_to(folder)))
        sections.append(f'<details class="call" id="call-{index}"><summary>{escape(title)}</summary>{body}</details>')
    return '<section><h2>调用过程与失败材料</h2>' + ("".join(sections) or '<p class="missing">暂无调用记录；本页不发起网络请求。</p>') + _file(workflow / "ledger.json", "完整账本") + _file(workflow / "workflow-result.json", "工作流终态、修改与采用事件") + "</section>"


def _gold(sample, actual, gold_name, label):
    expected = _first(sample, [f"fixture/{gold_name}", f"input/{gold_name}", f"input-fixture/{gold_name}", gold_name])
    return f'<h3>{escape(label)}</h3><div class="two"><div>{_file(expected, "人工预期", opened=True)}</div><div>{_file(sample / actual, "实际产物", opened=True)}</div></div>'


def _assets(output):
    target = output / "_assets/katex"
    source = ROOT / "site/assets/practice/vendor/katex-0.18.9"
    if source.is_dir():
        shutil.copytree(source, target, dirs_exist_ok=True)
        return True
    return False


def _document(title, body, katex):
    assets = '<link rel="stylesheet" href="_assets/katex/katex.min.css"><script defer src="_assets/katex/katex.min.js"></script>' if katex else ""
    return '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>' + escape(title) + '</title><style>' + CSS + '</style>' + assets + '</head><body><main>' + body + '</main><script>window.addEventListener("DOMContentLoaded",()=>{' + JS + '});</script></body></html>'


def _scopes(scope, path="/root"):
    yield path, scope
    children = scope.get("children", [])
    for index, child in enumerate(children if isinstance(children, list) else []):
        if isinstance(child, dict):
            yield from _scopes(child, f"{path}/children/{index}")


def _sample_page(sample, row, katex):
    candidate_path = _first(sample, ["candidate.json", "candidates/final.json"])
    candidate = _dict(candidate_path)
    original = candidate.get("original_text", "")
    original = original if isinstance(original, str) else ""
    features = _dict(sample / "features.json").get("features", [])
    features = [feature for feature in features if isinstance(feature, dict)] if isinstance(features, list) else []
    title = str(row.get("case_id", sample.parent.name)) + " / " + str(row.get("sample_id", sample.name))
    source = _first(sample, ["input/source.png", "input-fixture/source.png", "source.png", "fixture/source.png"])
    if not source.is_file():
        frozen = _dict(sample / "frozen.json")
        reference = (ROOT / str(frozen.get("source_reference", ""))).resolve()
        if (reference.is_relative_to(CORPUS) and reference.is_file()
                and sha256(reference.read_bytes()).hexdigest() == frozen.get("fixture_hashes", {}).get("source.png")):
            source = reference
    image = '<p class="missing">未找到本次实际题图</p>'
    if source.is_file():
        image = '<img alt="本次输入的原题图片" src="data:image/png;base64,' + base64.b64encode(source.read_bytes()).decode() + '">'
    source_manifest = _first(sample, ["fixture/source-manifest.json", "input/source-manifest.json", "input-fixture/source-manifest.json", "source-manifest.json"])
    source_kind = _dict(source_manifest).get("source_kind", "来源类型未记录")
    mode = row.get("mode", "offline_replay" if row.get("historical_live") else "已保存运行")
    mode_text = "当前离线重评 · 新网络调用 0 次；历史 live 结果单独保存" if mode == "offline_replay" else str(mode)
    body = '<header><a href="index.html">← 批次汇总</a><div class="eyebrow">只读 · 离线调试</div><h1>' + escape(title) + '</h1>' + _badge(row.get("passed"), row.get("status", "unknown")) + '<p class="muted">题图来源：' + escape(str(source_kind)) + ' · ' + escape(mode_text) + '</p></header>'
    if row.get("historical_live"):
        body += '<section><h2>历史 live 结论（保持原样）</h2>' + _pre(row["historical_live"]) + '</section>'
    left = '<div class="source card"><h2>题源与转录</h2>' + image + '<h3>模型转录（公式预览）</h3><div class="math-text">' + escape(original or "未产出题文") + '</div><h3>转录原文</h3><div class="original">' + escape(original or "未产出题文") + '</div></div>'
    right = '<div><section><h2>题意</h2>'
    root = candidate.get("root", {})
    for path, scope in _scopes(root if isinstance(root, dict) else {}):
        if path != "/root":
            right += '<h3>' + escape(str(scope.get("label", path))) + ' <code>' + escape(path) + '</code></h3>'
        for field in ("definitions", "facts", "goals"):
            values = scope.get(field, [])
            if isinstance(values, list):
                for index, value in enumerate(values):
                    right += '<div class="entry"><code>' + escape(f"{path}/{field}/{index}") + '</code>' + _pre(value) + '</div>'
    right += _file(candidate_path, "完整候选（无法解析时保留原文）", opened=not candidate) + '</section><section><h2>数学特征与计算链</h2>'
    if not features:
        right += '<p class="missing">特征尚未产出</p>'
    target = None
    for feature in features:
        if feature.get("target_ref") != target:
            target = feature.get("target_ref")
            right += '<h3>目标 <code>' + escape(str(target)) + '</code></h3>'
        name = str(feature.get("feature_id", "unknown"))
        right += '<div class="entry"><b>' + escape(name) + '</b> ' + _badge(True if feature.get("status") == "known" else None, feature.get("status", "unknown")) + _pre(feature.get("value")) + '<details><summary>输入、计算依据、依赖及 unknown 诊断</summary>' + _pre(feature) + '</details></div>'
    right += _file(_first(sample, ["feature-trace.json", "features.json"]), "完整特征计算链") + '</section></div>'
    body += '<div class="grid">' + left + right + '</div><section><h2>验证与独立金标差异</h2>'
    body += _file(sample / "validation.json", "记法与作用域校验", opened=True)
    body += _file(sample / "evaluation.json", "独立验收（题文／语义／特征）", opened=True)
    for filename, gold, label in (("candidate.json", "notation.gold.json", "题意语义"), ("features.json", "features.gold.json", "结构特征")):
        body += _gold(sample, filename, gold, label)
    for name in ("preflight.json", "failure.json", "first-evaluation.json", "semantic-diff.json", "features-diff.json", "stage-one-result.json", "summary.json", "frozen.json", "replay-frozen.json"):
        if (sample / name).exists():
            body += _file(sample / name)
    body += '</section>' + _calls(sample)
    commands = (
        f"uv run python -m shuxueshuo_server.graph_lesson.stage_one.cli run --case {row.get('case_id', sample.parent.name)} --samples 1 --output <new-run-directory>\n"
        f"uv run python -m shuxueshuo_server.graph_lesson.stage_one.cli replay --batch {sample.parents[1]} --case {row.get('case_id', sample.parent.name)} --output <new-replay-directory>"
    )
    body += '<section><h2>版本与复现</h2><p class="small">命令从 server/ 运行；真实调用需显式设置 RUN_LLM_INTEGRATION=1。请使用新目录，保留当前失败记录。</p><pre>' + escape(commands) + '</pre>' + _file(source_manifest, "输入来源与哈希") + '<p class="small">本页只展示已保存材料，不重算、不改写历史结果。</p></section>'
    return _document(title, body, katex)


STATE_FILE = "sample-state.json"
TERMINAL_PHASES = ("summarized", "failed")


def sample_state(sample: Path) -> str:
    """Persisted phase: reserved, frozen, workflow_finished, summarized or failed."""
    phase = _dict(sample / STATE_FILE).get("phase")
    if isinstance(phase, str):
        return phase
    # Recordings made before explicit state files.
    if all((sample / name).is_file() for name in ("workflow/workflow-result.json", "summary.json", "frozen.json")):
        return "summarized"
    if (sample / "failure.json").is_file():
        return "failed"
    if (sample / "workflow/workflow-result.json").is_file():
        return "workflow_finished"
    return "interrupted"


def sample_number(sample: Path):
    number = sample.name.removeprefix("sample-")
    return int(number) if number.isdigit() else sample.name


def batch_rows(batch: Path, summary: dict) -> list[dict]:
    """Summary rows plus sample directories the summary never recorded.

    An interrupted batch keeps requests and responses of unfinished samples on
    disk; they are listed with ``incomplete`` so they are never read as passed.
    """
    rows = summary.get("results", [])
    if isinstance(rows, dict):
        rows = [dict(value, case_id=key) for key, value in rows.items() if isinstance(value, dict)]
    rows = [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
    recorded = {row.get("sample_dir") for row in rows}
    # Direct CLI batches and pytest's per-case batches have different depths.
    samples = set(batch.glob("q*/sample-*")) | set(batch.glob("q*/q*/sample-*"))
    for sample in sorted(samples):
        relative = str(sample.relative_to(batch))
        if not sample.is_dir() or relative in recorded:
            continue
        phase = sample_state(sample)
        finished = phase in TERMINAL_PHASES
        saved = (_dict(sample / "summary.json") or _dict(sample / "failure.json")) if finished else {}
        rows.append({**saved, "case_id": saved.get("case_id", sample.parent.name),
                     "sample_id": saved.get("sample_id", sample_number(sample)),
                     "sample_dir": relative, "incomplete": not finished, "phase": phase,
                     "status": saved.get("status", f"未完成：样本中断（{phase}）"),
                     "passed": saved.get("passed") is True and phase == "summarized"})
    return rows


def render_batch(batch: Path, output: Path) -> Path:
    """Render an immutable batch view and return its offline index.html path."""
    batch, output = Path(batch).resolve(), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    katex = _assets(output)
    summary = _dict(batch / "batch-summary.json")
    rows = batch_rows(batch, summary)
    table, durations = [], []
    for index, row in enumerate(rows, 1):
        sample = _safe_child(batch, row.get("sample_dir"), f"{row.get('case_id', 'unknown')}/{row.get('sample_id', 'sample-01')}")
        filename = f"sample-{index:03d}.html"
        (output / filename).write_text(_sample_page(sample, row, katex), encoding="utf-8")
        seconds = _seconds(row, sample)
        if seconds is not None:
            durations.append(seconds)
        first = row.get("first_passed")
        first_label = "通过" if first is True else "未通过" if first is False else "未记录"
        table.append('<tr><td><a href="' + filename + '">' + escape(str(row.get("case_id", "unknown"))) + '</a></td><td>' + escape(str(row.get("sample_id", sample.name))) + '</td><td>' + escape(first_label) + '</td><td>' + _badge(row.get("passed"), row.get("status", "unknown")) + '</td><td>' + (f"{seconds:.3f}s" if seconds is not None else "未记录") + '</td><td>' + escape(str(row.get("repair_calls", row.get("repairs", "未记录")))) + '</td></tr>')
    passed = sum(row.get("passed") is True for row in rows)
    p50 = f"{statistics.median(durations):.3f}s" if durations else "未记录"
    maximum = f"{max(durations):.3f}s" if durations else "未记录"
    requested = summary.get("requested_cases", _dict(batch / "batch-manifest.json").get("requested_cases"))
    expected = (len(set(requested)) if isinstance(requested, list) and requested
                and all(isinstance(case, str) for case in requested) else "未记录")
    metrics = [("样本通过", f"{passed} / {len(rows)}"), ("题目覆盖", f"{len({row.get('case_id') for row in rows})} / {expected}"), ("阶段① P50", p50), ("阶段①最大耗时", maximum)]
    body = '<header><div class="eyebrow">GRAPH LESSON · STAGE 01</div><h1>' + TITLE + '</h1><p class="muted">题图 → 题意 → 数学特征。点击每个样本检查实际输入、独立金标差异与全部调用材料。</p><p>来源：synthetic-rendered 合成题图；本页展示已保存结果，不代表真实扫描识图验收。</p></header>'
    if summary.get("mode") == "offline_replay":
        body += '<section><h2>当前离线重评</h2><p>新网络调用 0 次。下表为当前代码重评结果；各样本页单独保留历史 live 结论，未修改历史批次。</p></section>'
    if "complete" in summary:
        purpose = "正式验收批次" if summary.get("purpose") == "formal_acceptance" else "局部调试批次"
        completeness = "样本完整" if summary["complete"] else "尚未完成全部请求样本"
        body += '<p>' + purpose + ' · ' + completeness + ' · 预计样本 ' + escape(str(summary.get("expected_samples"))) + ' · 人工核对待完成</p>'
    body += '<div class="metrics">' + ''.join('<div class="metric"><span>' + escape(label) + '</span><b>' + escape(value) + '</b></div>' for label, value in metrics) + '</div>'
    body += '<p class="small muted">耗时统计仅包含已记录总耗时的样本：' + str(len(durations)) + ' / ' + str(len(rows)) + '；缺失耗时不按零计。</p>'
    body += '<section><div class="table-wrap"><table><thead><tr><th>题目</th><th>样本</th><th>首轮</th><th>最终状态</th><th>总耗时</th><th>修复调用</th></tr></thead><tbody>' + ''.join(table) + '</tbody></table></div></section>'
    body += _file(batch / "batch-summary.json", "完整批次汇总", opened=not rows) + _file(batch / "batch-manifest.json", "冻结批次清单")
    body += '<p class="small muted">输入目录：' + escape(str(batch)) + ' · 离线报告只读。' + _path_link(batch / "batch-summary.json", output, "原始汇总文件") + '</p>'
    index = output / "index.html"
    index.write_text(_document(TITLE, body, katex), encoding="utf-8")
    return index
