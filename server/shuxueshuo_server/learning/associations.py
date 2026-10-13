"""Resolve authored associations using confirmed observations, never guessed answers."""

from fastapi import HTTPException
from sqlalchemy import text

ABILITY_KINDS = ('knowledge', 'skill', 'method', 'problem_type')
DIRECTORY_KINDS = ('textbook', 'chapter', 'section')


def content_metadata(c):
    row = c.execute(text('''SELECT r.content_version,r.schema_version,r.counts
        FROM learning_content_current x JOIN learning_content_releases r
        ON r.content_version=x.content_version WHERE x.id='public' ''')).mappings().first()
    if not row:
        raise HTTPException(503, '新知识图谱尚未发布。')
    return dict(row)


def require_content(c, requested):
    current = content_metadata(c)
    if requested != current['content_version']:
        raise HTTPException(409, {
            'code': 'learning_content_changed',
            'message': '教学内容已更新，请刷新页面后重新开练。',
            'content_version': current['content_version'],
        })
    return current['content_version']


def branches(tree, conditions=None):
    if not tree:
        return []
    conditions = conditions or {}
    if isinstance(tree, dict) and 'field' in tree:
        return [branch for value, child in tree['options'].items()
                for branch in branches(child, conditions | {tree['field']: value})]
    return [{'conditions': conditions, 'value': tree}]


def select(tree, choices, options=None, passed_fields=()):
    """Mirror teaching-model.mjs, including withheld unanswered partial branches."""
    possible = [b for b in branches(tree) if all(
        field not in choices or choices[field] == value
        for field, value in b['conditions'].items())]
    actual = [b for b in possible if all(field in choices for field in b['conditions'])]
    pending = [b for b in possible if b not in actual]
    options = options or {}
    withheld = any(field not in choices and field not in passed_fields and any(
        not any(p['conditions'].get(field) == value for p in pending)
        for value in options.get(field, []))
        for b in pending for field in b['conditions'])
    return {'actual': actual, 'candidates': [] if withheld else pending, 'withheld': withheld}


def resolved_refs(tree, choices):
    return list(dict.fromkeys(ref for branch in select(tree, choices)['actual']
                              for ref in branch['value']))


def matches_ref(ref, node_id, entry=None):
    identity, _, part = ref.partition('#')
    return identity == node_id and (entry is None or part == entry)


def snapshot(c, problem, route):
    row = c.execute(text('''SELECT label,methods,association_hash FROM practice_routes
        WHERE problem_id=:p AND route_id=:r AND is_active'''),
        {'p': problem, 'r': route}).mappings().first()
    if not row:
        raise HTTPException(404, '题目或路线不可用于新练习。')
    steps = {s['step_id']: dict(s) for s in c.execute(text('''
        SELECT step_id,title,position,refs,tip,reason FROM practice_steps
        WHERE problem_id=:p AND route_id=:r AND is_active ORDER BY position'''),
        {'p': problem, 'r': route}).mappings()}
    types = list(c.execute(text('SELECT node_id FROM practice_problem_types WHERE problem_id=:p ORDER BY node_id'),
                          {'p': problem}).scalars())
    return {'route_id': route, 'label': row['label'], 'methods': row['methods'],
            'types': types, 'steps': steps, 'association_hash': row['association_hash']}


def directory_progress(c, scope, statuses):
    nodes = {n['id']: dict(n) for n in c.execute(text(
        'SELECT id,kind,label FROM knowledge_nodes WHERE is_active')).mappings()}
    if scope not in nodes or nodes[scope]['kind'] not in DIRECTORY_KINDS:
        raise HTTPException(404, '没有找到教材、章或节。')
    edges = list(c.execute(text("SELECT source_id,target_id,relation_type FROM knowledge_edges WHERE relation_type IN ('contains','extends')")).mappings())
    sections, pending, visited = set(), [scope], set()
    while pending:
        source = pending.pop()
        if source in visited:
            continue
        visited.add(source)
        if nodes[source]['kind'] == 'section':
            sections.add(source)
        else:
            pending.extend(e['target_id'] for e in edges if e['source_id'] == source
                           and e['target_id'] in nodes and nodes[e['target_id']]['kind'] in DIRECTORY_KINDS)
    index = {n['node_id']: n for n in statuses}

    def count(rows):
        return {'total': len(rows), 'eligible': sum(r['eligible'] for r in rows),
                'statuses': {s: sum(r['status'] == s for r in rows)
                             for s in ('unassessed', 'mastered', 'needs_review')}}

    result = {'scope': scope, 'label': nodes[scope]['label']}
    for relation in ('contains', 'extends'):
        ids = {e['target_id'] for e in edges if e['source_id'] in sections
               and e['relation_type'] == relation and e['target_id'] in index}
        rows = [index[i] for i in sorted(ids)]
        result[relation] = count(rows) | {
            'node_ids': sorted(ids),
            'by_kind': {kind: count([r for r in rows if r['kind'] == kind]) for kind in ABILITY_KINDS}}
    return result
