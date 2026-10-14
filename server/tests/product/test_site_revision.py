"""Read-only full-release guards, exercised against real temporary Git histories."""

import subprocess

import pytest

from shuxueshuo_server.product.config import REPO


def git(repo, *args):
    return subprocess.run(
        ['git', '-C', str(repo), *args], check=True, capture_output=True, text=True,
    ).stdout.strip()


def commit(repo, text):
    (repo / 'page.html').write_text(text)
    git(repo, 'add', '.')
    git(repo, '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
        '-c', 'commit.gpgsign=false', 'commit', '-qm', text)
    return git(repo, 'rev-parse', 'HEAD')


@pytest.fixture
def repository(tmp_path):
    repo = tmp_path / 'site repo'
    repo.mkdir()
    git(repo, 'init', '-q')
    (repo / '.gitignore').write_text('.env\n')
    first = commit(repo, 'first')
    target = commit(repo, 'target')
    return repo, first, target


def check(repo, target, *, allow_forward=False):
    before = (git(repo, 'rev-parse', 'HEAD'), git(repo, 'status', '--porcelain'))
    result = subprocess.run(
        ['/bin/bash', str(REPO / 'deploy/product/server/check-site-revision.sh'),
         '--repo', str(repo), '--revision', target,
         *(['--allow-forward'] if allow_forward else [])],
        capture_output=True, text=True, check=False,
    )
    assert before == (git(repo, 'rev-parse', 'HEAD'), git(repo, 'status', '--porcelain'))
    return result


@pytest.mark.parametrize('allow_forward', [False, True])
def test_clean_exact_commit_passes(repository, allow_forward):
    repo, _, target = repository
    result = check(repo, target, allow_forward=allow_forward)
    assert result.returncode == 0, result.stderr


def test_ancestor_passes_preflight_but_needs_update_before_verification(repository):
    repo, first, target = repository
    git(repo, 'checkout', '--detach', first)
    assert check(repo, target, allow_forward=True).returncode == 0
    result = check(repo, target)
    assert result.returncode != 0 and 'HEAD 与发布包提交不同' in result.stderr
    git(repo, 'merge', '--ff-only', target)
    assert check(repo, target).returncode == 0


@pytest.mark.parametrize('state', ['ahead', 'diverged'])
def test_refuse_ahead_or_diverged_without_changing_checkout(repository, state):
    repo, first, target = repository
    if state == 'diverged':
        git(repo, 'checkout', '--detach', first)
    commit(repo, 'later pages')
    result = check(repo, target, allow_forward=True)
    assert result.returncode != 0 and '已领先于目标提交或与其分叉' in result.stderr
    assert check(repo, target).returncode != 0


@pytest.mark.parametrize('state', ['unstaged', 'staged', 'untracked'])
def test_dirty_checkout_is_refused_in_both_modes(repository, state):
    repo, _, target = repository
    if state == 'untracked':
        (repo / 'untracked.html').write_text('new page')
    else:
        (repo / 'page.html').write_text('changed')
        if state == 'staged':
            git(repo, 'add', '.')
    for forward in (False, True):
        result = check(repo, target, allow_forward=forward)
        assert result.returncode != 0 and '未提交或未跟踪' in result.stderr


def test_ignored_server_configuration_is_allowed(repository):
    repo, _, target = repository
    (repo / '.env').write_text('LOCAL_CONFIGURATION=fixture\n')
    assert check(repo, target).returncode == 0


def test_missing_commit_is_refused_before_maintenance(repository):
    repo, _, _ = repository
    result = check(repo, 'f' * 40, allow_forward=True)
    assert result.returncode != 0 and '先 git fetch' in result.stderr


def test_short_revision_is_not_an_exact_release_identity(repository):
    repo, _, target = repository
    result = check(repo, target[:12])
    assert result.returncode != 0 and '完整 PRODUCT_SOURCE_REVISION' in result.stderr


def test_repository_subdirectory_is_not_the_published_site_root(repository):
    repo, _, target = repository
    nested = repo / 'nested'
    nested.mkdir()
    result = check(nested, target)
    assert result.returncode != 0 and '仓库根目录' in result.stderr
