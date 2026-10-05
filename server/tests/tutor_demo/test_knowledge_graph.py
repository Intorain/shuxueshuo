"""Knowledge graph data: graph.json holds only nodes and edges, display.json how each node is shown."""

import json
import re
import subprocess
from collections import Counter
from glob import glob

from .test_local_practice import ROOT

DATA = ROOT / 'site/data/knowledge'
GRAPH = json.loads((DATA / 'graph.json').read_text())
DISPLAY = json.loads((DATA / 'display.json').read_text())
NODES = {node['id']: node for node in GRAPH['nodes']}
EDGE_TYPES = {'prerequisite', 'uses'}


def edges(kind):
    return [(edge['from'], edge['to']) for edge in GRAPH['edges'] if edge['type'] == kind]


EXPLAIN = ROOT / 'site/assets/explain'


def explainer_files():
    return {path.stem: path for kind in ('knowledge', 'method') for path in sorted((EXPLAIN / kind).glob('*.js'))}


def test_graph_has_only_nodes_and_edges():
    assert set(GRAPH) == {'nodes', 'edges'}
    assert [id for id, count in Counter(node['id'] for node in GRAPH['nodes']).items() if count > 1] == []
    for node in GRAPH['nodes']:
        assert set(node) - {'subtype'} == {'id', 'kind', 'label'}, node
        assert re.fullmatch(r'[a-z0-9]+(-[a-z0-9]+)*', node['id']), node
        assert node['kind'] in {'knowledge', 'method'}, node
        assert (node['kind'] == 'method') == node['id'].startswith('method-'), node
        if 'subtype' in node:
            assert node['kind'] == 'method' and node['subtype'] == 'technique', node
    assert len({node['label'] for node in GRAPH['nodes']}) == len(GRAPH['nodes'])
    for edge in GRAPH['edges']:
        assert set(edge) == {'type', 'from', 'to'}, edge
        assert edge['type'] in EDGE_TYPES, edge
        assert edge['from'] in NODES and edge['to'] in NODES and edge['from'] != edge['to'], edge
    pairs = [(edge['type'], *sorted((edge['from'], edge['to']))) for edge in GRAPH['edges']]
    assert len(pairs) == len(set(pairs))


def test_edge_kinds_connect_the_right_nodes():
    kind = lambda id: NODES[id]['kind']
    assert all((kind(a), kind(b)) == ('method', 'knowledge') for a, b in edges('uses'))
    assert all((kind(a), kind(b)) == ('knowledge', 'knowledge') for a, b in edges('prerequisite'))


def test_nodes_match_the_inventory():
    inventory = (ROOT / 'docs/knowledge-graph-topic-inventory.md').read_text()
    table = lambda section: inventory.split(f'### {section}', 1)[1].split('###', 1)[0]
    knowledge = re.findall(r'^\| `([a-z-]+)` \|', table('4.2'), re.M)
    methods = dict(re.findall(r'^\| `(method-[a-z-]+)` \| [^|]+ \| [^|]+ \| (technique|—) \|$', table('4.3'), re.M))
    assert {id for id, node in NODES.items() if node['kind'] == 'knowledge'} == set(knowledge)
    assert {id: node.get('subtype', '—') for id, node in NODES.items() if node['kind'] == 'method'} == methods


def test_prerequisites_are_acyclic_cover_edges():
    after = {}
    for a, b in edges('prerequisite'):
        after.setdefault(a, set()).add(b)

    def reachable(start):
        seen, stack = set(), [start]
        while stack:
            for nxt in after.get(stack.pop(), ()):
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        return seen

    for a in after:
        assert a not in reachable(a), f'cycle through {a}'
    for a, b in edges('prerequisite'):
        others = after[a] - {b}
        assert not any(b == c or b in reachable(c) for c in others), f'{a} -> {b} follows from other edges'


