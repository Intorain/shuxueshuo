"""Keep release identities portable without relying on mutable Docker tags."""
import hashlib
import io
import json
import runpy
import tarfile
from pathlib import Path

import pytest


identities = runpy.run_path(
    str(Path(__file__).resolve().parents[3] / 'deploy/product/image-identities.py')
)['identities']


def image_archive(tmp_path, *, oci=True, fault=None):
    files = {}
    manifest, descriptors, expected = [], [], {}

    def blob(value):
        raw = json.dumps(value, sort_keys=True).encode()
        digest = 'sha256:' + hashlib.sha256(raw).hexdigest()
        name = 'blobs/sha256/' + digest.split(':')[1]
        files[name] = raw
        return digest, name

    for role in ('admin', 'app', 'postgres', 'rabbitmq'):
        config, config_name = blob({
            'os': 'linux',
            'architecture': 'arm64' if fault == 'platform' and role == 'admin' else 'amd64',
            'config': {'Labels': {'role': role}},
        })
        tags = None if role == 'postgres' else [f'{role}:test']
        manifest.append({'Config': config_name, 'RepoTags': tags, 'Layers': []})
        expected[role] = {'config': config, 'oci': config}
        if fault == 'config' and role == 'admin':
            files[config_name] += b' '
        if oci:
            value = {'schemaVersion': 2, 'config': {'digest': config}, 'layers': []}
            digest, name = blob(value)
            descriptors.append({'digest': digest})
            expected[role]['oci'] = digest
            if fault == 'oci' and role == 'admin':
                files[name] += b' '
            if fault == 'ambiguous' and role == 'admin':
                other, _ = blob({**value, 'annotations': {'variant': 'second'}})
                descriptors.append({'digest': other})
    files['manifest.json'] = json.dumps(manifest).encode()
    if oci:
        files['index.json'] = json.dumps({'schemaVersion': 2, 'manifests': descriptors}).encode()
    archive = tmp_path / 'images.tar'
    with tarfile.open(archive, 'w') as target:
        for name, raw in files.items():
            member = tarfile.TarInfo(name)
            member.size = len(raw)
            target.addfile(member, io.BytesIO(raw))
    return archive, expected


@pytest.mark.parametrize('oci', [False, True], ids=['classic', 'oci'])
def test_archive_pins_config_and_related_manifest(tmp_path, oci):
    archive, expected = image_archive(tmp_path, oci=oci)
    assert identities(archive, 'admin:test', 'app:test', 'linux/amd64') == expected


@pytest.mark.parametrize(('fault', 'message'), [
    ('config', 'release.image_config_checksum'),
    ('platform', 'release.image_platform_mismatch'),
    ('ambiguous', 'release.ambiguous_oci_identity'),
    ('oci', 'release.oci_checksum'),
])
def test_invalid_archive_identities_are_rejected(tmp_path, fault, message):
    archive, _ = image_archive(tmp_path, fault=fault)
    with pytest.raises(ValueError, match=message):
        identities(archive, 'admin:test', 'app:test', 'linux/amd64')
