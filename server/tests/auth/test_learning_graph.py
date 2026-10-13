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

NODE = "method-amgm-direct"
PID = "basic-inequality-q01"


def test_practice_route_conflict_requires_explicit_choice(client, auth, phone):
    user = UUID(login(client, auth, phone).json()["user"]["id"])
    first_route, other_route = list(load_lesson(PID)["routes"])[:2]
    original = practice.start(auth.db, user, PID, first_route, uuid4())
    requested_id = str(uuid4())
    payload = {"id": requested_id, "problem_id": PID, "route_id": other_route,
               "content_version": client.get('/api/learning/content').json()['content_version']}
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
        json={"id": str(uuid4()), "node_id": node, "previous_attempt_id": previous,
              "content_version": client.get('/api/learning/content').json()['content_version']},
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
    for _ in range(8):
        denied = client.post('/api/tutor-demo/sessions', json={
            'lesson_id': PID, 'practice_attempt_id': str(a['id']), 'content_version': 'stale'})
        assert denied.status_code == 409
        assert denied.json()['detail']['code'] == 'learning_content_changed'
    r = client.post(
        "/api/tutor-demo/sessions",
        json={"lesson_id": PID, "practice_attempt_id": str(a["id"]),
              'content_version': a['content_version']},
    )
    assert r.status_code == 201, r.text
    view = r.json()
    assert view['content_version'] == a['content_version']
    assert view['confirmed_choices'] == {}
    path = f"/api/tutor-demo/sessions/{view['session_id']}/events"
    event = {
        "event_id": str(uuid4()),
        "revision": 0,
        "kind": "text",
        "text": "为什么先判断和与积？",
        "practice_attempt_id": str(a["id"]),
        "practice_step_id": step,
    }
    assert client.post(path, json={**event, 'practice_attempt_id': str(uuid4())}).status_code == 409
    response = client.post(path, json=event)
    assert response.status_code == 200, response.text
    assert client.post(path, json=event).json() == response.json()
    assert response.json()["learning_delivery"]["attempt_id"] == str(a["id"])
    assert not client.get(f"/api/learning/practice/{a['id']}").json()["steps"]
    evidence = client.get('/api/learning/nodes/amgm-formula/evidence',
                          params={'entry': 'checklist'}).json()['evidence']
    assert len(evidence) == 1
    assert evidence[0]['attempt_id'] == str(a['id']) and evidence[0]['step_id'] == step
    assert evidence[0]['submit_count'] == 0 and not evidence[0]['passed']
    assert evidence[0]['source'] == 'practice_context'
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
        json={"lesson_id": PID, "practice_attempt_id": str(a["id"]),
              'content_version': a['content_version']},
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
    practice.shown_reference(auth.db, user, a["id"], identity, "structure", 'amgm-formula')
    practice.shown_reference(auth.db, user, a["id"], identity, "structure", 'amgm-formula')
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


def test_content_version_is_public_and_old_pages_cannot_start(client, auth, phone):
    metadata = client.get('/api/learning/content')
    assert metadata.status_code == 200
    assert set(metadata.json()) == {'content_version', 'schema_version', 'counts'}
    assert metadata.json()['schema_version'] == 2
    assert client.get('/api/learning/nodes').status_code == 401
    user = UUID(login(client, auth, phone).json()['user']['id'])
    for path, payload in [
        ('/api/learning/drills', {'node_id': NODE}),
        ('/api/learning/practice', {'problem_id': PID, 'route_id': 'direct'}),
    ]:
        identity = str(uuid4())
        assert client.post(path, json={'id': identity, **payload}).status_code == 422
        response = client.post(path, json={'id': identity, **payload, 'content_version': 'outdated'})
        assert response.status_code == 409
        assert response.json()['detail']['code'] == 'learning_content_changed'
    with transaction(auth.db) as c:
        for table in ('knowledge_drill_attempts', 'student_practice_attempts'):
            assert c.scalar(text(f'SELECT count(*) FROM {table} WHERE user_id=:u'), {'u': user}) == 0


def test_four_ability_types_and_underfilled_pools(client, auth, phone):
    login(client, auth, phone)
    nodes = client.get('/api/learning/nodes').json()['nodes']
    assert {n['kind'] for n in nodes} == {'knowledge', 'skill', 'method', 'problem_type'}
    assert sum(n['eligible'] for n in nodes) == 16
    assert all(n['status'] == 'unassessed' and n['probability'] is None for n in nodes)
    formula = next(n for n in nodes if n['node_id'] == 'amgm-formula')
    assert formula['item_count'] == 1 and not formula['eligible']
    version = client.get('/api/learning/content').json()['content_version']
    for node, status in [('amgm-formula', 409), ('rule-quadratic-method', 422),
                         ('chapter-quadratic-equations-inequalities', 422)]:
        response = client.post('/api/learning/drills', json={
            'id': str(uuid4()), 'node_id': node, 'content_version': version})
        assert response.status_code == status, response.text


