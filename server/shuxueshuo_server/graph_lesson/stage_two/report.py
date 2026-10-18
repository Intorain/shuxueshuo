"""Portable, read-only HTML reports; all content is escaped and no provider is loaded."""

import base64
import json
from html import escape
from pathlib import Path
from urllib.parse import quote

from ..stage_one.report import CSS

LABELS = {
    "completed": "流程完成", "partial": "部分完成", "failed": "判型失败",
    "input_error": "输入未通过校验", "resolved": "已确认题型", "unsupported": "暂不支持",
    "selection_failed": "LLM 选择失败", "supported": "支持", "conflict": "冲突", "unknown": "未知",
}


def _read(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _json(value):
    return "<pre>" + escape(json.dumps(value, ensure_ascii=False, indent=2)) + "</pre>"


def _details(label, value):
    return "<details><summary>" + escape(label) + "</summary>" + _json(value) + "</details>"


def _badge(status):
    style = "" if status in {"completed", "resolved", "supported"} else " unknown" if status in {"unknown", "unsupported"} else " bad"
    return f'<span class="badge{style}">{escape(LABELS.get(status, status))}</span>'


def _page(title, body):
    return ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1"><title>'
            + escape(title) + '</title><style>' + CSS + '</style></head><body><main>'
            + body + '</main></body></html>')


def _highlight(original, fragment):
    start, end = fragment.get("start"), fragment.get("end")
    if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(original):
        return escape(original)
    return escape(original[:start]) + "<mark>" + escape(original[start:end]) + "</mark>" + escape(original[end:])


def render_result(directory):
    directory = Path(directory)
    result = _read(directory / "stage-two-result.json")
    value = _read(directory / "input.json")
    value = value if isinstance(value, dict) else {}
    candidate = value.get("candidate") or {}
    original = candidate.get("original_text", "") if isinstance(candidate, dict) else ""
    title = "图谱课程 · 阶段②调试报告"
    body = '<header><div class="eyebrow">离线报告 · 按目标判型</div><h1>' + title + '</h1>'
    body += _badge(result.get("status", "input_error"))
    body += '<p>运行：' + escape(str(result.get("run_id", directory.name))) + '</p></header>'
    if result.get("replay_comparison") is not None:
        comparison = result["replay_comparison"]
        message = "与历史结论一致" if comparison["ok"] else "与历史结论不一致，回放验收未通过"
        body += '<section><h2>回放结论比对</h2><p>' + message + '</p>' + _json(comparison) + '</section>'
    body += '<section><h2>题图与原文</h2>'
    if (directory / "source.png").is_file():
        image = base64.b64encode((directory / "source.png").read_bytes()).decode()
        body += '<img style="max-width:100%;max-height:420px" alt="阶段①输入题图" src="data:image/png;base64,' + image + '">'
    body += '<div class="original">' + escape(str(original)) + '</div></section>'
    body += '<section><h2>输入准入与运行状态</h2>' + _json(result.get("input_validation", {}))
    body += _details("阶段①状态", value.get("statuses"))
    body += _details("本次 LLM 调用计数", result.get("llm"))
    if result.get("historical"):
        body += _details("历史录制结果与调用计数", result["historical"])
    if result.get("previous_run"):
        body += _details("本次回放读取的上一轮运行", result["previous_run"])
    if (directory / "input-raw.txt").is_file():
        body += '<details><summary>无法解析的原始输入</summary><pre>'
        body += escape((directory / "input-raw.txt").read_text(encoding="utf-8")) + '</pre></details>'
    body += '</section>'
    for number, goal in enumerate(result.get("goals", []), 1):
        body += '<section id="goal-' + str(number) + '"><h2>' + escape(goal.get("label") or f"目标 {number}") + '</h2>'
        body += _badge(goal["status"]) + ' <code>' + escape(goal["target_ref"]) + '</code>'
        body += '<p>主要归属：' + escape(str(goal.get("primary") or "未确认")) + ' · 来源：' + escape(str(goal.get("primary_source") or "—")) + '</p>'
        body += _details("诊断", goal.get("diagnostics", []))
        body += '<h3>特征与知识点</h3>' + _details("本目标特征", [f for f in value.get("features", []) if isinstance(f, dict) and f.get("target_ref") == goal["target_ref"]])
        body += _json(goal["knowledge"])
        body += '<h3>全部题型检查</h3>'
        for report in goal["types"]:
            body += '<details><summary>' + escape(report["type_id"]) + ' · ' + _badge(report["status"]) + '</summary>' + _json(report) + '</details>'
        body += '<h3>D1 · 原文片段</h3>'
        d1 = goal.get("d1") or goal.get("debug_d1") or {}
        if goal.get("d1") is None:
            body += '<p class="muted">未生成学生 D1；如有定位材料，仅供调试。</p>'
        for fragment in d1.get("fragments", []):
            body += '<details><summary>' + escape(fragment["text"]) + '</summary><div class="original">' + _highlight(original, fragment) + '</div>' + _json(fragment) + '</details>'
        body += _details("D1 定位诊断", d1.get("diagnostics", []))
        body += '<h3>D2 · 题型选项</h3>' + _json(goal.get("d2"))
        body += _details("和积验证步骤与依据", goal["verification"])
        if goal.get("unsupported_record"):
            body += '<p><a href="' + quote(goal["unsupported_record"], safe="/") + '">打开待处理记录</a></p>'
        body += '<h3>LLM 选择与失败材料</h3>' + _json(goal.get("llm"))
        folder = directory / "calls" / f"goal-{number:03}"
        if folder.is_dir():
            for path in sorted(folder.glob("*.json")):
                body += _details(path.name, _read(path))
        body += '</section>'
    body += '<section><h2>完整产物</h2><p><a href="stage-two-result.json">阶段②结果 JSON</a> · <a href="input.json">阶段①输入快照</a> · <a href="frozen.json">版本快照</a></p></section>'
    path = directory / "index.html"
    path.write_text(_page(title, body), encoding="utf-8")
    return path


def render_batch(directory):
    directory = Path(directory)
    summary = _read(directory / "batch-summary.json")
    body = '<header><div class="eyebrow">阶段② · 批次调试</div><h1>题型判定与 D1/D2</h1><p>阶段①真实录制回放；按目标展示判断依据。</p></header>'
    body += '<section><h2>调用计数</h2>' + _json(summary.get("llm", {})) + '</section>'
    body += '<section><table><thead><tr><th>题目／样本</th><th>运行状态</th><th>确认目标</th><th>暂不支持目标</th></tr></thead><tbody>'
    for row in summary.get("results", []):
        rel = row["sample_dir"]
        # Batch rows originate from the retained manifest; refuse traversal if edited.
        if not (directory / rel).resolve().is_relative_to(directory.resolve()):
            continue
        body += '<tr><td><a href="' + quote(rel + "/index.html", safe="/") + '">' + escape(f'{row["case_id"]} / {row["sample_id"]}') + '</a></td><td>' + _badge(row["status"]) + '</td><td>' + str(row["resolved"]) + '</td><td>' + str(row["unsupported"]) + '</td></tr>'
    body += '</tbody></table></section>'
    path = directory / "index.html"
    path.write_text(_page("阶段②批次报告", body), encoding="utf-8")
    return path
