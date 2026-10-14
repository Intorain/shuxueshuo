"""Chapter indexes: the type directory matches the groups below it."""

import json
import re

import pytest

from .test_local_practice import ROOT

CHAPTERS = ["1", "2"]


@pytest.mark.parametrize("chapter", CHAPTERS)
def test_directory_matches_groups(chapter):
    home = (ROOT / f"site/{chapter}/index.html").read_text()
    toc = re.search(r'<nav class="toc" id="toc".*?</nav>', home, re.S)[0]
    entries = re.findall(
        r'href="#(group-[a-z]+)"><span class="toc-index" aria-hidden="true">(\d\d)</span>'
        r'<span class="toc-name">(.*?)</span>.*?<span class="toc-count">(\d+) 题</span>',
        toc,
    )
    groups = []
    for block in re.split(r'(?=<section class="type-group")', home)[1:]:
        block = block.split("</section>")[0]
        groups.append((
            re.search(r'id="(group-[a-z]+)"', block)[1],
            re.search(r'class="type-index" aria-hidden="true">(\d\d)<', block)[1],
            re.search(r"<h3 [^>]*>(.*?)</h3>", block)[1],
            str(len(re.findall(rf'class="problem-card" href="/{chapter}/q\d+/"', block))),
        ))
        assert f'<span class="type-count">{groups[-1][3]} 题</span>' in block
    assert entries == groups
    assert [g[1] for g in groups] == [f"{i:02d}" for i in range(1, len(groups) + 1)]
    for number in re.findall(r"第 (\d\d) 组", home):
        assert 1 <= int(number) <= len(groups)


def test_always_true_explainers_teach_when_to_use_the_method():
    home = (ROOT / "site/2/index.html").read_text()
    links = re.findall(r'data-node-ref="(method-[a-z-]+)" href="([^"]+)"', home)
    methods = {
        "method-discriminant", "method-interval-extremum",
        "method-separation", "method-variable-swap",
    }
    assert len(links) == 4 and {method for method, _ in links} == methods
    assert 'data-explain=' not in home
    source = ROOT / "site/data/knowledge-next"
    catalog = json.loads((source / "catalog.json").read_text())
    topic = json.loads((source / "topics/quadratic-always.json").read_text())
    rule = json.loads((source / "nodes/rule-quadratic-method.json").read_text())
    assert rule['subtype'] == 'method_selection'
    assert {branch['target'] for branch in rule['branches']} == methods
    assert all(branch['condition'] for branch in rule['branches'])
    problems = set(re.findall(r'class="problem-card" href="(/2/q\d+/)"', home))
    for method, href in links:
        assert href == f'/knowledge/{method}/'
        node = json.loads((source / f"nodes/{method}.json").read_text())
        assert node['kind'] == 'method'
        assert all(node[field] for field in ('input', 'output', 'conditions'))
        assert len(node['steps']) >= 3
        assert all(step['title'] and step['body'] for step in node['steps'])
        step_ids = {step['id'] for step in node['steps']}
        assert len(step_ids) == len(node['steps'])
        assert node['examples'] and all(example['solution'] for example in node['examples'])
        assert all(example['url'] in problems for example in node['examples'] if 'url' in example)
        assert any(
            method in route['methods']
            for problem in topic['problems'].values()
            for route in problem['routes'].values()
        ), method
        # The new detail page reuses the explicitly registered figure, while
        # method choice and ordered teaching steps come from the public node.
        figures = [catalog['resources'][ref] for ref in node['resources']]
        assert figures and all(figure.get('part') == 'figure' for figure in figures)
        assert any(figure['scope'] == method for figure in figures), method
        for figure in figures:
            if 'after' in figure:
                assert figure['after'] in step_ids
            content = (ROOT / 'site' / figure['module'].lstrip('/')).read_text()
            assert '<svg' in content, figure['module']
