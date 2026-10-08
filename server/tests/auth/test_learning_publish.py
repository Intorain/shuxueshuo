"""Publisher/migration acceptance against a disposable PostgreSQL instance."""

import json
import os
import re
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from shuxueshuo_server.learning.content import ROOT, load_content, publish
from shuxueshuo_server.learning.identity import ALIASES
from shuxueshuo_server.product.config import Settings
from shuxueshuo_server.product.db import engine, transaction


@pytest.mark.parametrize('invalid', [
    'duplicate_node', 'invalid_kind', 'invalid_subtype', 'missing_endpoint',
    'self_edge', 'invalid_relation', 'uses_direction', 'prerequisite_types',
    'duplicate_edge', 'prerequisite_cycle',
])
@pytest.mark.parametrize('entry', ['load', 'publish'])
def test_graph_validation_at_both_entry_points(tmp_path, invalid, entry):
    nodes = [
        {'id': 'k1', 'kind': 'knowledge'}, {'id': 'k2', 'kind': 'knowledge'},
        {'id': 'm', 'kind': 'method', 'subtype': 'technique'},
    ]
    edges = [{'source_id': 'k1', 'target_id': 'k2', 'relation_type': 'prerequisite'}]
    if invalid == 'duplicate_node':
        nodes.append(dict(nodes[0]))
    elif invalid == 'invalid_kind':
        nodes[0]['kind'] = 'other'
    elif invalid == 'invalid_subtype':
        nodes[0]['subtype'] = 'technique'
    elif invalid == 'missing_endpoint':
        edges[0]['source_id'] = 'missing'
    elif invalid == 'self_edge':
        edges[0]['target_id'] = 'k1'
    elif invalid == 'invalid_relation':
        edges[0]['relation_type'] = 'other'
    elif invalid == 'uses_direction':
        edges[0].update(target_id='m', relation_type='uses')
    elif invalid == 'prerequisite_types':
        edges[0]['source_id'] = 'm'
    elif invalid == 'duplicate_edge':
        edges.append(dict(edges[0]))
    else:
        edges.append({'source_id': 'k2', 'target_id': 'k1', 'relation_type': 'prerequisite'})

    if entry == 'publish':
        # Rejection must happen before opening a DB transaction or reading other rows.
        with pytest.raises(ValueError):
            publish(None, {'knowledge_nodes': nodes, 'knowledge_edges': edges})
    else:
        base = tmp_path / 'site/data/knowledge'
        base.mkdir(parents=True)
        (base / 'graph.json').write_text(json.dumps({'nodes': nodes, 'edges': [
            {'from': e['source_id'], 'to': e['target_id'], 'type': e['relation_type']}
            for e in edges
        ]}))
        (base / 'display.json').write_text('{}')
        (base / 'problem-id-aliases.json').write_text(json.dumps(ALIASES))
        # No renderer/lessons are present: graph validation must fail first.
        with pytest.raises(ValueError):
            load_content(tmp_path)


@pytest.mark.parametrize('change', ['tip', 'mapping'])
@pytest.mark.parametrize('route,step_id,branch', [
    ('direct', 'structure', ()),
    ('elimination', 'quadratic', ('vertex', 'n')),
])
def test_load_rejects_unmapped_step_explainers(monkeypatch, change, route, step_id, branch):
    # Mutate real authored input in memory: cover edits to either the page or
    # the topic mapping, including a nested, non-default choice branch.
    pid = 'basic-inequality-q01'
    page_path = ROOT / 'site/1/q01/index.html'
    topic_path = ROOT / 'site/data/knowledge/topics/basic-inequality.json'
    page = page_path.read_text()
    match = re.search(r'id="practice-config">\s*(.*?)</script>', page, re.DOTALL)
    config = json.loads(match[1])
    topic = json.loads(topic_path.read_text())
    step = next(n for n in config['routes'][route] if n['id'] == step_id)
    tip = step['tip']
    for choice in branch:
        tip = tip['options'][choice]
    mapping = topic['problems'][pid]['routes'][route][step_id]
    if change == 'mapping':
        mapping.remove(tip['id'])
    else:
        tip['id'] = 'inequality-properties'
        assert tip['id'] not in mapping
    overrides = {
        page_path: page[:match.start(1)] + json.dumps(config) + page[match.end(1):],
        topic_path: json.dumps(topic),
    }
    read_text = Path.read_text
    monkeypatch.setattr(Path, 'read_text', lambda path, *a, **kw:
                        overrides[path] if path in overrides else read_text(path, *a, **kw))
    message = f"{pid}/{route}/{step_id}: explainer {tip['id']} is missing from the step-node mapping"
    with pytest.raises(ValueError, match=re.escape(message)):
        load_content()


