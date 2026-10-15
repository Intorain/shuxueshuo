"""Offline recorder tests: the JS bridge owns grading, not the Python actor."""

import importlib.util
import json
import signal
import sys
import time
from pathlib import Path
from typing import ClassVar

import pytest

FILE = Path(__file__).resolve().parents[2] / "tools/run_graph_walk_actor.py"
spec = importlib.util.spec_from_file_location("graph_walk_actor", FILE)
actor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(actor)

VERSION = "a" * 64
PROBLEM = "quadratic-always-q01"


class FakeClient:
    model = "fake-deepseek"
    api_key = "never-serialize-this-secret"
    last_usage: ClassVar[dict] = {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12, "api_key": api_key}
    last_provider_attempts = ({"provider_attempt": 1, "usage": last_usage, "api_key": api_key},)
    last_provider_responses = ()

    def __init__(self, answers):
        self.answers = iter(answers)
        self.inputs = []

    def complete(self, payload):
        self.inputs.append(payload)
        value = next(self.answers)
        if isinstance(value, Exception):
            raise value
        return value


class FakeBridge:
    instances: ClassVar[list] = []
    legs: ClassVar[tuple] = (("discriminant", ("D1", "D2")),)

    def __init__(self, stderr_path):
        self.actions = []
        self.leg = 0
        self.position = 0
        self.closed = False
        self.feedback = None
        self.instances.append(self)

    def steps(self):
        return self.legs[self.leg][1]

    def state(self):
        route_done = self.position == len(self.steps())
        more = route_done and self.leg + 1 < len(self.legs)
        done = route_done and not more
        return {
            "bundleVersion": VERSION, "problemId": PROBLEM,
            "done": done, "nextRoute": self.legs[self.leg + 1][0] if more else None,
            "status": "completed" if done else "in_progress",
            "feedback": self.feedback,
            "decision": None if route_done else {
                "id": self.steps()[self.position], "question": "选出可用的思路",
                "problem": {"text": "恒成立 Q01", "root": {"facts": ["a∈ℝ"]}},
                "results": [], "interaction": {"options": ["yes", "no"]},
                "answerFormat": "选项 value", "previousFeedback": self.feedback,
            },
        }

    def request(self, payload):
        if payload["op"] == "init":
            assert Path(payload["bundle"]).is_absolute()
            assert "route" not in payload
        elif payload["op"] == "answer":
            action = payload["action"]
            self.actions.append(action)
            passed = action["decision"] == self.steps()[self.position] and action["answer"] == "yes"
            self.feedback = {"status": "passed" if passed else "wrong", "text": "请核对当前条件"}
            if passed:
                self.position += 1
        elif payload["op"] == "switch":
            route = self.state()["nextRoute"]
            assert route
            self.actions.append({"switch_route": route})
            self.leg, self.position, self.feedback = self.leg + 1, 0, None
        elif payload["op"] == "export":
            return {"bundleVersion": VERSION, "problemId": PROBLEM,
                    "routes": [route for route, _ in self.legs[:self.leg + 1]],
                    "actions": self.actions, "status": self.state()["status"],
                    "privateExtra": "must not be published"}
        elif payload["op"] == "validate_replay":
            replay = payload["replay"]
            assert replay["actions"] == self.actions
            return {"valid": self.state()["done"] and replay["status"] == "completed"}
        return self.state()

    def close(self):
        self.closed = True


def answer(decision, value="yes"):
    return json.dumps({"decision": decision, "answer": value, "reason": "根据题设"})


@pytest.fixture
def bundle(tmp_path):
    path = tmp_path / "bundle.json"
    path.write_text(json.dumps({"version": VERSION, "expected": "must-not-go-to-model"}))
    return path


def record(bundle, tmp_path, client, bridge=FakeBridge, **kwargs):
    return actor.record_walk(bundle, tmp_path / "private", client, bridge_factory=bridge, **kwargs)


class TwoRouteBridge(FakeBridge):
    legs: ClassVar[tuple] = (("discriminant", ("D1", "D2")), ("extremum", ("E1",)))


def test_record_uses_projected_input_and_exports_only_replay_contract(bundle, tmp_path):
    client = FakeClient([answer("D1"), answer("D2")])
    replay, summary = record(bundle, tmp_path, client)
    assert replay["status"] == "completed"
    assert summary["calls"] == 2
    assert summary["usage"] == {"prompt_tokens": 20, "completion_tokens": 4, "total_tokens": 24}
    assert set(replay) == {"schemaVersion", "bundleVersion", "problemId", "routes", "actions", "status"}
    assert FakeBridge.instances[-1].closed
    audit = (tmp_path / "private/call-001.json").read_text()
    assert "raw" in audit and "input" in audit and "duration_seconds" in audit
    assert "never-serialize-this-secret" not in audit
    assert "must-not-go-to-model" not in json.dumps(client.inputs)
    assert "expected" not in json.dumps(client.inputs)
    assert (tmp_path / "private/call-001.json").stat().st_mode & 0o077 == 0


