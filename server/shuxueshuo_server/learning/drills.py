"""Five fixed items, immutable first answers, reversible latest-completed mastery."""

import json
import secrets
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text

from ..product.db import lock, transaction


def one(c, sql, **values):
    return c.execute(text(sql), values).mappings().first()


def owned(c, aid, user, *, locked=False):
    a = one(
        c,
        "SELECT * FROM knowledge_drill_attempts WHERE id=:id AND user_id=:user"
        + (" FOR UPDATE" if locked else ""),
        id=aid,
        user=user,
    )
    if not a:
        raise HTTPException(404, "没有找到这轮练习。")
    return a


def view(c, a):
    items = []
    for row in c.execute(
        text("""SELECT r.*,q.statement_md,q.question_type,q.options,q.answer_spec,q.explanation_md
      FROM knowledge_drill_answers r JOIN knowledge_drill_items q ON q.node_id=:node AND q.item_id=r.item_id
      WHERE r.attempt_id=:id ORDER BY r.position"""),
        {"node": a["node_id"], "id": a["id"]},
    ).mappings():
        item = {
            k: row[k]
            for k in (
                "position",
                "item_id",
                "selected",
                "is_correct",
                "answered_at",
                "statement_md",
                "question_type",
            )
        }
        # Authored IDs such as "right" must not disclose the answer before submission.
        public_ids = {
            o["value"]: f"option-{i}" for i, o in enumerate(row["options"], 1)
        }
        item["options"] = [
            {"value": public_ids[o["value"]], "label": o["label"]}
            for o in row["options"]
        ]
        item["selected"] = (
            [public_ids[v] for v in row["selected"]]
            if row["selected"] is not None
            else None
        )
        if row["answered_at"]:
            answer = row["answer_spec"]["selected"]
            notes = [
                o["feedback"]
                for o in row["options"]
                if o["value"] in row["selected"] and o["value"] not in answer
            ]
            if not row["is_correct"] and not notes:
                notes = ["正确选项还没有选全。"]
            item.update(
                answer=[public_ids[v] for v in answer],
                feedback=notes,
                explanation=row["explanation_md"],
            )
        items.append(item)
    return dict(a, items=items)


def start(db, user, node, aid, previous=None):
    with transaction(db) as c:
        lock(c, "drill", str(user), node)
        exists = one(c, "SELECT * FROM knowledge_drill_attempts WHERE id=:id", id=aid)
        if exists:
            if exists["user_id"] != UUID(str(user)) or exists["node_id"] != node:
                raise HTTPException(409, "练习编号已用于其他请求。")
            return view(c, exists)
        if not one(
            c, "SELECT id FROM knowledge_nodes WHERE id=:n AND is_active", n=node
        ):
            raise HTTPException(404, "本节点已停用，不能开始新练习。")
        current = one(
            c,
            "SELECT * FROM knowledge_drill_attempts WHERE user_id=:user AND node_id=:node AND status='in_progress' FOR UPDATE",
            user=user,
            node=node,
        )
        if previous:
            old = owned(c, previous, user, locked=True)
            if old["node_id"] != node or (current and current["id"] != previous):
                raise HTTPException(409, "练习已更新，请刷新后重试。")
        elif current:
            return view(c, current)
        pool = list(
            c.execute(
                text(
                    "SELECT item_id FROM knowledge_drill_items WHERE node_id=:node AND is_active ORDER BY item_id"
                ),
                {"node": node},
            ).scalars()
        )
        if len(pool) < 5:
            raise HTTPException(409, "本节点可用题目不足五道。")
        if current:
            c.execute(
                text(
                    "UPDATE knowledge_drill_attempts SET status='closed' WHERE id=:id"
                ),
                {"id": current["id"]},
            )
        a = one(
            c,
            "INSERT INTO knowledge_drill_attempts(id,user_id,node_id) VALUES(:id,:user,:node) RETURNING *",
            id=aid,
            user=user,
            node=node,
        )
        for i, item in enumerate(secrets.SystemRandom().sample(pool, 5), 1):
            c.execute(
                text(
                    "INSERT INTO knowledge_drill_answers(attempt_id,position,item_id) VALUES(:id,:i,:item)"
                ),
                {"id": aid, "i": i, "item": item},
            )
        return view(c, a)


def answer(db, user, aid, position, selected):
    with transaction(db) as c:
        a = owned(c, aid, user, locked=True)
        row = one(
            c,
            """SELECT r.*,q.options,q.question_type,q.answer_spec FROM knowledge_drill_answers r
          JOIN knowledge_drill_items q ON q.node_id=:node AND q.item_id=r.item_id
          WHERE attempt_id=:id AND position=:p""",
            node=a["node_id"],
            id=aid,
            p=position,
        )
        if not row:
            raise HTTPException(404, "题目不属于本轮练习。")
        public_ids = {
            f"option-{i}": o["value"] for i, o in enumerate(row["options"], 1)
        }
        if (
            len(set(selected)) != len(selected)
            or not set(selected) <= public_ids.keys()
            or (row["question_type"] != "multi" and len(selected) != 1)
        ):
            raise HTTPException(422, "请选择本题有效选项。")
        picked = sorted(public_ids[v] for v in selected)
        if row["answered_at"]:
            if picked != row["selected"]:
                raise HTTPException(409, "首答已保存，不能覆盖；可开始新一轮练习。")
            return view(c, a)
        if a["status"] != "in_progress":
            raise HTTPException(409, "本轮已结束。")
        c.execute(
            text("""UPDATE knowledge_drill_answers SET selected=CAST(:selected AS jsonb),is_correct=:correct,answered_at=clock_timestamp()
          WHERE attempt_id=:id AND position=:p AND answered_at IS NULL"""),
            {
                "selected": json.dumps(picked),
                "correct": picked == sorted(row["answer_spec"]["selected"]),
                "id": aid,
                "p": position,
            },
        )
        count = c.scalar(
            text(
                "SELECT count(*) FROM knowledge_drill_answers WHERE attempt_id=:id AND answered_at IS NOT NULL"
            ),
            {"id": aid},
        )
        if count == 5:
            a = one(
                c,
                "UPDATE knowledge_drill_attempts SET status='completed',completed_at=clock_timestamp() WHERE id=:id RETURNING *",
                id=aid,
            )
        return view(c, a)


def statuses(c, user):
    result = []
    for row in c.execute(
        text("""SELECT n.id AS node_id,a.id AS attempt_id,a.completed_at,
      (SELECT count(*) FROM knowledge_drill_answers r WHERE r.attempt_id=a.id AND r.is_correct) AS correct_count,
      EXISTS(SELECT 1 FROM knowledge_drill_attempts p WHERE p.user_id=:user AND p.node_id=n.id AND p.status='in_progress') AS in_progress
      FROM knowledge_nodes n LEFT JOIN LATERAL
      (SELECT * FROM knowledge_drill_attempts x WHERE x.user_id=:user AND x.node_id=n.id AND x.status='completed'
      ORDER BY completed_at DESC,id DESC LIMIT 1) a ON true WHERE n.is_active ORDER BY n.id"""),
        {"user": user},
    ).mappings():
        result.append(
            dict(
                row,
                status="unassessed"
                if row["attempt_id"] is None
                else "mastered"
                if row["correct_count"] == 5
                else "needs_review",
                source="drill_first_answers",
            )
        )
    return result
