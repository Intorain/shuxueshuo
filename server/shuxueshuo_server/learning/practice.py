"""Persistent route evidence; grades are produced only by rules or the trusted tutor."""

import json
from uuid import NAMESPACE_URL, uuid5

from fastapi import HTTPException
from sqlalchemy import text

from ..product.db import lock, transaction
from ..tutor_demo.contracts import InvalidAction, apply_action, fresh_state, slot_count
from ..tutor_demo.llm import Action
from ..tutor_demo.session import load_lesson
from .drills import one
from .identity import canonical_id


def eid(value, suffix):
    return uuid5(NAMESPACE_URL, f"practice:{value}:{suffix}")


def owned(c, aid, user):
    a = one(
        c,
        "SELECT * FROM student_practice_attempts WHERE id=:id AND user_id=:u FOR UPDATE",
        id=aid,
        u=user,
    )
    if not a:
        raise HTTPException(404, "没有找到本次练习。")
    return a


def nodes(a):
    return load_lesson(a["problem_id"])["routes"][a["route_id"]]["nodes"]


def node(a, step):
    n = next((n for n in nodes(a) if n["id"] == step), None)
    if not n:
        raise HTTPException(422, "步骤不属于本次路线。")
    return n


def append(c, a, identity, step, kind, payload, related=None):
    old = one(c, "SELECT * FROM student_practice_events WHERE id=:id", id=identity)
    if old:
        if (
            old["attempt_id"] != a["id"]
            or old["step_id"] != step
            or old["event_type"] != kind
            or old["payload"] != payload
            or old["related_event_id"] != related
        ):
            raise HTTPException(409, "同一事件编号不能用于不同输入。")
        return old
    seq = c.scalar(
        text(
            "SELECT coalesce(max(sequence),0)+1 FROM student_practice_events WHERE attempt_id=:a"
        ),
        {"a": a["id"]},
    )
    return one(
        c,
        """INSERT INTO student_practice_events(id,attempt_id,step_id,sequence,event_type,payload,related_event_id)
      VALUES(:id,:a,:s,:seq,:kind,CAST(:payload AS jsonb),:related) RETURNING *""",
        id=identity,
        a=a["id"],
        s=step,
        seq=seq,
        kind=kind,
        payload=json.dumps(payload, ensure_ascii=False),
        related=related,
    )


def context(c, a, step):
    saved = one(
        c,
        "SELECT * FROM student_practice_events WHERE id=:id",
        id=eid(a["id"], step + ":context"),
    )
    if saved:
        return saved
    n = node(a, step)
    return append(
        c,
        a,
        eid(a["id"], step + ":context"),
        step,
        "context",
        {k: n[k] for k in ("question", "interaction", "expected_answer", "criteria")},
    )


def active_step(c, a):
    passed = set(
        c.execute(
            text(
                "SELECT step_id FROM student_step_results WHERE attempt_id=:a AND passed"
            ),
            {"a": a["id"]},
        ).scalars()
    )
    return next((n["id"] for n in nodes(a) if n["id"] not in passed), None)


def passed_answers(c, a):
    """Use the exact passing rule submission, or an established standard conclusion."""
    route = {n["id"]: n for n in nodes(a)}
    answers = {}
    for row in c.execute(
        text("""SELECT r.step_id,input.payload AS answer
          FROM student_step_results r
          LEFT JOIN student_practice_events g ON g.attempt_id=r.attempt_id
            AND g.step_id=r.step_id AND g.sequence=r.summary_through_sequence
            AND g.event_type='grade' AND g.payload->>'result'='passed'
            AND g.payload->>'source'='rule'
          LEFT JOIN student_practice_events input ON input.id=g.related_event_id
            AND input.attempt_id=r.attempt_id AND input.step_id=r.step_id
            AND input.event_type='answer' AND input.sequence<g.sequence
          WHERE r.attempt_id=:a AND r.passed"""),
        {"a": a["id"]},
    ).mappings():
        n = route[row["step_id"]]
        expected = n["expected_answer"]
        fallback = (
            {"value": expected["one_of"][0]}
            if n["interaction"]["type"] == "choice"
            else {
                "terms": list(expected["terms"]),
                **(
                    {"fixed": expected["fixed"]}
                    if n["interaction"]["type"] == "structure"
                    else {}
                ),
            }
        )
        answers[row["step_id"]] = fallback | (row["answer"] or {})
    return answers


