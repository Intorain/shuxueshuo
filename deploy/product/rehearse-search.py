"""Repackage cached dependencies and rehearse student search on an isolated Docker network."""

import argparse
import hashlib
import json
import os
import secrets
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def run(*command, capture=False):
    result = subprocess.run(command, check=True, text=True, capture_output=capture)
    return result.stdout.strip() if capture else None


def private_file(path, content):
    with path.open('x', encoding='utf-8') as stream:
        os.chmod(path, 0o600)
        stream.write(content)


def image_info(image):
    return json.loads(run('docker', 'image', 'inspect', image, capture=True))[0]


def offline_recipe(kind, base):
    original = (REPO / f'deploy/product/Dockerfile.{kind}').read_text()
    tail = original[original.index('COPY server /app/server'):]
    return (
        f'FROM {base}\n'
        'COPY deploy/product/requirements.lock /tmp/rehearsal-requirements.lock\n'
        'RUN cmp /tmp/requirements.lock /tmp/rehearsal-requirements.lock\n'
        'RUN rm -rf /app/server /app/tools /app/internal /app/site\n' + tail
    )


def prepare_fixtures(output):
    fixtures = output / 'fixtures'
    fixtures.mkdir()
    source = REPO / 'server/tests/solver/fixtures'
    shutil.copytree(source / 'graph-guided-stage-two/recorded/q01-20261018-02', fixtures / 'recording')
    shutil.copyfile(source / 'graph-guided-stage-one/quadratic-always/q01/notation.gold.json', fixtures / 'candidate.json')
    shutil.copyfile(REPO / 'server/tests/search/server_rehearsal.py', fixtures / 'server_rehearsal.py')
    shutil.copyfile(REPO / 'deploy/ocr/sidecar_server.py', fixtures / 'sidecar_server.py')
    return fixtures


def wait_container(name, command, timeout=120):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        checked = subprocess.run(['docker', 'exec', name, *command], capture_output=True, check=False)
        if checked.returncode == 0:
            return
        state = run('docker', 'inspect', '--format', '{{.State.Running}}', name, capture=True)
        if state != 'true':
            raise RuntimeError(f'{name} exited before becoming ready')
        time.sleep(1)
    raise TimeoutError(f'{name} did not become ready')


