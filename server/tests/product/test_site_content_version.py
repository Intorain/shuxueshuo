"""Site-version failures cannot disable optional startup checks; no database used."""

import json
from pathlib import Path

import pytest

from shuxueshuo_server.learning import content
from shuxueshuo_server.product.admin import learning
from shuxueshuo_server.product.errors import Conflict

META = {'content_version': 'a' * 64, 'schema_version': 2}


@pytest.fixture
def matching_database(monkeypatch):
    monkeypatch.setattr(content, 'load_content', lambda: {'_meta': dict(META)})
    monkeypatch.setattr(learning, 'preflight', lambda _settings: {'state': 'current', **META})


def check_invalid_site(version):
    assert learning.site_content(version) is None
    assert learning.verify_release(None, version, require_site=False) == {
        'ok': True, 'content_version': META['content_version'], 'site': 'missing',
    }
    with pytest.raises(Conflict, match='^release.site_content_missing$'):
        learning.verify_release(None, version)


@pytest.mark.parametrize('data', [
    None, 42, True, 'content_version schema_version', [],
    ['content_version', 'schema_version'], {},
    {'content_version': META['content_version']}, {'schema_version': 2},
    *[{**META, 'content_version': value} for value in (
        None, 42, [], {}, '', 'a' * 63, 'a' * 65, 'A' * 64, 'g' * 64, 'a' * 64 + '\n',
    )],
    *[{**META, 'schema_version': value} for value in (None, True, False, 0, -1, 2.0, '2', [], {})],
])
def test_invalid_json_shape_or_field_is_missing(tmp_path, matching_database, data):
    version = tmp_path / 'version.json'
    version.write_text(json.dumps(data), encoding='utf-8')
    check_invalid_site(version)


@pytest.mark.parametrize('data', [b'{', b'{"content_version":"\xff"}'])
def test_invalid_json_or_non_utf8_is_missing(tmp_path, matching_database, data):
    version = tmp_path / 'version.json'
    version.write_bytes(data)
    check_invalid_site(version)


def test_absent_file_and_directory_are_missing(tmp_path, matching_database):
    for version in (None, tmp_path / 'absent.json', tmp_path):
        check_invalid_site(version)


@pytest.mark.parametrize('operation', ['is_file', 'read_text'])
def test_unreadable_site_is_missing(tmp_path, matching_database, monkeypatch, operation):
    version = tmp_path / 'version.json'
    version.write_text(json.dumps(META), encoding='utf-8')

    def denied(*_args, **_kwargs):
        raise PermissionError('unreadable site version')

    monkeypatch.setattr(Path, operation, denied)
    check_invalid_site(version)


def test_matching_content_is_accepted_in_both_modes(tmp_path, matching_database):
    version = tmp_path / 'version.json'
    data = {**META, 'counts': {'nodes': 67}}
    version.write_text(json.dumps(data), encoding='utf-8')
    assert learning.site_content(version) == data
    for required in (False, True):
        assert learning.verify_release(None, version, require_site=required) == {
            'ok': True, 'content_version': META['content_version'], 'site': 'match',
        }


@pytest.mark.parametrize('data', [
    {**META, 'content_version': 'b' * 64},
    {**META, 'schema_version': 3},
])
def test_valid_stale_content_or_future_schema_is_mismatch(tmp_path, matching_database, data):
    version = tmp_path / 'version.json'
    version.write_text(json.dumps(data), encoding='utf-8')
    assert learning.site_content(version) == data
    assert learning.verify_release(None, version, require_site=False)['site'] == 'mismatch'
    with pytest.raises(Conflict, match='^release.site_content_mismatch$'):
        learning.verify_release(None, version)


@pytest.mark.parametrize('state', [
    {'state': 'empty'},
    {'state': 'current', **META, 'content_version': 'b' * 64},
    {'state': 'current', **META, 'schema_version': 3},
])
@pytest.mark.parametrize('required', [False, True])
def test_optional_site_never_bypasses_database_image_mismatch(
    tmp_path, matching_database, monkeypatch, state, required,
):
    version = tmp_path / 'version.json'
    version.write_text(json.dumps(META), encoding='utf-8')
    monkeypatch.setattr(learning, 'preflight', lambda _settings: state)
    with pytest.raises(Conflict, match='^release.content_version_mismatch$'):
        learning.verify_release(None, version, require_site=required)
