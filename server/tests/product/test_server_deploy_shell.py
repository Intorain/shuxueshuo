"""Run the packaged deploy shell with transport stubs, including Bash 3.2."""

import json
import os
import shutil
import subprocess
import sys

import pytest

from shuxueshuo_server.product.config import REPO


def shell_fixture(tmp_path, *, site, services=False, failure=''):
    release = tmp_path / 'release'
    shutil.copytree(REPO / 'deploy/product', release / 'scripts')
    admin_id = 'sha256:' + 'a' * 64
    postgres_id = 'sha256:' + 'b' * 64
    (release / 'release.env').write_text(
        'PRODUCT_RELEASE_ID=shell-test\n'
        'PRODUCT_PLATFORM=linux/amd64\n'
        f'PRODUCT_ADMIN_IMAGE={admin_id}\n'
        f'PRODUCT_POSTGRES_IMAGE={postgres_id}\n'
    )
    root = tmp_path / 'existing instance'
    config = root / 'config'
    config.mkdir(parents=True)
    (config / 'compose.env').write_text("PRODUCT_DB_PORT='55439'\n")
    (config / 'bootstrap.env').write_text("PRODUCT_BOOTSTRAP_PASSWORD='fixture'\n")
    (config / 'release-path').write_text(str(release) + '\n')
    repo = tmp_path / 'repo'
    teaching = repo / 'site/knowledge/teaching'
    teaching.mkdir(parents=True)
    if site:
        (teaching / 'version.json').write_text('{}')
    if services:
        with (release / 'release.env').open('a') as stream:
            stream.write('PRODUCT_APP_IMAGE=sha256:' + 'c' * 64 + '\n')
            stream.write('PRODUCT_RABBITMQ_IMAGE=sha256:' + 'd' * 64 + '\n')
        (config / 'runtime.env').write_text(
            "BROKER_PORT='5672'\nBROKER_USER='fixture'\nBROKER_PASSWORD='fixture'\n"
            "BROKER_VHOST='fixture'\nBROKER_COOKIE='fixture'\n"
            "API_PORT='8000'\nFRONTEND_PORT='3000'\n"
        )
        (repo / 'server').mkdir()
        (repo / 'server/.env').write_text('')

    binary = tmp_path / 'bin'
    binary.mkdir()
    log = tmp_path / 'docker-calls.jsonl'
    docker = binary / 'docker'
    docker.write_text(f'#!{sys.executable}\n' + '''
import json
import os
from pathlib import Path
import sys

args = sys.argv[1:]
with open(os.environ['DOCKER_CALL_LOG'], 'a') as stream:
    stream.write(json.dumps(args) + '\\n')
if args[:2] == ['compose', 'version']:
    pass
elif args[:2] == ['image', 'inspect']:
    if len(args) == 3:
        pass
    elif args[3] == '{{.Id}}':
        print(args[-1])
    elif args[3] == '{{.Os}}/{{.Architecture}}':
        print('linux/amd64')
    else:
        raise AssertionError(args)
elif args[:2] == ['volume', 'inspect']:
    sys.exit(1)
elif args[:3] == ['inspect', '--format', '{{.Image}}']:
    print(os.environ['TEST_POSTGRES_IMAGE'])
elif args[0] == 'run':
    assert args[-1] == 'configure' or '--entrypoint' in args, args
elif args[0] == 'compose':
    if args[-3:] == ['ps', '-q', 'postgres']:
        print('fixture-postgres-container')
    elif 'stop' in args:
        assert Path(os.environ['TEST_DRAIN_MARKER']).exists(), args
        if os.environ['TEST_SERVICE_FAILURE'] == 'stop-api' and args[-1] == 'api':
            sys.exit(39)
    elif 'up' in args:
        if os.environ['TEST_SERVICE_FAILURE'] == 'up' and args[-1] == 'publisher':
            sys.exit(39)
    elif args[-1] == 'services-doctor':
        assert Path(os.environ['TEST_DRAIN_MARKER']).exists(), args
        if os.environ['TEST_SERVICE_FAILURE'] == 'doctor':
            sys.exit(39)
        print(json.dumps({'ok': True}))
    else:
        assert 'run' in args and 'admin' in args, args
        assert 'deploy' in args or 'verify-release' in args, args
        print(json.dumps({'ok': True, 'site': 'match'}))
else:
    raise AssertionError(args)
''')
    docker.chmod(0o755)
    def run(operation, *flags):
        # macOS /bin/bash is 3.2: an empty "${array[@]}" fails under set -u there.
        # Execute the real script; Docker transport alone is stubbed.
        return subprocess.run(
            ['/bin/bash', str(release / 'scripts/server/run.sh'), '--mode', 'server',
             '--release', str(release), '--data-dir', str(root), operation, *flags],
            env={**os.environ, 'PATH': str(binary) + os.pathsep + os.environ['PATH'],
                 'DOCKER_CALL_LOG': str(log), 'TEST_POSTGRES_IMAGE': postgres_id,
                 'PRODUCT_REPO_HOST': str(repo), 'PRODUCT_HOST_HOME': str(tmp_path / 'home'),
                 'TEST_DRAIN_MARKER': str(root / 'locks/services-draining'),
                 'TEST_SERVICE_FAILURE': failure},
            capture_output=True, text=True, check=False,
        )
    return release, root, repo, log, run


