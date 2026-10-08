"""Real PostgreSQL: first answers, reversible mastery and original evidence."""

from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from test_auth import login

from shuxueshuo_server.learning import drills, practice
from shuxueshuo_server.product.db import transaction
from shuxueshuo_server.tutor_demo.session import Event, Session, load_lesson

NODE = "amgm-formula"
PID = "basic-inequality-q01"


def test_practice_route_conflict_requires_explicit_choice(client, auth, phone):
    user = UUID(login(client, auth, phone).json()["user"]["id"])
    first_route, other_route = list(load_lesson(PID)["routes"])[:2]
    original = practice.start(auth.db, user, PID, first_route, uuid4())
    requested_id = str(uuid4())
    payload = {"id": requested_id, "problem_id": PID, "route_id": other_route}
    for _ in range(2):
        response = client.post("/api/learning/practice", json=payload)
        assert response.status_code == 409
        assert response.json()["detail"] == {
            "code": "practice_route_conflict",
            "message": "本题已有进行中的练习，请选择继续原路线或重新开始。",
            "current_attempt": {"id": str(original["id"]), "route_id": first_route},
        }
    assert (
        client.get(f"/api/learning/practice/{original['id']}").json()["status"]
        == "in_progress"
    )
    # Continuing the original route neither replaces nor creates an attempt.
    assert (
        practice.start(auth.db, user, PID, first_route, uuid4())["id"] == original["id"]
    )
    replacement = client.post(
        "/api/learning/practice",
        json={
            **payload,
            "previous_attempt_id": str(original["id"]),
        },
    )
    assert replacement.status_code == 200
    assert replacement.json()["id"] == requested_id
    assert replacement.json()["route_id"] == other_route
    assert (
        client.get(f"/api/learning/practice/{original['id']}").json()["status"]
        == "closed"
    )
    # A stale tab cannot close the newly chosen attempt, even using a prior ID.
    with pytest.raises(HTTPException) as error:
        practice.start(auth.db, user, PID, first_route, uuid4(), original["id"])
    assert error.value.status_code == 409
    assert error.value.detail["current_attempt"]["id"] == requested_id


def start(client, node=NODE, previous=None):
    r = client.post(
        "/api/learning/drills",
        json={"id": str(uuid4()), "node_id": node, "previous_attempt_id": previous},
    )
    assert r.status_code == 200, r.text
    return r.json()


def spec(auth, item, node=NODE):
    with transaction(auth.db) as c:
        row = (
            c.execute(
                text(
                    "SELECT answer_spec,options FROM knowledge_drill_items WHERE node_id=:n AND item_id=:i"
                ),
                {"n": node, "i": item["item_id"]},
            )
            .mappings()
            .one()
        )
        return [
            f"option-{i}"
            for i, o in enumerate(row["options"], 1)
            if o["value"] in row["answer_spec"]["selected"]
        ]


def state(client):
    return next(
        n
        for n in client.get("/api/learning/nodes").json()["nodes"]
        if n["node_id"] == NODE
    )


def test_round_reversal_only_at_five_and_retry(client, auth, phone):
    login(client, auth, phone)
    assert state(client)["status"] == "unassessed"
    first = start(client)
    assert len(first["items"]) == 5 and len({i["item_id"] for i in first["items"]}) == 5
    assert all("answer" not in i and "explanation" not in i for i in first["items"])
    assert all(
        o["value"].startswith("option-") for i in first["items"] for o in i["options"]
    )
    assert start(client)["id"] == first["id"]
    for i in first["items"]:
        path = f"/api/learning/drills/{first['id']}/answers/{i['position']}"
        payload = {"selected": spec(auth, i)}
        r = client.post(path, json=payload)
        assert r.status_code == 200, r.text
        assert client.post(path, json=payload).json() == r.json()
    assert state(client)["status"] == "mastered"
    second = start(client)
    for index, i in enumerate(second["items"]):
        answer = spec(auth, i)
        if index == 0:
            answer = [
                next(o["value"] for o in i["options"] if o["value"] not in answer)
            ]
        path = f"/api/learning/drills/{second['id']}/answers/{i['position']}"
        assert client.post(path, json={"selected": answer}).status_code == 200
        assert state(client)["status"] == ("needs_review" if index == 4 else "mastered")
        if index == 0:
            assert (
                client.post(path, json={"selected": spec(auth, i)}).status_code == 409
            )
    assert state(client)["correct_count"] == 4
    abandoned = start(client)
    replacement = start(client, previous=abandoned["id"])
    assert state(client)["status"] == "needs_review"
    assert (
        client.get(f"/api/learning/drills/{abandoned['id']}").json()["status"]
        == "closed"
    )
    assert start(client)["id"] == replacement["id"]


