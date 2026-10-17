"""Stage one live, replay and report entry points; offline commands never load credentials."""

import argparse
import json
from pathlib import Path

from .runner import CASES, record_batch, replay_batch, run_batch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("run", "replay", "report", "record"):
        child = commands.add_parser(name)
        child.add_argument("--output", required=True, type=Path)
        if name != "run":
            child.add_argument("--batch", required=True, type=Path)
        if name in {"run", "replay"}:
            child.add_argument("--case", choices=("all", *CASES), default="all")
        if name == "run":
            child.add_argument("--samples", type=int, default=2)
            child.add_argument("--workers", type=int, default=3)
            child.add_argument("--provider", choices=("deepseek", "doubao"), default="deepseek")
    args = parser.parse_args()
    if args.command == "run":
        from shuxueshuo_server.problem_understanding.batch_smoke import (
            live_provider_factory,
        )

        result = run_batch(args.output, live_provider_factory(args.provider),
                           cases=CASES if args.case == "all" else (args.case,), samples=args.samples, workers=args.workers)
    elif args.command == "replay":
        result = replay_batch(args.batch, args.output, cases=CASES if args.case == "all" else (args.case,))
    elif args.command == "record":
        print(record_batch(args.batch, args.output))
        return
    else:
        from .report import render_batch

        print(render_batch(args.batch, args.output))
        return
    from .report import render_batch

    report = render_batch(args.output, args.output)
    print(json.dumps({"passed": result["passed"], "samples": len(result["results"]),
                      "output": str(args.output.resolve()), "report": str(report.resolve())}, ensure_ascii=False))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
