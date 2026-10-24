"""Offline production wiring contracts for the private search application."""

import json
import re

import pytest

from shuxueshuo_server.product.config import REPO


def service_configuration(name):
    source = (REPO / 'deploy/product/compose.app.yml').read_text()
    match = re.search(rf'^  {name}:\n(.*?)(?=^  [a-z]|^volumes:|\Z)', source, re.MULTILINE | re.DOTALL)
    assert match, name
    return match.group(1)


def command(configuration):
    return json.loads(re.search(r'^    command: (\[.*\])$', configuration, re.MULTILINE).group(1))


@pytest.mark.parametrize('via_cdn', [False, True], ids=['https', 'http-cdn-origin'])
def test_private_search_proxy_preserves_origin_without_trusting_forwarded_input(via_cdn):
    source = (REPO / 'deploy/nginx/shuxueshuo.conf').read_text()
    servers = re.findall(r'^server \{.*?^\}', source, re.MULTILINE | re.DOTALL)
    server = next(block for block in servers if 'root ' in block and ('listen 80;' in block) == via_cdn)
    location = re.search(r'^    location \^~ /api/search/ \{(.*?)^    \}', server, re.MULTILINE | re.DOTALL).group(1)
    assert re.search(r'map \$http_upgrade \$search_connection_upgrade \{\s*default upgrade;\s*\x27\x27 close;\s*\}', source)
    for directive in (
        'client_max_body_size 20m;',
        'client_body_timeout 120s;',
        'proxy_pass http://127.0.0.1:8000;',
        'proxy_http_version 1.1;',
        'proxy_set_header Host $host;',
        'proxy_set_header Upgrade $http_upgrade;',
        'proxy_set_header Connection $search_connection_upgrade;',
        'proxy_set_header Origin $http_origin;',
        'proxy_set_header X-Real-IP $remote_addr;',
        'proxy_set_header X-Forwarded-For $remote_addr;',
        'proxy_connect_timeout 5s;',
        'proxy_read_timeout 3600s;',
        'proxy_send_timeout 3600s;',
        'proxy_request_buffering off;',
        'proxy_buffering off;',
        'proxy_cache off;',
        'proxy_hide_header Cache-Control;',
        'add_header Cache-Control "private, no-store" always;',
        'add_header X-Frame-Options "SAMEORIGIN" always;',
        'add_header X-Content-Type-Options "nosniff" always;',
    ):
        assert directive in location
    forwarded_scheme = 'https' if via_cdn else '$scheme'
    assert f'proxy_set_header X-Forwarded-Proto {forwarded_scheme};' in location
    if via_cdn:
        assert 'if ($http_x_forwarded_proto != "https")' in server
    other_api = re.search(r'^    location /api/ \{(.*?)^    \}', server, re.MULTILINE | re.DOTALL).group(1)
    assert 'proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;' in other_api
    assert 'proxy_set_header X-Forwarded-Proto $scheme;' in other_api
    assert not any(setting in other_api for setting in ('Upgrade', 'Origin', 'Cache-Control', 'client_max_body_size'))


def test_search_api_is_single_process_strict_storage_with_persistent_private_data():
    api = service_configuration('api')
    arguments = command(api)
    assert arguments[arguments.index('--workers') + 1] == '1'
    assert arguments[arguments.index('--host') + 1] == '0.0.0.0'
    assert arguments[arguments.index('--forwarded-allow-ips') + 1] == '172.16.0.0/12'
    assert '--reload' not in arguments
    assert 'PRODUCT_EXECUTION_STORAGE_CONTEXT_REQUIRED: "1"' in api
    assert 'PRODUCT_DATA_DIR: /var/lib/shuxueshuo' in api
    assert 'PRODUCT_OCR_URL: http://ocr:8080' in api
    assert '127.0.0.1:${PRODUCT_API_PORT:-8000}:8000' in api
    assert '${PRODUCT_DATA_DIR:?data root required}:/var/lib/shuxueshuo' in api
    assert 'stop_grace_period: 10m' in api
    image = (REPO / 'deploy/product/Dockerfile.app').read_text()
    image_command = json.loads(re.search(r'^CMD (\[.*\])$', image, re.MULTILINE).group(1))
    assert image_command == arguments


def test_search_ocr_is_private_and_uses_the_same_persistent_data_root():
    ocr = service_configuration('ocr')
    assert 'PRODUCT_DATA_DIR: /var/lib/shuxueshuo' in ocr
    assert '${PRODUCT_DATA_DIR:?data root required}:/var/lib/shuxueshuo' in ocr
    assert not re.search(r'^    ports:', ocr, re.MULTILINE)
    assert command(ocr) == ['python', '/opt/shuxueshuo/deploy/ocr/sidecar_server.py']


def test_app_image_includes_production_execution_graph_without_test_fixtures():
    image = (REPO / 'deploy/product/Dockerfile.app').read_text()
    ignore = (REPO / 'deploy/product/Dockerfile.app.dockerignore').read_text().splitlines()
    assert 'COPY site/data/knowledge-next /app/site/data/knowledge-next' in image
    assert 'test -f /app/site/data/knowledge-next/execution/milestones.json' in image
    for pattern in ('!site/', '!site/data/', '!site/data/knowledge-next/', '!site/data/knowledge-next/**'):
        assert pattern in ignore
    assert 'server/tests' in ignore and 'server/tests/**' in ignore
    assert '!server/tests/**' not in ignore
    for relative in ('execution/milestones.json', 'selection/rule-quadratic-method.json', 'catalog.json'):
        assert (REPO / 'site/data/knowledge-next' / relative).is_file()
    for relative in ('site/knowledge/graph.json', 'site/data/graph-walk/quadratic-always-q01.source.json'):
        assert f'COPY {relative} /app/{relative}' in image
        assert f'test -f /app/{relative}' in image
        assert f'!{relative}' in ignore
        assert (REPO / relative).is_file()
    assert '!site/knowledge/' in ignore and '!site/data/graph-walk/' in ignore
    assert '!site/knowledge/**' not in ignore and '!site/data/graph-walk/**' not in ignore
    assert not re.search(r'^COPY site/? /app/site/?$', image, re.MULTILINE)
