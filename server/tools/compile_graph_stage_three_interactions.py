"""Compile a read-only interaction audit from actual, frozen stage-three seeds.

This tool never runs mathematical solvers, reconstructs seeds or opens the
source event database. After one mathematical recording, rule changes can be
audited repeatedly without changing that recording. Open index.html directly.
"""

import argparse
import json
import shutil
from collections import Counter, defaultdict
from hashlib import sha256
from html import escape
from pathlib import Path
from time import perf_counter

from shuxueshuo_server.graph_lesson.stage_three import interaction
from shuxueshuo_server.graph_lesson.stage_three.contracts import ROOT
from shuxueshuo_server.graph_lesson.stage_three.revision_manifest import math_step_hash
from shuxueshuo_server.problem_understanding.identity import revision


def _save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _file_hash(path):
    return sha256(path.read_bytes()).hexdigest()


def _sources(source):
    source = Path(source).resolve()
    if (source / "checkpoint.json").is_file():
        return [("single", source / "checkpoint.json")]
    files = sorted(path.parent / "checkpoint.json" for path in source.rglob("stage-three-result.json")
                   if ".event-exports" not in path.parts)
    if not files:
        raise ValueError("coverage.no_recordings")
    return [(str(path.parent.relative_to(source)), path) for path in files]


def _read_recording(label, path):
    snapshot_bytes = path.read_bytes()
    snapshot = json.loads(snapshot_bytes)
    result_path = path.with_name("stage-three-result.json")
    result_bytes = result_path.read_bytes()
    result = json.loads(result_bytes)
    if any(result.get(name) != snapshot.get(name) for name in ("run_id", "lesson_version")):
        raise ValueError(f"coverage.result_identity_mismatch:{label}")
    checkpoints = snapshot.get("checkpoints")
    if not isinstance(checkpoints, list) or not checkpoints:
        raise ValueError(f"coverage.missing_checkpoints:{label}")
    routes, seen = [], set()
    for checkpoint in checkpoints:
        identity = {key: checkpoint[key] for key in ("run_id", "lesson_version", "target_ref", "route_id")}
        key = identity["target_ref"], identity["route_id"]
        if key in seen or any(identity[name] != snapshot[name] for name in ("run_id", "lesson_version")):
            raise ValueError(f"coverage.identity_mismatch:{label}")
        seen.add(key)
        state = checkpoint.get("driver_state", {})
        cards, seeds = state.get("fragments", []), state.get("interaction_seeds")
        if not isinstance(seeds, list) or not seeds or len(seeds) != len(cards):
            raise ValueError(f"coverage.missing_frozen_seeds:{label}:{key}")
        ordinals, step_ids = [], set()
        for seed, card in zip(seeds, cards, strict=True):
            if seed.get("contract") != "graph-interaction-seed/v1":
                raise ValueError(f"coverage.seed_contract:{label}")
            if (any(seed.get(name) != value or card.get(name) != value for name, value in identity.items())
                    or any(seed.get(name) != card.get(name) for name in (
                        "step_id", "math_step_sha256", "ordinal", "display_unit", "method_ref", "case_path"))
                    or math_step_hash(card) != card["math_step_sha256"]):
                raise ValueError(f"coverage.seed_card_mismatch:{label}")
            if seed["step_id"] in step_ids:
                raise ValueError(f"coverage.duplicate_step:{label}")
            step_ids.add(seed["step_id"])
            ordinals.append(seed["ordinal"])
        if ordinals != list(range(1, len(cards) + 1)):
            raise ValueError(f"coverage.card_order:{label}")
        routes.append({"identity": identity, "status": checkpoint["status"],
                       "method": state.get("method"), "cards": cards, "seeds": seeds})
    expected_routes = {}
    for goal in result["goals"]:
        for route in goal["routes"]:
            key = goal["target_ref"], route["route_id"]
            if key in expected_routes:
                raise ValueError(f"coverage.result_duplicate_route:{label}")
            expected_routes[key] = {"status": route["status"], "method": route["method"]}
    actual_routes = {(route["identity"]["target_ref"], route["identity"]["route_id"]):
                     {"status": route["status"], "method": route["method"]} for route in routes}
    if expected_routes != actual_routes:
        raise ValueError(f"coverage.result_routes_mismatch:{label}")
    return {"label": label, "source": path, "source_sha256": sha256(snapshot_bytes).hexdigest(),
            "result_source": result_path, "result_source_sha256": sha256(result_bytes).hexdigest(),
            "math_result_status": result["status"], "routes": routes}


def _counts():
    return Counter({name: 0 for name in (
        "cards", "interactive_cards", "readonly_cards", "interactive_groups", "readonly_groups",
        "questions", "pending_cards", "compile_errors", "graph_fallbacks", "stem_graphs", "option_graphs",
        "completion_graphs")})


