"""Supported infinite endpoint mistakes use bounded, item-scoped repairs."""

import json
from copy import deepcopy

import pytest
from _math_notation_test_support import Recorded

from shuxueshuo_server.graph_lesson.stage_one import runner
from shuxueshuo_server.graph_lesson.stage_one.evaluation import read_json

CONFIRMED = {"status": "confirmed", "findings": []}


class Sequence(Recorded):
    """Prepare real requests while returning only authored offline responses."""

    def __init__(self, *responses):
        super().__init__("")
        self.responses = list(responses)
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        if not self.responses:
            raise AssertionError("unexpected additional provider call")
        self.text = json.dumps(self.responses.pop(0), ensure_ascii=False)
        return super().complete(request)


def candidates(domain):
    correct = read_json(runner.CORPUS / "q06/notation.gold.json")
    incorrect = deepcopy(correct)
    incorrect["root"]["facts"][1] = incorrect["root"]["facts"][1].replace(
        "(-∞,0)", domain
    )
    return incorrect, correct


def run(tmp_path, provider):
    output = tmp_path / "sample"
    summary = runner.run_sample(
        "q06", output, provider, run_id="offline-infinity-repair"
    )
    return summary, read_json(output / "workflow/workflow-result.json")


@pytest.mark.parametrize(
    "domain,code",
    [
        ("[-∞,0)", "type.closed_infinite_endpoint"),
        ("(+∞,0)", "type.infinite_endpoint_direction"),
        ("(-∞,-∞)", "type.infinite_endpoint_direction"),
    ],
)
def test_infinite_endpoint_errors_are_repaired_then_source_reviewed(
    tmp_path, domain, code
):
    incorrect, correct = candidates(domain)
    provider = Sequence(incorrect, correct, CONFIRMED)
    summary, workflow = run(tmp_path, provider)

    assert summary["passed"], workflow
    assert workflow["status"] == "reviewed_candidate"
    assert workflow["source_reviewed"]
    assert workflow["candidate"] == correct
    assert [event["stage"] for event in workflow["events"]] == [
        "extract", "repair", "review"
    ]
    assert provider.calls == 3
    assert summary["repair_calls"] == summary["review_calls"] == 1
    repair = json.loads(provider.requests[1].prompt.user_prefix)
    assert repair["base_candidate"] == incorrect
    assert [
        (item["code"], item["path"], item["action"])
        for item in repair["diagnostics"]
    ] == [(code, "/root/facts/1", "repair")]
    assert json.loads(provider.requests[2].prompt.user_prefix)["candidate"] == correct


def test_endpoint_repair_rejects_an_unrelated_condition_change(tmp_path):
    incorrect, correct = candidates("[-∞,0)")
    unrelated_edit = deepcopy(correct)
    unrelated_edit["root"]["facts"][0] = "a>0"
    provider = Sequence(incorrect, unrelated_edit, correct, CONFIRMED)
    summary, workflow = run(tmp_path, provider)

    assert summary["passed"], workflow
    assert workflow["candidate"] == correct
    assert provider.calls == 4
    rejected = workflow["events"][1]
    assert not rejected["adopted"]
    assert [item["path"] for item in rejected["repair_rejected"]] == [
        "/root/facts/0"
    ]
    for request in provider.requests[1:3]:
        repair = json.loads(request.prompt.user_prefix)
        assert repair["base_candidate"] == incorrect
        assert [item["path"] for item in repair["diagnostics"]] == ["/root/facts/1"]
    assert json.loads(provider.requests[2].prompt.user_prefix)["repair_feedback"][0][
        "code"
    ] == "repair.outside_authorized_path"


def test_infinity_as_a_scalar_does_not_gain_endpoint_repair_authority(tmp_path):
    _, incorrect = candidates("(-∞,0)")
    incorrect["root"]["facts"].append("∞>0")
    provider = Sequence(incorrect)
    summary, workflow = run(tmp_path, provider)

    assert not summary["passed"]
    assert workflow["status"] == "code_gap"
    assert provider.calls == 1
    assert workflow["diagnostics"][0]["code"] == "type.infinity_outside_interval"
    assert workflow["diagnostics"][0]["action"] == "code_gap"
