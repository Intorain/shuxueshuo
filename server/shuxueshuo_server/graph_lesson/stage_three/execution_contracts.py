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
    "method-interval-extremum",
    "quadratic-inequality-solve",
    "method-square-extremum",
)
SCHEMA = DATA.parents[2] / "internal/schemas/graph-method-execution-v1.schema.json"


@lru_cache(maxsize=1)
def schema_validator():
    return Draft202012Validator(json.loads(SCHEMA.read_text()))


def read(name):
    return json.loads((DIRECTORY / f"{name}.json").read_text())


def route_methods():
    """Executable top-level routes come from selection contracts, not child calls."""
    methods = set()
    for path in sorted((DATA / "selection").glob("*.json")):
        selection = json.loads(path.read_text())
        if selection.get("schema_version") == "graph-method-selection/v1":
            methods.update(branch["target"] for branch in selection["branches"])
    return methods.intersection(METHODS)


def actions(step):
    return sorted(
        [
            *(dict(v, kind="call") for v in step["calls"]),
            *(dict(v, kind="judgment") for v in step["judgments"]),
            *(dict(v, kind="merge") for v in step.get("merges", [])),
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


def guard_references(guard):
    if not guard:
        return set()
    if "all" in guard:
        return set().union(*(guard_references(item) for item in guard["all"]))
    return {guard["ref"].split(".")[0]} if "ref" in guard else set()


def _atoms(guard):
    if not guard or guard == {"constant": True}:
        return frozenset()
    if guard == {"constant": False}:
        return frozenset({("__never__", "true")})
    if set(guard) == {"all"} and isinstance(guard["all"], list) and guard["all"]:
        return frozenset().union(*(_atoms(item) for item in guard["all"]))
    if set(guard) != {"ref", "equals"} or not isinstance(guard["ref"], str):
        raise ValueError("execution.invalid_guard")
    return frozenset({(guard["ref"], json.dumps(guard["equals"], sort_keys=True))})


def _combine(*guards):
    return {"all": [guard for guard in guards if guard]} if any(guards) else None


def _require(required, environment, guard=None):
    for name in required:
        if name not in environment:
            raise ValueError("execution.future_or_branch_binding")
        if not _atoms(environment[name]) <= _atoms(guard):
            raise ValueError("execution.unmerged_branch_binding")


def validate_contract(contract, nodes=None):
    schema_validator().validate(contract)
    nodes = load_nodes() if nodes is None else nodes
    method = contract["method"]
    public = nodes[method]["steps"]
    if [s["id"] for s in contract["steps"]] != [s["id"] for s in public]:
        raise ValueError("execution.step_mismatch")
    mappings = read("skill-capabilities")
    templates = read("presentation-registry")["templates"]
    environment = {name: None for name in contract["inputs"]}
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

    def validate_step(step, node, env):
        allowed = {c["ref"] for c in node.get("calls", [])}
        rule = nodes.get(node.get("rule"))
        rule_targets = {branch["id"]: branch["target"] for branch in rule["branches"]} if rule else {}
        allowed.update(rule_targets.values())
        ids, executed_refs = set(), set()
        ordered = actions(step)
        if len({action["order"] for action in ordered}) != len(ordered):
            raise ValueError("execution.duplicate_order")
        _atoms(step.get("guard"))
        _require(guard_references(step.get("guard")), env)
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
        for action in ordered:
            if (
                not isinstance(action.get("id"), str)
                or not action["id"]
                or type(action.get("order")) is not int
            ):
                raise ValueError("execution.action_fields")
            if action["id"] in ids:
                raise ValueError("execution.duplicate_action")
            ids.add(action["id"])
            active_guard = _combine(step.get("guard"), action.get("guard"))
            _atoms(active_guard)
            _require(guard_references(action.get("guard")), env, active_guard)
            if action["kind"] == "merge":
                branch_outputs = [
                    set(branch["bindings"]) for branch in action["branches"]
                ]
                if not branch_outputs or any(
                    keys != branch_outputs[0] for keys in branch_outputs
                ):
                    raise ValueError("execution.merge_outputs")
                for branch in action["branches"]:
                    guard = _combine(active_guard, branch["guard"])
                    _atoms(guard)
                    _require(guard_references(branch["guard"]), env, active_guard)
                    _require(references(branch["bindings"]), env, guard)
                outputs = branch_outputs[0]
            else:
                if not {"inputs", "outputs"} <= action.keys():
                    raise ValueError("execution.action_fields")
                required = set(references(action["inputs"])) | guard_references(
                    action.get("guard")
                )
                _require(required, env, active_guard)
                if action["kind"] == "judgment":
                    if action["function"] not in judgments.REGISTRY:
                        raise ValueError("execution.unregistered_judgment")
                    validate_dependencies(action["depends_on"], required, set(env))
                    choices = [option.get("id") for option in action["options"]]
                    if (
                        not choices
                        or any(
                            not isinstance(choice, str) or not choice
                            for choice in choices
                        )
                        or len(set(choices)) != len(choices)
                    ):
                        raise ValueError("execution.judgment_options")
                    if action.get("rule_ref") and (
                        action["rule_ref"] != node.get("rule") or set(choices) != set(rule_targets)
                    ):
                        raise ValueError("execution.rule_decision_options")
                else:
                    ref, cap = action["public_ref"], action["capability"]
                    if ref is not None:
                        if ref not in allowed or not valid_ref(ref, nodes):
                            raise ValueError("execution.public_call_position")
                        if ref in rule_targets.values():
                            branch = action.get("branch")
                            if action.get("rule_ref") != node["rule"] or rule_targets.get(branch) != ref:
                                raise ValueError("execution.rule_branch_source")
                            decision = next((j for j in step["judgments"]
                                             if j.get("rule_ref") == node["rule"]), None)
                            if not decision or branch not in {o["id"] for o in decision["options"]}:
                                raise ValueError("execution.rule_branch_decision")
                            choice_bindings = [name for name, value in decision["outputs"].items() if value == "choice"]
                            if len(choice_bindings) != 1 or not _atoms({"ref": choice_bindings[0], "equals": branch}) <= _atoms(active_guard):
                                raise ValueError("execution.rule_branch_guard")
                        elif action.get("rule_ref") or action.get("branch"):
                            raise ValueError("execution.unexpected_rule_source")
                        if cap not in mappings["skills"].get(ref, []):
                            raise ValueError("execution.capability_mapping")
                        executed_refs.add(ref)
                    elif method + "#" + node["id"] not in mappings["internal"].get(
                        cap, []
                    ):
                        raise ValueError("execution.internal_call_position")
                    if (
                        cap not in REGISTRY
                        and cap not in PLANNED
                        and cap != "submethod"
                    ):
                        raise ValueError("execution.unknown_capability")
                    if cap == "submethod" and ref not in METHODS:
                        raise ValueError("execution.unavailable_child")
                outputs = set(action["outputs"])
            for name in outputs:
                env[name] = active_guard
            for unit in step["display_units"]:
                if unit["after"] == action["id"]:
                    required = set(references(unit["bindings"]))
                    validate_dependencies(unit["depends_on"], required, set(env))
                    _require(guard_references(unit.get("guard")), env, active_guard)
                    _require(required, env, _combine(active_guard, unit.get("guard")))
        if executed_refs != allowed:
            raise ValueError("execution.missing_public_call")
        if any(unit["after"] not in ids for unit in step["display_units"]):
            raise ValueError("execution.display_trigger")

    index = 0
    while index < len(contract["steps"]):
        step, node = contract["steps"][index], public[index]
        validate_step(step, node, environment)
        cases = step.get("cases")
        if not cases:
            index += 1
            continue
        _require([cases["source"]], environment)
        end = next(
            (
                i
                for i, row in enumerate(contract["steps"])
                if row["id"] == cases["through"]
            ),
            -1,
        )
        if (
            end < index
            or cases["binding"] in environment
            or cases["collect"] in environment
        ):
            raise ValueError("execution.invalid_case_scope")
        child = dict(environment, **{cases["binding"]: None})
        validate_step(dict(cases["entry"], id=step["id"]), node, child)
        for child_index in range(index + 1, end + 1):
            if contract["steps"][child_index].get("cases"):
                raise ValueError("execution.nested_case_span")
            validate_step(contract["steps"][child_index], public[child_index], child)
        _require(references(cases["outputs"]), child)
        environment[cases["collect"]] = None
        index = end + 1
    try:
        _require(references(contract["outputs"]), environment)
    except ValueError as exc:
        raise ValueError("execution.missing_return_binding") from exc
    return contract


def load_contracts():
    nodes = load_nodes()
    boundary_steps = read("presentation-registry").get("boundary_steps", {})
    if not isinstance(boundary_steps, dict):
        raise TypeError("execution.invalid_boundary_step")
    missing = route_methods().difference(boundary_steps)
    if missing:
        raise ValueError("execution.missing_boundary_step:" + ",".join(sorted(missing)))
    contracts = {name: validate_contract(read(name), nodes) for name in METHODS}

    def visit(name, path):
        if name in path:
            raise ValueError("execution.recursive_method")
        for step in contracts[name]["steps"]:
            for call in [
                *step["calls"],
                *step.get("cases", {}).get("entry", {}).get("calls", []),
            ]:
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
    for method, anchor in boundary_steps.items():
        if not valid_ref(method + "#" + anchor, nodes):
            raise ValueError("execution.invalid_boundary_step")
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
