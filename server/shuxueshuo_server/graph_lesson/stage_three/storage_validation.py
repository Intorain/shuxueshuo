"""Cache compiled storage schemas by the actual file revision, not their names."""

import json
from functools import lru_cache
from pathlib import Path

from jsonschema import Draft202012Validator


def _file_version(path):
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


class _ChangedDuringRead(Exception):
    pass


@lru_cache(maxsize=32)
def _validator(path, version):
    raw = path.read_bytes()
    if _file_version(path) != version:
        raise _ChangedDuringRead
    return Draft202012Validator(json.loads(raw))


def validate_schema(path, value):
    """A rewrite/replace invalidates cache even when file size and mtime match.

    The ctime and inode also belong to the key. A read racing an edit is never
    cached under the old metadata; repeated edits fail explicitly rather than
    silently validating with a stale schema. Paths are part of the key so tests
    and alternate schema roots cannot contaminate one another.
    """
    path = Path(path).resolve()
    for _ in range(3):
        try:
            validator = _validator(path, _file_version(path))
        except _ChangedDuringRead:
            continue
        validator.validate(value)
        return
    raise ValueError("events.schema_changed_during_read")
