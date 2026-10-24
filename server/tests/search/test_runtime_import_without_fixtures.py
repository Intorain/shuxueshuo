"""Production search imports and saved reports do not require test corpora."""

import os
import shutil
import subprocess
import sys
from pathlib import Path


def test_server_imports_and_saved_report_without_test_files(tmp_path):
    root = Path(__file__).resolve().parents[3]
    image = tmp_path / "app"
    for relative in ("server/shuxueshuo_server", "internal/schemas", "internal/llm-prompts", "site/data/knowledge-next"):
        shutil.copytree(root / relative, image / relative, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for relative in ("site/knowledge/graph.json", "site/data/graph-walk/quadratic-always-q01.source.json"):
        target = image / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / relative, target)
    assert not (image / "server/tests").exists()
    script = """
import json
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from shuxueshuo_server.graph_lesson.stage_one import runner
from shuxueshuo_server.graph_lesson.stage_one.report import render_batch
from shuxueshuo_server.graph_lesson.stage_three import runner as execution_runner
from shuxueshuo_server.search import dev_api, lesson, walk
from shuxueshuo_server.main import app
root = Path(sys.argv[1]).parent
assert Path(runner.__file__).is_relative_to(root)
assert Path(dev_api.__file__).is_relative_to(root)
assert runner.candidate_features(None)['features'] == []
assert any(route.path == '/api/search/pages' for route in app.routes)
assert not (root / 'server/tests').exists()
graph = walk._graph()
assert graph['nodes'] and graph['edges']
node_path = next(lesson.NODES.glob('*.json'))
assert lesson._node(node_path.stem)['label']
primary = 'type-quantified-quadratic'
assert primary in graph['nodes']
presented = walk.walk({'status':'resolved', 'target_ref':'root', 'primary':primary,
    'd1':{'rows':[]}, 'knowledge':[{'ref':'quadratic-function'}],
    'd2':[{'type_id':primary, 'label':graph['nodes'][primary]['label'], 'reasons':[], 'role':'primary'}]},
    'Production resource probe', 'probe')
assert presented['bundle']['graph']['nodes']
assert presented['bundle']['graphVersion'] == graph['version']
source = root / 'site/data/graph-walk/quadratic-always-q01.source.json'
assert any(row['id'] == 'D3' for row in json.loads(source.read_text())['intro'])
assert 'site/data/graph-walk/quadratic-always-q01.source.json' in execution_runner.fingerprint()
try:
    tuple(runner.CASES)
except FileNotFoundError:
    pass
else:
    raise AssertionError('acceptance corpus must not silently disappear')
batch = root / 'batch'
batch.mkdir()
(batch / 'batch-summary.json').write_text(json.dumps({'requested_cases':['q01','q02'], 'results':[
    {'case_id':'q01','sample_id':1,'sample_dir':'q01/sample-01','status':'interrupted','passed':False}]}))
report = render_batch(batch, root / 'report')
assert '1 / 2' in report.read_text()
print('fixture-free imports and saved report passed')
"""
    completed = subprocess.run(
        [sys.executable, "-I", "-c", script, str(image / "server")], cwd=image,
        env={**os.environ, "PRODUCT_MODE": "server", "REVIEW_BACKEND": "product",
             "PYTHONDONTWRITEBYTECODE": "1", "RUN_LLM_INTEGRATION": "0"},
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "fixture-free imports and saved report passed" in completed.stdout