def test_progress_counts_contains_and_extensions_without_inferred_mastery(client, auth, phone):
    login(client, auth, phone)
    summary = client.get('/api/learning/progress', params={'scope': 'chapter-quadratic-equations-inequalities'})
    assert summary.status_code == 200, summary.text
    for relation in ('contains', 'extends'):
        group = summary.json()[relation]
        assert group['total'] == len(set(group['node_ids']))
        assert group['total'] == group['statuses']['unassessed']
        assert group['statuses']['mastered'] == 0
        assert sum(g['total'] for g in group['by_kind'].values()) == group['total']
    assert client.get('/api/learning/progress', params={'scope': 'amgm-formula'}).status_code == 404


def test_assessment_replay_uses_fixed_answers_and_is_idempotent(client, auth, phone):
    from shuxueshuo_server.learning import assessment

    user = UUID(login(client, auth, phone).json()['user']['id'])
    round_ = start(client)
    with transaction(auth.db) as c:
        records = c.execute(text('SELECT * FROM knowledge_drill_answers WHERE attempt_id=:a'),
                            {'a': round_['id']}).mappings().all()
        assert all(r['node_id'] == NODE and r['content_hash'] and r['item_snapshot']['answer_spec'] for r in records)
    assert 'item_snapshot' not in str(round_)
    for item in round_['items']:
        client.post(f"/api/learning/drills/{round_['id']}/answers/{item['position']}",
                    json={'selected': spec(auth, item)})
    before = state(client)
    assert before['strategy_version'] == 'drill_round_v1'
    assert before['evidence_position'] == 5 and before['probability'] is None
    assert assessment.rebuild(auth.db, user)['nodes'] == 1
    assert assessment.rebuild(auth.db, user)['nodes'] == 1
    assert state(client) == before


def test_administrative_replay_removes_assessment_without_evidence(client, auth, phone):
    import os

    from shuxueshuo_server.learning import assessment
    from shuxueshuo_server.product.config import Settings
    from shuxueshuo_server.product.db import engine

    user = UUID(login(client, auth, phone).json()['user']['id'])
    settings = Settings.load('local', os.environ['PRODUCT_TEST_DATA_DIR'],
                             os.getenv('PRODUCT_TEST_INSTANCE', 'auth-stage1'))
    migration_db = engine(settings.url('migration'))
    try:
        with transaction(migration_db) as c:
            c.execute(text('''INSERT INTO student_node_assessments
                (user_id,node_id,status,strategy_version,evidence_position,correct_count)
                VALUES(:u,:n,'mastered','damaged_state',0,5)'''), {'u': user, 'n': NODE})
        assert state(client)['status'] == 'mastered'
        assert assessment.rebuild(migration_db, user)['removed'] == 1
        assert state(client)['status'] == 'unassessed'
        assert assessment.rebuild(migration_db, user)['removed'] == 0
    finally:
        migration_db.dispose()


def test_entry_evidence_uses_attempt_snapshot(client, auth, phone):
    user = UUID(login(client, auth, phone).json()['user']['id'])
    attempt = practice.start(auth.db, user, PID, 'direct', uuid4())
    aid = attempt['id']
    practice.submit(auth.db, user, aid, uuid4(), 'structure', {'terms': ['m', 'n'], 'fixed': 'sum'})
    with transaction(auth.db) as c:
        recorded = practice.owned(c, aid, user)['association_snapshot']
        assert recorded['steps']['structure']['refs']
        assert recorded['association_hash']
    evidence = client.get('/api/learning/nodes/amgm-formula/evidence', params={'entry': 'checklist'}).json()
    assert [e['attempt_id'] for e in evidence['evidence']] == [str(aid)]
    assert evidence['evidence'][0]['source'] == 'practice_context'
    assert client.get('/api/learning/nodes/amgm-formula/evidence', params={'entry': 'formula'}).json()['evidence'] == []
    assert all(n['status'] == 'unassessed' for n in client.get('/api/learning/nodes').json()['nodes'])


def test_explainer_without_submission_is_entry_evidence(client, auth, phone):
    user = UUID(login(client, auth, phone).json()['user']['id'])
    attempt = practice.start(auth.db, user, PID, 'direct', uuid4())
    path = '/api/learning/nodes/amgm-formula/evidence'
    assert client.get(path).json()['evidence'] == []
    practice.shown_reference(auth.db, user, attempt['id'], uuid4(), 'structure',
                             'amgm-formula', 'amgm-formula#checklist', 'amgm-semicircle')
    assert client.get(f"/api/learning/practice/{attempt['id']}").json()['steps'] == []
    row, = client.get(path, params={'entry': 'checklist'}).json()['evidence']
    assert row['submit_count'] == row['wrong_count'] == 0
    assert row['hint_used'] and not row['passed'] and row['last_submitted_at'] is None
    assert row['last_activity_at']
    assert row['shown_references'] == [{
        'ref': 'amgm-formula#checklist', 'resource_id': 'amgm-semicircle', 'candidate': False}]
    assert client.get(path, params={'entry': 'formula'}).json()['evidence'] == []
    assert all(n['status'] == 'unassessed' for n in client.get('/api/learning/nodes').json()['nodes'])


