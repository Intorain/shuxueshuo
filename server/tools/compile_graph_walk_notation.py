"""Read a notation candidate from stdin; emit its validated mathematical projection."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shuxueshuo_server.problem_understanding.notation_compile import NotationValidator


def compile_candidate(candidate):
    report = NotationValidator().validate(candidate)
    if not report.ok:
        raise ValueError(json.dumps(report.issues, ensure_ascii=False))
    # Extraction/matching metadata is not an input to the demo actor.
    return {
        'root': report.normalized['root'],
        'semantic': report.semantic,
        'source_locations': report.source_locations,
    }


if __name__ == '__main__':
    try:
        print(json.dumps(compile_candidate(json.load(sys.stdin)), ensure_ascii=False))
    except (ValueError, KeyError, TypeError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1) from error
