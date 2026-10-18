"""Write the problem page's prototype lessons from recorded runs (no provider calls).

    uv run python tools/build_demo_lessons.py
"""

import json
import tempfile
from pathlib import Path

from shuxueshuo_server.search.lesson import present_lesson, run_stage_two

SERVER = Path(__file__).resolve().parents[1]
STAGE_ONE = SERVER / "tests/solver/fixtures/graph-guided-stage-one/recorded/live-v2-20261017-02"
STAGE_TWO = SERVER / "tests/solver/fixtures/graph-guided-stage-two/recorded"
SITE = SERVER.parent / "site/lab/search"


def stage_one(case):
    value = json.loads((STAGE_ONE / case / "sample-01/stage-one-result.json").read_text(encoding="utf-8"))
    return {"status": value["statuses"]["extraction"], "source_reviewed": True, "candidate": value["candidate"],
            "features": value["features"], "features_ok": value["statuses"]["features"]}


def write(name, lesson):
    (SITE / name).write_text(json.dumps(lesson, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def main():
    # Q01 needs the one recorded LLM selection between two supported types.
    q01 = stage_one("q01")
    recorded = json.loads((STAGE_TWO / "q01-20261018-01/stage-two-result.json").read_text(encoding="utf-8"))
    write("demo-lesson-q01.json", present_lesson(recorded, q01["features"], q01["candidate"]["original_text"], "demo-q01"))
    q10 = stage_one("q10")
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp) / "q10"
        directory.mkdir()
        result = run_stage_two(directory, q10, provider=None, unsupported_root=Path(tmp) / "unsupported")
    write("demo-lesson-q10.json", present_lesson(result, q10["features"], q10["candidate"]["original_text"], "demo-q10"))


if __name__ == "__main__":
    main()