def test_candidate_display_is_evidence_but_not_a_chosen_method(client, auth, phone):
    user = UUID(login(client, auth, phone).json()['user']['id'])
    attempt = practice.start(auth.db, user, PID, 'elimination', uuid4())
    aid = attempt['id']
    first = load_lesson(PID)['routes']['elimination']['nodes'][0]
    practice.submit(auth.db, user, aid, uuid4(), first['id'],
                    {'value': first['expected_answer']['one_of'][0]})
    practice.shown_reference(auth.db, user, aid, uuid4(), 'quadratic',
                             'quadratic-function-properties',
                             'quadratic-function-properties#vertex', 'parabola-axis-drag')
    path = '/api/learning/nodes/quadratic-function-properties/evidence'
    row, = client.get(path, params={'entry': 'vertex'}).json()['evidence']
    assert row['step_id'] == 'quadratic' and row['submit_count'] == 0
    assert row['source'] == 'shown_reference'
    assert row['shown_references'][0]['candidate']
    assert 'method-quadratic-extremum' not in row['refs']
    assert client.get('/api/learning/nodes/method-quadratic-extremum/evidence').json()['evidence'] == []
    assert client.get(path, params={'entry': 'forms'}).json()['evidence'] == []
    # Choosing the other branch later must not turn the old candidate display
    # into evidence that the vertex method was actually selected.
    practice.submit(auth.db, user, aid, uuid4(), 'quadratic', {'value': 'square'})
    row, = client.get(path, params={'entry': 'vertex'}).json()['evidence']
    assert row['source'] == 'shown_reference' and row['shown_references'][0]['candidate']
    assert 'method-quadratic-extremum' not in row['refs']
    assert client.get('/api/learning/nodes/method-quadratic-extremum/evidence').json()['evidence'] == []


def test_q30_hint_refuses_unconfirmed_choice_and_accepts_passing_choice(client, auth, phone):
    from shuxueshuo_server.learning.associations import branches

    user = UUID(login(client, auth, phone).json()['user']['id'])
    pid = 'basic-inequality-q30'
    lesson = load_lesson(pid)
    route = next(iter(lesson['routes']))
    attempt = practice.start(auth.db, user, pid, route, uuid4())
    aid = attempt['id']
    for n in lesson['routes'][route]['nodes'][:4]:
        exp = n['expected_answer']
        answer = {'value': exp['one_of'][0]} if n['interaction']['type'] == 'choice' else {
            'terms': exp['terms'], **({'fixed': exp['fixed']} if n['interaction']['type'] == 'structure' else {})}
        practice.submit(auth.db, user, aid, uuid4(), n['id'], answer)
    n = lesson['routes'][route]['nodes'][4]
    tip = branches(attempt['associations']['steps'][n['id']]['tip'])[0]['value']
    args = (auth.db, user, aid, uuid4(), n['id'], tip['ref'].split('#')[0], tip['ref'], tip.get('resource'))
    with pytest.raises(HTTPException) as rejected:
        practice.shown_reference(*args)
    assert rejected.value.status_code == 422
    # Completing the step through the tutor cannot fabricate a rule-selected branch.
    event = Event(event_id=str(uuid4()), revision=0, kind='text', text='这里用和积关系。')
    practice.begin_dialogue(auth.db, user, aid, event, n['id'], pid)
    practice.finish_dialogue(auth.db, user, aid, event, n['id'], {
        'messages': [{'role': 'assistant', 'text': '这一步成立。'}],
        'completed': [{'node': n['id'], 'route': route}], 'learning_intent': 'answer'})
    history = client.get(f'/api/learning/practice/{aid}').json()
    assert n['interaction']['field'] not in history['confirmed_choices']
    assert practice.shown_reference(*args) == {'saved': True}
    history = client.get(f'/api/learning/practice/{aid}').json()
    shown = next(e for e in history['events'] if e['payload'].get('source') == 'node_explainer')
    assert shown['payload']['candidate'] is True
    assert n['interaction']['field'] not in history['confirmed_choices']
    with transaction(auth.db) as c:
        a = practice.owned(c, aid, user)
        assert practice.passed_answers(c, a)[n['id']]  # UI can restore a standard answer.
        assert n['interaction']['field'] not in practice.confirmed_choices(c, a)
    # Start a separate round and submit an actual rule choice.
    attempt = practice.start(auth.db, user, pid, route, uuid4(), aid)
    for n in lesson['routes'][route]['nodes'][:5]:
        exp = n['expected_answer']
        answer = {'value': exp['one_of'][0]} if n['interaction']['type'] == 'choice' else {
            'terms': exp['terms'], **({'fixed': exp['fixed']} if n['interaction']['type'] == 'structure' else {})}
        attempt = practice.submit(auth.db, user, attempt['id'], uuid4(), n['id'], answer)
    assert attempt['confirmed_choices'][n['interaction']['field']] == exp['one_of'][0]
    from shuxueshuo_server.learning.associations import select
    tip = select(attempt['associations']['steps'][n['id']]['tip'], attempt['confirmed_choices'])['actual'][0]['value']
    assert practice.shown_reference(auth.db, user, attempt['id'], uuid4(), n['id'],
                                   tip['ref'].split('#')[0], tip['ref'], tip.get('resource')) == {'saved': True}