def test_finished_route_switches_to_the_remaining_route_without_a_model_call(bundle, tmp_path):
    client = FakeClient([answer("D1"), answer("D2"), answer("E1")])
    replay, summary = record(bundle, tmp_path, client, bridge=TwoRouteBridge)
    assert replay["status"] == "completed"
    assert replay["routes"] == ["discriminant", "extremum"]
    assert summary["routes"] == ["discriminant", "extremum"]
    assert summary["calls"] == 3
    assert replay["actions"][2] == {"switch_route": "extremum"}
    assert [action.get("decision") for action in replay["actions"]] == ["D1", "D2", None, "E1"]


def test_wrong_answers_use_bridge_feedback_and_keep_attempts(bundle, tmp_path):
    client = FakeClient([answer("D1", "no"), answer("D1"), answer("D2")])
    replay, summary = record(bundle, tmp_path, client)
    assert summary["calls"] == 3
    assert len(replay["actions"]) == 3
    second_input = json.loads(client.inputs[1]["messages"][1]["content"])
    assert second_input["id"] == "D1"
    assert second_input["previousFeedback"]["status"] == "wrong"


def test_three_failed_answers_stop_and_preserve_failed_replay(bundle, tmp_path):
    client = FakeClient([answer("D1", "no")] * 4)
    replay, summary = record(bundle, tmp_path, client)
    assert len(client.inputs) == 3
    assert len(replay["actions"]) == 3
    assert replay["status"] == "failed"
    assert summary["failure"] == "actor.corrections_exhausted"


@pytest.mark.parametrize("raw", [
    "not json", '```json\n{}\n```', '[]', '{"decision":"D2","answer":"yes"}',
    '{"decision":"D1","answer":"no","answer":"yes"}',
    '{"decision":"D1","answer":NaN}', '{"decision":"D1","answer":"yes","secret":1}',
    '{"decision":"D1","answer":"yes","reason":[]}',
])
def test_malformed_output_is_a_wrong_attempt_in_shared_bridge(bundle, tmp_path, raw):
    client = FakeClient([raw, answer("D1"), answer("D2")])
    replay, summary = record(bundle, tmp_path, client)
    assert summary["status"] == "completed"
    assert replay["actions"][0]["answer"] is None
    assert replay["actions"][0]["decision"] == "D1"
    audit = json.loads((tmp_path / "private/call-001.json").read_text())
    assert audit["raw"] == raw
    assert audit["parse_error"] == "actor.invalid_json_action"
    assert audit["feedback"]["status"] == "wrong"


def test_provider_failure_does_not_erase_previous_success_or_leak_exception(bundle, tmp_path):
    replay, summary = record(bundle, tmp_path, FakeClient([
        answer("D1"), RuntimeError("Authorization: never-serialize-this-secret")]))
    assert replay["status"] == "failed"
    assert len(replay["actions"]) == 1
    assert summary["failure"] == "actor.provider_failed"
    audit = (tmp_path / "private/call-002.json").read_text()
    assert "RuntimeError" in audit
    assert "Authorization" not in audit and "never-serialize-this-secret" not in audit


def test_turn_limit_stops_without_an_extra_model_call(bundle, tmp_path):
    client = FakeClient([answer("D1"), answer("D2")])
    replay, summary = record(bundle, tmp_path, client, max_turns=1)
    assert summary["failure"] == "actor.turn_limit"
    assert len(client.inputs) == 1
    assert replay["status"] == "failed"