def result(c, a):
    answers = passed_answers(c, a)
    steps = [
        dict(r, **({"answer": answers[r["step_id"]]} if r["passed"] else {}))
        for r in c.execute(
            text(
                "SELECT * FROM student_step_results WHERE attempt_id=:a ORDER BY last_submitted_at"
            ),
            {"a": a["id"]},
        ).mappings()
    ]
    return {
        k: a[k]
        for k in (
            "id",
            "problem_id",
            "route_id",
            "status",
            "started_at",
            "completed_at",
        )
    } | {"steps": steps, "active_step": active_step(c, a)}


def start(db, user, pid, route, identity, previous=None):
    pid = canonical_id(pid)
    with transaction(db) as c:
        lock(c, "practice", str(user), pid)
        old = one(
            c, "SELECT * FROM student_practice_attempts WHERE id=:id", id=identity
        )
        if old:
            if (
                old["user_id"] != user
                or old["problem_id"] != pid
                or old["route_id"] != route
            ):
                raise HTTPException(409, "尝试编号已被使用。")
            return result(c, old)
        current = one(
            c,
            "SELECT * FROM student_practice_attempts WHERE user_id=:u AND problem_id=:p AND status='in_progress' FOR UPDATE",
            u=user,
            p=pid,
        )
        if previous:
            old = owned(c, previous, user)
            if old["problem_id"] != pid or (current and current["id"] != previous):
                if current and old["problem_id"] == pid:
                    raise_start_conflict(current)
                raise HTTPException(409, "练习已更新，请刷新后重试。")
        elif current:
            if current["route_id"] != route:
                raise_start_conflict(current)
            return result(c, current)
        p = one(c, "SELECT * FROM practice_problems WHERE id=:p AND is_active", p=pid)
        if not p or not one(
            c,
            "SELECT * FROM practice_problem_methods WHERE problem_id=:p AND route_id=:r",
            p=pid,
            r=route,
        ):
            raise HTTPException(404, "题目或路线不可用于新练习。")
        if current:
            c.execute(
                text(
                    "UPDATE student_practice_attempts SET status='closed',updated_at=clock_timestamp() WHERE id=:id"
                ),
                {"id": current["id"]},
            )
        a = one(
            c,
            """INSERT INTO student_practice_attempts(id,user_id,problem_id,route_id,problem_context)
          VALUES(:id,:u,:p,:r,CAST(:ctx AS jsonb)) RETURNING *""",
            id=identity,
            u=user,
            p=pid,
            r=route,
            ctx=json.dumps(p["problem_data"], ensure_ascii=False),
        )
        context(c, a, nodes(a)[0]["id"])
        return result(c, a)


def raise_start_conflict(current):
    raise HTTPException(
        409,
        {
            "code": "practice_route_conflict",
            "message": "本题已有进行中的练习，请选择继续原路线或重新开始。",
            "current_attempt": {
                "id": str(current["id"]),
                "route_id": current["route_id"],
            },
        },
    )


def grade(c, a, step, source_id, outcome, source):
    identity = eid(source_id, "grade")
    if one(c, "SELECT id FROM student_practice_events WHERE id=:id", id=identity):
        return
    event = append(
        c, a, identity, step, "grade", {"result": outcome, "source": source}, source_id
    )
    # Discussion after passing is evidence but never overwrites the original step result.
    old = one(
        c,
        "SELECT * FROM student_step_results WHERE attempt_id=:a AND step_id=:s",
        a=a["id"],
        s=step,
    )
    if old and old["passed"]:
        return
    c.execute(
        text("""INSERT INTO student_step_results(attempt_id,step_id,passed,submit_count,wrong_count,last_grading_source,last_submitted_at,summary_through_sequence)
      VALUES(:a,:s,:passed,1,:wrong,:source,clock_timestamp(),:seq)
      ON CONFLICT(attempt_id,step_id) DO UPDATE SET passed=excluded.passed,submit_count=student_step_results.submit_count+1,
      wrong_count=student_step_results.wrong_count+excluded.wrong_count,last_grading_source=excluded.last_grading_source,
      last_submitted_at=excluded.last_submitted_at,summary_through_sequence=excluded.summary_through_sequence"""),
        {
            "a": a["id"],
            "s": step,
            "passed": outcome == "passed",
            "wrong": int(outcome == "wrong"),
            "source": source,
            "seq": event["sequence"],
        },
    )
    refresh_hint(c, a, step)
    if a["status"] == "in_progress" and active_step(c, a) is None:
        c.execute(
            text(
                "UPDATE student_practice_attempts SET status='completed',completed_at=clock_timestamp(),updated_at=clock_timestamp() WHERE id=:a"
            ),
            {"a": a["id"]},
        )
        c.execute(
            text("""INSERT INTO student_learning_marks(user_id,problem_id,practiced) VALUES(:u,:p,true)
          ON CONFLICT(user_id,problem_id) DO UPDATE SET practiced=true"""),
            {"u": a["user_id"], "p": a["problem_id"]},
        )
    else:
        c.execute(
            text(
                "UPDATE student_practice_attempts SET updated_at=clock_timestamp() WHERE id=:a"
            ),
            {"a": a["id"]},
        )


