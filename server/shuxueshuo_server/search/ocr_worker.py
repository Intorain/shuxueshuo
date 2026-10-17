"""Long-lived page OCR worker for question segmentation, run by the isolated OCR interpreter.

Protocol: one JSON object per stdin line ``{"image": "/abs/path"}``; one JSON
object per stdout line. Models load once, so only the first request pays the
start-up cost.

Segmentation only needs where each text line is and whether it starts with a
question number, so the page is detected at reduced resolution and only the
head of each row-leading line is recognised. Full-page recognition took
15–20 s per page; this takes about 1.5–2.5 s on a laptop CPU.
"""

import json
import sys
from time import monotonic

import numpy as np
from PIL import Image, ImageOps

from shuxueshuo_server.search.segmentation import head_candidates

MAX_SIDE = 1600
DETECT_SIDE = 736
HEAD_HEIGHTS = 3
ENGINE = {"run_mode": "paddle", "device_type": "cpu", "cpu_threads": 8, "enable_new_ir": False}


def load_models():
    from paddlex import create_model

    return {name: create_model(model, engine="paddle_static", engine_config=ENGINE)
            for name, model in (("layout", "PP-DocLayout-S"), ("det", "PP-OCRv6_medium_det"),
                                ("rec", "PP-OCRv6_medium_rec"))}


def _bounds(points):
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def observe(models, path):
    image = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    scale = min(1.0, MAX_SIDE / max(image.size))
    if scale < 1:
        image = image.resize((round(image.width * scale), round(image.height * scale)), Image.LANCZOS)
    pixels = np.asarray(image)
    w, h = image.size
    timings = {}

    started = monotonic()
    layout = next(iter(models["layout"].predict(pixels))).json["res"]
    timings["layout"] = round((monotonic() - started) * 1000)

    started = monotonic()
    detected = next(iter(models["det"].predict(pixels, limit_side_len=DETECT_SIDE, limit_type="max"))).json["res"]
    timings["detect"] = round((monotonic() - started) * 1000)

    polys = [[(float(x), float(y)) for x, y in poly] for poly in detected.get("dt_polys", ())]
    boxes = [_bounds(poly) for poly in polys]
    # Per-line recognition costs ~40 ms on CPU and batching does not help, so only
    # row-leading lines (the only ones that can start a question) are recognised.
    wanted = head_candidates(boxes)
    crops = []
    for i in wanted:
        x0, y0, x1, y1 = boxes[i]
        line_h = max(1.0, y1 - y0)
        crops.append(pixels[int(y0):int(y1) + 1, int(x0):int(min(x1, x0 + HEAD_HEIGHTS * line_h)) + 1])
    started = monotonic()
    heads = dict(zip(wanted, (r.json["res"] for r in models["rec"].predict(crops)), strict=True)) if crops else {}
    timings["recognize_heads"] = round((monotonic() - started) * 1000)

    return {
        "width": w,
        "height": h,
        "lines": [
            {"box": [x0 / w, y0 / h, x1 / w, y1 / h], "poly": [[x / w, y / h] for x, y in poly],
             "head": heads.get(i, {}).get("rec_text", ""),
             "confidence": float(heads.get(i, {}).get("rec_score", 0.0))}
            for i, ((x0, y0, x1, y1), poly) in enumerate(zip(boxes, polys, strict=True))
        ],
        "layout": [
            {"label": str(item.get("label")), "confidence": float(item.get("score", 0.0)),
             "box": [item["coordinate"][0] / w, item["coordinate"][1] / h,
                     item["coordinate"][2] / w, item["coordinate"][3] / h]}
            for item in layout.get("boxes", ())
        ],
        "latency_ms": timings,
    }


def main():
    # Paddle logs to stdout; keep it for protocol replies only.
    replies, sys.stdout = sys.stdout, sys.stderr
    models = load_models()
    print(json.dumps({"ready": True}), file=replies, flush=True)
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            reply = {"ok": True, **observe(models, json.loads(line)["image"])}
        except Exception as exc:  # noqa: BLE001 - one bad image must not kill the worker
            reply = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        print(json.dumps(reply, ensure_ascii=False), file=replies, flush=True)


if __name__ == "__main__":
    main()