@pytest.mark.parametrize('replace_public', [False, True])
@pytest.mark.parametrize('site', [False, True])
def test_deploy_forwards_optional_flags_under_nounset(tmp_path, replace_public, site):
    _, root, repo, log, run = shell_fixture(tmp_path, site=site)
    flags = ['--replace-legacy-public'] if replace_public else []
    result = run('deploy', *flags)
    assert result.returncode == 0, result.stderr
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    deployments = [args for args in calls if args[0] == 'compose' and 'deploy' in args]
    assert len(deployments) == 1
    command = deployments[0]
    assert command[command.index('deploy'):] == ['deploy', *flags]
    # Only the repository's teaching version is mounted; the release package carries no site.
    mount = f'{repo / "site/knowledge/teaching"}:/site-teaching:ro'
    assert (mount in command) == site
    assert ('--site-version' in command) == site
    assert not any(':/release' in arg for arg in command) and '--release-dir' not in command
    assert not (root / 'locks/server-operation').exists()
    assert len(list((root / 'deployments').glob('*.json'))) == 1


@pytest.mark.parametrize('state', ['clean', 'ahead', 'dirty'])
def test_strict_verify_checks_repository_before_configure_or_database(tmp_path, state):
    release, root, repo, log, run = shell_fixture(tmp_path, site=True)

    def git(*args):
        return subprocess.run(['git', '-C', str(repo), '-c', 'commit.gpgsign=false', *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    git('init', '-q')
    git('add', '.')
    git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'release')
    revision = git('rev-parse', 'HEAD')
    with (release / 'release.env').open('a') as stream:
        stream.write(f'PRODUCT_SOURCE_REVISION={revision}\n')
    if state != 'clean':
        (repo / 'site/knowledge/teaching/version.json').write_text('{"changed":true}')
        if state == 'ahead':
            git('add', '.')
            git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'later pages')

    before = {str(file.relative_to(root)): file.read_bytes() for file in root.rglob('*') if file.is_file()}
    result = run('verify-release')
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    admin_calls = [args for args in calls if args[0] == 'compose' and 'run' in args]
    configure_calls = [args for args in calls if args[-1] == 'configure']
    if state == 'clean':
        assert result.returncode == 0, result.stderr
        assert len(configure_calls) == 1
        assert len(admin_calls) == 1
        assert admin_calls[0][-1] == 'verify-release'
        assert '--site-version' in admin_calls[0]
        assert '--site-optional' not in admin_calls[0]
        assert json.loads(result.stdout.splitlines()[-1])['site'] == 'match'
    else:
        assert result.returncode != 0
        expected = '未提交或未跟踪' if state == 'dirty' else 'HEAD 与发布包提交不同'
        assert expected in result.stderr
        assert not configure_calls and not admin_calls
        assert not [args for args in calls if args[0] == 'compose' and args[1:] != ['version']]
        assert not (root / 'locks').exists()
        assert before == {str(file.relative_to(root)): file.read_bytes() for file in root.rglob('*') if file.is_file()}


@pytest.mark.parametrize('failure', ['', 'stop-api'])
def test_service_stop_drains_api_before_ocr_and_retains_marker(tmp_path, failure):
    _, root, _, log, run = shell_fixture(tmp_path, site=False, services=True, failure=failure)
    marker = root / 'locks/services-draining'
    assert not marker.exists()
    result = run('services-stop')
    assert result.returncode == (39 if failure else 0), result.stderr
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    stops = [args[args.index('stop') + 1:] for args in calls if 'stop' in args]
    assert stops == ([['api']] if failure else [['api'], ['worker', 'publisher'], ['ocr', 'rabbitmq']])
    assert marker.exists()
    assert not (root / 'locks/server-operation').exists()
    if not failure:
        assert json.loads(result.stdout.splitlines()[-1])['postgres'] == 'left_running'


@pytest.mark.parametrize('operation', ['services-start', 'services-doctor'])
@pytest.mark.parametrize('failure', ['', 'up', 'doctor'])
def test_service_start_only_reopens_admission_after_health_checks(tmp_path, operation, failure):
    _, root, _, log, run = shell_fixture(tmp_path, site=False, services=True, failure=failure)
    marker = root / 'locks/services-draining'
    marker.parent.mkdir()
    marker.touch()
    result = run(operation)
    assert result.returncode == (39 if failure else 0), result.stderr
    assert marker.exists() == bool(failure or operation == 'services-doctor')
    assert not (root / 'locks/server-operation').exists()
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    assert any(args[-1] == 'verify-release' or args[-2:] == ['verify-release', '--site-optional'] for args in calls)
    doctors = [args for args in calls if args[-1] == 'services-doctor']
    assert len(doctors) == (0 if failure == 'up' else 1)
