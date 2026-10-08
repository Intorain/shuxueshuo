"""Validate authored files together, then atomically publish read-only public content."""

import hashlib
import json
import re
import subprocess
from html.parser import HTMLParser
from pathlib import Path

from sqlalchemy import text

from ..product.db import lock, transaction
from .identity import ALIASES

ROOT = Path(__file__).resolve().parents[3]


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


class Prose(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("svg", "style", "script"):
            self.skip += 1
        if not self.skip and tag in ("p", "li", "h2", "h3", "section", "div"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("svg", "style", "script"):
            self.skip -= 1
        if not self.skip and tag in ("p", "li", "h2", "h3"):
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)

    @classmethod
    def read(cls, html):
        parser = cls()
        parser.feed(html)
        return "\n".join(
            line.strip() for line in "".join(parser.parts).splitlines() if line.strip()
        )


def validate_graph(nodes, edges):
    """Shared validation for authored files and direct publishing callers."""
    node_types = {}
    for node in nodes:
        if node["id"] in node_types:
            raise ValueError("duplicate nodes")
        if (node["kind"], node.get("subtype")) not in {
            ("knowledge", None), ("method", None), ("method", "technique"),
        }:
            raise ValueError("invalid node kind/subtype")
        node_types[node["id"]] = node["kind"]
    edge_types = {
        "uses": ("method", "knowledge"),
        "prerequisite": ("knowledge", "knowledge"),
    }
    adjacency = {node: [] for node in node_types}
    seen_edges = set()
    for edge in edges:
        a, b, kind = edge["source_id"], edge["target_id"], edge["relation_type"]
        if a not in node_types or b not in node_types or a == b:
            raise ValueError("invalid edge endpoint")
        if kind not in edge_types or (node_types[a], node_types[b]) != edge_types[kind]:
            raise ValueError("invalid edge types")
        if (a, b, kind) in seen_edges:
            raise ValueError("duplicate edge")
        seen_edges.add((a, b, kind))
        if kind == "prerequisite":
            adjacency[a].append(b)
    visited, active = set(), set()

    def visit(node):
        if node in active:
            raise ValueError("prerequisite cycle")
        if node in visited:
            return
        active.add(node)
        for target in adjacency[node]:
            visit(target)
        active.remove(node)
        visited.add(node)

    for node in node_types:
        visit(node)
    return node_types


def load_content(root=ROOT):

    def read(path):
        return json.loads((root / path).read_text())

    base = "site/data/knowledge/"
    (graph, display) = (read(base + "graph.json"), read(base + "display.json"))
    if read(base + "problem-id-aliases.json") != ALIASES:
        raise ValueError("alias copies differ")
    edges = [
        {"source_id": e["from"], "target_id": e["to"], "relation_type": e["type"]}
        for e in graph["edges"]
    ]
    validate_graph(graph["nodes"], edges)
    nodes = {n["id"]: n for n in graph["nodes"]}
    rendered = json.loads(
        subprocess.check_output(
            ["node", str(root / "tools/export-knowledge-text.mjs")], text=True
        )
    )
    rows = {
        name: []
        for name in (
            "knowledge_nodes",
            "knowledge_edges",
            "practice_topics",
            "practice_problems",
            "practice_topic_problems",
            "practice_problem_methods",
            "practice_steps",
            "practice_step_nodes",
            "knowledge_drill_items",
        )
    }
    for n in nodes.values():
        explanation = Prose.read(rendered[n["id"]])
        if not explanation:
            raise ValueError("Invalid authored content")
        rows["knowledge_nodes"].append(
            dict(
                n,
                subtype=n.get("subtype"),
                summary=display[n["id"]]["summary"],
                sheet=display[n["id"]]["sheet"],
                explanation_md=explanation,
            )
        )
    rows["knowledge_edges"] = sorted(
        edges, key=lambda e: (e["source_id"], e["target_id"], e["relation_type"])
    )
    registered = {}
    for path in sorted((root / base / "topics").glob("*.json")):
        topic = json.loads(path.read_text())
        if set(topic["nodes"]) - nodes.keys():
            raise ValueError("Invalid authored content")
        rows["practice_topics"].append({k: topic[k] for k in ("id", "label", "path")})
        methods = {m["route"]: m["node"] for m in topic["methods"]}
        for pid, p in topic["problems"].items():
            if pid in ALIASES:
                raise ValueError("Invalid authored content")
            page = (root / "site" / p["path"].strip("/") / "index.html").read_text()
            config = json.loads(
                re.search('id="practice-config">\\s*(.*?)</script>', page, re.DOTALL)[1]
            )
            lesson = read(f"server/shuxueshuo_server/tutor_demo/lessons/{pid}.json")
            if (
                config["id"] != pid or lesson["id"] != pid
                or config["version"] != lesson["version"]
            ):
                raise ValueError(pid)
            if (
                set(p["routes"]) != set(config["routes"])
                or set(p["routes"]) != set(lesson["routes"])
            ):
                raise ValueError(pid)
            contract = {}
            for route, mapping in p["routes"].items():
                if nodes[methods[route]]["kind"] != "method":
                    raise ValueError("Invalid authored content")
                frontend = config["routes"][route]
                backend = lesson["routes"][route]["nodes"]
                if [n["id"] for n in frontend] != [n["id"] for n in backend]:
                    raise ValueError("Invalid authored content")
                if not (
                    len(mapping) == len(frontend) == len({n["id"] for n in frontend})
                    and set(mapping) == {n["id"] for n in frontend}
                ):
                    raise ValueError("Invalid authored content")
                for f, b in zip(frontend, backend):
                    for key in (
                        "title",
                        "question",
                        "interaction",
                        "expected_answer",
                        "feedback",
                    ):
                        if f.get(key) != b.get(key):
                            raise ValueError((pid, route, key))
                    # Include every choice branch, not just the initial/default tip.
                    pending = [f["tip"]] if f.get("tip") else []
                    while pending:
                        tip = pending.pop()
                        if tip.get("field"):
                            pending.extend(tip["options"].values())
                        elif tip["id"] not in mapping[f["id"]]:
                            raise ValueError(
                                f"{pid}/{route}/{f['id']}: explainer {tip['id']} "
                                "is missing from the step-node mapping"
                            )
                contract[route] = {
                    "method": methods[route],
                    "steps": [
                        (
                            n["id"],
                            n["interaction"],
                            n["expected_answer"],
                            n["required_evidence"],
                            n["criteria"],
                            mapping[n["id"]],
                        )
                        for n in backend
                    ],
                }
                rows["practice_problem_methods"].append(
                    {
                        "problem_id": pid,
                        "route_id": route,
                        "method_node_id": methods[route],
                    }
                )
                for i, n in enumerate(frontend):
                    rows["practice_steps"].append(
                        {
                            "problem_id": pid,
                            "route_id": route,
                            "step_id": n["id"],
                            "title": n["title"],
                            "position": i,
                        }
                    )
                    for nid in mapping[n["id"]]:
                        if nid not in nodes:
                            raise ValueError("Invalid authored content")
                        rows["practice_step_nodes"].append(
                            {
                                "problem_id": pid,
                                "route_id": route,
                                "step_id": n["id"],
                                "node_id": nid,
                            }
                        )
            problem_data = dict(
                lesson["problem"],
                contract_hash=hashlib.sha256(
                    encoded({"routes": contract, "problem": lesson["problem"]}).encode()
                ).hexdigest(),
            )
            row = {
                "id": pid,
                "label": p["label"],
                "path": p["path"],
                "lesson_file": f"{pid}.json",
                "statement_md": lesson["problem"]["statement"],
                "problem_data": problem_data,
                "is_active": True,
            }
            if pid in registered and registered[pid] != row:
                raise ValueError("cross-topic identity conflict")
            registered[pid] = row
            rows["practice_topic_problems"].append(
                {"topic_id": topic["id"], "problem_id": pid}
            )
    rows["practice_problems"] = list(registered.values())
    for path in sorted(
        (root / "server/shuxueshuo_server/learning/drills").glob("*.json")
    ):
        drill = json.loads(path.read_text())
        nid = drill["node"]
        if nid not in nodes:
            raise ValueError("Invalid authored content")
        if not (
            len(drill["items"]) >= 5
            and len({i["id"] for i in drill["items"]}) == len(drill["items"])
        ):
            raise ValueError("Invalid authored content")
        for item in drill["items"]:
            if item["type"] not in ("choice", "multi"):
                raise ValueError("authoring currently supports choice/multi only")
            values = [o["value"] for o in item["options"]]
            answer = (
                item["answer"] if isinstance(item["answer"], list) else [item["answer"]]
            )
            if not (
                len(set(values)) == len(values)
                and len(values) >= 2
                and answer
                and (set(answer) <= set(values))
            ):
                raise ValueError("Invalid authored content")
            if not (
                len(set(answer)) == len(answer)
                and (item["type"] == "multi" or len(answer) == 1)
            ):
                raise ValueError("Invalid authored content")
            if not all(
                o.get("feedback") for o in item["options"] if o["value"] not in answer
            ):
                raise ValueError("Invalid authored content")
            rows["knowledge_drill_items"].append(
                {
                    "node_id": nid,
                    "item_id": item["id"],
                    "statement_md": "\n\n".join(
                        filter(None, [item.get("given"), item["question"]])
                    ),
                    "question_type": item["type"],
                    "options": item["options"],
                    "answer_spec": {"selected": sorted(answer)},
                    "explanation_md": item.get("explanation", ""),
                    "is_active": True,
                }
            )
    return rows


KEYS = {
    "knowledge_nodes": ["id"],
    "knowledge_edges": ["source_id", "target_id", "relation_type"],
    "practice_topics": ["id"],
    "practice_problems": ["id"],
    "practice_topic_problems": ["topic_id", "problem_id"],
    "practice_problem_methods": ["problem_id", "route_id"],
    "practice_steps": ["problem_id", "route_id", "step_id"],
    "practice_step_nodes": ["problem_id", "route_id", "step_id", "node_id"],
    "knowledge_drill_items": ["node_id", "item_id"],
}
JSON_FIELDS = {"problem_data", "options", "answer_spec"}


def publish(db, rows):
    node_types = validate_graph(rows["knowledge_nodes"], rows["knowledge_edges"])
    for name, field in (
        ("practice_problem_methods", "method_node_id"),
        ("practice_step_nodes", "node_id"),
        ("knowledge_drill_items", "node_id"),
    ):
        for row in rows[name]:
            if row[field] not in node_types:
                raise ValueError(f"{name}: reference to a removed node")
    topic_ids = {t["id"] for t in rows["practice_topics"]}
    problem_ids = {p["id"] for p in rows["practice_problems"]}
    if any(
        r["topic_id"] not in topic_ids or r["problem_id"] not in problem_ids
        for r in rows["practice_topic_problems"]
    ):
        raise ValueError("topic membership references removed content")
    with transaction(db) as c:
        lock(c, "learning.publish")
        # Current catalog relations have no student-history references. Remove
        # memberships before their topics; retain historical problem/step identities.
        for name in ("knowledge_edges", "practice_topic_problems", "practice_topics"):
            keys = KEYS[name]
            keep = {tuple(r[k] for k in keys) for r in rows[name]}
            for old in c.execute(text(f"SELECT * FROM {name}")).mappings():
                if tuple(old[k] for k in keys) not in keep:
                    c.execute(
                        text(
                            f"DELETE FROM {name} WHERE "
                            + " AND ".join(f"{k}=:{k}" for k in keys)
                        ),
                        dict(old),
                    )
        for name, items in rows.items():
            for row in items:
                if name == "knowledge_nodes":
                    row = {**row, "is_active": True}
                keys = KEYS[name]
                where = " AND ".join(f"{k}=:{k}" for k in keys)
                old = (
                    c.execute(text(f"SELECT * FROM {name} WHERE {where}"), row)
                    .mappings()
                    .first()
                )
                if (
                    old
                    and name == "practice_problems"
                    and (
                        old["problem_data"]["contract_hash"]
                        != row["problem_data"]["contract_hash"]
                    )
                ):
                    raise ValueError(
                        f"{row['id']}: teaching contract changed; allocate a new ID"
                    )
                if (
                    old
                    and name == "knowledge_drill_items"
                    and not all(
                        old[k] == row[k]
                        for k in (
                            "statement_md",
                            "question_type",
                            "options",
                            "answer_spec",
                        )
                    )
                ):
                    raise ValueError(
                        f"{row['item_id']}: drill changed; allocate a new ID"
                    )
                if (
                    old
                    and name == "knowledge_nodes"
                    and not (
                        old["kind"] == row["kind"] and old["subtype"] == row["subtype"]
                    )
                ):
                    raise ValueError("node identity changed")
                fields = list(row)
                updates = [k for k in fields if k not in keys]
                values = ",".join(
                    f"CAST(:{k} AS jsonb)" if k in JSON_FIELDS else f":{k}"
                    for k in fields
                )
                action = (
                    "DO UPDATE SET " + ",".join(f"{k}=excluded.{k}" for k in updates)
                    if updates
                    else "DO NOTHING"
                )
                c.execute(
                    text(
                        f"INSERT INTO {name} ({','.join(fields)}) VALUES ({values}) ON CONFLICT ({','.join(keys)}) {action}"
                    ),
                    {
                        k: encoded(v) if k in JSON_FIELDS else v
                        for (k, v) in row.items()
                    },
                )
        for name, fields in [
            ("knowledge_nodes", ["id"]),
            ("practice_problems", ["id"]),
            ("knowledge_drill_items", ["node_id", "item_id"]),
        ]:
            keep = {tuple(row[k] for k in fields) for row in rows[name]}
            for old in c.execute(text(f"SELECT * FROM {name}")).mappings():
                if tuple(old[k] for k in fields) not in keep:
                    c.execute(
                        text(
                            f"UPDATE {name} SET is_active=false WHERE "
                            + " AND ".join(f"{k}=:{k}" for k in fields)
                        ),
                        dict(old),
                    )
    return {name: len(items) for (name, items) in rows.items()}
