"""Validate executable method graphs against the public knowledge graph."""

import hashlib
import json
from functools import lru_cache
from pathlib import Path

from jsonschema import Draft202012Validator

from ..stage_two.recognition import DATA, load_nodes
from . import judgments
from .capabilities import PLANNED, REGISTRY

DIRECTORY = DATA / "execution"
METHODS = (
    "method-discriminant",
    "method-separation",
    "quadratic-inequality-solve",
    "method-square-extremum",
)
SCHEMA = DATA.parents[2] / "internal/schemas/graph-method-execution-v1.schema.json"


@lru_cache(maxsize=1)
def schema_validator():
    return Draft202012Validator(json.loads(SCHEMA.read_text()))


def read(name):
    return json.loads((DIRECTORY / f"{name}.json").read_text())


def actions(step):
    return sorted(
        [
            *(dict(v, kind="call") for v in step["calls"]),
            *(dict(v, kind="judgment") for v in step["judgments"]),
        ],
        key=lambda v: v["order"],
    )


def references(value):
    if isinstance(value, str) and value.startswith("$"):
        yield value[1:].split(".")[0]
    elif isinstance(value, dict):
        for child in value.values():
            yield from references(child)
    elif isinstance(value, list):
        for child in value:
            yield from references(child)


def valid_ref(reference, nodes):
    name, _, anchor = reference.partition("#")
    if name not in nodes:
        return False
    if not anchor:
        return True

    def ids(value):
        if isinstance(value, dict):
            yield value.get("id")
            for child in value.values():
                yield from ids(child)
        elif isinstance(value, list):
            for child in value:
                yield from ids(child)

    return anchor in set(ids(nodes[name]))


def validate_dependencies(declared, required, available):
    """The readiness declaration must describe every actual binding read."""
    if len(set(declared)) != len(declared) or set(declared) != set(required):
        raise ValueError("execution.dependency_declaration_mismatch")
    if not set(declared) <= available:
        raise ValueError("execution.future_dependency")


