"""Image-only preprocessing for the row heads sent to OCR recognition."""

import math

from PIL import Image


def head_crop(image: Image.Image, poly, *, head_heights: int = 3) -> Image.Image:
    """Rectify the detected line head, rather than cropping its sloping AABB.

    An axis-aligned crop of a steep line includes the previous line and can
    hide its number. Character scale comes from the quadrilateral's short
    edges, independent of the line's length or page angle.
    """
    top_left, top_right, bottom_right, bottom_left = poly
    height = max(1, round(max(math.dist(top_left, bottom_left), math.dist(top_right, bottom_right))))
    width = max(1, round(max(math.dist(top_left, top_right), math.dist(bottom_left, bottom_right))))
    fraction = min(1, head_heights * height / width)
    top_end = [a + fraction * (b - a) for a, b in zip(top_left, top_right)]
    bottom_end = [a + fraction * (b - a) for a, b in zip(bottom_left, bottom_right)]
    quad = (*top_left, *bottom_left, *bottom_end, *top_end)
    return image.transform((min(width, head_heights * height), height), Image.Transform.QUAD,
                           quad, resample=Image.Resampling.BICUBIC)
