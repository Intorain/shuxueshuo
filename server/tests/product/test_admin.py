import json
import os
import shutil
import subprocess

import pytest
from shuxueshuo_server.product.config import REPO, Settings
from shuxueshuo_server.product.errors import Conflict, ProductError


def test_settings_reinstall_keeps_passwords_and_instance(tmp_path):
    root = tmp_path / 'data with spaces'
    first = Settings.load('local', root, 'test', 55432, initialize=True)
    original = {p.name: p.read_bytes() for p in (root / 'config').iterdir()}
    second = Settings.load('local', root, 'test', initialize=True)
    assert first.credentials == second.credentials
    assert second.port == 55432
    assert original == {p.name: p.read_bytes() for p in (root / 'config').iterdir()}
    with pytest.raises(Conflict): Settings.load('local', root, 'different', initialize=True)
    with pytest.raises(Conflict): Settings.load('local', root, 'test', 55433, initialize=True)
    with pytest.raises(ProductError): Settings.load('local', root / 'work/nested', 'test', initialize=True)


def test_status_does_not_initialize_config(tmp_path):
    root = tmp_path / 'not-installed'
    with pytest.raises(ProductError): Settings.load('local', root, 'test')
    assert not root.exists()


def test_backup_counts_skip_tables_from_later_migrations(settings):
    import sqlalchemy as sa
    from shuxueshuo_server.product import models as m
    from shuxueshuo_server.product.admin.backup import table_counts
    from shuxueshuo_server.product.db import engine, transaction

    pending = sa.Table('not_yet_migrated', m.metadata, sa.Column('id', sa.Integer))
    db = engine(settings.url('migration'))
    try:
        with transaction(db) as c:
            counts = table_counts(c)
    finally:
        m.metadata.remove(pending)
        db.dispose()
    assert 'not_yet_migrated' not in counts
    assert counts['users'] >= 1


def test_release_packaged_manage_dispatches_without_repository(tmp_path):
    # Validate the offline package's relative layout without invoking Docker.
    package = tmp_path / 'release' / 'scripts'
    shutil.copytree(REPO / 'deploy/product', package)
    result = subprocess.run([str(package / 'manage.sh'), '--mode', 'server', '--data-dir', str(tmp_path / 'absent'), 'status'],
                            capture_output=True, text=True)
    assert result.returncode == 2
    assert '实例尚未安装' in result.stderr
    assert not (tmp_path / 'absent').exists()


def test_script_syntax():
    scripts = sorted((REPO / 'deploy/product').rglob('*.sh'))
    for script in scripts:
        subprocess.run(['bash', '-n', str(script)], check=True, capture_output=True)