def test_display_covers_every_node_and_names_real_sheets():
    assert set(DISPLAY) == set(NODES)
    files = explainer_files()
    for id, view in DISPLAY.items():
        assert set(view) <= {'summary', 'sheet'}, id
        assert view['summary'], id
        if 'sheet' in view:
            assert view['sheet'] == id and id in files, id
            assert files[id].parent.name == NODES[id]['kind'], id
    assert set(files) == {id for id, view in DISPLAY.items() if 'sheet' in view}


def test_explainer_modules_follow_the_contract():
    for id, path in explainer_files().items():
        source = path.read_text()
        assert 'export default {' in source and re.search(r'^  render[(:]', source, re.M), id
        assert not re.search(r'\bfetch\(|document\.(body|querySelector)', source), id
        assert not re.search(r'data-math-text[^\n]*data-explain-open', source), id
        assert 'tip.note' not in source or 'problemNote(tip.note)' in source, id
        for target in re.findall(r'data-explain-open="([a-z-]+)"', source):
            assert target != id and DISPLAY[target].get('sheet') == target, (id, target)
        stylesheet = re.search(r"stylesheet: new URL\('([a-z-]+\.css)\?v=\d+', import\.meta\.url\)", source)
        if 'stylesheet' in source:
            assert stylesheet and stylesheet[1] == f'{id}.css', id
            css = re.sub(r'/\*.*?\*/', '', (path.parent / stylesheet[1]).read_text(), flags=re.S)
            selectors = [s.strip() for block in re.findall(r'([^{}]+)\{[^{}]*\}', css) for s in block.split(',')]
            selectors = [s for s in selectors if s and not s.startswith('@')]
            assert selectors and all(s.startswith(f'.explain-{id} ') for s in selectors), id


def sheet_source(id):
    return (ROOT / 'site/assets/explain' / ('method' if id.startswith('method-') else 'knowledge') / f'{id}.js').read_text()


def tip_leaves(nodes, index):
    """Resolve a step's tip into its {id, case?, note} leaves. A tip may branch on a choice made at or before this
    step, {field, options}, with one option per accepted answer."""
    answers = {node['interaction']['field']: node['expected_answer']['one_of'] for node in nodes[:index + 1]
               if node['interaction']['type'] == 'choice'}
    pending = [nodes[index]['tip']]
    while pending:
        tip = pending.pop()
        if 'field' in tip:
            assert set(tip) == {'field', 'options'} and sorted(tip['options']) == sorted(answers[tip['field']]), tip
            pending.extend(tip['options'].values())
        else:
            yield tip


def test_practice_tips_point_at_graph_nodes_with_sheets():
    tips = set()
    for path in sorted(glob(str(ROOT / 'site/*/q[0-9]*/index.html'))):
        config = json.loads(re.search(r'id="practice-config">\s*(.*?)</script>', open(path).read(), re.S)[1])
        for nodes in config['routes'].values():
            for index in (index for index, node in enumerate(nodes) if 'tip' in node):
                for tip in tip_leaves(nodes, index):
                    tips.add(tip['id'])
                    assert set(tip) <= {'id', 'case', 'note'} and tip['note'].startswith('本题'), (path, tip)
                    if 'case' in tip:
                        assert f"'{tip['case']}'" in sheet_source(tip['id']), (path, tip)
    assert tips and all(DISPLAY[id].get('sheet') == id for id in tips)
    for id in tips:
        assert 'problemNote(tip.note)' in sheet_source(id), id


TOPIC_FILES = {path.stem: json.loads(path.read_text()) for path in sorted((DATA / 'topics').glob('*.json'))}


def practice_configs(topic):
    configs = {}
    for path in sorted(glob(str(ROOT / 'site' / topic['path'].strip('/') / 'q*/index.html'))):
        config = json.loads(re.search(r'id="practice-config">\s*(.*?)</script>', open(path).read(), re.S)[1])
        configs[config['id']] = (config, path.split('/')[-2])
    return configs