def rehearse(args, output):
    identity = 'search-rehearsal-' + secrets.token_hex(5)
    network, volume = identity, identity + '-postgres'
    names = {key: identity + '-' + key for key in ('postgres', 'api', 'ocr', 'nginx')}
    images = {key: image_info(getattr(args, key)) for key in ('app', 'admin', 'postgres', 'nginx')}
    report = {
        'kind': 'offline-search-image-rehearsal/v1',
        'source_revision': run('git', '-C', str(REPO), 'rev-parse', 'HEAD', capture=True),
        'working_tree': run('git', '-C', str(REPO), 'status', '--short', capture=True),
        'bases': {key: {'id': value['Id'], 'platform': value['Os'] + '/' + value['Architecture']}
                  for key, value in images.items()},
        'paid_calls': 0,
        'production_deployment': False,
        'passed': False,
        'limitations': ['Cached dependency layers, not a fresh dependency installation.',
                        'Synthetic public review, recorded stage two, fixture SMS and OCR inference.',
                        'Real production API, OCR HTTP transport, Nginx TLS/WebSocket and PostgreSQL execution.'],
    }
    tags = {kind: 'docker.io/library/' + identity + '-' + kind for kind in ('app', 'admin')}
    for kind, tag in tags.items():
        recipe = output / f'{kind}.Dockerfile'
        recipe.write_text(offline_recipe(kind, getattr(args, kind)))
        shutil.copyfile(REPO / f'deploy/product/Dockerfile.{kind}.dockerignore', Path(str(recipe) + '.dockerignore'))
        run('docker', 'build', '--pull=false', '--network=none', '--platform', report['bases'][kind]['platform'],
            '-f', str(recipe), '-t', tag, str(REPO))
        report[kind + '_image'] = image_info(tag)['Id']
        run('docker', 'run', '--rm', '--pull=never', '--network=none',
            '--entrypoint', '/opt/product/bin/python', tag, '-c',
            'from pathlib import Path; root=Path("/app/server"); '
            'assert not any((root/name).exists() for name in (".env", ".venv", ".venv-ocr", "tests"))')
    data = output / 'data'
    data.mkdir(mode=0o700)
    fixtures = prepare_fixtures(output)
    uid = f'{os.getuid()}:{os.getgid()}'
    common = ['--pull=never', '--user', uid, '-e', 'PRODUCT_IN_CONTAINER=1', '-e', 'PRODUCT_MODE=server',
              '-e', 'PRODUCT_INSTANCE=search-rehearsal', '-e', 'PRODUCT_DATA_DIR=/var/lib/shuxueshuo',
              '-v', f'{data}:/var/lib/shuxueshuo']
    admin = ['docker', 'run', '--rm', *common, tags['admin'], '--mode', 'server',
             '--instance', 'search-rehearsal', '--data-dir', '/var/lib/shuxueshuo']
    run(*admin[:3], '--network=none', *admin[3:], 'configure')
    bootstrap = (data / 'config/bootstrap.env').read_text().split('=', 1)[1].strip().strip("'")
    private_file(output / 'postgres.env', f'POSTGRES_USER=product_bootstrap\nPOSTGRES_PASSWORD={bootstrap}\n')
    private_file(output / 'api.env', '\n'.join([
        'PRODUCT_EXECUTION_STORAGE_CONTEXT_REQUIRED=1', 'PRODUCT_OCR_URL=http://ocr:8080',
        'AUTH_ENVIRONMENT=production', 'AUTH_ORIGIN=https://shuxueshuo.com', 'AUTH_COOKIE_SECURE=1',
        'AUTH_SMS_MODE=aliyun_sms', 'AUTH_SECRET=' + secrets.token_urlsafe(48),
        'ALIYUN_SMS_ACCESS_KEY_ID=offline-fixture', 'ALIYUN_SMS_ACCESS_KEY_SECRET=offline-fixture',
        'ALIYUN_SMS_SIGN_NAME=offline-fixture', 'ALIYUN_SMS_TEMPLATE_CODE=offline-fixture',
        'RUN_LLM_INTEGRATION=1', 'REVIEW_BACKEND=product',
    ]) + '\n')
    certificate = output / 'cert'
    certificate.mkdir()
    run('openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
        '-subj', '/CN=shuxueshuo.com', '-keyout', str(certificate / 'shuxueshuo.com.key'),
        '-out', str(certificate / 'shuxueshuo.com.pem'))
    proxy = output / 'shuxueshuo.conf'
    proxy.write_bytes((REPO / 'deploy/nginx/shuxueshuo.conf').read_bytes())
    report['nginx_config_sha256'] = hashlib.sha256(proxy.read_bytes()).hexdigest()
    started = []
    network_created = volume_created = False
    try:
        run('docker', 'network', 'create', '--internal', network)
        network_created = True
        run('docker', 'volume', 'create', volume)
        volume_created = True
        run('docker', 'run', '--pull=never', '-d', '--name', names['postgres'], '--network', network,
            '--network-alias', 'postgres', '--env-file', str(output / 'postgres.env'),
            '-v', f'{volume}:/var/lib/postgresql/data', args.postgres)
        started.append(names['postgres'])
        wait_container(names['postgres'], ['pg_isready', '-U', 'product_bootstrap', '-d', 'postgres'])
        run(*admin[:3], '--network', network, *admin[3:], 'install')
        runtime = ['docker', 'run', '--rm', '--network', network, *common,
                   '--env-file', str(output / 'api.env'), '-v', f'{fixtures}:/rehearsal:ro',
                   '--entrypoint', '/opt/product/bin/python', tags['app'], '/rehearsal/server_rehearsal.py']
        for service in ('ocr', 'api'):
            command = ['docker', 'run', '-d', '--name', names[service], '--network', network,
                       '--network-alias', service, *common, '--env-file', str(output / 'api.env'),
                       '-v', f'{fixtures}:/rehearsal:ro', '--entrypoint', '/opt/product/bin/python']
            if service == 'api':
                command.extend(['--network-alias', 'shuxueshuo.com', '--network-alias', 'www.shuxueshuo.com'])
            run(*command, tags['app'], '/rehearsal/server_rehearsal.py', service)
            started.append(names[service])
            port = '8080' if service == 'ocr' else '8000'
            path = '/health' if service == 'ocr' else '/api/health'
            wait_container(names[service], ['/opt/product/bin/python', '-c',
                f"import urllib.request; urllib.request.urlopen('http://127.0.0.1:{port}{path}', timeout=2)"])
        run('docker', 'run', '--pull=never', '-d', '--name', names['nginx'], '--network', 'container:' + names['api'],
            '-v', f'{proxy}:/etc/nginx/conf.d/default.conf:ro',
            '-v', f'{certificate}:/home/ronghao/cert/shuxueshuo:ro',
            '-v', f'{REPO / "site"}:/home/ronghao/code/shuxueshuo/site:ro', args.nginx)
        started.append(names['nginx'])
        wait_container(names['nginx'], ['nginx', '-t'])
        run(*runtime, 'exercise')
        run('docker', 'restart', '--time', '30', names['api'])
        wait_container(names['api'], ['/opt/product/bin/python', '-c',
            "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2)"])
        run('docker', 'restart', names['nginx'])
        wait_container(names['nginx'], ['nginx', '-t'])
        run(*runtime, 'recovery')
        run(*runtime[:-1], '-m', 'shuxueshuo_server.search.maintenance', '--mode', 'server',
            '--instance', 'search-rehearsal', 'cleanup')
        report['checks'] = json.loads((data / 'work/rehearsal-report.json').read_text())
        report['passed'] = True
    finally:
        for name in started:
            log = subprocess.run(['docker', 'logs', name], text=True, capture_output=True, check=False)
            (output / (name + '.log')).write_text(log.stdout + log.stderr)
        for name in reversed(started):
            subprocess.run(['docker', 'rm', '-f', name], check=False)
        if volume_created:
            subprocess.run(['docker', 'volume', 'rm', volume], check=False)
        if network_created:
            subprocess.run(['docker', 'network', 'rm', network], check=False)
        (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', required=True, help='Existing local app image with the current requirements.lock')
    parser.add_argument('--admin', required=True, help='Existing local admin image with the current requirements.lock')
    parser.add_argument('--postgres', required=True, help='Existing local PostgreSQL 17 image')
    parser.add_argument('--nginx', required=True, help='Existing local Nginx image')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    output = args.output or Path(tempfile.mkdtemp(prefix='search-image-rehearsal-'))
    if output.resolve().is_relative_to(REPO):
        raise ValueError('Rehearsal data and fixture credentials must be outside the repository')
    if args.output:
        output.mkdir(mode=0o700)
    print(f'Offline rehearsal output: {output}', flush=True)
    rehearse(args, output)


if __name__ == '__main__':
    main()