def release_repository(tmp_path):
    repo = tmp_path / 'source tree'
    shutil.copytree(REPO / 'deploy/product', repo / 'deploy/product')
    (repo / 'server').mkdir()
    (repo / 'server/content.txt').write_text('committed source')
    teaching = repo / 'site/knowledge/teaching'
    teaching.mkdir(parents=True)
    (teaching / 'version.json').write_text('{"schema_version":2,"content_version":"' + 'a'*64 + '"}')
    (repo / 'site/index.html').write_text('committed site')
    tools = repo / 'tools'
    tools.mkdir()
    (tools / 'build-public-knowledge-graph.mjs').write_text('if (!process.argv.includes("--check")) process.exit(1);')
    (tools / 'export-public-knowledge.mjs').write_text('console.log(JSON.stringify({schema_version:2,content_version:"' + 'a'*64 + '"}));')

    versions = repo / 'server/alembic/versions'
    versions.mkdir(parents=True)
    (versions / '0001.py').write_text("revision = 'fixture_base'\ndown_revision = None\n")
    (versions / '0002.py').write_text("revision = 'fixture_head'\ndown_revision = 'fixture_base'\n")
    (repo / '.gitignore').write_text('server/ignored.txt\n')
    for args in (['init', '-q'], ['add', '.'], ['-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'fixture']):
        subprocess.run(['git', '-C', str(repo), *args], check=True, capture_output=True)
    return repo


@pytest.mark.parametrize('dirty', ['tracked', 'untracked', 'staged'])
def test_release_rejects_dirty_tree_before_docker(tmp_path, dirty):
    repo = release_repository(tmp_path)
    target = repo / ('untracked.txt' if dirty == 'untracked' else 'server/content.txt')
    target.write_text('uncommitted')
    if dirty == 'staged':
        subprocess.run(['git', '-C', str(repo), 'add', '.'], check=True)
    output = tmp_path / 'release'
    result = subprocess.run([str(repo / 'deploy/product/build-release.sh'), '--release', 'test-v1',
                             '--platform', 'linux/arm64', '--output', str(output)], capture_output=True, text=True)
    assert result.returncode == 2 and '干净工作树' in result.stderr
    assert not output.exists()


def test_release_uses_committed_archive_not_live_or_ignored_files(tmp_path):
    repo = release_repository(tmp_path)
    revision = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip()
    readme = (repo / 'deploy/product/README.md').read_bytes()
    (repo / 'server/ignored.txt').write_text('must not enter image')
    scratch = tmp_path / 'real-scratch'
    scratch.mkdir()
    alias = tmp_path / 'scratch-alias'
    alias.symlink_to(scratch, target_is_directory=True)
    binary = tmp_path / 'bin'
    binary.mkdir()
    # Fake the image transport only. Real git archive, tar, release packaging and checksums run.
    docker = binary / 'docker'
    docker.write_text('''#!/usr/bin/env python3
import os,sys,io,json,tarfile,hashlib
from pathlib import Path
a=sys.argv[1:]
if a[:2]==['buildx','build']:
    context=Path(a[-1])
    assert (context/'server/content.txt').read_text()=='committed source'
    assert not (context/'server/ignored.txt').exists()
    (Path(os.environ['TEST_SOURCE_REPO'])/'deploy/product/README.md').write_text('changed during build')
elif a[:2]==['image','inspect']:
    print('sha256:'+'a'*64)
elif a[0]=='save':
    # Packaging reads content IDs from Docker's archive manifest, not inspect.
    tags=a[a.index('-o')+2:]
    manifest=[]; blobs={}; descriptors=[]
    for i,tag in enumerate(tags,1):
        config=json.dumps({'os':'linux','architecture':'arm64','fixture':i}).encode()
        digest=hashlib.sha256(config).hexdigest()
        blobs[digest+'.json']=config
        manifest.append({'Config':digest+'.json','RepoTags':[tag],'Layers':[]})
        oci=json.dumps({'schemaVersion':2,'config':{'digest':'sha256:'+digest},'layers':[]}).encode()
        oid=hashlib.sha256(oci).hexdigest(); blobs['blobs/sha256/'+oid]=oci
        descriptors.append({'digest':'sha256:'+oid})
    blobs['manifest.json']=json.dumps(manifest).encode()
    blobs['index.json']=json.dumps({'manifests':descriptors}).encode()
    with tarfile.open(a[a.index('-o')+1], 'w') as archive:
        for name,content in blobs.items():
            info=tarfile.TarInfo(name); info.size=len(content)
            archive.addfile(info,io.BytesIO(content))
''')
    docker.chmod(0o755)
    output = tmp_path / 'release'
    subprocess.run([str(repo / 'deploy/product/build-release.sh'), '--release', 'test-v1',
                    '--platform', 'linux/arm64', '--output', str(output)], check=True, capture_output=True,
                   env={**os.environ, 'PATH': str(binary) + os.pathsep + os.environ['PATH'], 'TEST_SOURCE_REPO': str(repo), 'TMPDIR': str(alias)})
    assert f'PRODUCT_SOURCE_REVISION={revision}\n' in (output / 'release.env').read_text()
    assert 'PRODUCT_ALEMBIC_REVISION=fixture_head\n' in (output / 'release.env').read_text()
    assert (output / 'scripts/README.md').read_bytes() == readme
    assert f'PRODUCT_CONTENT_VERSION={"a" * 64}\n' in (output / 'release.env').read_text()
    # The public site is updated by git pull on the server, never shipped in the package.
    files = json.loads((output / 'manifest.json').read_text())['files']
    assert {n for n in files if not n.startswith('scripts/')} == {'release.env', 'images.sha256'}
    assert not any(p.name.startswith('site') for p in output.iterdir())
