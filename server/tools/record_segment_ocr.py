"""Record Paddle layout + text output for segmentation fixtures (or any images).

Run from server/: uv run python tools/record_segment_ocr.py [image ...]
Without arguments, records ocr.json next to every tests/search/fixtures/segment-pages/*/page.png.
With image paths, prints the OCR JSON path written to /tmp/segment-ocr/.
"""

import json
import sys
from pathlib import Path

from shuxueshuo_server.search.ocr_client import OcrClient

SERVER = Path(__file__).resolve().parents[1]
PAGES = SERVER / "tests/search/fixtures/segment-pages"


def main():
    client = OcrClient()
    targets = [Path(p) for p in sys.argv[1:]] or sorted(PAGES.glob("*/page.png"))
    try:
        for image in targets:
            reply = client.observe(image.resolve())
            reply.pop("ok")
            if sys.argv[1:]:
                output = Path("/tmp/segment-ocr") / f"{image.stem}.ocr.json"
                output.parent.mkdir(exist_ok=True)
            else:
                output = image.with_name("ocr.json")
            output.write_text(json.dumps(reply, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            print(output, reply["latency_ms"], f"{len(reply['lines'])} lines, {len(reply['layout'])} layout boxes")
    finally:
        client.close()


if __name__ == "__main__":
    main()