def _count_results(seeds, results, pending):
    counts, templates, reasons = _counts(), defaultdict(_counts), Counter()
    by_id = {seed["step_id"]: seed for seed in seeds}
    counts["cards"], counts["pending_cards"] = len(seeds), len(pending)
    for seed in seeds:
        templates[seed["template"]]["cards"] += 1
    for chunk, diagnostics in results:
        status = chunk["status"]
        counts[status + "_groups"] += 1
        counts[status + "_cards"] += len(chunk["steps"])
        counts["questions"] += len(chunk["parts"])
        counts["compile_errors"] += chunk.get("reason") == "compile_error"
        graph_counts = Counter({"graph_fallbacks": sum(row.get("result") == "graph_fallback" for row in diagnostics)})
        if status == "readonly":
            reasons[chunk["reason"]] += 1
        for part in chunk["parts"]:
            graph_counts["stem_graphs"] += "graph" in part
            graph_counts["completion_graphs"] += "completion_graph" in part
            graph_counts["option_graphs"] += sum("graph" in option for option in part["interaction"].get("options", []))
        counts.update(graph_counts)
        # Card counts belong to every covered template; a group's questions are
        # attributed once, to its first card, so aggregate totals never double.
        for item in chunk["steps"]:
            templates[by_id[item["step_id"]]["template"]][status + "_cards"] += 1
        first = templates[by_id[chunk["steps"][0]["step_id"]]["template"]]
        first[status + "_groups"] += 1
        first["questions"] += len(chunk["parts"])
        first["compile_errors"] += chunk.get("reason") == "compile_error"
        first.update(graph_counts)
    return counts, templates, reasons


_STYLE = """body{max-width:1100px;margin:32px auto;padding:0 18px;font:16px/1.6 system-ui;color:#203b37}
article,section{border:1px solid #d5e1de;border-radius:12px;padding:18px;margin:18px 0}
table{border-collapse:collapse;width:100%}td,th{padding:8px;border:1px solid #d5e1de;text-align:left}
pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f2f6f5;padding:12px}
.options{display:flex;flex-wrap:wrap;gap:12px}.option{border:1px solid #ccd8d4;padding:10px;flex:1 1 240px}
.correct{border:2px solid #4c927e}.graph{display:block;max-width:410px}.graph svg{width:100%;height:auto}
small{overflow-wrap:anywhere}.readonly{background:#f4f5f4}.answer{color:#256453}figure{margin:8px 0}
"""
_SCRIPT = """document.querySelectorAll('[data-graph]').forEach(node=>{
try{node.innerHTML=window.PracticeComponents.graph(JSON.parse(node.dataset.graph));}
catch(error){node.textContent='图像不可用：'+error.message;}});
if(window.renderMathInElement)window.renderMathInElement(document.body,{throwOnError:false,trust:false,
delimiters:[{left:'$$',right:'$$',display:true},{left:'$',right:'$',display:false}]});"""


def _page(title, body, assets):
    base = escape(assets, quote=True)
    return ("<!doctype html><html lang='zh-CN'><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{escape(title)}</title><style>{_STYLE}</style>"
            f"<link rel='stylesheet' href='{base}/katex/katex.min.css'>"
            f"<body><h1>{escape(title)}</h1>{body}"
            f"<script src='{base}/components.js'></script><script src='{base}/katex/katex.min.js'></script>"
            f"<script src='{base}/katex/auto-render.min.js'></script><script>{_SCRIPT}</script></body></html>")


def _graph(spec):
    if not spec:
        return ""
    data = escape(json.dumps(spec, ensure_ascii=False), quote=True)
    return f"<figure><span class='graph' data-graph='{data}'></span><figcaption>{escape(spec.get('caption', ''))}</figcaption></figure>"


def _part(part):
    expected, spec = part["expected_answer"], part["interaction"]
    body = f"<h3>{escape(part['title'])}</h3><p>{escape(part['question'])}</p>" + _graph(part.get("graph"))
    if "options" in spec:
        answers = expected.get("one_of", expected.get("required", []))
        options = []
        for option in spec["options"]:
            correct = option["value"] in answers
            options.append(f"<div class='option{' correct' if correct else ''}'><b>{'正确：' if correct else ''}"
                           f"{escape(option['label'])}</b>{_graph(option.get('graph'))}"
                           f"<p>{escape(option.get('feedback', ''))}</p></div>")
        body += "<div class='options'>" + "".join(options) + "</div>"
    elif "slots" in spec:
        for index, slot in enumerate(spec["slots"]):
            answer = expected["terms"][index]
            body += f"<p>{escape(slot['label'])}</p><ul>" + "".join(
                f"<li>{'✓ ' if option['value'] == answer else ''}{escape(option['label'])}</li>"
                for option in slot["options"]) + "</ul>"
    else:
        labels = spec.get("term_labels", {})
        body += "<p>候选：" + "，".join(escape(labels.get(value, value)) for value in spec.get("terms", [])) + "</p>"
        body += "<p class='answer'>答案：" + "，".join(escape(labels.get(value, value)) for value in expected.get("terms", [])) + "</p>"
    body += "<p class='answer'>" + escape("；".join(part.get("feedback", {}).values())) + "</p>"
    return body + _graph(part.get("completion_graph"))