def ensure_current(c, a, step):
    node(a, step)
    if a["status"] != "in_progress" or active_step(c, a) != step:
        raise HTTPException(409, "步骤已更新，请继续当前步骤。")


def submit(db, user, aid, identity, step, answer):
    with transaction(db) as c:
        a = owned(c, aid, user)
        old = one(c, "SELECT * FROM student_practice_events WHERE id=:id", id=identity)
        if not old:
            ensure_current(c, a, step)
        n = node(a, step)
        lesson = load_lesson(a["problem_id"])
        state = fresh_state(lesson)
        state["method"] = a["route_id"]
        state["active"] = next(i for i, x in enumerate(nodes(a)) if x["id"] == step)
        comp = n["interaction"]
        actions = []
        if comp["type"] == "choice":
            if set(answer) != {"value"} or not isinstance(answer.get("value"), str):
                raise HTTPException(422, "选择题需要一个选项。")
            actions = [Action(kind="choice", value=answer["value"])]
        else:
            if (
                set(answer) - {"terms", "fixed"}
                or not isinstance(answer.get("terms"), list)
                or len(answer["terms"]) != slot_count(comp)
                or any(not isinstance(v, str) for v in answer["terms"])
                or ("fixed" in answer and answer["fixed"] not in ("sum", "product"))
            ):
                raise HTTPException(422, "请提交本步选项。")
            actions = [
                Action(kind="fill", index=i, value=v)
                for i, v in enumerate(answer["terms"])
                if v
            ]
            if comp["type"] == "structure":
                actions.append(Action(kind="swap", value=answer.get("fixed", "sum")))
        try:
            for action in actions:
                apply_action(state, action, lesson)
        except (InvalidAction, ValueError) as exc:
            raise HTTPException(422, "选项不属于本步。") from exc
        ctx = context(c, a, step)
        append(c, a, identity, step, "answer", answer, ctx["id"])
        if old:
            return result(c, a)
        try:
            apply_action(state, Action(kind="submit"), lesson)
            outcome = "passed"
        except InvalidAction:
            outcome = (
                "incomplete"
                if (comp["type"] != "choice" and any(not x for x in answer["terms"]))
                else "wrong"
            )
        grade(c, a, step, identity, outcome, "rule")
        updated = owned(c, aid, user)
        next_step = active_step(c, updated)
        if next_step:
            context(c, updated, next_step)
        return result(c, updated)


def begin_dialogue(db, user, aid, event, step, problem_id):
    with transaction(db) as c:
        a = owned(c, aid, user)
        node(a, step)
        if a["problem_id"] != canonical_id(problem_id):
            raise HTTPException(409, "对话题目与练习记录不一致。")
        if not one(
            c,
            "SELECT id FROM student_practice_events WHERE id=:id",
            id=eid(f"{aid}:{event.event_id}", "student"),
        ):
            if a["status"] == "closed":
                raise HTTPException(409, "本次练习已关闭。")
            if a["status"] == "in_progress" and active_step(c, a) != step:
                raise HTTPException(409, "对话步骤与练习进度不一致。")
        context(c, a, step)
        append(
            c,
            a,
            eid(f"{aid}:{event.event_id}", "student"),
            step,
            "message",
            {
                "role": "student",
                "text": event.text if event.kind == "text" else "给点提示",
                "channel": "text",
            },
        )
        return a["route_id"]


def finish_dialogue(db, user, aid, event, step, response):
    with transaction(db) as c:
        a = owned(c, aid, user)
        student = eid(f"{aid}:{event.event_id}", "student")
        reply = (
            response["messages"][-1]["text"]
            if response["messages"] and response["messages"][-1]["role"] == "assistant"
            else ""
        )
        identity = eid(f"{aid}:{event.event_id}", "teacher")
        append(
            c,
            a,
            identity,
            step,
            "hint" if event.kind == "help" else "message",
            {"role": "tutor", "text": reply},
            student,
        )
        passed = any(
            x["node"] == step and x["route"] == a["route_id"]
            for x in response["completed"]
        )
        if (
            event.kind == "text"
            and a["status"] == "in_progress"
            and response.get("learning_intent") == "answer"
        ):
            grade(c, a, step, student, "passed" if passed else "incomplete", "llm")
        c.execute(
            text(
                "UPDATE student_practice_attempts SET updated_at=clock_timestamp() WHERE id=:a"
            ),
            {"a": aid},
        )
        return str(identity)


