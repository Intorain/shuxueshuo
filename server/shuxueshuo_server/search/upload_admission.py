"""Bound upload and OCR requests before their bodies are buffered."""

import os
import threading
from contextlib import contextmanager


class UploadAdmissionBusy(RuntimeError):
    pass


class UploadLease:
    def __init__(self, admission, user_id):
        self.admission = admission
        self.user_id = user_id
        self._references = 1
        self._request_active = True

    def _release(self):
        self._references -= 1
        if self._references:
            return
        count = self.admission._accounts[self.user_id] - 1
        if count:
            self.admission._accounts[self.user_id] = count
        else:
            del self.admission._accounts[self.user_id]
        self.admission._total -= 1

    def release_request(self):
        with self.admission._lock:
            if self._request_active:
                self._request_active = False
                self._release()

    @contextmanager
    def hold(self):
        with self.admission._lock:
            if not self._request_active:
                raise UploadAdmissionBusy("search.upload_busy")
            self._references += 1
        try:
            yield
        finally:
            with self.admission._lock:
                self._release()


class UploadAdmission:
    def __init__(self, *, account_limit=2, global_limit=10):
        if any(type(value) is not int or value < 1 for value in (account_limit, global_limit)):
            raise ValueError("Search upload limits must be positive integers")
        self.account_limit = account_limit
        self.global_limit = global_limit
        self._lock = threading.Lock()
        self._accounts = {}
        self._total = 0

    @classmethod
    def from_env(cls):
        return cls(
            account_limit=int(os.getenv("SEARCH_UPLOAD_ACCOUNT_LIMIT", "2")),
            global_limit=int(os.getenv("SEARCH_UPLOAD_GLOBAL_LIMIT", "10")),
        )

    @contextmanager
    def admit(self, user_id):
        user_id = str(user_id)
        with self._lock:
            count = self._accounts.get(user_id, 0)
            if count >= self.account_limit or self._total >= self.global_limit:
                raise UploadAdmissionBusy("search.upload_busy")
            self._accounts[user_id] = count + 1
            self._total += 1
            lease = UploadLease(self, user_id)
        try:
            yield lease
        finally:
            lease.release_request()