def _route_page(route, results, assets):
    seeds = {seed["step_id"]: seed for seed in route["seeds"]}
    cards = {card["step_id"]: card for card in route["cards"]}
    body = ("<p><a href='seeds.json'>冻结种子</a> · <a href='chunks.json'>编译结果</a> · "
            "<a href='diagnostics.json'>诊断</a> · <a href='provenance.json'>出处与哈希</a></p>")
    for chunk, diagnostics in results:
        group = " / ".join(seeds[item["step_id"]]["template"] for item in chunk["steps"])
        body += f"<article class='{chunk['status']}'><h2>{escape(group)} · {escape(chunk['status'])}</h2>"
        for item in chunk["steps"]:
            card = cards[item["step_id"]]
            body += f"<details><summary>数学卡 {card['ordinal']}：{escape(card['title'])}</summary>"
            body += f"<p>{escape(card['explanation'])}</p><pre>{escape(json.dumps(card, ensure_ascii=False, indent=2))}</pre></details>"
        body += "".join(_part(part) for part in chunk["parts"])
        if chunk["status"] == "readonly":
            body += f"<p>只读原因：{escape(chunk['reason'])}</p>"
        body += f"<details><summary>编译诊断</summary><pre>{escape(json.dumps(diagnostics, ensure_ascii=False, indent=2))}</pre></details></article>"
    return _page(f"{route['identity']['target_ref']} · {route['identity']['route_id']}", body, assets)


