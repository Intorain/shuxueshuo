"""Draw segmentation regions (and gold boxes, when present) on a page image.

Red: tap area (box). Blue, inset: crop sent to stage one. Green: gold.

Run from server/: uv run python tools/segment_preview.py PAGE_DIR_OR_IMAGE [...]
A fixture directory uses its recorded ocr.json; a bare image is sent to the OCR worker.
Writes <name>.segments.jpg to /tmp/segment-preview/ and prints the regions.
"""

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from shuxueshuo_server.search.segmentation import segment

OUT = Path("/tmp/segment-preview")
FONT = "/System/Library/Fonts/STHeiti Medium.ttc"


def load(target):
    target = Path(target)
    if target.is_dir():
        gold = target / "gold.json"
        return (target.name, target / "page.png", json.loads((target / "ocr.json").read_text()),
                json.loads(gold.read_text()) if gold.exists() else None)
    from shuxueshuo_server.search.ocr_client import OcrClient

    client = OcrClient()
    try:
        ocr = client.observe(target.resolve())
    finally:
        client.close()
    return target.stem, target, ocr, None


def draw(name, image_path, result, gold):
    image = Image.open(image_path).convert("RGB")
    w, h = image.size
    pen = ImageDraw.Draw(image)
    size = max(18, w // 60)
    font = ImageFont.truetype(FONT, size)
    for q in (gold or {}).get("questions", []):
        pen.rectangle(q["box"], outline=(40, 160, 60), width=max(2, w // 600))
    for region in result.regions:
        cx0, cy0, cx1, cy1 = region.get("crop", region["box"])
        pen.rectangle((cx0 * w + 4, cy0 * h, cx1 * w - 4, cy1 * h), outline=(40, 90, 220), width=max(2, w // 700))
        x0, y0, x1, y1 = region["box"]
        box = (x0 * w, y0 * h, x1 * w, y1 * h)
        pen.rectangle(box, outline=(220, 40, 40), width=max(3, w // 400))
        label = f"{region['index']}" + (f" (#{region['number']})" if region["number"] else "")
        pen.text((box[2] - size * 4, box[3] - size * 1.3), label, fill=(220, 40, 40), font=font)
    OUT.mkdir(exist_ok=True)
    path = OUT / f"{name}.segments.jpg"
    image.save(path, quality=88)
    return path


def main():
    for target in sys.argv[1:]:
        name, image, ocr, gold = load(target)
        result = segment(ocr)
        path = draw(name, image, result, gold)
        print(path, result.mode, result.diagnostics)
        for region in result.regions:
            print("  ", region)


if __name__ == "__main__":
    main()
