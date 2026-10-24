"""Private local storage keys and leases independent of removable artifacts."""

import fcntl
import re
import shutil
from contextlib import ExitStack
from hashlib import sha256
from pathlib import Path, PurePosixPath


class SearchError(RuntimeError):
    def __init__(self, code, status=409):
        super().__init__(code)
        self.code = code
        self.status = status
        self.status_code = status


class LifecycleLease:
    def __init__(self, stream):
        self.stream = stream

    def close(self):
        if not self.stream.closed:
            fcntl.flock(self.stream, fcntl.LOCK_UN)
            self.stream.close()

    release = close

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


class SearchStorage:
    def __init__(self, root):
        self.root = Path(root).resolve()
        for name in ('pages', 'submissions', 'locks'):
            self.path(name).mkdir(mode=0o700, parents=True, exist_ok=True)

    def path(self, key):
        key = str(key)
        parts = PurePosixPath(key).parts
        if not parts or key.startswith('/') or '\\' in key or any(part in {'.', '..'} for part in parts):
            raise SearchError('storage.invalid_key', 400)
        result = self.root.joinpath(*parts)
        for parent in (result, *result.parents):
            if parent == self.root:
                break
            if parent.is_symlink():
                raise SearchError('storage.symlink', 400)
        if not result.resolve().is_relative_to(self.root):
            raise SearchError('storage.invalid_key', 400)
        return result

    @staticmethod
    def identifier(value):
        if not isinstance(value, str) or re.fullmatch(r'[0-9a-f]{12}', value) is None:
            raise SearchError('search.not_found', 404)
        return value

    def page_key(self, page_id):
        return f'pages/{self.identifier(page_id)}'

    def submission_key(self, search_id):
        return f'submissions/{self.identifier(search_id)}'

    def lifecycle_lock(self, search_id, *, blocking=False):
        return self._lock('submission-' + self.identifier(search_id), blocking)

    def page_lock(self, page_id, *, blocking=False):
        return self._lock('page-' + self.identifier(page_id), blocking)

    def read_lock(self, search_id, *, shared=True, blocking=True):
        return self._lock('read-' + self.identifier(search_id), blocking, shared=shared)

    def cleanup_lock(self, search_id):
        stack = ExitStack()
        try:
            stack.enter_context(self.lifecycle_lock(search_id))
            stack.enter_context(self.read_lock(search_id, shared=False, blocking=False))
        except BaseException:
            stack.close()
            raise
        return stack

    def _lock(self, name, blocking, *, shared=False):
        stream = self.path(f'locks/{name}.lock').open('a+b')
        try:
            fcntl.flock(stream, (fcntl.LOCK_SH if shared else fcntl.LOCK_EX) | (0 if blocking else fcntl.LOCK_NB))
        except BlockingIOError as exc:
            stream.close()
            raise SearchError('search.running', 409) from exc
        return LifecycleLease(stream)

    def remove(self, key):
        parts = PurePosixPath(str(key)).parts
        if (len(parts) != 2 or parts[0] not in {'pages', 'submissions'}
                or re.fullmatch(r'[0-9a-f]{12}', parts[1]) is None):
            raise SearchError('storage.invalid_cleanup_key', 400)
        path = self.path(key)
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)

    def digest(self, key):
        return sha256(self.path(key).read_bytes()).hexdigest()