def compile_batch(source, output, *, registry=None):
    source, output = Path(source).resolve(), Path(output).resolve()
    if output == source or output.is_relative_to(source):
        raise ValueError("coverage.output_inside_source")
    if output.exists():
        raise FileExistsError(output)
    # Preflight all recordings before creating any output. Missing old seeds
    # must fail loudly; they are never reconstructed from a final checkpoint.
    recordings = [_read_recording(label, path) for label, path in _sources(source)]
    registry = interaction.load_registry() if registry is None else interaction.validate_registry(registry)
    registry_revision, engine_revision = interaction.registry_revision(registry), interaction.engine_revision()
    presentation_path = ROOT / "site/data/knowledge-next/execution/presentation-registry.json"
    declared_templates = sorted(json.loads(presentation_path.read_text(encoding="utf-8"))["templates"])
    output.mkdir(parents=True)
    assets = output / "assets"
    assets.mkdir()
    shutil.copyfile(ROOT / "site/assets/practice/components.js", assets / "components.js")
    shutil.copytree(ROOT / "site/assets/practice/vendor/katex-0.18.9", assets / "katex")
    _save(output / "registry.json", registry)
    summary = {"contract": "graph-interaction-coverage/v1", "source": str(source),
               "interaction_revision": registry_revision, "engine_revision": engine_revision,
               "presentation_registry": {"source": str(presentation_path), "sha256": _file_hash(presentation_path)},
               "declared_templates": declared_templates, "declared_template_count": len(declared_templates),
               "recordings": [], "templates": {}, "totals": _counts(), "readonly_reasons": Counter(),
               "new_llm_calls": 0, "new_mathematical_runs": 0}
    template_totals, html_rows = defaultdict(_counts), []
    for index, recording in enumerate(recordings, 1):
        record = {"sample": recording["label"], "source": str(recording["source"]),
                  "source_sha256": recording["source_sha256"],
                  "result_source": str(recording["result_source"]),
                  "result_source_sha256": recording["result_source_sha256"],
                  "math_result_status": recording["math_result_status"], "counts": _counts(), "routes": []}
        for route_index, route in enumerate(recording["routes"], 1):
            folder = output / f"sample-{index:03d}" / f"route-{route_index:03d}"
            folder.mkdir(parents=True)
            started = perf_counter()
            results, pending = interaction.compile_route(route["seeds"], registry, final=True, revision=registry_revision)
            expected_steps = [{key: seed[key] for key in ("step_id", "math_step_sha256")} for seed in route["seeds"]]
            actual_steps = [item for chunk, _ in results for item in chunk["steps"]]
            if pending or actual_steps != expected_steps:
                raise ValueError("coverage.incomplete_or_reordered_groups")
            for chunk, _ in results:
                interaction.validate_chunk(chunk)
                if chunk["interaction_sha256"] != interaction.chunk_sha256(chunk):
                    raise ValueError("coverage.chunk_hash_mismatch")
            counts, templates, reasons = _count_results(route["seeds"], results, pending)
            row = {**route["identity"], "method": route["method"], "math_status": route["status"],
                   "counts": counts, "templates": dict(templates), "readonly_reasons": reasons,
                   "elapsed_seconds": round(perf_counter() - started, 6),
                   "report": str((folder / "index.html").relative_to(output))}
            provenance = {**row, "source": record["source"], "source_sha256": record["source_sha256"],
                          "result_source": record["result_source"], "result_source_sha256": record["result_source_sha256"],
                          "seeds_sha256": revision(route["seeds"]), "interaction_revision": registry_revision,
                          "engine_revision": engine_revision,
                          "cards": [{key: card[key] for key in ("step_id", "math_step_sha256", "ordinal")}
                                    for card in route["cards"]]}
            _save(folder / "seeds.json", route["seeds"])
            _save(folder / "chunks.json", [chunk for chunk, _ in results])
            _save(folder / "diagnostics.json", [{"interaction_id": chunk["interaction_id"], "diagnostics": diagnostics}
                                                for chunk, diagnostics in results])
            _save(folder / "provenance.json", provenance)
            (folder / "index.html").write_text(_route_page(route, results, "../../assets"), encoding="utf-8")
            record["routes"].append(row)
            record["counts"].update(counts)
            summary["totals"].update(counts)
            summary["readonly_reasons"].update(reasons)
            for template, values in templates.items():
                template_totals[template].update(values)
            html_rows.append(f"<tr><td>{escape(record['sample'])}</td><td><a href='{escape(row['report'], quote=True)}'>"
                             f"{escape(row['target_ref'])} / {escape(row['route_id'])}</a></td>"
                             f"<td>{counts['cards']}</td><td>{counts['questions']}</td>"
                             f"<td>{counts['interactive_cards']}</td><td>{counts['readonly_cards']}</td></tr>")
        # The source snapshot must remain byte-for-byte unchanged throughout.
        if (_file_hash(recording["source"]) != recording["source_sha256"]
                or _file_hash(recording["result_source"]) != recording["result_source_sha256"]):
            raise ValueError("coverage.source_changed")
        summary["recordings"].append(record)
    if interaction.engine_revision() != engine_revision or interaction.registry_revision(registry) != registry_revision:
        raise ValueError("coverage.compiler_changed")
    summary["templates"] = dict(sorted(template_totals.items()))
    summary["seen_templates"] = sorted(template_totals)
    summary["unseen_templates"] = sorted(set(declared_templates) - set(template_totals))
    summary["undeclared_templates"] = sorted(set(template_totals) - set(declared_templates))
    summary["completed"] = not summary["totals"]["pending_cards"] and not summary["totals"]["compile_errors"]
    _save(output / "summary.json", summary)
    body = (f"<p>录制 {len(recordings)} 份；路线 {sum(len(record['routes']) for record in summary['recordings'])} 条。"
            "只使用冻结种子；未重算数学，未调用 LLM。</p><p><a href='summary.json'>完整统计与出处</a> · "
            "<a href='registry.json'>本次规则</a></p>"
            f"<p>声明展示模板 {len(declared_templates)} 个，本批实际出现 {len(template_totals)} 个。"
            f"本批未出现：{escape('、'.join(summary['unseen_templates']) or '无')}。"
            "未出现的模板不计为通过录制验收。</p>"
            "<table><tr><th>录制</th><th>目标 / 路线</th><th>数学卡</th>"
            "<th>问题数</th><th>交互卡</th><th>只读卡</th></tr>" + "".join(html_rows) + "</table>"
            f"<h2>汇总</h2><pre>{escape(json.dumps(summary['totals'], ensure_ascii=False, indent=2))}</pre>")
    (output / "index.html").write_text(_page("冻结种子交互覆盖验收", body, "assets"), encoding="utf-8")
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path, help="阶段③单次运行或带 checkpoint 的录制批次")
    parser.add_argument("--output", required=True, type=Path, help="新的报告目录，不得位于原录制目录内")
    args = parser.parse_args(argv)
    summary = compile_batch(args.source, args.output)
    print(json.dumps({"completed": summary["completed"], "totals": summary["totals"],
                      "report": str((args.output / "index.html").resolve())}, ensure_ascii=False))
    return 0 if summary["completed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
