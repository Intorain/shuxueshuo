"""Read existing solution/family knowledge as context, never as current facts."""

import hashlib
import json
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).parent
REPO = ROOT.parents[3]


def family_guidance(family_id):
    if not family_id:
        return None
    from ...solver.family import BASIC_INEQUALITY_FAMILY, DEFAULT_FAMILY_REGISTRY

    # Authoring-only families may supply prose without enabling solver execution.
    families = (*DEFAULT_FAMILY_REGISTRY.families, BASIC_INEQUALITY_FAMILY)
    family = next((f for f in families if f.family_id == family_id), None)
    if family is None:
        raise ValueError(f"Unknown explanation family: {family_id}")
    guidance = {"family_id": family.family_id, "title": family.title,
                "description": family.description, "use_when": family.use_when,
                "do_not_use_when": list(family.do_not_use_when),
                "strategy_principles": list(family.strategy_principles)}
    if family.strategy_reference:
        path = (REPO / family.strategy_reference).resolve()
        if not path.is_relative_to(REPO.resolve()):
            raise ValueError("Family strategy reference must stay in the repository")
        raw = path.read_bytes()
        strategy = json.loads(raw)
        if strategy.get("family_id") != family_id:
            raise ValueError("Family strategy reference mismatch")
        guidance.update(source=family.strategy_reference, version=hashlib.sha256(raw).hexdigest()[:12])
        # Mathematical planning prose only, not solver tool contracts or dispatch IDs.
        for key in ("strategy_overview", "methods"):
            if key in strategy:
                guidance[key] = deepcopy(strategy[key])
    return guidance


def load_references(problem_id):
    raw = json.loads((ROOT / "problems" / f"{problem_id}.json").read_text())
    solutions = []
    for route in raw.get("reference_routes", []):
        solutions.append({"id": route["id"], "title": route["label"],
                          "operations": deepcopy(route["steps"]),
                          "sources": [f"explanation/problems/{problem_id}.json#reference_routes/{route['id']}"]})
    from ...learning.identity import canonical_id
    lesson_id = canonical_id(problem_id)
    lesson_path = ROOT.parent / "lessons" / f"{lesson_id}.json"
    if lesson_path.is_file():
        lesson = json.loads(lesson_path.read_text())
        for key, route in lesson.get("routes", {}).items():
            derivation = [{"title": n["title"], "lines": deepcopy(n["results"])}
                          for n in route.get("nodes", []) if n.get("results")]
            if not derivation:
                continue
            solution = next((s for s in solutions if s["id"] == key), None)
            if solution is None:
                solution = {"id": key, "title": route["label"], "sources": []}
                solutions.append(solution)
            solution["derivation"] = derivation
            solution["sources"].append(f"lessons/{lesson_id}.json#routes/{key}")
    family_id = raw.get("family_id") or raw.get("problem_ir", "").partition("/")[0]
    return {"reference_solutions": solutions, "family_guidance": family_guidance(family_id)}
