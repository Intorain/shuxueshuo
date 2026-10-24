"""Bounded search-page OCR transport, independent of the product journal protocol."""

import math

MAX_REQUEST_BYTES = 8192
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_IMAGE_BYTES = 64 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
REQUEST_TIMEOUT = 15
SEARCH_LOCK_TIMEOUT = 100
OBSERVE_TIMEOUT = 120
STARTUP_TIMEOUT = 180


def _number(value, lower, upper):
    return type(value) in (int, float) and math.isfinite(value) and lower <= value <= upper


def _box(value):
    return (isinstance(value, list) and len(value) == 4
            and all(_number(coordinate, -1, 2) for coordinate in value)
            and value[0] <= value[2] and value[1] <= value[3])


def valid_observation(value):
    if not isinstance(value, dict) or value.get("ok") is not True:
        return False
    if any(type(value.get(key)) is not int or not 1 <= value[key] <= 1600 for key in ("width", "height")):
        return False
    orientation = value.get("orientation")
    if not isinstance(orientation, dict) or orientation.get("status") not in {"upright", "corrected", "manual", "uncertain"}:
        return False
    if type(orientation.get("rotation_degrees")) is not int or orientation["rotation_degrees"] not in (0, 90, 180, 270):
        return False
    predicted = orientation.get("predicted_degrees")
    if predicted is not None and (type(predicted) is not int or predicted not in (0, 90, 180, 270)):
        return False
    confidence = orientation.get("confidence")
    if confidence is not None and not _number(confidence, 0, 1):
        return False
    for key in ("lines", "layout"):
        items = value.get(key)
        if not isinstance(items, list) or len(items) > 10000:
            return False
        for item in items:
            if not isinstance(item, dict) or not _box(item.get("box")) or not _number(item.get("confidence"), 0, 1):
                return False
            label = item.get("head" if key == "lines" else "label")
            if not isinstance(label, str) or len(label) > 4096:
                return False
            if key == "lines":
                poly = item.get("poly")
                if not isinstance(poly, list) or not 3 <= len(poly) <= 64:
                    return False
                if any(not isinstance(point, list) or len(point) != 2
                       or not all(_number(coordinate, -1, 2) for coordinate in point) for point in poly):
                    return False
    timings = value.get("latency_ms")
    return (isinstance(timings, dict) and 1 <= len(timings) <= 16
            and all(isinstance(key, str) and _number(duration, 0, 3_600_000) for key, duration in timings.items()))
