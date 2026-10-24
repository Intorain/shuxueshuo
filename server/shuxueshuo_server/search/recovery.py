"""Independent, durable deletion authority for restoring private search backups."""

import fcntl
import json
import logging
import os
import re
import stat
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import cached_property
from hashlib import sha256
from pathlib import Path
from time import monotonic, sleep
from uuid import UUID, uuid4

import sqlalchemy as sa

from ..product.db import canonical, transaction
from ..product.models import metadata
from .storage import SearchError

STATE = metadata.tables['search_recovery_state']
SCHEMA = 'search-deletions/v1'
WRITE_LOCK_TIMEOUT = 0.25
LOGGER = logging.getLogger(__name__)


def _failure(code='invalid'):
    return SearchError('recovery.' + code, 503)


def entry_key(row):
    created = row['created_at']
    if isinstance(created, str):
        created = datetime.fromisoformat(created)
    if created.tzinfo is None:
        raise _failure()
    return str(UUID(str(row['user_id']))), str(row.get('search_id', row.get('id'))), created.astimezone(UTC).isoformat()


def _digest(value):
    return sha256(canonical(value).encode('utf-8')).hexdigest()


@dataclass(frozen=True)
class JournalSnapshot:
    authority_id: str
    entries: tuple
    digests: tuple

    @property
    def cursor(self):
        return {'authority_id': self.authority_id, 'sequence': len(self.digests) - 1, 'digest': self.digests[-1]}

    @cached_property
    def deleted_keys(self):
        return frozenset(entry_key(entry) for entry in self.entries)

    @cached_property
    def keys_by_owner(self):
        owners = {}
        for key in self.deleted_keys:
            owners.setdefault(key[0], []).append(key)
        return {owner: tuple(keys) for owner, keys in owners.items()}

    def validate_cursor(self, cursor):
        if not isinstance(cursor, dict) or cursor.get('authority_id') != self.authority_id:
            raise _failure('authority_mismatch')
        sequence = cursor.get('sequence')
        if (type(sequence) is not int or sequence < 0 or sequence >= len(self.digests)
                or cursor.get('digest') != self.digests[sequence]):
            raise _failure('journal_behind')
        return self