def test_cli_records_one_walk_and_public_index_without_private_fields(bundle, tmp_path, capsys):
    output, public = tmp_path / "audit", tmp_path / "published"
    public.mkdir()
    (public / "old-route.json").write_text("{}")
    (public / "unrelated.json").write_text("{}")
    (public / "index.json").write_text(json.dumps({"bundleVersion": "old", "replays": [{"path": "old-route.json"}]}))
    result = actor.main(["--bundle", str(bundle), "--output", str(output), "--public-dir", str(public)],
                       client_factory=lambda _: FakeClient([answer("D1"), answer("D2"), answer("E1")]),
                       bridge_factory=TwoRouteBridge)
    assert result == 0
    index = json.loads((public / "index.json").read_text())
    assert index["bundleVersion"] == VERSION
    assert [item["routes"] for item in index["replays"]] == [["discriminant", "extremum"]]
    assert index["replays"][0]["label"] == "DeepSeek · 判别式法 → 分离参数法"
    assert not (public / "old-route.json").exists()
    assert (public / "unrelated.json").exists()
    for item in index["replays"]:
        value = json.loads((public / item["path"]).read_text())
        assert value["status"] == "completed"
        assert not {"input", "raw", "feedback", "privateExtra", "usage", "model"} & value.keys()
    assert "never-serialize-this-secret" not in capsys.readouterr().out
    with pytest.raises(FileExistsError):
        actor.main(["--bundle", str(bundle), "--output", str(output), "--public-dir", str(public)])


def test_cli_refuses_private_audit_under_site_before_loading_credentials(bundle, monkeypatch):
    with pytest.raises(SystemExit) as raised:
        actor.main(["--bundle", str(bundle), "--output", str(actor.REPO / "site/actor-audit")],
                   client_factory=lambda _: pytest.fail("must not load client"))
    assert raised.value.code == 2


@pytest.mark.parametrize("private_inside", [True, False])
def test_cli_refuses_overlapping_public_private_directories(bundle, tmp_path, private_inside):
    base, child = tmp_path / "data", tmp_path / "data/nested"
    private, public = (child, base) if private_inside else (base, child)
    with pytest.raises(SystemExit):
        actor.main(["--bundle", str(bundle), "--output", str(private), "--public-dir", str(public)],
                   client_factory=lambda _: pytest.fail("must not load client"))


def test_node_bridge_json_lines_and_process_cleanup(tmp_path):
    program = "import sys,json\nfor line in sys.stdin:\n print(json.dumps({'echo':json.loads(line)}),flush=True)\n"
    bridge = actor.NodeBridge(tmp_path / "stderr", command=[sys.executable, "-c", program])
    try:
        assert bridge.request({"x": "数学"}) == {"echo": {"x": "数学"}}
        assert bridge.request({"op": "export"}) == {"echo": {"op": "export"}}
    finally:
        bridge.close()
    assert bridge.process.poll() == 0


def test_node_bridge_rejects_protocol_errors(tmp_path):
    program = "import sys\nfor line in sys.stdin:\n print('not json',flush=True)\n"
    bridge = actor.NodeBridge(tmp_path / "stderr", command=[sys.executable, "-c", program])
    try:
        with pytest.raises(actor.BridgeError):
            bridge.request({"op": "init"})
    finally:
        bridge.close()


def test_node_bridge_timeout_includes_incomplete_line(tmp_path):
    program = "import sys,time\nsys.stdin.readline()\nsys.stdout.write('{');sys.stdout.flush()\ntime.sleep(.2)\n"
    bridge = actor.NodeBridge(tmp_path / "stderr", command=[sys.executable, "-c", program], timeout=.03)
    try:
        with pytest.raises(actor.BridgeError, match="bridge.timeout"):
            bridge.request({"op": "init"})
    finally:
        bridge.close()


def test_failure_before_any_route_still_exports_a_failed_replay(tmp_path):
    real = actor.REPO / "site/data/graph-walk/quadratic-always-q01.json"
    wrong = json.dumps({"decision": "D1", "answer": ["every"], "reason": "只看量词"})
    replay, summary = actor.record_walk(real, tmp_path / "private", FakeClient([wrong] * 3))
    assert replay["routes"] == []
    assert replay["status"] == "failed"
    assert [action["decision"] for action in replay["actions"]] == ["D1"] * 3
    assert summary["failure"] == "actor.corrections_exhausted"
    assert (tmp_path / "private/replay.json").exists() and (tmp_path / "private/summary.json").exists()
    with pytest.raises(ValueError, match="only completed"):
        actor.publish_replay(tmp_path / "public", replay)
    assert not (tmp_path / "public").exists()


def test_public_replay_requires_a_route_only_when_completed():
    value = {"bundleVersion": VERSION, "problemId": PROBLEM, "routes": [], "actions": [], "status": "in_progress"}
    assert actor.public_replay(value, version=VERSION, problem_id=PROBLEM, failed=True)["routes"] == []
    with pytest.raises(actor.BridgeError):
        actor.public_replay({**value, "status": "completed"}, version=VERSION, problem_id=PROBLEM)


def test_public_replay_rejects_mismatched_bundle():
    with pytest.raises(actor.BridgeError):
        actor.public_replay({"bundleVersion": "wrong", "routes": ["discriminant"], "actions": []},
                            version=VERSION, problem_id=PROBLEM)