def test_topic_files_select_graph_nodes():
    assert 'quadratic-always' in TOPIC_FILES
    for name, topic in TOPIC_FILES.items():
        assert set(topic) == {'id', 'label', 'path', 'nodes', 'methods', 'problems'}, name
        assert topic['id'] == name
        assert len(topic['nodes']) == len(set(topic['nodes'])), name
        assert set(topic['nodes']) <= set(NODES), set(topic['nodes']) - set(NODES)


def test_topic_problems_match_practice_pages_step_by_step():
    for name, topic in TOPIC_FILES.items():
        configs = practice_configs(topic)
        assert set(topic['problems']) == set(configs), name
        for problem_id, (config, folder) in configs.items():
            problem = topic['problems'][problem_id]
            assert problem['path'] == f"{topic['path']}{folder}/" and problem['label'] == folder.upper()
            assert list(problem['routes']) == list(config['routes']), problem_id
            for route, steps in config['routes'].items():
                mapped = problem['routes'][route]
                assert list(mapped) == [step['id'] for step in steps], (problem_id, route)
                for index, step in enumerate(steps):
                    ids = mapped[step['id']]
                    assert len(ids) == len(set(ids)) and set(ids) <= set(topic['nodes']), (problem_id, step['id'])
                    if 'tip' in step:
                        assert all(tip['id'] in ids for tip in tip_leaves(steps, index)), (problem_id, step['id'])


def test_topic_methods_cover_routes_in_step_order():
    for name, topic in TOPIC_FILES.items():
        catalog = (ROOT / 'site' / topic['path'].strip('/') / 'index.html').read_text()
        routes = {route for problem in topic['problems'].values() for route in problem['routes']}
        assert {method['route'] for method in topic['methods']} == routes, name
        for method in topic['methods']:
            assert set(method) - {'examples'} == {'node', 'route', 'group', 'sequence'}, method['node']
            assert NODES[method['node']]['kind'] == 'method' and method['node'] in topic['nodes']
            assert f'id="{method["group"]}"' in catalog, method['group']
            for example in method.get('examples', []):
                assert set(example) == {'problem', 'note'} and example['note'], example
                assert method['route'] in topic['problems'][example['problem']]['routes'], example
            used = []
            for problem in topic['problems'].values():
                for step, ids in problem['routes'].get(method['route'], {}).items():
                    if step.endswith('_basis'):
                        assert ids == [method['node']], (method['route'], step)
                    used += [id for id in ids if id != method['node'] and id not in used]
            sequence = method['sequence']
            assert len(sequence) == len(set(sequence)) and set(sequence) == set(used), (method['node'], set(used) ^ set(sequence))


def test_knowledge_page_loads_the_data_files():
    page = (ROOT / 'site/knowledge/index.html').read_text()
    config = json.loads(re.search(r'id="knowledge-config">(.*?)</script>', page, re.S)[1])
    for url in (config['graph'], config['display'], *config['topics']):
        assert (ROOT / 'site' / url.split('?')[0].lstrip('/')).exists(), url
    assert {url.split('?')[0].rsplit('/', 1)[1][:-5] for url in config['topics']} == set(TOPIC_FILES)
    assert 'src="/knowledge/graph.js?v=' in page
    script = (ROOT / 'site/knowledge/graph.js').read_text()
    assert 'confused' not in script + page


