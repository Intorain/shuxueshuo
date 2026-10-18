"""Stage-two classification, verified stage-one replay, and offline selection replay."""

import argparse
import json
from pathlib import Path

from .runner import record_run, replay_run, run_recorded_batch, run_sample


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("run", "batch", "replay", "record", "report"):
        child = commands.add_parser(name)
        if name != "report":
            child.add_argument("--output", required=True, type=Path)
        if name == "run":
            child.add_argument("--input", required=True, type=Path)
            child.add_argument("--image", type=Path)
        elif name == "batch":
            child.add_argument("--batch", required=True, type=Path)
            child.add_argument("--case", default="all")
        else:
            child.add_argument("--recording" if name == "replay" else "--run", required=True, type=Path)
        if name in ("run", "batch"):
            child.add_argument("--verify-amgm", action="store_true")
            choice = child.add_mutually_exclusive_group()
            choice.add_argument("--live-selection", action="store_true")
            choice.add_argument("--selection-recording", type=Path)
    args = parser.parse_args()
    provider = None
    if getattr(args, "live_selection", False):
        from .selection import live_provider_factory

        provider = live_provider_factory()
    elif getattr(args, "selection_recording", None):
        from .selection import RecordedSelectionProvider

        provider = lambda: RecordedSelectionProvider(args.selection_recording)
    if args.command == "run":
        result = run_sample(args.input, args.output, provider=provider, verify=args.verify_amgm, source_image=args.image)
    elif args.command == "batch":
        result = run_recorded_batch(args.batch, args.output, cases=None if args.case == "all" else (args.case,),
                                    provider=provider, verify=args.verify_amgm)
    elif args.command == "replay":
        result = replay_run(args.recording, args.output)
    elif args.command == "record":
        print(record_run(args.run, args.output))
        return
    else:
        from .report import render_batch, render_result

        print(render_batch(args.run) if (args.run / "batch-summary.json").exists() else render_result(args.run))
        return
    print(json.dumps({key: result[key] for key in ("status", "completed", "llm", "replay_comparison") if key in result}
                     | {"report": str((args.output / "index.html").resolve())}, ensure_ascii=False))
    success = result.get("completed") if args.command == "batch" else result["status"] == "completed"
    if args.command == "replay":
        success = success and result["replay_comparison"]["ok"]
    raise SystemExit(0 if success else 1)


if __name__ == "__main__":
    main()