@pytest.mark.parametrize("value", [
    {"routes": ["nowhere"], "actions": []},
    {"routes": ["discriminant", "discriminant"], "actions": []},
    {"routes": ["discriminant"], "actions": [{"switch_route": "extremum"}]},
])
def test_public_replay_rejects_unknown_or_unwalked_routes(value):
    with pytest.raises(actor.BridgeError):
        actor.public_replay({"bundleVersion": VERSION, "problemId": PROBLEM, "status": "completed", **value},
                            version=VERSION, problem_id=PROBLEM)


def test_deadline_escapes_sdk_style_exception_retry_and_saves_failure(bundle, tmp_path):
    class RetryingClient:
        retries = 0

        def complete(self, payload):
            while True:
                try:
                    time.sleep(5)
                    return answer("D1")
                except Exception:  # noqa: BLE001 -- reproduce SDK retry handlers
                    self.retries += 1

    client = RetryingClient()
    handler = signal.getsignal(signal.SIGALRM)
    started = time.monotonic()
    replay, summary = record(bundle, tmp_path, client, call_timeout=.05)
    assert time.monotonic() - started < 1
    assert client.retries == 0
    assert replay["status"] == "failed" and replay["actions"] == []
    assert summary["failure"] == "actor.provider_timeout"
    audit = json.loads((tmp_path / "private/call-001.json").read_text())
    assert audit["status"] == "failed" and audit["error_type"] == "CallTimeoutError"
    assert audit["call_timeout_seconds"] == .05
    assert signal.getsignal(signal.SIGALRM) == handler
    assert signal.getitimer(signal.ITIMER_REAL) == (0, 0)
    assert FakeBridge.instances[-1].closed
    # The alarm is also removed on normal return and on ordinary provider errors.
    assert actor.complete_with_deadline(FakeClient(["ok"]), {}, .05) == "ok"
    with pytest.raises(ValueError):
        actor.complete_with_deadline(FakeClient([ValueError("failed")]), {}, .05)
    assert signal.getsignal(signal.SIGALRM) == handler
    assert signal.getitimer(signal.ITIMER_REAL) == (0, 0)


def test_real_sdk_dripping_response_cannot_extend_total_deadline(bundle, tmp_path):
    import httpx
    from openai import OpenAI

    from shuxueshuo_server.solver.runtime.llm_clients import DeepSeekPlannerClient

    class DrippingBody(httpx.SyncByteStream):
        closed = False
        chunks = 0

        def __iter__(self):
            for _ in range(100):
                self.chunks += 1
                yield b" "
                time.sleep(.02)

        def close(self):
            self.closed = True

    body, requests = DrippingBody(), []
    warming_up = True

    def respond(request):
        if warming_up:
            return httpx.Response(200, json={"id": "offline", "object": "chat.completion", "created": 0,
                "model": "offline-test", "choices": [{"index": 0, "finish_reason": "stop",
                    "message": {"role": "assistant", "content": "{}"}}]})
        requests.append(request)
        return httpx.Response(200, headers={"Content-Type": "application/json"}, stream=body)

    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        client = DeepSeekPlannerClient(api_key="offline-test", base_url="https://offline.invalid/v1",
            model="offline-test", sdk_max_retries=2,
            client_factory=lambda **kwargs: OpenAI(**kwargs, http_client=http))
        # Complete lazy SDK imports before measuring the deliberately short deadline.
        client.complete({"messages": [{"role": "user", "content": "offline warmup"}]})
        warming_up = False
        started = time.monotonic()
        _, summary = record(bundle, tmp_path, client, call_timeout=.15)
    assert time.monotonic() - started < 1
    assert summary["failure"] == "actor.provider_timeout"
    assert len(requests) == 1 and body.chunks > 1 and body.closed


@pytest.mark.parametrize("timeout", ["0", "-1", "nan", "inf"])
def test_cli_rejects_invalid_timeout_before_loading_credentials(bundle, tmp_path, timeout):
    with pytest.raises(SystemExit) as raised:
        actor.main(["--bundle", str(bundle), "--output", str(tmp_path / "audit"),
                    "--call-timeout", timeout],
                   client_factory=lambda _: pytest.fail("must not load client"))
    assert raised.value.code == 2
    assert not (tmp_path / "audit").exists()


