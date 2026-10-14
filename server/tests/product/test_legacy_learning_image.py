"""Restore a real 0010 backup using the corresponding historical admin image."""
import json
import os
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

from shuxueshuo_server.product.config import Settings, write_private

pytestmark = pytest.mark.skipif(
    os.getenv('RUN_LEGACY_IMAGE_RESTORE') != '1',
    reason='Requires explicit old/new admin images; creates isolated Docker volumes',
)


def test_legacy_backup_restored_with_matching_old_admin_image(tmp_path):
    old_image = os.environ['PRODUCT_TEST_LEGACY_ADMIN_IMAGE']
    new_image = os.environ['PRODUCT_TEST_ADMIN_IMAGE']
    projects = []

    def cluster(label):
        project = 'sss-legacy-restore-' + uuid4().hex[:12]
        base = tmp_path / label
        base.mkdir()
        root = base / 'data'
        settings = Settings.load('server', root, label, initialize=True)
        credentials = base / 'postgres.env'
        write_private(credentials, {'POSTGRES_USER': 'product_bootstrap',
                                    'POSTGRES_PASSWORD': settings.credentials['bootstrap'], 'POSTGRES_DB': 'postgres'})
        profile = {'platform': 'linux/amd64', 'user': f'{os.getuid()}:{os.getgid()}',
                   'read_only': True, 'tmpfs': ['/tmp'], 'security_opt': ['no-new-privileges:true'],
                   'environment': {'PRODUCT_IN_CONTAINER': '1', 'PRODUCT_PG_BIN_DIR': '/usr/lib/postgresql/17/bin'},
                   'volumes': [f'{root}:/var/lib/shuxueshuo']}
        spec = {'services': {
            'postgres': {'image': 'postgres:17.10-bookworm@sha256:9b18b78397054fce88a9552e9d5a3ad5bb7fd258c5b3cc1c5028e46373d6ea8f',
                         'platform': 'linux/amd64', 'env_file': [str(credentials)],
                         'volumes': ['database:/var/lib/postgresql/data'],
                         'healthcheck': {'test': ['CMD-SHELL', 'pg_isready -U product_bootstrap -d postgres'],
                                         'interval': '1s', 'timeout': '3s', 'retries': 40}},
            'old': {**profile, 'image': old_image}, 'new': {**profile, 'image': new_image}},
            'volumes': {'database': {}}}
        file = base / 'compose.json'
        file.write_text(json.dumps(spec))
        prefix = ['docker', 'compose', '-f', str(file), '-p', project]
        projects.append(prefix)

        def run(*args):
            result = subprocess.run(prefix + list(args), capture_output=True, text=True, timeout=180, check=False)
            assert result.returncode == 0, result.stdout + result.stderr
            return result.stdout

        def admin(service, operation):
            return json.loads(run('run', '--rm', '--no-deps', service, '--mode', 'server',
                                  '--data-dir', '/var/lib/shuxueshuo', '--instance', label, operation))
        run('up', '-d', '--wait', 'postgres')
        return root, run, admin

    try:
        source_root, _source_run, source = cluster('legacy-source')
        assert source('old', 'install')['revision'] == '0010_learning_record_integrity'
        inventory = source('new', 'preflight-learning')
        assert inventory['state'] == 'legacy_public_only'
        saved = source('new', 'backup')
        source_backup = source_root / Path(saved['backup']).relative_to('/var/lib/shuxueshuo')
        manifest = json.loads((source_backup / 'manifest.json').read_text())
        assert manifest['revision'] == '0010_learning_record_integrity'
        _, restore_run, restored = cluster('legacy-restored')
        restored('old', 'bootstrap')
        output = restore_run('run', '--rm', '--no-deps', '-v', f'{source_backup}:/restore:ro',
            '--entrypoint', '/opt/product/bin/python', 'old', '-c',
            'import json; from shuxueshuo_server.product.config import Settings; '
            'from shuxueshuo_server.product.admin.backup import restore_data; '
            'print(json.dumps(restore_data(Settings.load("server","/var/lib/shuxueshuo","legacy-restored"),"/restore")))')
        assert json.loads(output)['revision'] == '0010_learning_record_integrity'
        assert restored('old', 'doctor')['ok']
        after = restored('new', 'preflight-learning')
        assert after['state'] == 'legacy_public_only' and after['counts'] == inventory['counts']
    finally:
        for prefix in reversed(projects):
            subprocess.run(prefix + ['down', '--volumes', '--remove-orphans'], check=True, capture_output=True, timeout=90)
