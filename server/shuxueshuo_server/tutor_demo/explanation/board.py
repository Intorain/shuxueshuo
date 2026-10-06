"""Student-visible steps and derivations, built from verified execution snapshots."""

from copy import deepcopy

from .math import tex


def groups(steps):
    out = []
    for index, step in enumerate(steps):
        selection = step.get("candidate_id")
        if selection and out and out[-1][-1][1].get("candidate_id") == selection:
            out[-1].append((index, step))
        else:
            out.append([(index, step)])
    return out


def number(steps, index):
    return next(n for n, group in enumerate(groups(steps), 1) if any(i == index for i, _ in group))


def board_steps(branch):
    out = []
    for group in groups(branch.steps):
        start, end = group[0][0], group[-1][0]
        members = [step for _, step in group]
        card = deepcopy(members[-1])
        card["step_count"] = end + 1  # Exact internal snapshot boundary for branching.
        card["member_ids"] = [s["id"] for s in members]
        card["turn_ids"] = list(dict.fromkeys(t for s in members for t in s["turn_ids"]))
        card["judgments"] = [j for s in members for j in s["judgments"]]
        card["inferred"] = list(dict.fromkeys(v for s in members for v in s["inferred"]))
        card["echo"] = []
        for step in members:
            if card["echo"]:
                card["echo"].append({"text": "，"})
            card["echo"].extend(step["echo"])
        if all(s["operation"]["op"] == "substitute" for s in members):
            before, after = branch.snapshots[start], branch.snapshots[end + 1]
            definitions = [f"{s['operation']['name']}={tex(before.parse(s['operation']['a']))}" for s in members]
            # Use the final verified state: never show the half-substituted target
            # as the result of a combined substitution selected by the student.
            card["title"] = "换元"
            card["derivation"] = [
                {"lead": "设", "math": r",\quad ".join(definitions)},
                {"lead": "因为", "math": r",\quad ".join(before.view()["conditions"])},
                {"lead": "所以", "math": r",\quad ".join(after.view()["conditions"])},
                {"lead": "原式可化为", "math": before.board_tex() + "=" + after.board_tex()},
            ]
            card["lines"] = [row["math"] for row in card["derivation"]]
            card["result"] = card["derivation"][-1]["math"]
        elif len(members) > 1:
            card["title"] = "、".join(dict.fromkeys(s["title"] for s in members))
            card["lines"] = [line for step in members for line in step["lines"]]
        out.append(card)
    return out
