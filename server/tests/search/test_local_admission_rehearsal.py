import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from tests.search.local_admission_rehearsal import run_rehearsal
from tests.search.server_rehearsal import api


def test_occupied_port_is_never_replaced():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        with pytest.raises(OSError):
            run_rehearsal(port=port)
        assert listener.getsockname()[1] == port


def test_docker_fixture_api_requires_explicit_offline_opt_in(monkeypatch):
    monkeypatch.delenv("SEARCH_OFFLINE_REHEARSAL", raising=False)
    with pytest.raises(RuntimeError, match="SEARCH_OFFLINE_REHEARSAL=1"):
        api()


def test_local_http_rehearsal_completes_with_default_limits_and_no_external_calls(tmp_path):
    if not os.environ.get("PRODUCT_TEST_DATA_DIR"):
        pytest.fail("Offline HTTP rehearsal requires independently migrated PRODUCT_TEST_DATA_DIR")
    report = tmp_path / "report.json"
    completed = subprocess.run([
        sys.executable, "-m", "tests.search.local_admission_rehearsal", "--output", str(report),
    ], cwd=Path(__file__).resolve().parents[2], check=False, capture_output=True, text=True, timeout=90)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    evidence = json.loads(report.read_text())
    assert evidence["passed"] is True
    assert evidence["base_url"] == f"http://127.0.0.1:{evidence['port']}"
    assert evidence["limits"] == {
        "generation_account_daily": 10, "rerun_account_daily": 3,
        "generation_global_daily": 100, "rerun_global_daily": 50,
        "generation_account_concurrency": 1, "generation_workers": 2, "generation_queue_size": 4,
        "upload_account_limit": 2, "upload_global_limit": 10,
    }
    assert evidence["paid_calls"] == evidence["real_sms_calls"] == 0
    assert evidence["synthetic_recognition_calls"] == 10
    assert evidence["synthetic_course_calls"] == 13
    assert evidence["production_deployment"] is False