@pytest.fixture
def publisher():
    root = os.getenv("PRODUCT_TEST_DATA_DIR")
    if not root:
        pytest.skip("Requires independent PostgreSQL")
    db = engine(
        Settings.load(
            "local", root, os.getenv("PRODUCT_TEST_INSTANCE", "auth-stage1")
        ).url("migration")
    )
    yield db
    db.dispose()


def test_import_repeat_and_rollback(publisher):
    rows = load_content()
    before = publish(publisher, rows)
    assert publish(publisher, rows) == before
    assert before["practice_problems"] == 39 and before["practice_steps"] == 259
    changed = deepcopy(rows)
    changed["knowledge_nodes"][0]["label"] = "MUST ROLLBACK"
    changed["practice_problems"][0]["problem_data"]["contract_hash"] = "changed"
    with pytest.raises(ValueError, match="teaching contract changed"):
        publish(publisher, changed)
    with transaction(publisher) as c:
        assert (
            c.scalar(
                text("SELECT count(*) FROM knowledge_nodes WHERE label='MUST ROLLBACK'")
            )
            == 0
        )
    invalid = deepcopy(rows)
    invalid["knowledge_edges"].append(
        {
            "source_id": rows["knowledge_edges"][0]["target_id"],
            "target_id": rows["knowledge_edges"][0]["source_id"],
            "relation_type": "uses",
        }
    )
    with pytest.raises(ValueError):
        publish(publisher, invalid)


def test_identity_migration_preserves_records_and_rejects_collision(publisher):
    migration = (
        Path(__file__).resolve().parents[2]
        / "alembic/versions/0008_practice_identity.sql"
    ).read_text()
    # A temporary table shadows only this connection's table. No student data is touched.
    with publisher.connect() as c, c.begin():
        c.exec_driver_sql(
            "CREATE TEMP TABLE student_learning_marks(user_id uuid,problem_id text,practiced boolean,learning_status text,PRIMARY KEY(user_id,problem_id)) ON COMMIT DROP"
        )
        user = uuid4()
        c.execute(
            text(
                "INSERT INTO student_learning_marks VALUES(:u,'q01',true,'mastered'),(:u,'quadratic-always-q01',true,'needs_review')"
            ),
            {"u": user},
        )
        c.execute(text(migration))
        actual = c.execute(
            text(
                "SELECT problem_id,practiced,learning_status FROM student_learning_marks ORDER BY problem_id"
            )
        ).all()
        assert actual == [
            ("basic-inequality-q01", True, "mastered"),
            ("quadratic-always-q01", True, "needs_review"),
        ]
        c.exec_driver_sql("DROP TABLE practice_id_migration")
        c.execute(text(migration))
        assert (
            c.execute(
                text(
                    "SELECT problem_id,practiced,learning_status FROM student_learning_marks ORDER BY problem_id"
                )
            ).all()
            == actual
        )
        c.exec_driver_sql("DROP TABLE practice_id_migration")
        c.execute(
            text(
                "INSERT INTO student_learning_marks VALUES(:u,'q01',false,'unmarked')"
            ),
            {"u": user},
        )
        with pytest.raises(DBAPIError), c.begin_nested():
            c.execute(text(migration))
        assert c.scalar(text("SELECT count(*) FROM student_learning_marks")) == 3