def test_parallel_start_and_account_isolation(client, auth, phone):
    user = UUID(login(client, auth, phone).json()["user"]["id"])
    with ThreadPoolExecutor(5) as pool:
        rounds = list(
            pool.map(lambda _: drills.start(auth.db, user, NODE, uuid4()), range(10))
        )
    assert len({r["id"] for r in rounds}) == 1
    aid = str(rounds[0]["id"])
    login(client, auth, "138" + phone[3:])
    assert client.get(f"/api/learning/drills/{aid}").status_code == 404
    assert (
        client.post(
            f"/api/learning/drills/{aid}/answers/1", json={"selected": ["fake"]}
        ).status_code
        == 404
    )
    assert state(client)["status"] == "unassessed"


def test_practice_raw_records_summary_and_help_ack(client, auth, phone):
    user = UUID(login(client, auth, phone).json()["user"]["id"])
    lesson = load_lesson(PID)
    route = next(iter(lesson["routes"]))
    nodes = lesson["routes"][route]["nodes"]
    step = nodes[0]["id"]
    attempt = practice.start(auth.db, user, "q01", route, uuid4())
    aid = attempt["id"]
    assert attempt["problem_id"] == PID
    assert practice.start(auth.db, user, PID, route, uuid4())["id"] == aid
    event = Event(event_id=str(uuid4()), revision=0, kind="help")
    practice.begin_dialogue(auth.db, user, aid, event, step, PID)
    response = {
        "messages": [{"role": "assistant", "text": "先观察条件。"}],
        "completed": [],
        "learning_intent": "question",
    }
    delivery = UUID(practice.finish_dialogue(auth.db, user, aid, event, step, response))
    with transaction(auth.db) as c:
        assert not practice.result(c, practice.owned(c, aid, user))["steps"]
    practice.acknowledge(auth.db, user, aid, delivery)
    question = event.model_copy(
        update={"event_id": str(uuid4()), "kind": "text", "text": "什么是定和？"}
    )
    practice.begin_dialogue(auth.db, user, aid, question, step, PID)
    practice.finish_dialogue(auth.db, user, aid, question, step, response)
    for node in nodes:
        exp = node["expected_answer"]
        answer = (
            {"value": exp["one_of"][0]}
            if node["interaction"]["type"] == "choice"
            else {
                "terms": exp["terms"],
                **(
                    {"fixed": exp["fixed"]}
                    if node["interaction"]["type"] == "structure"
                    else {}
                ),
            }
        )
        identity = uuid4()
        r = practice.submit(auth.db, user, aid, identity, node["id"], answer)
        assert practice.submit(auth.db, user, aid, identity, node["id"], answer) == r
    assert r["status"] == "completed"
    assert all(s["submit_count"] == 1 for s in r["steps"])
    assert r["steps"][0]["hint_used"]
    assert state(client)["status"] == "unassessed"
    history = client.get(f"/api/learning/practice/{aid}").json()
    assert "criteria" not in next(
        e["payload"] for e in history["events"] if e["event_type"] == "context"
    )
    assert [e["sequence"] for e in history["events"]] == list(
        range(1, len(history["events"]) + 1)
    )
    session = Session(lesson)
    practice.restore_session(auth.db, user, aid, session)
    assert session.state["active"] == len(nodes) and len(session.completed) == len(
        nodes
    )
    assert any(m["text"] == "什么是定和？" for m in session.messages)
    with pytest.raises(Exception) as exc:
        practice.begin_dialogue(
            auth.db, user, aid, question, step, "quadratic-always-q01"
        )
    assert exc.value.status_code == 409


