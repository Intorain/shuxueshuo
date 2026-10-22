"""Pixel-level checks for the crop sent to recognition; no OCR models needed."""

import math

import pytest
from PIL import Image, ImageDraw
from shuxueshuo_server.search.ocr_crops import head_crop


def _tilted_lines(angle, *, length=340, height=24):
    """Paint two parallel lines in page coordinates, with distinct head markers.

    Red belongs only to the preceding line. The target's first three character
    widths are green, blue and yellow; its leading stroke and asymmetric top /
    bottom markers expose clipping, horizontal reversal and vertical reversal.
    """
    radians = math.radians(angle)
    cosine, sine = math.cos(radians), math.sin(radians)

    def point(along, across):
        return 80 + along * cosine - across * sine, 180 + along * sine + across * cosine

    image = Image.new("RGB", (520, 420), "white")
    draw = ImageDraw.Draw(image)

    def band(left, top, right, bottom, color):
        draw.polygon([point(left, top), point(right, top), point(right, bottom), point(left, bottom)], fill=color)

    band(0, -2 * height, length, -height, (230, 15, 20))
    band(0, 0, length, height, (20, 180, 45))
    band(height, 0, 2 * height, height, (20, 60, 220))
    band(2 * height, 0, 3 * height, height, (235, 210, 20))
    band(0, 2, 5, height - 2, (25, 25, 25))
    band(10, 2, 20, 9, (15, 210, 210))
    band(10, height - 9, 20, height - 2, (150, 30, 180))
    return image, [point(0, 0), point(length, 0), point(length, height), point(0, height)]


def _red_fraction(image):
    pixels = image.tobytes()
    return sum(red > 180 and green < 65 and blue < 65
               for red, green, blue in zip(pixels[::3], pixels[1::3], pixels[2::3])) / (image.width * image.height)


@pytest.mark.parametrize("angle", [-25, -12, 12, 25])
def test_rectified_head_retains_its_number_and_orientation_without_the_previous_line(angle):
    image, poly = _tilted_lines(angle)
    crop = head_crop(image, poly)
    assert crop.size == (72, 24)
    assert crop.mode == "RGB" and len(crop.tobytes()) == 72 * 24 * 3
    # Probe well inside the painted strokes, away from interpolation edges.
    for (row, column), expected in [
        ((12, 2), [25, 25, 25]),       # leading stroke survives at the left edge
        ((5, 15), [15, 210, 210]),     # top marker remains above the bottom marker
        ((19, 15), [150, 30, 180]),
        ((12, 35), [20, 60, 220]),     # second character remains before the third
        ((12, 60), [235, 210, 20]),
    ]:
        assert all(abs(actual - wanted) <= 3 for actual, wanted in zip(crop.getpixel((column, row)), expected))
    assert _red_fraction(crop.crop((2, 2, crop.width - 2, crop.height - 2))) == 0

    # This fixture actually reproduces the old failure: its axis-aligned head
    # includes the red preceding line. Otherwise a blank-background fixture
    # could pass while failing to exercise cross-line contamination at all.
    x0, y0 = min(x for x, _ in poly), min(y for _, y in poly)
    x1, y1 = max(x for x, _ in poly), max(y for _, y in poly)
    old_head = image.crop((int(x0), int(y0), int(min(x1, x0 + 3 * (y1 - y0))) + 1, int(y1) + 1))
    assert _red_fraction(old_head) > .02


def test_a_short_line_keeps_its_far_end_without_extending_into_background():
    image = Image.new("RGB", (100, 80), (230, 15, 20))
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 30, 54, 49), fill=(20, 180, 45))
    draw.rectangle((51, 30, 54, 49), fill=(25, 25, 25))
    crop = head_crop(image, [(20, 30), (55, 30), (55, 50), (20, 50)])
    assert crop.size == (35, 20)
    assert crop.mode == "RGB"
    assert crop.getpixel((1, 10)) == (20, 180, 45)
    assert crop.getpixel((33, 10)) == (25, 25, 25)
    assert _red_fraction(crop) == 0


@pytest.mark.parametrize("angle", [-25, 0, 25])
def test_prefix_width_uses_character_height_instead_of_sloping_bounding_box_height(angle):
    image, poly = _tilted_lines(angle, length=380, height=10)
    crop = head_crop(image, poly)
    assert crop.size == (30, 10)
    assert crop.mode == "RGB" and len(crop.tobytes()) == 30 * 10 * 3


def test_subpixel_detection_still_produces_a_nonempty_rgb_uint8_crop():
    image = Image.new("RGB", (10, 10), (20, 180, 45))
    crop = head_crop(image, [(3.1, 4.1), (3.5, 4.2), (3.4, 4.5), (3.0, 4.4)])
    assert crop.size == (1, 1)
    assert crop.mode == "RGB" and len(crop.tobytes()) == 3
    assert crop.getpixel((0, 0)) == (20, 180, 45)
