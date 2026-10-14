#!/usr/bin/env python3
"""Resolve archive-verified config and OCI identities, never deployment tags."""
import hashlib
import json
import re
import shlex
import sys
import tarfile


def identities(archive_path, admin_tag, app_tag, platform):
    with tarfile.open(archive_path) as archive:
        manifest = json.load(archive.extractfile('manifest.json'))
        selected, untagged = {}, []
        for item in manifest:
            tags = item.get('RepoTags') or []
            role = ('admin' if admin_tag in tags else 'app' if app_tag in tags else
                    'rabbitmq' if any('rabbitmq:' in tag for tag in tags) else
                    'postgres' if any('postgres:' in tag for tag in tags) else None)
            if role:
                if role in selected:
                    raise ValueError('release.multiple_image_configs')
                selected[role] = item
            elif not tags:
                untagged.append(item)
        if 'postgres' not in selected and len(untagged) == 1:
            selected['postgres'] = untagged[0]
        if set(selected) != {'admin', 'app', 'postgres', 'rabbitmq'}:
            raise ValueError('release.missing_image_config')
        result, configs = {}, {}
        for role, item in selected.items():
            value = item['Config'].split('/')[-1].removesuffix('.json')
            if not re.fullmatch('[a-f0-9]{64}', value):
                raise ValueError('release.invalid_image_config')
            raw = archive.extractfile(item['Config']).read()
            if hashlib.sha256(raw).hexdigest() != value:
                raise ValueError('release.image_config_checksum')
            config = json.loads(raw)
            if f"{config.get('os')}/{config.get('architecture')}" != platform:
                raise ValueError('release.image_platform_mismatch')
            identity = 'sha256:' + value
            result[role] = {'config': identity, 'oci': identity}
            configs[identity] = role
        try:
            index = json.load(archive.extractfile('index.json'))
        except KeyError:
            return result  # classic Docker archive: config identities are runnable
        candidates = {role: set() for role in selected}
        pending = list(index['manifests'])
        visited = set()
        while pending:
            descriptor = pending.pop()
            if descriptor.get('annotations', {}).get('io.containerd.manifest.subject'):
                continue  # attestations are not runnable images
            identity = descriptor['digest']
            if identity in visited:
                continue
            if not re.fullmatch('sha256:[a-f0-9]{64}', identity):
                raise ValueError('release.invalid_oci_identity')
            visited.add(identity)
            raw = archive.extractfile('blobs/sha256/' + identity.split(':')[1]).read()
            if 'sha256:' + hashlib.sha256(raw).hexdigest() != identity:
                raise ValueError('release.oci_checksum')
            data = json.loads(raw)
            if 'manifests' in data:
                pending.extend(data['manifests'])
            elif data.get('config', {}).get('digest') in configs:
                candidates[configs[data['config']['digest']]].add(identity)
        for role, values in candidates.items():
            if len(values) != 1:
                raise ValueError('release.ambiguous_oci_identity')
            result[role]['oci'] = values.pop()
        return result


if __name__ == '__main__':
    for role, values in identities(*sys.argv[1:]).items():
        print(f'{role}_id={shlex.quote(values["config"])}')
        print(f'{role}_oci_id={shlex.quote(values["oci"])}')
