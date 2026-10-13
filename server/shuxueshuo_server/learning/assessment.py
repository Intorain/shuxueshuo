"""Versioned, replayable assessment over immutable drill observations."""

from sqlalchemy import text

from ..product.db import lock, transaction

STRATEGY = 'drill_round_v1'


def evaluate_node(c, user, node):
    """Caller owns the transaction; completed observations alone change mastery."""
    lock(c, 'assessment', str(user), node)
    row = c.execute(text('''SELECT a.id,a.completed_at,
        count(r.position) FILTER (WHERE r.answered_at IS NOT NULL) AS answers,
        count(r.position) FILTER (WHERE r.is_correct) AS correct_count
        FROM knowledge_drill_attempts a JOIN knowledge_drill_answers r ON r.attempt_id=a.id
        WHERE a.user_id=:u AND a.node_id=:n AND a.status='completed'
        GROUP BY a.id HAVING count(r.position) FILTER (WHERE r.answered_at IS NOT NULL)=5
        ORDER BY a.completed_at DESC,a.id DESC LIMIT 1'''),
        {'u': user, 'n': node}).mappings().first()
    if not row or row['answers'] != 5:
        return None
    updated = c.execute(text('''INSERT INTO student_node_assessments
        (user_id,node_id,status,probability,strategy_version,evidence_attempt_id,evidence_position,evaluated_at,correct_count)
        VALUES(:u,:n,:s,NULL,:strategy,:a,5,clock_timestamp(),:count)
        ON CONFLICT(user_id,node_id) DO UPDATE SET status=excluded.status,
        probability=NULL,strategy_version=excluded.strategy_version,
        evidence_attempt_id=excluded.evidence_attempt_id,evidence_position=5,
        evaluated_at=excluded.evaluated_at,correct_count=excluded.correct_count
        WHERE student_node_assessments.evidence_attempt_id IS DISTINCT FROM excluded.evidence_attempt_id
          OR student_node_assessments.strategy_version IS DISTINCT FROM excluded.strategy_version
          OR student_node_assessments.status IS DISTINCT FROM excluded.status
          OR student_node_assessments.correct_count IS DISTINCT FROM excluded.correct_count
          OR student_node_assessments.evidence_position IS DISTINCT FROM excluded.evidence_position
          OR student_node_assessments.probability IS NOT NULL
        RETURNING *'''), {'u': user, 'n': node, 'a': row['id'], 'count': row['correct_count'],
                        'strategy': STRATEGY, 's': 'mastered' if row['correct_count'] == 5 else 'needs_review'}).mappings().first()
    if updated is not None:
        return updated
    return c.execute(text('SELECT * FROM student_node_assessments WHERE user_id=:u AND node_id=:n'),
                     {'u': user, 'n': node}).mappings().one()


def rebuild(db, user=None):
    """Administrative replay; API code never deletes source evidence."""
    with transaction(db) as c:
        lock(c, 'learning.publish')
        rows = list(c.execute(text('''SELECT DISTINCT a.user_id,a.node_id
            FROM knowledge_drill_attempts a WHERE a.status='completed'
            AND (SELECT count(*) FROM knowledge_drill_answers r
                 WHERE r.attempt_id=a.id AND r.answered_at IS NOT NULL)=5 ''' +
            ('AND a.user_id=:u' if user else '')), {'u': user} if user else {}).mappings())
        # Source/derived queries run under READ COMMITTED. A first completion
        # can arrive between them: re-check its evidence under the same per-node
        # lock used by answer evaluation before deciding that a result is stale.
        existing = list(c.execute(text('SELECT user_id,node_id FROM student_node_assessments ' +
            ('WHERE user_id=:u' if user else '')), {'u': user} if user else {}).mappings())
        targets = {(row['user_id'], row['node_id']) for row in rows + existing}
        removed, evaluated = 0, 0
        for owner, node in sorted(targets, key=lambda target: (str(target[0]), target[1])):
            lock(c, 'assessment', str(owner), node)
            if evaluate_node(c, owner, node) is None:
                deleted = c.execute(text('DELETE FROM student_node_assessments WHERE user_id=:u AND node_id=:n'),
                                    {'u': owner, 'n': node})
                removed += deleted.rowcount
            else:
                evaluated += 1
        return {'strategy_version': STRATEGY, 'nodes': evaluated, 'removed': removed}