def test_tutor_records_question_answer_and_failed_call(client, app, auth, phone):
    from shuxueshuo_server.tutor_demo.api import create_router
    from shuxueshuo_server.tutor_demo.llm import Proposal, TutorUnavailable
    from tests.tutor_demo.auth_helpers import TeachingOnlyBudget

    class Tutor:
        fail = False

        async def respond(self, **kw):
            if self.fail:
                raise TutorUnavailable("test unavailable")
            return Proposal(
                reply="先比较两项的和与积。", intent="question", evidence=[], actions=[]
            )

    tutor = Tutor()
    app.include_router(create_router(tutor, TeachingOnlyBudget()))
    user = UUID(login(client, auth, phone).json()["user"]["id"])
    lesson = load_lesson(PID)
    route = next(iter(lesson["routes"]))
    step = lesson["routes"][route]["nodes"][0]["id"]
    a = practice.start(auth.db, user, PID, route, uuid4())
    r = client.post(
        "/api/tutor-demo/sessions",
        json={"lesson_id": PID, "practice_attempt_id": str(a["id"])},
    )
    assert r.status_code == 201, r.text
    view = r.json()
    path = f"/api/tutor-demo/sessions/{view['session_id']}/events"
    event = {
        "event_id": str(uuid4()),
        "revision": 0,
        "kind": "text",
        "text": "为什么先判断和与积？",
        "practice_attempt_id": str(a["id"]),
        "practice_step_id": step,
    }
    response = client.post(path, json=event)
    assert response.status_code == 200, response.text
    assert client.post(path, json=event).json() == response.json()
    assert response.json()["learning_delivery"]["attempt_id"] == str(a["id"])
    assert not client.get(f"/api/learning/practice/{a['id']}").json()["steps"]
    tutor.fail = True
    event.update(
        event_id=str(uuid4()), revision=response.json()["revision"], text="请再解释一下"
    )
    assert client.post(path, json=event).status_code == 503
    history = client.get(f"/api/learning/practice/{a['id']}").json()
    assert len([e for e in history["events"] if e["event_type"] == "message"]) == 3
    assert history["events"][-1]["payload"]["text"] == "请再解释一下"