def test_pages_open_explainers_through_the_shell():
    shell = (EXPLAIN / 'explain.js').read_text()
    assert "new URL('explain.css?v=1', import.meta.url)" in shell and (EXPLAIN / 'explain.css').exists()
    graph_url = re.search(r"GRAPH_URL = '([^']+)'", shell)[1]
    topic_version = re.search(r"topics/\$\{id\}\.json\?(v=\d+)", (EXPLAIN / 'links.js').read_text())[1]
    assert "import('/assets/explain/explain.js?v=1')" in (ROOT / 'site/knowledge/data.js').read_text()
    assert "import(new URL('../explain/explain.js?v=1', runtimeSrc)" in (ROOT / 'site/assets/practice/runtime.js').read_text()
    for name, topic in TOPIC_FILES.items():
        catalog = (ROOT / 'site' / topic['path'].strip('/') / 'index.html').read_text()
        for page in (catalog, (ROOT / 'site/knowledge/index.html').read_text()):
            urls = re.findall(r'"(/data/knowledge/[^"]+)"', page)
            assert graph_url in urls and f'/data/knowledge/topics/{name}.json?{topic_version}' in urls
        explain_buttons = re.findall(r'data-explain="([a-z-]+)"', catalog)
        if explain_buttons:
            assert "import {openExplainer} from '/assets/explain/explain.js?v=1'" in catalog
            assert f"topic: '{name}'" in catalog and 'method-sheet' not in catalog
            # A group can hold several methods (/1/ group-direct also has 配方); its chip opens the first one.
            leads = {}
            for method in topic['methods']:
                leads.setdefault(method['group'], method['node'])
            assert explain_buttons == list(leads.values())
            for group, node in leads.items():
                block = catalog.split(f'id="{group}"', 1)[1].split('</section>', 1)[0]
                assert f'data-explain="{node}"' in block, node


def test_detail_pages_are_generated_for_every_node():
    result = subprocess.run(['node', 'tools/build-knowledge-pages.mjs', '--check'], cwd=ROOT, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    pages = {path.parent.name for path in (ROOT / 'site/knowledge').glob('*/index.html')}
    assert pages == set(NODES)
    for id in NODES:
        page = (ROOT / f'site/knowledge/{id}/index.html').read_text()
        assert f'<link rel="canonical" href="https://shuxueshuo.com/knowledge/{id}/">' in page
        assert (f'data-explainer="{id}"' in page) == ('sheet' in DISPLAY[id]), id


DRILLS = {path.stem: json.loads(path.read_text()) for path in sorted((DATA / 'drills').glob('*.json'))}


def test_detail_pages_do_not_list_problems():
    problem_paths = {problem['path'] for topic in TOPIC_FILES.values() for problem in topic['problems'].values()}
    for id in NODES:
        page = (ROOT / f'site/knowledge/{id}/index.html').read_text()
        assert not any(f'href="{path}"' in page for path in problem_paths), id
    for path in ('site/knowledge/topic-map.js', 'site/knowledge/graph.js', 'site/assets/explain/explain.js'):
        source = (ROOT / path).read_text()
        assert re.search(r"import \{[^}]*detailHref[^}]*\} from '[./a-z]*links\.js\?v=1'", source), path
        assert 'problem.path' not in source and 'drill' not in source, path
    assert 'drill' not in (ROOT / 'site/assets/practice/runtime.js').read_text()


def test_drill_files_embed_into_their_detail_pages():
    assert DRILLS, 'at least one 刷题 file'
    for name, drill in DRILLS.items():
        assert drill['node'] == name and name in NODES
        page = (ROOT / f'site/knowledge/{name}/index.html').read_text()
        assert f'刷题 · {len(drill["items"])} 题</button>' in page
        embedded = json.loads(re.search(r'<script type="application/json" id="kn-drill-data">(.*?)</script>', page, re.S)[1])
        assert embedded == {'label': NODES[name]['label'], 'items': [{k: v for k, v in item.items() if k != 'source'} for item in drill['items']]}
        for item in drill['items']:
            # An abstract f(x) on a closed interval need not attain its extremes, so the premise must say it does.
            if re.search(r'_\{\\(max|min)\}', ' '.join(option['label'] for option in item['options'])):
                assert '有最大值和最小值' in item.get('given', ''), item['id']
            # A question rewritten from a practice step still trains this node: the topic maps that step to it.
            if 'source' in item:
                problem, route, step = item['source'].split('/')
                topic = next(topic for topic in TOPIC_FILES.values() if problem in topic['problems'])
                assert name in topic['problems'][problem]['routes'][route][step], item['id']
    for id in set(NODES) - set(DRILLS):
        assert 'kn-drill-data' not in (ROOT / f'site/knowledge/{id}/index.html').read_text(), id
