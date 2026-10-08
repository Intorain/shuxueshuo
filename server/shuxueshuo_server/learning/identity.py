"""One-time legacy identities remain reserved aliases, never new exercises."""

import json
from pathlib import Path

ALIASES = json.loads(Path(__file__).with_name("problem_aliases.json").read_text())


def canonical_id(value: str) -> str:
    return ALIASES.get(value, value)