@pytest.mark.parametrize("same_version", [True, False])
@pytest.mark.parametrize("failure", ["timeout", "wrong"])
def test_failed_cli_keeps_successful_publication_byte_for_byte(bundle, tmp_path, same_version, failure):
    public = tmp_path / "public"
    args = ["--bundle", str(bundle), "--public-dir", str(public)]
    assert actor.main([*args, "--output", str(tmp_path / "first")],
        client_factory=lambda _: FakeClient([answer("D1"), answer("D2"), answer("E1")]),
        bridge_factory=TwoRouteBridge) == 0
    index = json.loads((public / "index.json").read_text())
    if not same_version:
        previous = json.loads((public / index["replays"][0]["path"]).read_text())
        previous["bundleVersion"] = "b" * 64
        actor.publish_replay(public, previous)
    before = {p.name: p.read_bytes() for p in public.iterdir()}
    answers = [actor.CallTimeoutError("timeout")] if failure == "timeout" else [answer("D1", "no")] * 3
    assert actor.main([*args, "--output", str(tmp_path / "failed")],
        client_factory=lambda _: FakeClient(answers), bridge_factory=TwoRouteBridge) == 1
    assert {p.name: p.read_bytes() for p in public.iterdir()} == before
    summary = json.loads((tmp_path / "failed/summary.json").read_text())
    assert summary["status"] == "failed"
    assert (tmp_path / "failed/walk/replay.json").exists()


def test_index_write_failure_preserves_previous_recording_of_same_bundle(bundle, tmp_path, monkeypatch):
    replay, _ = record(bundle, tmp_path, FakeClient([answer("D1"), answer("D2")]))
    public = tmp_path / "public"
    index = actor.publish_replay(public, replay)
    previous = {p.name: p.read_bytes() for p in public.iterdir()}
    replay["actions"][0]["reason"] = "a different recording of the same bundle"
    write_json = actor.write_json

    def fail_index(path, value, **kwargs):
        if path.name == "index.json":
            raise OSError("simulated index write failure")
        write_json(path, value, **kwargs)

    monkeypatch.setattr(actor, "write_json", fail_index)
    with pytest.raises(OSError, match="index write failure"):
        actor.publish_replay(public, replay)
    assert all((public / name).read_bytes() == data for name, data in previous.items())
    assert (public / index["replays"][0]["path"]).exists()


def test_publisher_attributes_assistant_authored_recordings(bundle, tmp_path):
    replay, _ = record(bundle, tmp_path, FakeClient([answer("D1"), answer("D2")]))
    index = actor.publish_replay(tmp_path / "public", replay, recorder="Codex")
    assert index["replays"][0]["recorder"] == "Codex"
    assert index["replays"][0]["label"] == "Codex · 判别式法"


def test_completed_export_must_pass_replay_validation(bundle, tmp_path):
    class InvalidExportBridge(FakeBridge):
        def request(self, payload):
            if payload["op"] == "validate_replay":
                return {"valid": False}
            return super().request(payload)

    with pytest.raises(actor.BridgeError, match="invalid_completed_replay"):
        record(bundle, tmp_path, FakeClient([answer("D1"), answer("D2")]), bridge=InvalidExportBridge)
    assert not (tmp_path / "private/replay.json").exists()
    assert FakeBridge.instances[-1].closed


def test_real_bridge_validates_both_completed_routes_and_rejects_corruption(tmp_path):
    path = actor.REPO / "site/data/graph-walk/quadratic-always-q01.json"
    real = json.loads(path.read_text())
    decisions = {d["id"]: d for d in real["intro"] + [d for r in real["routes"].values() for d in r["steps"]]}

    class ScriptedClient:
        def complete(self, payload):
            decision = decisions[json.loads(payload["messages"][1]["content"])["id"]]
            expected = decision["expected_answer"]
            if decision["interaction"]["type"] == "plane":
                method = next(m for m in decision["interaction"]["methods"] if m.get("route") == "discriminant")
                value = [*expected["cell"], method["value"]]
            else:
                value = expected.get("terms", expected.get("required", expected.get("cell")))
                if "one_of" in expected:
                    value = expected["one_of"][0]
            return json.dumps({"decision": decision["id"], "answer": value})

    replay, summary = actor.record_walk(path, tmp_path / "real", ScriptedClient())
    assert summary["status"] == "completed"
    assert set(replay["routes"]) == set(real["routes"])
    bridge = actor.NodeBridge(tmp_path / "validate.log")
    try:
        bridge.request({"op": "init", "bundle": str(path)})
        assert bridge.request({"op": "validate_replay", "replay": replay}) == {"valid": True}
        replay["actions"].pop()
        with pytest.raises(actor.BridgeError):
            bridge.request({"op": "validate_replay", "replay": replay})
    finally:
        bridge.close()