class RecoveryJournal:
    def __init__(self, root):
        self.root = Path(root) / 'recovery'
        self.path = self.root / 'deletions.jsonl'
        self.lock_path = self.root / 'authority.lock'
        self._cached = None

    def _safe(self):
        if any(path.is_symlink() for path in (self.root, self.path, self.lock_path)):
            raise _failure('symlink')

    @contextmanager
    def _lock(self, *, write=False, create=False, timeout=None):
        self._safe()
        if create:
            self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not self.root.is_dir():
            raise _failure('missing')
        try:
            descriptor = os.open(self.lock_path,
                os.O_NOFOLLOW | os.O_NONBLOCK | (os.O_RDWR if write or create else os.O_RDONLY)
                | (os.O_CREAT if create else 0), 0o600)
        except FileNotFoundError as exc:
            raise _failure('missing') from exc
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            os.close(descriptor)
            raise _failure('not_regular')
        with os.fdopen(descriptor, 'r+b' if write or create else 'rb') as stream:
            deadline = None if timeout is None else monotonic() + timeout
            while True:
                try:
                    fcntl.flock(stream, (fcntl.LOCK_EX if write else fcntl.LOCK_SH)
                                | (0 if deadline is None else fcntl.LOCK_NB))
                    break
                except BlockingIOError as exc:
                    remaining = deadline - monotonic()
                    if remaining <= 0:
                        raise _failure('busy') from exc
                    sleep(min(0.01, remaining))
            try:
                self._safe()
                if not self.lock_path.exists() or self.lock_path.stat().st_ino != os.fstat(descriptor).st_ino:
                    raise _failure('lock_replaced')
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)

    def _parse(self, raw):
        records = [json.loads(line) for line in raw.splitlines()]
        first = records[0]
        authority = str(UUID(first['authority_id']))
        header = {'schema_version': SCHEMA, 'authority_id': authority, 'sequence': 0}
        if first != {**header, 'digest': _digest(header)}:
            raise _failure()
        digests, entries = [first['digest']], []
        for sequence, record in enumerate(records[1:], 1):
            payload = {key: value for key, value in record.items() if key != 'digest'}
            if (set(payload) != {'sequence', 'previous_digest', 'entries'}
                    or type(record['sequence']) is not int or record['sequence'] != sequence
                    or record['previous_digest'] != digests[-1] or _digest(payload) != record['digest']
                    or not isinstance(record['entries'], list) or not record['entries']):
                raise _failure()
            for entry in record['entries']:
                if (set(entry) != {'user_id', 'search_id', 'created_at'}
                        or re.fullmatch(r'[0-9a-f]{12}', entry['search_id']) is None
                        or entry_key(entry) != (entry['user_id'], entry['search_id'], entry['created_at'])):
                    raise _failure()
            entries.extend(record['entries'])
            digests.append(record['digest'])
        return JournalSnapshot(authority, tuple(entries), tuple(digests))

    def _validate_checkpoint(self, snapshot, state):
        if not state['initialized']:
            raise _failure('uninitialized')
        snapshot.validate_cursor({'authority_id': str(state['authority_id']),
                                  'sequence': state['sequence'], 'digest': state['digest']})
        if state['replayed_sequence'] > snapshot.cursor['sequence']:
            raise _failure('journal_behind')
        return snapshot

    def _read(self, *, repair_state=None):
        try:
            descriptor = os.open(self.path, (os.O_RDWR if repair_state is not None else os.O_RDONLY)
                                 | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(descriptor, 'r+b' if repair_state is not None else 'rb') as stream:
                information = os.fstat(descriptor)
                if not stat.S_ISREG(information.st_mode):
                    raise _failure('not_regular')
                signature = (information.st_dev, information.st_ino, information.st_size,
                             information.st_mtime_ns, information.st_ctime_ns)
                if self._cached is not None and self._cached[0] == signature:
                    return self._cached[1]
                raw = stream.read()
                complete_size = raw.rfind(b'\n') + 1
                if not complete_size or (complete_size != len(raw) and repair_state is None):
                    raise _failure('truncated')
                snapshot = self._parse(raw[:complete_size])
                if complete_size != len(raw):
                    self._validate_checkpoint(snapshot, repair_state)
                    os.ftruncate(descriptor, complete_size)
                    os.fsync(descriptor)
                    LOGGER.warning('Repaired incomplete search deletion journal tail: path=%s bytes=%s sequence=%s',
                                   self.path, len(raw) - complete_size, snapshot.cursor['sequence'])
                    information = os.fstat(descriptor)
                    signature = (information.st_dev, information.st_ino, information.st_size,
                                 information.st_mtime_ns, information.st_ctime_ns)
            self._cached = signature, snapshot
            return snapshot
        except FileNotFoundError as exc:
            raise _failure('missing') from exc
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise _failure() from exc

    @contextmanager
    def locked_snapshot(self):
        with self._lock():
            yield self._read()

    def snapshot(self):
        with self.locked_snapshot() as snapshot:
            return snapshot

    def _sync_directory(self):
        directory = os.open(self.root, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)

    def _discard_uninitialized_fragment(self):
        try:
            descriptor = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except FileNotFoundError:
            return
        with os.fdopen(descriptor, 'rb') as stream:
            information = os.fstat(descriptor)
            if not stat.S_ISREG(information.st_mode):
                raise _failure('not_regular')
            raw = stream.read()
            if b'\n' in raw:
                return
            current = self.path.lstat()
            if (current.st_dev, current.st_ino) != (information.st_dev, information.st_ino):
                raise _failure('journal_replaced')
            self.path.unlink()
            self._cached = None
            self._sync_directory()
            LOGGER.warning('Discarded uninitialized search deletion journal fragment: path=%s bytes=%s',
                           self.path, len(raw))

    def _write(self, payload, *, create=False):
        flags = os.O_WRONLY | os.O_NOFOLLOW | (os.O_CREAT | os.O_EXCL if create else os.O_APPEND)
        descriptor = os.open(self.path, flags, 0o600)
        try:
            information = os.fstat(descriptor)
            if not stat.S_ISREG(information.st_mode):
                raise _failure('not_regular')
            try:
                pending = memoryview((canonical(payload) + '\n').encode('utf-8'))
                while pending:
                    written = os.write(descriptor, pending)
                    if not written:
                        raise OSError('Deletion journal write made no progress')
                    pending = pending[written:]
                os.fsync(descriptor)
                if create:
                    self._sync_directory()
            except OSError:
                self._cached = None
                try:
                    if create:
                        current = self.path.lstat()
                        if (current.st_dev, current.st_ino) != (information.st_dev, information.st_ino):
                            raise OSError('Created deletion journal was replaced')
                        self.path.unlink()
                        self._sync_directory()
                    else:
                        os.ftruncate(descriptor, information.st_size)
                        os.fsync(descriptor)
                except OSError:
                    LOGGER.exception('Could not roll back failed search deletion journal write: path=%s', self.path)
                raise
        finally:
            os.close(descriptor)

    def initialize(self, db):
        with transaction(db) as connection:
            state = dict(connection.execute(sa.select(STATE).with_for_update()).mappings().one())
            with self._lock(write=True, create=not state['initialized']):
                if not state['initialized']:
                    if state['sequence'] != 0 or state['replayed_sequence'] != 0 or state['digest'] != '':
                        raise _failure('invalid_initial_state')
                    self._discard_uninitialized_fragment()
                    authority = str(state['authority_id'])
                    if not self.path.exists():
                        header = {'schema_version': SCHEMA, 'authority_id': authority, 'sequence': 0}
                        self._write({**header, 'digest': _digest(header)}, create=True)
                    snapshot = self._read()
                    if snapshot.authority_id != authority:
                        raise _failure('authority_mismatch')
                    connection.execute(STATE.update().values(initialized=True, **{
                        name: snapshot.cursor[name] for name in ('sequence', 'digest')}))
                else:
                    self.validate_state(connection, self._read(repair_state=state), state=state)
        db._search_recovery = self

    def validate_state(self, connection, snapshot=None, *, state=None):
        state = state or connection.execute(sa.select(STATE)).mappings().one()
        snapshot = snapshot or self.snapshot()
        return self._validate_checkpoint(snapshot, state)

    def is_deleted(self, connection, row, *, snapshot=None):
        return entry_key(row) in self.validate_state(connection, snapshot).deleted_keys

    def append(self, connection, rows):
        state = connection.execute(sa.select(STATE).with_for_update()).mappings().one()
        with self._lock(write=True, timeout=WRITE_LOCK_TIMEOUT):
            snapshot = self.validate_state(connection, self._read(), state=state)
            applied = state['replayed_sequence'] == snapshot.cursor['sequence']
            entries = [dict(zip(('user_id', 'search_id', 'created_at'), entry_key(row))) for row in rows]
            entries = [entry for entry in entries if entry_key(entry) not in snapshot.deleted_keys]
            if entries:
                payload = {'sequence': snapshot.cursor['sequence'] + 1,
                           'previous_digest': snapshot.cursor['digest'], 'entries': entries}
                self._write({**payload, 'digest': _digest(payload)})
                snapshot = self._read()
            values = {'sequence': snapshot.cursor['sequence'], 'digest': snapshot.cursor['digest']}
            if applied:
                values['replayed_sequence'] = snapshot.cursor['sequence']
            connection.execute(STATE.update().values(**values))
            return snapshot


def initialize_restored_authority(db, root):
    journal = RecoveryJournal(root)
    if journal.root.exists():
        raise _failure('target_authority_exists')
    with transaction(db) as connection:
        connection.execute(STATE.delete())
        connection.execute(STATE.insert().values(singleton=True, authority_id=uuid4(), initialized=False,
                                                sequence=0, digest=''))
    journal.initialize(db)
    return journal
