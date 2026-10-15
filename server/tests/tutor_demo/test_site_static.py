"""Every static response revalidates, so shared assets need no version in their URLs."""

import re

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from shuxueshuo_server.product.config import REPO
from tools.run_site import SiteStaticFiles


@pytest.fixture
def site(tmp_path):
    for path in (
        'knowledge/index.html', 'knowledge/teaching/version.json',
        'assets/practice/runtime.js', 'assets/knowledge-next/graph.mjs',
    ):
        file = tmp_path / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text('example')
    app = FastAPI()

    @app.get('/api/example')
    def example():
        return JSONResponse({'value': 1}, headers={'Cache-Control': 'no-store'})

    app.mount('/', SiteStaticFiles(directory=tmp_path, html=True))
    return TestClient(app, follow_redirects=False)


@pytest.mark.parametrize('path', [
    '/knowledge/', '/knowledge/index.html', '/knowledge/teaching/version.json',
    '/assets/practice/runtime.js', '/assets/knowledge-next/graph.mjs',
])
def test_mutable_static_responses_revalidate(site, path):
    first = site.get(path)
    assert first.status_code == 200
    assert first.headers['cache-control'] == 'no-cache'
    cached = site.get(path, headers={'If-None-Match': first.headers['etag']})
    assert cached.status_code == 304
    assert cached.headers['cache-control'] == 'no-cache'


def test_missing_static_files_are_not_cached(site):
    missing = site.get('/assets/knowledge-next/missing.mjs')
    assert missing.status_code == 404
    assert missing.headers['cache-control'] == 'no-cache'


@pytest.mark.parametrize(('source', 'target'), [
    ('/knowledge-next', '/knowledge/'),
    ('/knowledge-next/', '/knowledge/'),
    ('/knowledge-next/chapters/compulsory-1-ch2/', '/knowledge/chapters/compulsory-1-ch2/'),
])
def test_legacy_namespace_redirect_preserves_encoded_query_without_javascript(site, source, target):
    query = '?preview=1&scope=section-2-2&graph=%2Fknowledge%2F%3Fview%3Dsolution'
    response = site.get(source + query)
    assert response.status_code == 301
    assert response.headers['location'] == target + query


def test_static_cache_policy_does_not_override_api_headers(site):
    assert site.get('/api/example').headers['cache-control'] == 'no-store'


def test_nginx_cache_policy_matches_local_and_retains_security_headers():
    # nginx -t remains an installation check; this test does not start Nginx.
    source = (REPO / 'deploy/nginx/shuxueshuo.conf').read_text()
    assert 'immutable' not in source and 'max-age' not in source
    locations = re.findall(r'^    location / \{(.*?)^    \}', source, re.MULTILINE | re.DOTALL)
    assert len(locations) == 2  # HTTP CDN origin and direct HTTPS
    for location in locations:
        assert 'add_header Cache-Control "no-cache" always;' in location
        assert 'add_header X-Frame-Options "SAMEORIGIN" always;' in location
        assert 'add_header X-Content-Type-Options "nosniff" always;' in location
    for location in re.findall(r'^    location /api/ \{(.*?)^    \}', source, re.MULTILINE | re.DOTALL):
        assert 'Cache-Control' not in location
    assert source.count('rewrite ^/knowledge-next/(?!assets(?:/|$))(.*)$ /knowledge/$1 permanent;') == 2
