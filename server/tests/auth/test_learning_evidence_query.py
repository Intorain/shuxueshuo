"""History selection filters nodes and batches choices, without changing attribution."""

from uuid import UUID, uuid4

from sqlalchemy import event
from test_auth import login

from shuxueshuo_server.learning import practice
from shuxueshuo_server.product.db import transaction
from shuxueshuo_server.tutor_demo.session import load_lesson


def test_evidence_queries_do_not_grow_with_attempt_count(client, auth, phone, monkeypatch):
    user = UUID(login(client, auth, phone).json()['user']['id'])
    expected = []
    previous = None
    for _ in range(3):
        attempt = practice.start(auth.db, user, 'basic-inequality-q01', 'direct',
                                 uuid4(), previous)
        previous = attempt['id']
        expected.append(previous)
        practice.submit(auth.db, user, previous, uuid4(), 'structure',
                        {'terms': ['m', 'n'], 'fixed': 'sum'})

    # An observed step in another topic should be filtered in SQL, before
    # loading its private teacher contract or resolving its choice fields.
    pid = 'quadratic-always-q01'
    lesson = load_lesson(pid)
    route = next(iter(lesson['routes']))
    unrelated = practice.start(auth.db, user, pid, route, uuid4())
    first = lesson['routes'][route]['nodes'][0]
    practice.submit(auth.db, user, unrelated['id'], uuid4(), first['id'],
                    {'terms': first['expected_answer']['terms']})

    statements = []
    resolved = set()
    original = practice.choices_from_rule_answers

    def record_choice_resolution(attempt, answers):
        resolved.add(attempt['id'])
        return original(attempt, answers)

    def record_sql(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith(('SELECT', 'WITH')):
            statements.append(statement)

    monkeypatch.setattr(practice, 'choices_from_rule_answers', record_choice_resolution)
    event.listen(auth.db, 'before_cursor_execute', record_sql)
    try:
        with transaction(auth.db) as c:
            result = practice.evidence(c, user, 'amgm-formula', 'checklist')
    finally:
        event.remove(auth.db, 'before_cursor_execute', record_sql)

    assert [r['attempt_id'] for r in result['evidence']] == list(reversed(expected))
    assert resolved == set(expected)
    # Node existence, relevant observations, batch choices, drill evidence.
    assert len(statements) == 4
    assert all(r['source'] == 'practice_context' for r in result['evidence'])
