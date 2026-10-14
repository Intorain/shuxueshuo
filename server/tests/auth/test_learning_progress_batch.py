"""Authenticated personal overlays use explicit versioned, independent states."""
from test_auth import login

CHAPTER = 'chapter-quadratic-equations-inequalities'
SECTION = 'section-basic-inequality'


def test_personal_nodes_and_directory_batch_share_published_version(client, auth, phone):
    login(client, auth, phone)
    version = client.get('/api/learning/content').json()['content_version']
    nodes = client.get('/api/learning/nodes').json()
    assert nodes['content_version'] == version
    assert {n['kind'] for n in nodes['nodes']} == {'knowledge', 'skill', 'method', 'problem_type'}
    single = client.get('/api/learning/progress', params={'scope': CHAPTER})
    assert single.status_code == 200
    batch = client.get('/api/learning/progress/batch', params=[('scope', CHAPTER), ('scope', CHAPTER)])
    assert batch.status_code == 200, batch.text
    assert batch.json() == {'content_version':version, 'progress':[
        {k:v for k,v in single.json().items() if k != 'content_version'}]}
    for group in batch.json()['progress'][0]['contains'], batch.json()['progress'][0]['extends']:
        assert group['total'] == len(set(group['node_ids']))
        assert group['statuses']['unassessed'] == group['total']
        assert 'probability' not in group


def test_progress_batch_validates_scopes_as_a_whole_and_requires_account(client, auth, phone):
    assert client.get('/api/learning/progress/batch', params={'scope':CHAPTER}).status_code == 401
    login(client, auth, phone)
    assert client.get('/api/learning/progress/batch').status_code == 422
    for invalid in ('amgm-formula', 'rule-interval-skill', 'missing'):
        response = client.get('/api/learning/progress/batch', params=[('scope', CHAPTER), ('scope', invalid)])
        assert response.status_code == 404
    assert client.get('/api/learning/progress/batch', params=[('scope', CHAPTER)] * 101).status_code == 422


def test_batch_multiple_scopes_match_individual_progress(client, auth, phone):
    login(client, auth, phone)
    # Find real directory IDs rather than tying this API contract to inventory counts.
    from sqlalchemy import text
    from shuxueshuo_server.product.db import transaction
    with transaction(auth.db) as c:
        scopes = list(c.execute(text("SELECT id FROM knowledge_nodes WHERE kind IN ('chapter','section','textbook') AND is_active ORDER BY id")).scalars())
    response = client.get('/api/learning/progress/batch', params=[('scope', scope) for scope in scopes])
    assert response.status_code == 200, response.text
    for row in response.json()['progress']:
        single = client.get('/api/learning/progress', params={'scope': row['scope']}).json()
        assert row == {k:v for k,v in single.items() if k != 'content_version'}
