"""Strict sidecar readiness and preheat cache checks, without importing real Paddle."""

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


def deployment_module(filename):
    path = Path(__file__).resolve().parents[3] / "deploy/ocr" / filename
    spec = importlib.util.spec_from_file_location("ocr_startup_" + path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("failure", [None, "manifests", "layout", "text_ocr", "formula_ocr", "search"])
def test_ready_requires_product_and_strict_search_warmup(monkeypatch, failure):
    from shuxueshuo_server.product import observation

    module = deployment_module("sidecar_server.py")
    models = {name: object() for name in ("layout", "det", "rec", "orientation")}
    calls = []

    def load(component):
        assert module.READY is False
        assert module.SEARCH_MODELS is None
        calls.append(component)
        if failure == component:
            raise RuntimeError("fixture model load failed")

    def load_models(*, require_orientation):
        assert require_orientation is True
        load("search")
        return models

    class Server:
        def __init__(self, address, handler):
            assert failure is None
            assert module.READY is True
            assert module.SEARCH_MODELS is models
            calls.append("server")

        def serve_forever(self):
            calls.append("serve")

    worker = SimpleNamespace(manifests=lambda: load("manifests"), _model=load)
    monkeypatch.setattr(observation, "get_paddle_worker", lambda: worker)
    monkeypatch.setitem(sys.modules, "shuxueshuo_server.search.ocr_worker", SimpleNamespace(load_models=load_models))
    monkeypatch.setattr(module, "ThreadingHTTPServer", Server)
    module.READY = True
    module.SEARCH_MODELS = {"stale": object()}
    assert module.main() == (0 if failure is None else 1)
    if failure is None:
        assert calls == ["manifests", "layout", "text_ocr", "formula_ocr", "search", "server", "serve"]
        assert module.READY_ERROR == ""
    else:
        assert calls[-1] == failure
        assert module.READY is False
        assert module.SEARCH_MODELS is None
        assert "server" not in calls


@pytest.fixture
def preheat(tmp_path, monkeypatch):
    module = deployment_module("preheat_models.py")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PADDLE_PDX_MODEL_SOURCE", "fixture")
    monkeypatch.setenv("OMP_NUM_THREADS", "1")
    root = tmp_path / ".paddlex/official_models"
    for name in module.MODEL_NAMES:
        directory = root / name
        directory.mkdir(parents=True)
        for filename in module.MODEL_FILES:
            (directory / filename).write_bytes(b"fixture cache")
    return SimpleNamespace(module=module, root=root)


@pytest.mark.parametrize("cache_complete", [True, False])
def test_preheat_loads_orientation_and_verifies_home_cache(preheat, tmp_path, monkeypatch, capsys, cache_complete):
    calls = []

    def create_model(*, model_name, **_kwargs):
        calls.append(("load", model_name))
        return SimpleNamespace(predict=lambda *_args, **_kwargs: calls.append(("predict", model_name)) or [])

    def text_ocr(**kwargs):
        assert kwargs["text_detection_model_name"] == "PP-OCRv6_medium_det"
        assert kwargs["text_recognition_model_name"] == "PP-OCRv6_medium_rec"
        return SimpleNamespace(predict=lambda *_args: calls.append(("predict", "text_ocr")) or [])

    monkeypatch.setitem(sys.modules, "paddlex", SimpleNamespace(create_model=create_model))
    monkeypatch.setitem(sys.modules, "paddleocr", SimpleNamespace(PaddleOCR=text_ocr))
    image = tmp_path / "source.png"
    image.write_bytes(b"fake models do not decode")
    if cache_complete:
        assert preheat.module.main(image) == 0
    else:
        (preheat.root / "PP-LCNet_x1_0_doc_ori/inference.pdiparams").unlink()
        with pytest.raises(RuntimeError, match="Incomplete OCR model cache"):
            preheat.module.main(image)
    assert calls == [("load", "PP-DocLayout-S"), ("predict", "PP-DocLayout-S"), ("predict", "text_ocr"),
                     ("load", "PP-FormulaNet_plus-M"), ("predict", "PP-FormulaNet_plus-M"),
                     ("load", "PP-LCNet_x1_0_doc_ori"), ("predict", "PP-LCNet_x1_0_doc_ori")]
    output = capsys.readouterr().out
    if cache_complete:
        assert str(preheat.root) in output
    assert output.endswith("PREHEAT_OK\n") is cache_complete


@pytest.mark.parametrize("model", ["PP-DocLayout-S", "PP-OCRv6_medium_det", "PP-OCRv6_medium_rec",
                                   "PP-FormulaNet_plus-M", "PP-LCNet_x1_0_doc_ori"])
@pytest.mark.parametrize("filename", ["inference.json", "inference.pdiparams", "inference.yml"])
@pytest.mark.parametrize("invalid", ["missing", "empty"])
def test_preheat_rejects_missing_or_empty_model_cache(preheat, model, filename, invalid):
    target = preheat.root / model / filename
    if invalid == "missing":
        target.unlink()
    else:
        target.write_bytes(b"")
    with pytest.raises(RuntimeError, match="Incomplete OCR model cache") as failed:
        preheat.module.validate_cache()
    assert str(target) in str(failed.value)
