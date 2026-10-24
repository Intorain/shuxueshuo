"""Run also with .venv-ocr/bin/python -m unittest discover -s tests/search -p test_ocr_orientation_worker.py.

The application environment intentionally excludes numpy/Paddle; these checks
exercise the isolated worker with fake model outputs and real raster arrays.
"""

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image


@unittest.skipUnless(importlib.util.find_spec("numpy"), "requires the isolated OCR interpreter")
class OrientationWorkerTests(unittest.TestCase):
    def test_server_requires_orientation_while_local_startup_can_fall_back(self):
        from shuxueshuo_server.search.ocr_worker import load_models

        calls = []

        def create_model(name, **_kwargs):
            calls.append(name)
            if name == "PP-LCNet_x1_0_doc_ori":
                raise RuntimeError("orientation cache unavailable")
            return object()

        with patch.dict(sys.modules, {"paddlex": SimpleNamespace(create_model=create_model)}):
            with self.assertRaisesRegex(RuntimeError, "orientation cache unavailable"):
                load_models(require_orientation=True)
            self.assertEqual(calls, ["PP-DocLayout-S", "PP-OCRv6_medium_det",
                                     "PP-OCRv6_medium_rec", "PP-LCNet_x1_0_doc_ori"])
            self.assertIsNone(load_models()["orientation"])

    def test_strict_startup_loads_every_search_model_and_rejects_missing_instances(self):
        from shuxueshuo_server.search.ocr_worker import load_models

        models = {name: object() for name in ("PP-DocLayout-S", "PP-OCRv6_medium_det",
                                              "PP-OCRv6_medium_rec", "PP-LCNet_x1_0_doc_ori")}

        def create_model(name, **_kwargs):
            return models[name]

        with patch.dict(sys.modules, {"paddlex": SimpleNamespace(create_model=create_model)}):
            result = load_models(require_orientation=True)
            self.assertEqual(set(result), {"layout", "det", "rec", "orientation"})
            self.assertEqual(set(result.values()), set(models.values()))
            models["PP-LCNet_x1_0_doc_ori"] = None
            with self.assertRaisesRegex(RuntimeError, "ocr.models_unavailable"):
                load_models(require_orientation=True)

    def run_observation(self, label="90", confidence=.99, *, automatic=True, failure=False, available=True):
        from shuxueshuo_server.search.ocr_worker import observe

        calls = []

        class Model:
            def __init__(self, name, result):
                self.name, self.result = name, result

            def predict(self, pixels, **kwargs):
                calls.append((self.name, pixels.copy()))
                if self.name == "orientation" and failure:
                    raise RuntimeError("third-party inference failure")
                yield SimpleNamespace(json={"res": self.result})

        models = {"orientation": Model("orientation", {"label_names": [label], "scores": [confidence]}),
                  "layout": Model("layout", {"boxes": []}),
                  "det": Model("det", {"dt_polys": []}),
                  "rec": Model("rec", {"rec_text": "1.", "rec_score": .99})}
        if not available:
            models["orientation"] = None
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "page.png"
            page = Image.new("RGB", (3, 2))
            page.putdata([(n, n, n) for n in range(6)])
            page.save(path)
            before = path.read_bytes()
            result = observe(models, path, auto_orient=automatic)
            self.assertEqual(path.read_bytes(), before)
        return result, calls

    def test_all_four_directions_are_corrected_before_detection(self):
        expected = {"0": (3, 2, [0, 1, 2, 3, 4, 5]), "90": (2, 3, [2, 5, 1, 4, 0, 3]),
                    "180": (3, 2, [5, 4, 3, 2, 1, 0]), "270": (2, 3, [3, 0, 4, 1, 5, 2])}
        for label, (w, h, pixels) in expected.items():
            with self.subTest(label=label):
                result, calls = self.run_observation(label)
                self.assertEqual((result["width"], result["height"]), (w, h))
                self.assertEqual([name for name, _ in calls], ["orientation", "layout", "det"])
                for _, array in calls[1:]:
                    self.assertEqual(array[:, :, 0].flatten().tolist(), pixels)

    def test_manual_rotation_bypasses_classifier_and_keeps_pixels(self):
        result, calls = self.run_observation(automatic=False, failure=True)
        self.assertEqual(result["orientation"]["status"], "manual")
        self.assertEqual(result["orientation"]["rotation_degrees"], 0)
        self.assertEqual([name for name, _ in calls], ["layout", "det"])
        self.assertEqual(calls[0][1][:, :, 0].flatten().tolist(), list(range(6)))

    def test_uncertain_failed_and_unavailable_classifiers_leave_manual_fallback_usable(self):
        for settings in ({"confidence": .5}, {"failure": True}, {"available": False}, {"label": "bad"}):
            with self.subTest(settings=settings):
                result, calls = self.run_observation(**settings)
                self.assertEqual(result["orientation"]["status"], "uncertain")
                self.assertEqual((result["width"], result["height"]), (3, 2))
                self.assertEqual(calls[-1][1][:, :, 0].flatten().tolist(), list(range(6)))


if __name__ == "__main__":
    unittest.main()