@pytest.mark.live_llm
@pytest.mark.skipif(
    __import__("os").getenv("RUN_LLM_INTEGRATION") != "1",
    reason="explicit live LLM opt in",
)
def test_live_tutor_persists_original_dialogue(client, app, auth, phone):
    from pathlib import Path

    from dotenv import load_dotenv

    from shuxueshuo_server.tutor_demo.api import create_router
    from tests.tutor_demo.auth_helpers import TeachingOnlyBudget

    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    app.include_router(create_router(budget=TeachingOnlyBudget()))
    user = UUID(login(client, auth, phone).json()["user"]["id"])
    lesson = load_lesson(PID)
    route = "direct"
    n = lesson["routes"][route]["nodes"][0]
    a = practice.start(auth.db, user, PID, route, uuid4())
    r = client.post(
        "/api/tutor-demo/sessions",
        json={"lesson_id": PID, "practice_attempt_id": str(a["id"])},
    )
    assert r.status_code == 201, r.text
    view = r.json()
    path = f"/api/tutor-demo/sessions/{view['session_id']}/events"
    event = {
        "event_id": str(uuid4()),
        "revision": 0,
        "kind": "help",
        "practice_attempt_id": str(a["id"]),
        "practice_step_id": n["id"],
    }
    r = client.post(path, json=event)
    assert r.status_code == 200, r.text
    response = r.json()
    delivery = response["learning_delivery"]
    assert response["messages"][-1]["text"]
    assert (
        client.post(
            f"/api/learning/practice/{a['id']}/displayed/{delivery['event_id']}",
            json={},
        ).status_code
        == 200
    )
    history = client.get(f"/api/learning/practice/{a['id']}").json()
    hints = [e for e in history["events"] if e["event_type"] == "hint"]
    assert (
        len(hints) == 1
        and hints[0]["payload"]["text"] == response["messages"][-1]["text"]
        and hints[0]["displayed_at"] is not None
    )
    assert not history["steps"] and state(client)["status"] == "unassessed"

    event.update(
        event_id=str(uuid4()),
        revision=response["revision"],
        kind="text",
        text="m、n 都是正数，m+n=2 是定值，所以是定和求积，选择 m 和 n。",
    )
    answered = client.post(path, json=event)
    assert answered.status_code == 200, answered.text
    assert answered.json()["state"]["active"] == 1, answered.json()["messages"][-1]
    assert client.post(path, json=event).json() == answered.json()
    history = client.get(f"/api/learning/practice/{a['id']}").json()
    step = history["steps"][0]
    assert step["passed"] and step["submit_count"] == 1
    assert step["hint_used"] and step["last_grading_source"] == "llm"
    assert state(client)["status"] == "unassessed"


def test_all_authored_routes_rule_recording(client, auth, phone):
    from shuxueshuo_server.learning.content import ROOT

    user = UUID(login(client, auth, phone).json()["user"]["id"])
    completed = 0
    for path in sorted(
        (ROOT / "server/shuxueshuo_server/tutor_demo/lessons").glob("*.json")
    ):
        lesson = load_lesson(path.stem)
        for route, config in lesson["routes"].items():
            a = practice.start(auth.db, user, lesson["id"], route, uuid4())
            for node in config["nodes"]:
                exp = node["expected_answer"]
                answer = (
                    {"value": exp["one_of"][0]}
                    if node["interaction"]["type"] == "choice"
                    else {
                        "terms": exp["terms"],
                        **(
                            {"fixed": exp["fixed"]}
                            if node["interaction"]["type"] == "structure"
                            else {}
                        ),
                    }
                )
                a = practice.submit(auth.db, user, a["id"], uuid4(), node["id"], answer)
            assert a["status"] == "completed", (lesson["id"], route, a)
            completed += 1
    assert completed == 50
    assert state(client)["status"] == "unassessed"


def test_shown_reference_is_trusted_and_counts_only_before_passing(client, auth, phone):
    from fastapi import HTTPException

    user = UUID(login(client, auth, phone).json()["user"]["id"])
    a = practice.start(auth.db, user, PID, "direct", uuid4())
    with pytest.raises(HTTPException):
        practice.shown_reference(
            auth.db, user, a["id"], uuid4(), "structure", "method-variable-swap"
        )
    identity = uuid4()
    practice.shown_reference(auth.db, user, a["id"], identity, "structure", NODE)
    practice.shown_reference(auth.db, user, a["id"], identity, "structure", NODE)
    a = practice.submit(
        auth.db,
        user,
        a["id"],
        uuid4(),
        "structure",
        {"terms": ["m", "n"], "fixed": "sum"},
    )
    assert a["steps"][0]["hint_used"]
    assert a["steps"][0]["submit_count"] == 1


