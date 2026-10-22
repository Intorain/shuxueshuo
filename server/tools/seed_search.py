"""Retest stages two and three on an already recognised photo search: no OCR, no LLM.

Run from server/ (the local site may keep running):

    uv run python tools/seed_search.py --from 64cf3475fc96    # copy as a new search
    uv run python tools/seed_search.py --rerun 64cf3475fc96   # new attempt on the same search

Stage two is replayed from the search's latest attempt with its recorded type
selection, so it reruns current code without a provider; stage three then runs
as the site would. The printed page URL opens the result.
"""

import argparse
import secrets
import shutil
import sys
import tempfile
import time
from pathlib import Path

from shuxueshuo_server.graph_lesson.stage_two.runner import record_run, replay_run
from shuxueshuo_server.product.config import Settings
from shuxueshuo_server.search import stage_three
from shuxueshuo_server.search.lesson import RESULT, attempts
from shuxueshuo_server.search.stage_one import RESULT_FILE

COPIED = (RESULT_FILE, "crop.json", "question.png")


def find_problem(root, search_id):
    matches = list(root.glob(f"*/problems/{search_id}"))
    if not matches:
        sys.exit(f"search not found under {root}: {search_id}")
    return matches[0]


def recorded_attempt(directory):
    done = [attempt for attempt in attempts(directory) if (attempt / RESULT).is_file()]
    if not done:
        sys.exit(f"no finished stage-two attempt to replay in {directory}")
    return done[-1]


def replay_and_run(source_attempt, target_attempt):
    started = time.monotonic()
    with tempfile.TemporaryDirectory() as scratch:
        recording = record_run(source_attempt, Path(scratch) / "recording")
        result = replay_run(recording, target_attempt)
    if not result["replay_comparison"]["ok"]:
        print("warning: stage-two decisions differ from the recorded run:", result["replay_comparison"]["differences"])
    print(f"stage two ({result['status']}) in {time.monotonic() - started:.1f}s")
    started = time.monotonic()
    outcome = stage_three.run_stage_three(target_attempt)
    print(f"stage three ({outcome.get('status')}) in {time.monotonic() - started:.1f}s")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--from", dest="source", metavar="SEARCH_ID", help="copy a recognised search as a new one")
    mode.add_argument("--rerun", metavar="SEARCH_ID", help="add a new attempt to the same search")
    parser.add_argument("--data-dir", help="Defaults to the persistent local product data directory")
    parser.add_argument("--instance", default="local")
    parser.add_argument("--port", type=int, default=8779)
    args = parser.parse_args()
    root = Settings.load("local", args.data_dir, args.instance).root / "work/search"
    source = find_problem(root, args.source or args.rerun)
    source_attempt = recorded_attempt(source)
    if args.source:
        search_id = secrets.token_hex(6)
        target = source.parent / search_id
        target.mkdir()
        for name in COPIED:
            shutil.copyfile(source / name, target / name)
    else:
        search_id, target = args.rerun, source
    try:
        lease = stage_three.acquire_problem(target)
    except stage_three.LessonBusy:
        sys.exit(f"search {search_id} is already running a lesson; wait for it to finish")
    try:
        replay_and_run(source_attempt, target / f"stage-two-{len(attempts(target)) + 1}")
    finally:
        stage_three.release_problem(lease)
    print(f"http://127.0.0.1:{args.port}/lab/search/problem.html?search={search_id}")


if __name__ == "__main__":
    main()
