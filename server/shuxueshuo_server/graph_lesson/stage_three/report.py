"""Self-contained, escaped reports for inspecting method choices without a server."""

import base64
import json
from html import escape
from pathlib import Path
from urllib.parse import quote

from ..stage_one.report import CSS
from ..stage_two.contracts import ROOT

LABELS = {
    "completed": "选法评估完成", "input_error": "输入未通过校验", "partial": "部分失败", "failed": "失败",
    "no_verified_route": "暂无已验证解法", "unsupported_type": "题型暂无选法契约", "skipped": "跳过未确认目标",
    "no_applicable_method": "暂无可用方法", "triggered": "触发", "not_triggered": "未触发", "unknown": "未知",
    "applicable": "适用", "not_applicable": "不适用", "preferred": "优先", "optional": "可选",
    "superseded": "不优先", "capability_gap": "详细步骤暂不支持", "not_planned": "不生成路线",
    "execution_error": "目标处理异常",
}
METHODS = {"discriminant": "判别式法", "interval": "区间最值法", "separation": "分离参数法", "swap": "更换主元法"}


def _read(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return None


def _json(value):
    return "<pre>" + escape(json.dumps(value, ensure_ascii=False, indent=2)) + "</pre>"


def _details(label, value):
    return "<details><summary>" + escape(label) + "</summary>" + _json(value) + "</details>"


def _label(value):
    return escape(LABELS.get(value, str(value)) if value is not None else "—")


def _page(title, body):
    extra = (".columns{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:20px}"
             "table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:10px;border:1px solid #dbe4e2}"
             "td.current{background:#e0f4e9}pre{overflow-wrap:anywhere;white-space:pre-wrap}"
             ".original{white-space:pre-wrap}code{overflow-wrap:anywhere}")
    return ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1"><title>' + escape(title)
            + '</title><style>' + CSS + extra + '</style></head><body><main>' + body + '</main></body></html>')


def _plane(d3):
    if not d3:
        return '<p>本目标没有学生 D3 片段。</p>'
    interaction = d3["interaction"]
    xs, ys = interaction["x"]["options"], interaction["y"]["options"]
    cell = d3["expected_answer"]["cell"]
    body = '<p>本目标格子：<code>' + escape(", ".join(cell)) + '</code></p><table><thead><tr><th>'
    body += escape(interaction["y"]["label"] + " / " + interaction["x"]["label"]) + '</th>'
    body += ''.join('<th>' + escape(x["label"] + " · " + x["value"]) + '</th>' for x in xs)
    body += '</tr></thead><tbody>'
    for y in ys:
        body += '<tr><th>' + escape(y["label"] + " · " + y["value"]) + '</th>'
        for x in xs:
            current = [x["value"], y["value"]]
            methods = [METHODS.get(branch, branch) for branch, cells in interaction["coverage"].items()
                       if current in cells]
            body += ('<td class="current">' if current == cell else '<td>')
            body += escape("、".join(methods) or "无可选方法") + '</td>'
        body += '</tr>'
    return body + '</tbody></table><p class="muted">高亮格为本目标；其他格只展示方法的典型用途。</p>'


def _verdicts(d3):
    if not d3:
        return ""
    return "".join('<p><strong>' + escape(METHODS.get(key, key)) + '</strong> · '
                   + escape(item["value"]) + '<br>' + escape(item["message"]) + '</p>'
                   for key, item in d3["verdicts"].items())