@pytest.mark.parametrize("pass_source", ["llm", "rule"])
def test_restore_uses_only_the_answer_linked_to_passing_grade(
    client, auth, phone, pass_source
):
    user = UUID(login(client, auth, phone).json()["user"]["id"])
    lesson = load_lesson(PID)
    aid = practice.start(auth.db, user, PID, "direct", uuid4())["id"]
    wrong = {"terms": ["m", "n"], "fixed": "product"}
    practice.submit(auth.db, user, aid, uuid4(), "structure", wrong)
    before = client.get(f"/api/learning/practice/{aid}").json()
    assert not before["steps"][0]["passed"] and "answer" not in before["steps"][0]
    if pass_source == "llm":
        event = Event(
            event_id=str(uuid4()),
            revision=0,
            kind="text",
            text="m、n都是正数，定和求积。",
        )
        practice.begin_dialogue(auth.db, user, aid, event, "structure", PID)
        practice.finish_dialogue(
            auth.db,
            user,
            aid,
            event,
            "structure",
            {
                "messages": [{"role": "assistant", "text": "是的，这是定和求积。"}],
                "completed": [{"node": "structure", "route": "direct"}],
                "learning_intent": "answer",
            },
        )
        expected = {"terms": ["m", "n"], "fixed": "sum"}
    else:
        # Reversed valid terms must be retained, not silently changed to the standard order.
        expected = {"terms": ["n", "m"], "fixed": "sum"}
        practice.submit(auth.db, user, aid, uuid4(), "structure", expected)
    history = client.get(f"/api/learning/practice/{aid}").json()
    assert history["steps"][0]["passed"]
    assert history["steps"][0]["answer"] == expected
    assert history["steps"][0]["wrong_count"] == 1
    assert history["steps"][0]["last_grading_source"] == pass_source
    assert any(
        e["event_type"] == "answer" and e["payload"] == wrong for e in history["events"]
    )
    session = Session(lesson)
    practice.restore_session(auth.db, user, aid, session)
    assert session.state["active"] == 1
    assert session.state["pairs"][0] == expected["terms"]
    assert session.state["swapped"] is False
    assert len(session.completed) == 1
    # Restoration is a view, not another student submission.
    assert (
        client.get(f"/api/learning/practice/{aid}").json()["events"]
        == history["events"]
    )


def test_display_ack_cannot_rewrite_raw_event_payload(client, auth, phone):
    from sqlalchemy.exc import DBAPIError

    user = UUID(login(client, auth, phone).json()["user"]["id"])
    aid = practice.start(auth.db, user, PID, "direct", uuid4())["id"]
    event = Event(event_id=str(uuid4()), revision=0, kind="help")
    practice.begin_dialogue(auth.db, user, aid, event, "structure", PID)
    response = {
        "messages": [{"role": "assistant", "text": "先观察条件。"}],
        "completed": [],
        "learning_intent": "question",
    }
    delivery = UUID(
        practice.finish_dialogue(auth.db, user, aid, event, "structure", response)
    )
    with transaction(auth.db) as c:
        original = practice.one(
            c, "SELECT * FROM student_practice_events WHERE id=:i", i=delivery
        )
        assert original["displayed_at"] is None
        # The real API database role must be denied, even for a no-op payload update.
        with pytest.raises(DBAPIError) as err, c.begin_nested():
            c.execute(
                text("UPDATE student_practice_events SET payload=payload WHERE id=:i"),
                {"i": delivery},
            )
        assert err.value.orig.sqlstate == "42501"
    practice.acknowledge(auth.db, user, aid, delivery)
    history = client.get(f"/api/learning/practice/{aid}").json()
    displayed = next(e for e in history["events"] if e["id"] == str(delivery))
    assert displayed["displayed_at"] is not None
    assert displayed["payload"] == original["payload"]
    practice.acknowledge(auth.db, user, aid, delivery)
    # Retrying the original reply after acknowledgement must remain idempotent.
    assert practice.finish_dialogue(
        auth.db, user, aid, event, "structure", response
    ) == str(delivery)
    assert (
        client.get(f"/api/learning/practice/{aid}").json()["events"]
        == history["events"]
    )
    practice.submit(
        auth.db, user, aid, uuid4(), "structure", {"terms": ["m", "n"], "fixed": "sum"}
    )
    assert client.get(f"/api/learning/practice/{aid}").json()["steps"][0]["hint_used"]
