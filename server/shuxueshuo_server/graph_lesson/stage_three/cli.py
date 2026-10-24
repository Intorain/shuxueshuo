"""Stage-three method execution, durable recovery and offline acceptance."""

import argparse
import json
import os
from pathlib import Path

from shuxueshuo_server.product.config import Settings
from shuxueshuo_server.product.db import engine

from .preparation import ADMISSION_BUDGET_SECONDS, SELECTION_BUDGET_SECONDS
from .runner import MILESTONE, MILESTONES, resume_sample, run_recorded_batch, run_sample
from .storage import current_storage, storage_context


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default=os.getenv("PRODUCT_TEST_DATA_DIR") or os.getenv("PRODUCT_DATA_DIR"))
    parser.add_argument("--instance", default=os.getenv("PRODUCT_TEST_INSTANCE") or os.getenv("PRODUCT_INSTANCE", "local"))
    commands = parser.add_subparsers(dest="command", required=True)
    single = commands.add_parser("run")
    single.add_argument("--input", required=True, type=Path)
    single.add_argument("--output", required=True, type=Path)
    single.add_argument("--reference-base", type=Path, help="仅用于同目录 input.json 缺失时的相对出处路径")
    single.add_argument("--milestone", choices=MILESTONES, default=MILESTONE)
    single.add_argument("--solve-budget-seconds", type=float, default=10)
    single.add_argument("--verification-budget-seconds", type=float, default=20)
    single.add_argument("--admission-budget-seconds", type=float, default=ADMISSION_BUDGET_SECONDS)
    single.add_argument("--selection-budget-seconds", type=float, default=SELECTION_BUDGET_SECONDS)
    batch = commands.add_parser("batch")
    batch.add_argument("--stage-one-batch", required=True, type=Path)
    batch.add_argument("--output", required=True, type=Path)
    batch.add_argument("--case", default="all")
    batch.add_argument("--milestone", choices=MILESTONES, default=MILESTONE)
    resume = commands.add_parser("resume")
    resume.add_argument("--run", required=True, type=Path)
    events = commands.add_parser("events")
    events.add_argument("--run", required=True, type=Path)
    events.add_argument("--after-seq", type=int, default=0)
    preview = commands.add_parser("serve")
    preview.add_argument("--run", required=True, type=Path)
    preview.add_argument("--port", type=int, default=8783)
    report = commands.add_parser("report")
    report.add_argument("--run", required=True, type=Path)
    args = parser.parse_args(argv)
    settings = Settings.load("local", args.data_dir, args.instance)
    if os.getenv("PRODUCT_TEST_SCHEMA"):
        if (not os.getenv("PRODUCT_TEST_DATA_DIR")
                or settings.root != Path(os.environ["PRODUCT_TEST_DATA_DIR"]).resolve()
                or settings.instance != os.getenv("PRODUCT_TEST_INSTANCE")):
            raise ValueError("events.test_schema_configuration_mismatch")
        database = current_storage().db
    else:
        database = engine(settings.url())
    try:
        with storage_context(database):
            return execute(args)
    finally:
        database.dispose()


def execute(args):
    if args.command in {"events", "serve"}:
        from .preview import open_store, serve

        if args.command == "serve":
            serve(args.run, port=args.port)
        else:
            store = open_store(args.run)
            rows = store.events(args.after_seq)
            print(json.dumps({"run_id": store.identity["run_id"], "events": rows,
                              "last_seq": rows[-1]["seq"] if rows else args.after_seq}, ensure_ascii=False))
        return 0
    if args.command == "report":
        from .report import render_batch, render_result

        path = render_batch(args.run) if (args.run / "batch-summary.json").exists() else render_result(args.run)
        print(path.resolve())
        return 0
    if args.command == "run":
        result = run_sample(args.input, args.output, reference_base=args.reference_base, milestone=args.milestone,
                            solve_budget_seconds=args.solve_budget_seconds,
                            verification_budget_seconds=args.verification_budget_seconds,
                            admission_budget_seconds=args.admission_budget_seconds,
                            selection_budget_seconds=args.selection_budget_seconds)
        success = result["status"] == "completed"
    elif args.command == "resume":
        args.output = args.run
        result = resume_sample(args.run)
        success = result["status"] == "completed"
    else:
        result = run_recorded_batch(args.stage_one_batch, args.output,
                                    cases=None if args.case == "all" else (args.case,), milestone=args.milestone)
        success = result["completed"]
    print(json.dumps({key: result[key] for key in ("status", "completed", "milestone", "llm") if key in result}
                     | {"report": str((args.output / "index.html").resolve())}, ensure_ascii=False))
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