def render_result(directory):
    directory = Path(directory)
    result = _read(directory / "stage-three-result.json")
    if not isinstance(result, dict):
        raise TypeError("缺少有效的阶段③结果，不能重建报告。")
    stage_one = _read(directory / "stage-one-input.json")
    stage_one = stage_one if isinstance(stage_one, dict) else {}
    candidate = stage_one.get("candidate") or {}
    candidate = candidate if isinstance(candidate, dict) else {}
    demo_source = _read(ROOT / "site/data/graph-walk/quadratic-always-q01.source.json") or {}
    demo = next((row for row in demo_source.get("intro", []) if row.get("id") == "D3"), None)
    title = "图谱课程 · 阶段③调试报告"
    body = '<header><div class="eyebrow">批次 1a · 入口与选法</div><h1>' + title + '</h1><p>'
    body += _label(result["status"]) + ' · <code>' + escape(result["run_id"]) + '</code></p>'
    body += '<p>本批生成选法与 D3/D4；尚未执行数学路线，不生成答案、求解事件或问答。</p></header>'
    body += '<section><h2>题图与原文</h2>'
    if (directory / "source.png").is_file():
        image = base64.b64encode((directory / "source.png").read_bytes()).decode()
        body += '<img style="max-width:100%;max-height:420px" alt="原题图" src="data:image/png;base64,' + image + '">'
    body += '<div class="original">' + escape(str(candidate.get("original_text", ""))) + '</div></section>'
    body += '<section><h2>输入准入与出处</h2>' + _json(result["input_validation"])
    body += _details("输入引用与哈希", _read(directory / "input.json"))
    body += _details("阶段①准入状态", stage_one.get("statuses"))
    body += _details("阶段③本次调用数（恒为零）", result["llm"])
    body += _details("上游阶段②调用计数（与本阶段分开）", result.get("upstream_llm")) + '</section>'
    for number, goal in enumerate(result["goals"], 1):
        body += '<section id="goal-' + str(number) + '"><h2>' + escape(goal["label"] or f"目标 {number}") + '</h2>'
        body += '<p>' + _label(goal["status"]) + ' · <code>' + escape(goal["target_ref"]) + '</code></p>'
        body += '<p>主要归属：' + escape(str(goal["primary"])) + ' · 来源：' + escape(str(goal["primary_source"])) + '</p>'
        body += _details("原始目标", goal["goal"]) + _details("诊断", goal["diagnostics"])
        body += '<h3>完整可见题设与来源</h3>' + _json(goal["constraint_context"])
        body += _details("阶段①原始特征（本阶段不重新提取）", goal["features"])
        selection = goal.get("selection") or {}
        body += '<h3>分支四项结论与前提证据</h3><table><thead><tr>'
        body += '<th>方法</th><th>触发</th><th>适用性</th><th>推荐</th><th>路线计划</th></tr></thead><tbody>'
        for branch in selection.get("branches", []):
            body += '<tr><th>' + escape(METHODS.get(branch["branch"], branch["branch"])) + '</th>'
            body += ''.join('<td>' + _label(branch[key]) + '</td>'
                            for key in ("trigger", "applicability", "recommendation", "route_plan")) + '</tr>'
        body += '</tbody></table>'
        for branch in selection.get("branches", []):
            body += _details(METHODS.get(branch["branch"], branch["branch"]) + " · 检查与绑定", branch)
        body += _details("推荐规则", selection.get("recommendation_rule"))
        body += '<h3>D3 · 方法坐标图</h3>' + _plane(goal.get("d3"))
        body += '<div class="columns"><div><h4>本题判断说明</h4>' + _verdicts(goal.get("d3")) + '</div>'
        body += '<details><summary>Q01 Demo 原稿参考（不参与本题计算）</summary>' + _verdicts(demo) + '</details></div>'
        body += _details("D3 原始片段", goal.get("d3"))
        body += '<h3>D4 · 方法路线</h3>' + _json(goal.get("d4"))
        body += _details("数学路线状态", goal["routes"]) + '</section>'
    body += '<section><h2>完整产物</h2><p>'
    links = [("stage-three-result.json", "阶段③结果"), ("input.json", "输入引用"),
             ("stage-two-input.json", "阶段②快照"), ("stage-one-input.json", "阶段①快照"), ("frozen.json", "实现版本")]
    body += ' · '.join('<a href="' + name + '">' + label + '</a>' for name, label in links) + '</p></section>'
    path = directory / "index.html"
    path.write_text(_page(title, body), encoding="utf-8")
    return path


def render_batch(directory):
    directory = Path(directory)
    summary = _read(directory / "batch-summary.json")
    if not isinstance(summary, dict):
        raise TypeError("缺少有效批次汇总。")
    title = "阶段③ · 录制批次选法验收"
    body = '<header><h1>' + title + '</h1><p>阶段①真实录制重验 → 阶段②离线判型 → 阶段③选法。</p>'
    body += '<p>' + ("批次完成" if summary["completed"] else "批次未通过") + '</p></header>'
    body += '<section><h2>本阶段调用计数</h2>' + _json(summary["llm"]) + '</section>'
    body += '<section><h2>逐题调试</h2><table><thead><tr><th>样本</th><th>状态</th><th>已确认目标</th>'
    body += '<th>跳过</th></tr></thead><tbody>'
    for row in summary["results"]:
        relative = Path(row["sample_dir"]) / "index.html"
        resolved = (directory / relative).resolve()
        if not resolved.is_relative_to(directory.resolve()) or not resolved.is_file():
            raise ValueError("批次报告只链接本输出目录内的有效报告。")
        body += '<tr><td><a href="' + quote(relative.as_posix(), safe="/") + '">'
        body += escape(f"{row['case_id']} / {row['sample_id']}") + '</a></td>'
        body += '<td>' + _label(row["status"]) + '</td><td>' + str(row["eligible"]) + '</td><td>'
        body += str(row["skipped"]) + '</td></tr>'
    body += '</tbody></table></section><p><a href="batch-summary.json">批次结果 JSON</a> · '
    body += '<a href="stage-two/index.html">本次阶段②报告与阶段①重验材料</a></p>'
    for relative, label in (("selection-replay/stage-three/index.html", "Q01 · 历史 LLM 判型准入"),
                            ("student-upload/stage-three/index.html", "Q13 · 真实学生上传准入")):
        if (directory / relative).is_file():
            body += '<p><a href="' + relative + '">' + label + '</a>（单列证据，不计入 22 份样本）</p>'
    path = directory / "index.html"
    path.write_text(_page(title, body), encoding="utf-8")
    return path
