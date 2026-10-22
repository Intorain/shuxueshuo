"""Direction conventions, conservative confidence handling, and worker protocol."""

import io
import json
from types import SimpleNamespace

import pytest
from PIL import Image

from shuxueshuo_server.search.ocr_client import OcrClient
from shuxueshuo_server.search.page_orientation import (
    orientation_from_prediction,
    rotate_clockwise,
)


@pytest.mark.parametrize("degrees,expected", [(0, [0, 1, 2, 3, 4, 5]), (90, [3, 0, 4, 1, 5, 2]),
                                             (180, [5, 4, 3, 2, 1, 0]), (270, [2, 5, 1, 4, 0, 3])])
def test_quarter_turn_preserves_each_pixel_in_clockwise_order(degrees, expected):
    image = Image.new("L", (3, 2))
    image.putdata(range(6))
    rotated = rotate_clockwise(image, degrees)
    assert list(rotated.tobytes()) == expected
    assert rotated.size == ((2, 3) if degrees in (90, 270) else (3, 2))
    assert list(image.tobytes()) == list(range(6))


@pytest.mark.parametrize("degrees", [True, False, 90.0, "90", -90, 45, 360, None])
def test_rotation_requires_an_exact_supported_integer(degrees):
    with pytest.raises(ValueError, match="invalid_rotation"):
        rotate_clockwise(Image.new("RGB", (2, 3)), degrees)


@pytest.mark.parametrize("label,clockwise", [("0", 0), ("90", 270), ("180", 180), ("270", 90)])
def test_paddle_counterclockwise_label_becomes_clockwise_correction(label, clockwise):
    result = orientation_from_prediction({"label_names": [label], "scores": [.95]})
    assert result == {"status": "corrected" if clockwise else "upright", "rotation_degrees": clockwise,
                      "predicted_degrees": clockwise, "confidence": .95}


@pytest.mark.parametrize("prediction", [None, {}, {"label_names": []}, {"label_names": ["90"], "scores": []},
    {"label_names": ["45"], "scores": [.99]}, {"label_names": ["90"], "scores": [True]},
    {"label_names": ["90"], "scores": [float("nan")]}, {"label_names": ["90"], "scores": [float("inf")]},
    {"label_names": ["90"], "scores": [1.01]}, {"label_names": ["90"], "scores": [-.1]}])
def test_invalid_prediction_keeps_the_source_orientation(prediction):
    result = orientation_from_prediction(prediction)
    assert result["status"] == "uncertain" and result["rotation_degrees"] == 0
    assert result["confidence"] is None


def test_low_confidence_does_not_apply_the_predicted_correction():
    result = orientation_from_prediction({"label_names": ["90"], "scores": [.899]})
    assert result == {"status": "uncertain", "rotation_degrees": 0, "predicted_degrees": 270,
                      "confidence": .899, "reason": "low_confidence"}


@pytest.mark.parametrize("automatic", [True, False])
def test_worker_request_explicitly_preserves_manual_orientation(automatic):
    client = OcrClient()
    process = SimpleNamespace(stdin=io.StringIO(), stdout=io.StringIO('{"ok":true}\n'), poll=lambda: None)
    client._process = process
    assert client.observe("/tmp/page.png", auto_orient=automatic) == {"ok": True}
    assert json.loads(process.stdin.getvalue()) == {"image": "/tmp/page.png", "auto_orient": automatic}


def test_invalid_worker_flag_is_rejected_before_starting_a_process():
    with pytest.raises(ValueError, match="invalid_auto_orient"):
        OcrClient().observe("/tmp/page.png", auto_orient="false")