def refresh_hint(c, a, step):
    # Only acknowledged display before the successful grading time counts.
    c.execute(
        text("""UPDATE student_step_results r SET hint_used=EXISTS(
      SELECT 1 FROM student_practice_events h WHERE h.attempt_id=r.attempt_id AND h.step_id=r.step_id
      AND h.event_type='hint' AND h.displayed_at IS NOT NULL
      AND (NOT r.passed OR h.displayed_at<=r.last_submitted_at))
      WHERE r.attempt_id=:a AND r.step_id=:s"""),
        {"a": a["id"], "s": step},
    )


def acknowledge(db, user, aid, identity):
    with transaction(db) as c:
        a = owned(c, aid, user)
        e = one(
            c,
            "SELECT * FROM student_practice_events WHERE id=:id AND attempt_id=:a AND (event_type='hint' OR payload->>'role'='tutor')",
            id=identity,
            a=aid,
        )
        if not e:
            raise HTTPException(404, "没有找到待确认内容。")
        c.execute(
            text(
                "UPDATE student_practice_events SET displayed_at=clock_timestamp() WHERE id=:id AND displayed_at IS NULL"
            ),
            {"id": identity},
        )
        refresh_hint(c, a, e["step_id"])
        c.execute(
            text(
                "UPDATE student_practice_attempts SET updated_at=clock_timestamp() WHERE id=:a"
            ),
            {"a": aid},
        )
        return {"saved": True}


def restore_session(db, user, aid, session):
    """Restore confirmed conclusions and original dialogue, never unsubmitted input."""
    from copy import deepcopy

    with transaction(db) as c:
        a = owned(c, aid, user)
        if a["problem_id"] != session.lesson["id"] or a["status"] == "closed":
            raise HTTPException(409, "练习题目或状态已改变。")
        session.state["method"] = a["route_id"]
        answers = passed_answers(c, a)
        route = nodes(a)
        for index, n in enumerate(route):
            if n["id"] not in answers:
                break
            # Already established conclusions are supplied by the system on resume;
            # they are not new answers and are never written as new evidence.
            answer = answers[n["id"]]
            if n["interaction"]["type"] == "choice":
                session.state["choices"][n["interaction"]["field"]] = answer["value"]
            else:
                session.state["pairs"][index] = list(answer["terms"])
                if n["interaction"]["type"] == "structure":
                    session.state["swapped"] = answer["fixed"] == "product"
            session.state["active"] = index + 1
            session.completed.append(
                {
                    "stage": index,
                    "route": a["route_id"],
                    "node": n["id"],
                    "state": deepcopy(session.state),
                    "evidence": n["required_evidence"],
                }
            )
        positions = {n["id"]: i for i, n in enumerate(route)}
        for event in c.execute(
            text(
                "SELECT * FROM student_practice_events WHERE attempt_id=:a AND event_type IN ('message','hint') ORDER BY sequence"
            ),
            {"a": aid},
        ).mappings():
            p = event["payload"]
            session.messages.append(
                {
                    "role": "student" if p["role"] == "student" else "assistant",
                    "kind": "text",
                    "text": p["text"],
                    "stage": positions[event["step_id"]],
                    "route": a["route_id"],
                    "attempt_id": session.attempt_id,
                    "revision": 0,
                }
            )
        session.messages = session.messages[-200:]


def shown_reference(db, user, aid, identity, step, node_id):
    """Accept only a registered step reference, never client-authored tutor text."""
    with transaction(db) as c:
        a = owned(c, aid, user)
        node(a, step)
        reference = one(
            c,
            """SELECT n.* FROM knowledge_nodes n JOIN practice_step_nodes s ON s.node_id=n.id
          WHERE s.problem_id=:p AND s.route_id=:r AND s.step_id=:s AND n.id=:n""",
            p=a["problem_id"],
            r=a["route_id"],
            s=step,
            n=node_id,
        )
        if not reference:
            raise HTTPException(422, "图解不属于本步关联节点。")
        if a["status"] == "closed":
            raise HTTPException(409, "本次练习已关闭。")
        # This endpoint is called only after the visible dialog has loaded successfully.
        append(
            c,
            a,
            identity,
            step,
            "hint",
            {
                "role": "tutor",
                "source": "node_explainer",
                "node_id": node_id,
                "text": reference["explanation_md"],
            },
        )
        c.execute(
            text(
                "UPDATE student_practice_events SET displayed_at=clock_timestamp() WHERE id=:id AND displayed_at IS NULL"
            ),
            {"id": identity},
        )
        refresh_hint(c, a, step)
        return {"saved": True}