def test_publish_removes_catalog_entries_but_preserves_retired_node_history(
    publisher, client, auth, phone
):
    from test_auth import login

    rows = load_content()
    changed = deepcopy(rows)
    retired = "retired-" + uuid4().hex
    topic = "retired-topic-" + uuid4().hex
    changed["knowledge_nodes"].append(
        {
            **next(n for n in rows["knowledge_nodes"] if n["id"] == "amgm-formula"),
            "id": retired,
        }
    )
    changed["knowledge_drill_items"].extend(
        {**q, "node_id": retired}
        for q in rows["knowledge_drill_items"]
        if q["node_id"] == "amgm-formula"
    )
    changed["practice_topics"].append(
        {"id": topic, "label": "temporary", "path": "/temporary/"}
    )
    changed["practice_topic_problems"].append(
        {"topic_id": topic, "problem_id": rows["practice_problems"][0]["id"]}
    )
    login(client, auth, phone)
    try:
        publish(publisher, changed)
        response = client.post(
            "/api/learning/drills", json={"id": str(uuid4()), "node_id": retired}
        )
        assert response.status_code == 200, response.text
        attempt = response.json()
        item = attempt["items"][0]
        response = client.post(
            f"/api/learning/drills/{attempt['id']}/answers/1",
            json={"selected": [item["options"][0]["value"]]},
        )
        assert response.status_code == 200
        saved = response.json()
        # Retiring is transactional too: a later contract error must undo catalog pruning.
        invalid = deepcopy(rows)
        invalid["practice_problems"][0]["problem_data"]["contract_hash"] = "invalid"
        with pytest.raises(ValueError):
            publish(publisher, invalid)
        with transaction(publisher) as c:
            assert (
                c.scalar(
                    text("SELECT count(*) FROM practice_topics WHERE id=:t"),
                    {"t": topic},
                )
                == 1
            )
        publish(publisher, rows)
        assert publish(publisher, rows) == {
            name: len(items) for name, items in rows.items()
        }
        with transaction(publisher) as c:
            assert (
                c.scalar(
                    text("SELECT is_active FROM knowledge_nodes WHERE id=:n"),
                    {"n": retired},
                )
                is False
            )
            assert (
                c.scalar(
                    text("SELECT count(*) FROM practice_topics WHERE id=:t"),
                    {"t": topic},
                )
                == 0
            )
            memberships = {
                tuple(r)
                for r in c.execute(
                    text("SELECT topic_id,problem_id FROM practice_topic_problems")
                )
            }
            assert memberships == {
                (r["topic_id"], r["problem_id"])
                for r in rows["practice_topic_problems"]
            }
            assert (
                c.scalar(
                    text(
                        "SELECT count(*) FROM knowledge_drill_items WHERE node_id=:n AND is_active"
                    ),
                    {"n": retired},
                )
                == 0
            )
        assert retired not in {
            n["node_id"] for n in client.get("/api/learning/nodes").json()["nodes"]
        }
        assert (
            client.post(
                "/api/learning/drills", json={"id": str(uuid4()), "node_id": retired}
            ).status_code
            == 404
        )
        assert client.get(f"/api/learning/drills/{attempt['id']}").json() == saved
        # Republish the same identity: original student evidence remains attached.
        publish(publisher, changed)
        assert retired in {
            n["node_id"] for n in client.get("/api/learning/nodes").json()["nodes"]
        }
        assert (
            client.post(
                "/api/learning/drills", json={"id": str(uuid4()), "node_id": retired}
            ).json()["id"]
            == attempt["id"]
        )
    finally:
        publish(publisher, rows)


def test_integrity_migration_preserves_display_time_and_raw_text(publisher):
    migration = (
        Path(__file__).resolve().parents[2]
        / "alembic/versions/0010_learning_record_integrity.sql"
    ).read_text()
    with publisher.connect() as c, c.begin():
        c.exec_driver_sql(
            "CREATE TEMP TABLE knowledge_nodes(id text PRIMARY KEY) ON COMMIT DROP"
        )
        c.exec_driver_sql(
            "CREATE TEMP TABLE student_practice_events(id int PRIMARY KEY,event_type text,payload jsonb) ON COMMIT DROP"
        )
        c.exec_driver_sql("INSERT INTO knowledge_nodes VALUES ('existing')")
        c.exec_driver_sql("""INSERT INTO student_practice_events VALUES
          (1,'hint','{"role":"tutor","text":"原始提示","displayed_at":"2026-10-08T01:02:03Z"}'),
          (2,'answer','{"value":"wrong"}'),
          (3,'message','{"role":"tutor","text":"原始对话"}')""")
        c.execute(text(migration))
        events = (
            c.execute(text("SELECT * FROM student_practice_events ORDER BY id"))
            .mappings()
            .all()
        )
        assert events[0]["payload"] == {"role": "tutor", "text": "原始提示"}
        assert events[0]["displayed_at"].isoformat() == "2026-10-08T01:02:03+00:00"
        assert (
            events[1]["payload"] == {"value": "wrong"}
            and events[1]["displayed_at"] is None
        )
        assert (
            events[2]["payload"] == {"role": "tutor", "text": "原始对话"}
            and events[2]["displayed_at"] is None
        )
        assert c.scalar(text("SELECT is_active FROM knowledge_nodes")) is True
        with pytest.raises(DBAPIError), c.begin_nested():
            c.exec_driver_sql(
                "UPDATE student_practice_events SET displayed_at=now() WHERE id=2"
            )
