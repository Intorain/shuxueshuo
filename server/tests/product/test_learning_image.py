"""Opt-in built-image test; all containers, credentials and data are disposable.

RUN_PRODUCT_IMAGE_INTEGRATION=1 PRODUCT_TEST_ADMIN_IMAGE=<tag> uv run pytest \
    tests/product/test_learning_image.py -q
"""

import json
import os
import subprocess
from html.parser import HTMLParser
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from shuxueshuo_server.learning.content import ROOT, load_content
from shuxueshuo_server.product.config import Settings, write_private

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_PRODUCT_IMAGE_INTEGRATION") != "1",
    reason="Requires a built admin image and Docker; creates only isolated test resources",
)


def test_admin_image_publishes_learning_with_readonly_nonroot_runtime(tmp_path):
    image = os.environ["PRODUCT_TEST_ADMIN_IMAGE"]
    project = "sss-learning-image-" + uuid4().hex[:12]
    root = tmp_path / "data"
    settings = Settings.load("server", root, "image-review", initialize=True)
    postgres_env = tmp_path / "postgres.env"
    write_private(
        postgres_env,
        {
            "POSTGRES_USER": "product_bootstrap",
            "POSTGRES_PASSWORD": settings.credentials["bootstrap"],
            "POSTGRES_DB": "postgres",
        },
    )
    compose = {
        "services": {
            "postgres": {
                "image": "postgres:17.10-bookworm@sha256:9b18b78397054fce88a9552e9d5a3ad5bb7fd258c5b3cc1c5028e46373d6ea8f",
                "platform": "linux/amd64",
                "env_file": [str(postgres_env)],
                "volumes": ["database:/var/lib/postgresql/data"],
                "healthcheck": {
                    "test": [
                        "CMD-SHELL",
                        "pg_isready -U product_bootstrap -d postgres",
                    ],
                    "interval": "1s",
                    "timeout": "3s",
                    "retries": 40,
                },
            },
            "admin": {
                "image": image,
                "platform": "linux/amd64",
                "user": f"{os.getuid()}:{os.getgid()}",
                "read_only": True,
                "tmpfs": ["/tmp"],
                "security_opt": ["no-new-privileges:true"],
                "environment": {
                    "PRODUCT_IN_CONTAINER": "1",
                    "PRODUCT_PG_BIN_DIR": "/usr/lib/postgresql/17/bin",
                },
                "volumes": [f"{root}:/var/lib/shuxueshuo"],
            },
        },
        "volumes": {"database": {}},
    }
    compose_path = tmp_path / "compose.json"
    compose_path.write_text(json.dumps(compose))
    command = ["docker", "compose", "-f", str(compose_path), "-p", project]

    def run(*args):
        result = subprocess.run(
            command + list(args),
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return result.stdout

    def admin(operation):
        return json.loads(
            run(
                "run",
                "--rm",
                "--no-deps",
                "admin",
                "--mode",
                "server",
                "--data-dir",
                "/var/lib/shuxueshuo",
                "--instance",
                "image-review",
                operation,
            )
        )

    try:
        run("up", "-d", "--wait", "postgres")
        # Same read-only/non-root profile as production. Install includes migrations
        # and initial import; repeated publish verifies the requested CLI explicitly.
        head = ScriptDirectory.from_config(Config(str(ROOT / 'server/alembic.ini'))).get_current_head()
        installed = admin("install")
        assert installed["ok"] and installed["revision"] == head
        expected = {key: len(values) for key, values in load_content().items() if key != '_meta'}
        assert admin("publish-learning") == expected
        assert admin("publish-learning") == expected
        checked = admin("doctor")
        assert checked["ok"] and checked["revision"] == head
        runtime = run(
            "run", "--rm", "--no-deps", "--entrypoint", "node", "admin", "--version"
        ).strip()
        assert runtime.startswith("v18."), runtime
        # Verify the actual Node runtime exports the same private structured input.
        exported = json.loads(
            run(
                "run",
                "--rm",
                "--no-deps",
                "--entrypoint",
                "node",
                "admin",
                "/app/tools/export-public-knowledge.mjs",
            )
        )
        local = json.loads(
            subprocess.check_output(
                ["node", str(ROOT / "tools/export-public-knowledge.mjs")], text=True
            )
        )
        assert exported == local
    finally:
        # Remove only this test's uniquely named containers, volume and network.
        run("down", "--volumes", "--remove-orphans")


def test_app_image_keeps_standalone_page_compiler_assets(tmp_path):
    import shutil

    image = os.getenv("PRODUCT_TEST_APP_IMAGE")
    if not image:
        pytest.skip("Set PRODUCT_TEST_APP_IMAGE to test the API/Worker image too")
    head = ScriptDirectory.from_config(Config(str(ROOT / 'server/alembic.ini'))).get_current_head()
    packaged = subprocess.run(
        ['docker', 'run', '--rm', '--platform', 'linux/amd64', '--read-only',
         '--entrypoint', '/opt/product/bin/python', image, '-c',
         ('from alembic.config import Config; from alembic.script import ScriptDirectory; '
         'from shuxueshuo_server.product import models; '
         'assert "updated_at" in models.metadata.tables["knowledge_drill_attempts"].c; '
         'print(ScriptDirectory.from_config(Config("/app/server/alembic.ini")).get_current_head())')],
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert packaged.returncode == 0, packaged.stdout + packaged.stderr
    assert packaged.stdout.strip() == head
    fixture = ROOT / "internal/lesson-specs/tj-2026-nankai-yimo-25"
    for name in ("geometry-spec.json", "step-decorations.json", "lesson-data.json"):
        shutil.copyfile(fixture / name, tmp_path / name)
    data = json.loads((tmp_path / "lesson-data.json").read_text())
    data["meta"]["outputPath"] = "/tmp/input/lesson.html"
    (tmp_path / "lesson-data.json").write_text(json.dumps(data))
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--platform",
            "linux/amd64",
            "--read-only",
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "--tmpfs",
            "/tmp",
            "--mount",
            f"type=bind,source={tmp_path},target=/tmp/input",
            "--workdir",
            "/app",
            "--entrypoint",
            "node",
            image,
            "tools/build-lesson-page.mjs",
            "/tmp/input",
            "--standalone",
            "--product-preview",
        ],
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    html = (tmp_path / "lesson.html").read_text()
    assert "GeometryLessonFromSpec" in html and "<style>" in html

    class InlineScripts(HTMLParser):
        def handle_starttag(self, tag, attrs):
            if tag == "script":
                assert "src" not in dict(attrs)

    InlineScripts().feed(html)
