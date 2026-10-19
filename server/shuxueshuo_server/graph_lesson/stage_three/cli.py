"""Stage-three method selection and offline acceptance (milestone 1a)."""

import argparse
import json
from pathlib import Path

from .runner import run_recorded_batch, run_sample


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    single = commands.add_parser("run")
    single.add_argument("--input", required=True, type=Path)
    single.add_argument("--output", required=True, type=Path)
    single.add_argument("--reference-base", type=Path, help="仅用于同目录 input.json 缺失时的相对出处路径")
    batch = commands.add_parser("batch")
    batch.add_argument("--stage-one-batch", required=True, type=Path)
    batch.add_argument("--output", required=True, type=Path)
    batch.add_argument("--case", default="all")
    report = commands.add_parser("report")
    report.add_argument("--run", required=True, type=Path)
    args = parser.parse_args(argv)
    if args.command == "report":
        from .report import render_batch, render_result

        path = render_batch(args.run) if (args.run / "batch-summary.json").exists() else render_result(args.run)
        print(path.resolve())
        return 0
    if args.command == "run":
        result = run_sample(args.input, args.output, reference_base=args.reference_base)
        success = result["status"] == "completed"
    else:
        result = run_recorded_batch(args.stage_one_batch, args.output,
                                    cases=None if args.case == "all" else (args.case,))
        success = result["completed"]
    print(json.dumps({key: result[key] for key in ("status", "completed", "milestone", "llm") if key in result}
                     | {"report": str((args.output / "index.html").resolve())}, ensure_ascii=False))
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