def validate_contract(contract, nodes=None):
    schema_validator().validate(contract)
    nodes = load_nodes() if nodes is None else nodes
    method = contract["method"]
    public = nodes[method]["steps"]
    if [s["id"] for s in contract["steps"]] != [s["id"] for s in public]:
        raise ValueError("execution.step_mismatch")
    mappings = read("skill-capabilities")
    templates = read("presentation-registry")["templates"]
    available = set(contract["inputs"])
    if any(
        not isinstance(role, dict)
        or not isinstance(role.get("role"), str)
        or not role["role"]
        for role in contract["inputs"].values()
    ):
        raise ValueError("execution.input_role")
    expected_exits = {"capability_gap", "math_failed", "execution_error"}
    if set(contract["exits"]) != expected_exits or any(
        contract["exits"][status] != {"status": status} for status in expected_exits
    ):
        raise ValueError("execution.exit_status")
    display_ids = set()
    for step, node in zip(contract["steps"], public):
        allowed = {c["ref"] for c in node.get("calls", [])}
        ids, executed_refs = set(), set()
        all_actions = [*step["calls"], *step["judgments"]]
        if any(
            not {"id", "order", "inputs", "outputs"} <= action.keys()
            or type(action["order"]) is not int
            or not isinstance(action["id"], str)
            or not action["id"]
            for action in all_actions
        ):
            raise ValueError("execution.action_fields")
        if len({action["order"] for action in all_actions}) != len(all_actions):
            raise ValueError("execution.duplicate_order")
        for unit in step["display_units"]:
            if not isinstance(unit.get("after"), str) or not unit["after"]:
                raise ValueError("execution.display_trigger")
            if unit["id"] in display_ids:
                raise ValueError("execution.duplicate_display_id")
            display_ids.add(unit["id"])
            if unit["template"] not in templates:
                raise ValueError("execution.unknown_display_template")
            if set(unit["bindings"]) != set(
                templates[unit["template"]]["required_bindings"]
            ):
                raise ValueError("execution.template_bindings")
            if not isinstance(unit["bindings"]["before"], list) or not isinstance(
                unit["bindings"]["after"], list
            ):
                raise TypeError("execution.display_math_lists")
        for action in actions(step):
            if action["id"] in ids:
                raise ValueError("execution.duplicate_action")
            ids.add(action["id"])
            required = set(references(action.get("inputs", {})))
            if action.get("guard", {}).get("ref"):
                required.add(action["guard"]["ref"])
            if not required <= available:
                raise ValueError("execution.future_or_branch_binding")
            if action["kind"] == "judgment":
                if action.get("guard"):
                    raise ValueError("execution.judgment_guard_unavailable")
                if action["function"] not in judgments.REGISTRY:
                    raise ValueError("execution.unregistered_judgment")
                validate_dependencies(action["depends_on"], required, available)
                choices = [option.get("id") for option in action["options"]]
                if (
                    not choices
                    or any(
                        not isinstance(choice, str) or not choice for choice in choices
                    )
                    or len(set(choices)) != len(choices)
                ):
                    raise ValueError("execution.judgment_options")
            if action["kind"] == "call":
                ref, cap = action["public_ref"], action["capability"]
                if ref is not None:
                    if ref not in allowed or not valid_ref(ref, nodes):
                        raise ValueError("execution.public_call_position")
                    if cap not in mappings["skills"].get(ref, []):
                        raise ValueError("execution.capability_mapping")
                    executed_refs.add(ref)
                elif method + "#" + step["id"] not in mappings["internal"].get(cap, []):
                    raise ValueError("execution.internal_call_position")
                if cap not in REGISTRY and cap not in PLANNED and cap != "submethod":
                    raise ValueError("execution.unknown_capability")
                if cap == "submethod" and ref not in METHODS:
                    raise ValueError("execution.unavailable_child")
            outputs = set(action.get("outputs", {}))
            if action.get("guard") and outputs:
                raise ValueError("execution.unmerged_branch_binding")
            available.update(outputs)
            for unit in step.get("display_units", []):
                if unit["after"] == action["id"]:
                    validate_dependencies(
                        unit["depends_on"], references(unit["bindings"]), available
                    )
        if executed_refs != allowed:
            raise ValueError("execution.missing_public_call")
        if any(unit["after"] not in ids for unit in step.get("display_units", [])):
            raise ValueError("execution.display_trigger")
    if not set(references(contract["outputs"])) <= available:
        raise ValueError("execution.missing_return_binding")
    return contract


def load_contracts():
    nodes = load_nodes()
    contracts = {name: validate_contract(read(name), nodes) for name in METHODS}

    def visit(name, path):
        if name in path:
            raise ValueError("execution.recursive_method")
        for step in contracts[name]["steps"]:
            for call in step["calls"]:
                if call["capability"] == "submethod":
                    child = contracts[call["public_ref"]]
                    if set(call["inputs"]) != set(child["inputs"]):
                        raise ValueError("execution.child_inputs")
                    if not set(call["outputs"].values()) <= set(child["outputs"]):
                        raise ValueError("execution.child_outputs")
                    visit(call["public_ref"], (*path, name))

    for method in contracts:
        visit(method, ())
    for refs in read("basis-operations")["operations"].values():
        if not all(valid_ref(ref, nodes) for ref in refs):
            raise ValueError("execution.invalid_basis")
    return contracts


def revisions():
    files = sorted(DIRECTORY.glob("*.json"))
    result = {
        path.stem: hashlib.sha256(path.read_bytes()).hexdigest() for path in files
    }
    folder = Path(__file__).parent
    result["capabilities"] = hashlib.sha256(
        b"".join(
            path.read_bytes() for path in sorted((folder / "capabilities").glob("*.py"))
        )
    ).hexdigest()
    for name in (
        "driver",
        "presentation",
        "trajectory",
        "judgments",
        "execution_contracts",
    ):
        result[name] = hashlib.sha256((folder / f"{name}.py").read_bytes()).hexdigest()
    result["selection"] = hashlib.sha256(
        (DATA / "selection/rule-quadratic-method.json").read_bytes()
    ).hexdigest()
    return result
