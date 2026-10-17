"""Turn a cropped question photo into the small, clean PNG sent to stage one.

Upload to the model's file API dominates stage-one latency and grows with
bytes, so the crop is reduced to what reading needs: grayscale, paper shading
flattened to white, 16 grey levels, long side capped.
"""

from io import BytesIO

from PIL import Image, ImageChops, ImageFilter, ImageOps

MAX_SIDE = 1600
LEVELS = 16
PAPER = 232


def question_png(crop, *, max_side=MAX_SIDE):
    """PNG bytes for a PIL crop; deterministic for the same input."""
    gray = ImageOps.grayscale(crop)
    scale = min(1.0, max_side / max(gray.size))
    if scale < 1:
        gray = gray.resize((round(gray.width * scale), round(gray.height * scale)), Image.LANCZOS)
    ink = ImageChops.subtract(_background(gray), gray)
    flat = ImageOps.invert(ink)
    flat = ImageOps.autocontrast(flat, cutoff=(1, 0))
    step = 256 // LEVELS
    flat = flat.point(lambda v: 255 if v >= PAPER else v // step * step)
    buffer = BytesIO()
    flat.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def _background(gray):
    """Paper brightness: strokes removed by a max filter at low resolution, then smoothed."""
    factor = 8
    small = gray.resize((max(1, gray.width // factor), max(1, gray.height // factor)), Image.BOX)
    small = small.filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.GaussianBlur(2))
    return small.resize(gray.size, Image.BILINEAR)
