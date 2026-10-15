"""Record a DeepSeek graph-walk actor through the browser's Node decision bridge.

Run from server/: uv run python tools/run_graph_walk_actor.py --bundle PATH
--output PRIVATE_DIRECTORY. This does not start a tutor, Solver or database.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import selectors
import signal
import subprocess
import sys
import threading
import time
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1]
REPO = SERVER.parent
sys.path.insert(0, str(SERVER))

ROUTES = {"discriminant": "判别式法", "extremum": "分离参数法"}
SYSTEM = (
    "你是数学题的作答者。只依据当前题目、已完成结果及当前决策作答，"
    "独立判断，不请求标准答案。严格按 answerFormat 和选项 value 输出 JSON："
    '{"decision":"当前决策 id","answer":当前答案,"reason":"简短理由"}。'
    "不要输出 Markdown；reason 只需简短数学依据，不需要展开内部思考过程；"
    "reason 里的数学式用 $…$ 包裹，如 $x^2-2x+3≥0$、$Δ≤0$；"
    "比较符号直接写 ≤ ≥ Δ，不写反斜杠命令。"
    "若上次回答未通过，请依据反馈重新检查。"
)


class BridgeError(RuntimeError):
    """The local state machine did not return a usable protocol response."""


class CallTimeoutError(TimeoutError):
    """The entire provider call, including SDK retries, exceeded its deadline."""


class _DeadlineExpired(BaseException):
    """Escape SDK handlers that catch Exception and retry network failures."""


def positive_seconds(value):
    seconds = float(value)
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError("timeout must be finite and positive")
    return seconds


def complete_with_deadline(client, payload, timeout):
    """Bound the synchronous Unix CLI call, even if response heartbeats never stop."""
    timeout = positive_seconds(timeout)
    if not hasattr(signal, "setitimer") or threading.current_thread() is not threading.main_thread():
        raise RuntimeError("provider deadline requires the Unix main thread")
    if any(signal.getitimer(signal.ITIMER_REAL)):
        raise RuntimeError("provider deadline cannot replace an active alarm")

    def expire(signum, frame):
        raise _DeadlineExpired()

    previous = signal.signal(signal.SIGALRM, expire)
    try:
        signal.setitimer(signal.ITIMER_REAL, timeout)
        return client.complete(payload)
    except _DeadlineExpired:
        raise CallTimeoutError("actor.provider_timeout") from None
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def write_json(path, value, *, private=True):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600 if private else 0o644)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    temporary.replace(path)


class NodeBridge:
    def __init__(self, stderr_path, *, command=None, timeout=30):
        self.timeout = timeout
        self.buffer = b""
        self.stderr = Path(stderr_path).open("w", encoding="utf-8")  # noqa: SIM115 -- owned by close()
        os.chmod(stderr_path, 0o600)
        try:
            self.process = subprocess.Popen(
                command or ["node", str(REPO / "tools/graph-walk-actor.mjs")],
                cwd=REPO, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=self.stderr, text=True, encoding="utf-8", bufsize=1,
            )
        except Exception:
            self.stderr.close()
            raise

    def request(self, payload):
        try:
            self.process.stdin.write(json.dumps(payload, ensure_ascii=False, allow_nan=False) + "\n")
            self.process.stdin.flush()
            deadline = time.monotonic() + self.timeout
            with selectors.DefaultSelector() as selector:
                selector.register(self.process.stdout, selectors.EVENT_READ)
                while b"\n" not in self.buffer:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0 or not selector.select(remaining):
                        raise BridgeError("bridge.timeout")
                    chunk = os.read(self.process.stdout.fileno(), 65_536)
                    if not chunk:
                        raise BridgeError("bridge.incomplete_response")
                    self.buffer += chunk
                    if len(self.buffer) > 1_048_576:
                        raise BridgeError("bridge.response_too_large")
            line, self.buffer = self.buffer.split(b"\n", 1)
            result = json.loads(line.decode("utf-8"))
            if not isinstance(result, dict) or "error" in result:
                raise BridgeError("bridge.invalid_response")
            return result
        except (BrokenPipeError, OSError, ValueError) as error:
            raise BridgeError("bridge.protocol_error") from error

    def close(self):
        if self.process.stdin:
            self.process.stdin.close()
        try:
            self.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=2)
        if self.process.stdout:
            self.process.stdout.close()
        self.stderr.close()


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value


def parse_action(raw, decision_id):
    if not isinstance(raw, str) or len(raw) > 65_536:
        raise ValueError("invalid response size")
    action = json.loads(raw, object_pairs_hook=_unique_object,
                        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
    if not isinstance(action, dict) or set(action) - {"decision", "answer", "reason"}:
        raise ValueError("invalid action fields")
    if action.get("decision") != decision_id or "answer" not in action:
        raise ValueError("wrong decision")
    if "reason" in action and (not isinstance(action["reason"], str) or len(action["reason"]) > 4000):
        raise ValueError("invalid reason")
    return action


def usage_view(value):
    keys = {"prompt_tokens", "completion_tokens", "total_tokens", "prompt_cache_hit_tokens", "prompt_cache_miss_tokens"}
    return {key: item for key, item in (value or {}).items()
            if key in keys and type(item) is int and item >= 0}


def client_audit(client):
    """Explicit allowlist; never serialize client/config objects or credentials."""
    attempts = []
    for item in getattr(client, "last_provider_attempts", ()):
        attempts.append({key: deepcopy(item[key]) for key in (
            "provider_attempt", "response_model", "finish_reason", "visible_content"
        ) if key in item} | {"usage": usage_view(item.get("usage"))})
    return {
        "model": getattr(client, "last_response_model", None) or getattr(client, "model", None),
        "usage": usage_view(getattr(client, "last_usage", None)),
        "provider_attempts": attempts,
        "provider_responses": [{key: deepcopy(item[key]) for key in (
            "provider_attempt", "text", "response_model", "finish_reason"
        ) if key in item} for item in getattr(client, "last_provider_responses", ())],
    }


def public_replay(value, *, version, problem_id, failed=False):
    """A failed walk may stop at D1-D3, before the AI has picked any route; only a completed walk needs one."""
    routes = value.get("routes")
    if (value.get("bundleVersion") != version or value.get("problemId") != problem_id
            or not isinstance(routes, list) or (not routes and not failed) or not set(routes) <= ROUTES.keys()
            or len(set(routes)) != len(routes) or not isinstance(value.get("actions"), list)):
        raise BridgeError("bridge.replay_binding_mismatch")
    actions = []
    for action in value["actions"]:
        if isinstance(action, dict) and set(action) == {"switch_route"} and action["switch_route"] in routes:
            actions.append({"switch_route": action["switch_route"]})
            continue
        if not isinstance(action, dict) or not {"decision", "answer"} <= action.keys():
            raise BridgeError("bridge.invalid_replay_action")
        actions.append({key: deepcopy(action[key]) for key in ("decision", "answer", "reason") if key in action})
    return {"schemaVersion": 2, "bundleVersion": version, "problemId": problem_id,
            "routes": list(routes), "actions": actions,
            "status": "failed" if failed else value["status"]}


def record_walk(bundle, output, client, *, max_corrections=2, max_turns=60,
                call_timeout=120, bridge_factory=NodeBridge):
    """The AI chooses its own first route; the bridge then switches to each remaining route."""
    call_timeout = positive_seconds(call_timeout)
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    bridge = bridge_factory(output / "bridge.stderr.log")
    state = None
    calls = []
    failure = None
    attempts = {}
    try:
        state = bridge.request({"op": "init", "bundle": str(bundle.resolve())})
        version, problem_id = state["bundleVersion"], state["problemId"]
        write_json(output / "binding.json", {"bundleVersion": version, "problemId": problem_id})
        while not state.get("done"):
            if state.get("nextRoute"):
                state = bridge.request({"op": "switch"})
                continue
            decision = state.get("decision")
            if not isinstance(decision, dict) or not isinstance(decision.get("id"), str):
                raise BridgeError("bridge.missing_decision")
            decision_id = decision["id"]
            number = attempts.get(decision_id, 0) + 1
            if number > 1 + max_corrections:
                failure = "actor.corrections_exhausted"
                break
            if len(calls) >= max_turns:
                failure = "actor.turn_limit"
                break
            attempts[decision_id] = number
            payload = {"messages": [{"role": "system", "content": SYSTEM},
                                    {"role": "user", "content": json.dumps(decision, ensure_ascii=False)}]}
            call = {"decision": decision_id, "attempt": number, "input": deepcopy(payload),
                    "call_timeout_seconds": call_timeout}
            calls.append(call)
            # Persist before the paid request: an interrupted attempt is visible.
            call_path = output / f"call-{len(calls):03d}.json"
            write_json(call_path, {**call, "status": "started"})
            started = time.monotonic()
            try:
                raw = complete_with_deadline(client, payload, call_timeout)
                call.update(raw=raw, **client_audit(client))
            except Exception as error:  # noqa: BLE001 -- redact provider errors before persisting
                # SDK error strings can contain request headers. Keep only type.
                call.update(error_type=type(error).__name__, **client_audit(client))
                failure = "actor.provider_timeout" if isinstance(error, CallTimeoutError) else "actor.provider_failed"
                call.update(status="failed", duration_seconds=time.monotonic() - started)
                write_json(call_path, call)
                break
            call["duration_seconds"] = time.monotonic() - started
            try:
                action = parse_action(raw, decision_id)
            except (ValueError, TypeError, RecursionError):
                call["parse_error"] = "actor.invalid_json_action"
                action = {"decision": decision_id, "answer": None, "reason": "模型响应无法解析"}
            call["action"] = action
            write_json(call_path, {**call, "status": "received"})
            # The Node state machine, never this recorder or LLM, decides success.
            state = bridge.request({"op": "answer", "action": action})
            call.update(status="answered", feedback=deepcopy(state.get("feedback")))
            write_json(call_path, call)
        if state.get("status") != "completed":
            failure = failure or "actor.incomplete"
        replay = public_replay(bridge.request({"op": "export"}), version=version,
                               problem_id=problem_id, failed=bool(failure))
        if not failure and not bridge.request({"op": "validate_replay", "replay": replay}).get("valid"):
            raise BridgeError("bridge.invalid_completed_replay")
        write_json(output / "replay.json", replay)
        summary = {"routes": replay["routes"], "bundleVersion": version, "problemId": problem_id,
                   "status": replay["status"], "calls": len(calls), "failure": failure,
                   "usage": {key: sum(call.get("usage", {}).get(key, 0) for call in calls)
                             for key in ("prompt_tokens", "completion_tokens", "total_tokens")}}
        write_json(output / "summary.json", summary)
        return replay, summary
    except Exception as error:
        write_json(output / "failure.json", {"error_type": type(error).__name__, "calls": len(calls),
                                             "last_state": state})
        raise
    finally:
        bridge.close()


def publish_replay(directory, replay, *, recorder="DeepSeek"):
    """Publish only the small replay contract, never private requests/answers keys.
    The index holds exactly one walk; files listed by the previous index are removed."""
    if replay.get("status") != "completed":
        raise ValueError("only completed recordings can be published")
    directory.mkdir(parents=True, exist_ok=True)
    version = replay["bundleVersion"]
    digest = sha256(json.dumps(replay, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()[:12]
    # A second recording of the same bundle must not overwrite the file that the
    # old index still points to if publishing the new index fails.
    name = f"walk-{version[:12]}-{digest}.json"
    index_path = directory / "index.json"
    old = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {}
    write_json(directory / name, replay, private=False)
    label = " → ".join(ROUTES[route] for route in replay["routes"]) or "未选定路线"
    index = {"bundleVersion": version, "replays": [{"label": f"{recorder} · {label}", "recorder": recorder, "path": name,
                                                    "routes": replay["routes"], "status": replay["status"]}]}
    write_json(directory / "index.json", index, private=False)
    for item in old.get("replays", []):
        stale = directory / Path(str(item.get("path", ""))).name
        if stale.name not in {"", "index.json", name} and stale.suffix == ".json" and stale.is_file():
            stale.unlink()
    return index


def build_client(args):
    from shuxueshuo_server.solver.runtime.config import SolverRuntimeConfig

    config = SolverRuntimeConfig.from_sources(llm_provider="deepseek", llm_model=args.model)
    return config.build_llm_client(thinking_effort=args.thinking_effort)


def main(argv=None, *, client_factory=build_client, bridge_factory=NodeBridge):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="new private audit directory, outside site/")
    parser.add_argument("--public-dir", type=Path, default=REPO / "site/data/graph-walk/replays")
    parser.add_argument("--model")
    parser.add_argument("--thinking-effort", choices=("disabled", "low"), default="low")
    parser.add_argument("--max-corrections", type=int, choices=(0, 1, 2), default=2)
    parser.add_argument("--call-timeout", type=positive_seconds, default=120,
                        help="wall-clock seconds per model call, including all SDK retries (Unix main thread)")
    args = parser.parse_args(argv)
    if not args.bundle.is_file():
        parser.error("bundle must be an existing file")
    if args.output.resolve().is_relative_to((REPO / "site").resolve()):
        parser.error("private output cannot be inside site/")
    if (args.public_dir.resolve().is_relative_to(args.output.resolve())
            or args.output.resolve().is_relative_to(args.public_dir.resolve())):
        parser.error("public replay directory must be separate from private output")
    args.output.mkdir(parents=True, exist_ok=False, mode=0o700)
    client = client_factory(args)
    replay, summary = record_walk(args.bundle, args.output / "walk", client,
                                  max_corrections=args.max_corrections, call_timeout=args.call_timeout,
                                  bridge_factory=bridge_factory)
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    write_json(args.output / "summary.json", summary)
    if summary["status"] != "completed":
        return 1
    publish_replay(args.public_dir, replay)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:  # noqa: BLE001 -- CLI must not print credential-bearing SDK errors
        print(f"Actor recording failed: {type(error).__name__}; inspect private output.", file=sys.stderr)
        raise SystemExit(2) from None
