"""Layout may disambiguate row starts; weak source labels still need context."""

import json
from pathlib import Path

import pytest

from shuxueshuo_server.search.segmentation import (
    head_candidates,
    page_head_candidates,
    segment,
)


def test_adjacent_sheet_fragment_does_not_hide_body_row_start():
    boxes = [(20, 100, 63, 140), (80, 105, 800, 135)]
    body = (75, 80, 820, 220)

    assert 1 not in head_candidates(boxes, median_h=30)
    assert 1 in head_candidates(boxes, median_h=30, text_regions=[body])


def test_same_body_formula_continuations_stay_blocked():
    boxes = [(80, 100, 450, 130), (470, 100, 500, 130), (515, 100, 700, 130)]
    body = (70, 80, 820, 220)

    assert head_candidates(boxes, median_h=30, text_regions=[body]) == [0]


@pytest.mark.parametrize("region", [
    (75, 80, 194, 220),  # Width is less than four median line heights.
    (75, 80, 220, 169),  # Height is less than three median line heights.
])
def test_small_paragraph_region_cannot_unblock_a_continuation(region):
    boxes = [(20, 100, 63, 130), (80, 100, 180, 130)]

    assert head_candidates(boxes, median_h=30, text_regions=[region]) == [0]


def test_body_region_accepts_exact_size_thresholds():
    boxes = [(20, 100, 63, 130), (80, 100, 180, 130)]

    assert 1 in head_candidates(boxes, median_h=30, text_regions=[(75, 80, 195, 170)])


def test_missing_layout_keeps_row_neighbour_fallback():
    boxes = [(20, 100, 63, 140), (80, 105, 800, 135)]

    assert head_candidates(boxes, median_h=30) == [0]
    assert head_candidates(boxes, median_h=30, text_regions=[]) == [0]


def test_detached_question_number_is_still_a_row_head():
    boxes = [(80, 100, 100, 130), (120, 100, 800, 130)]

    assert head_candidates(boxes, median_h=30, text_regions=[(70, 80, 820, 220)]) == [0]


@pytest.mark.parametrize("top", [10, 110, 300])
def test_broad_aligned_rows_share_the_column_of_a_detected_paragraph(top):
    # A slightly inset paragraph region anchors the entire printed column,
    # including sibling questions above and below the detected paragraph.
    boxes = [(20, top, 63, top + 30), (80, top, 800, top + 30)]
    assert head_candidates(boxes, median_h=30, text_regions=[(85, 100, 820, 220)]) == [0, 1]
    assert head_candidates(boxes, median_h=30) == [0]


@pytest.mark.parametrize("row", [
    (120, 300, 800, 330),  # Starts too far inside the column.
    (80, 300, 190, 330),   # A short fragment is not a sibling paragraph row.
    (80, 300, 700, 330),   # Right edge does not match the column.
])
def test_paragraph_column_does_not_unblock_short_or_misaligned_continuations(row):
    boxes = [(20, 300, 63, 330), row]
    assert head_candidates(boxes, median_h=30, text_regions=[(85, 100, 820, 220)]) == [0]


def test_real_preceding_text_in_the_same_column_still_blocks_a_broad_row():
    # Even a broad aligned row remains a continuation if preceding content
    # reaches into this column instead of belonging to a neighbouring sheet.
    boxes = [(20, 300, 88, 330), (80, 300, 800, 330)]
    assert head_candidates(boxes, median_h=40, text_regions=[(85, 100, 820, 220)]) == [0]


def _line(x, y, head, *, right=.88):
    return {"box": [x, y, right, y + .02], "head": head}


def _numbers(lines, layout=()):
    result = segment({"width": 1000, "height": 1000, "lines": lines, "layout": list(layout)})
    return [region["number"] for region in result.regions]


def test_layout_row_heads_feed_segmentation_not_only_head_recognition():
    lines = [_line(.02, .10, "x<0", right=.063), _line(.08, .10, "9. 已知"),
             _line(.02, .30, "x>0", right=.063), _line(.08, .30, "10. 已知")]
    layout = [{"label": "text", "box": [.075, .08, .90, .35]}]

    assert _numbers(lines, layout) == [9, 10]


@pytest.mark.parametrize("head", ["7x+1", "0.11", "(1) 若", "（1）设"])
def test_aligned_broad_formula_or_subquestion_never_becomes_a_numbered_question(head):
    lines = [_line(.08, .10, "6. 已知"), _line(.02, .30, "x<0", right=.063),
             _line(.08, .30, head), _line(.08, .50, "8. 已知")]
    layout = [{"label": "text", "box": [.085, .08, .90, .18]}]
    wanted = page_head_candidates(lines, layout, 1000, 1000)
    assert 2 in wanted, "recognition may read a broad row, but only numbering syntax may start a question"
    assert _numbers(lines, layout) == [6, 8]


def test_recorded_paragraph_layout_keeps_unrecognized_sibling_heads_available_to_ocr():
    path = Path(__file__).parent / "fixtures/segment-book-orientation.ocr.json"
    ocr = json.loads(path.read_text())
    wanted = set(page_head_candidates(ocr["lines"], ocr["layout"], ocr["width"], ocr["height"]))
    # These are detected full question lines whose original head recognition
    # was skipped. Preserve that raw evidence; do not manufacture OCR text.
    missed = [i for i, line in enumerate(ocr["lines"])
              if not line["head"] and .11 < line["box"][0] < .13 and line["box"][2] > .7]
    assert len(missed) == 2
    assert set(missed) <= wanted
    without_layout = page_head_candidates(ocr["lines"], [], ocr["width"], ocr["height"])
    assert not set(missed) & set(without_layout)


@pytest.mark.parametrize("head", ["10.2026上海", "10．2026上海"])
def test_year_source_label_recovers_between_adjacent_strong_numbers(head):
    lines = [_line(.08, .10, "9. 已知"), _line(.08, .25, head), _line(.08, .40, "11. 已知")]

    assert _numbers(lines) == [9, 10, 11]


@pytest.mark.parametrize(("head", "number"), [
    ("7", 7), ("12", 12), ("1O.", 10), ("1l.", 11),
    ("1O. 已知函数", 10), ("1l．已知集合", 11),
])
def test_damaged_or_isolated_number_recovers_only_its_matching_gap(head, number):
    lines = [_line(.08, .10, f"{number - 1}. 已知"), _line(.08, .25, head),
             _line(.08, .40, f"{number + 1}. 已知")]
    result = segment({"width": 1000, "height": 1000, "lines": lines, "layout": []})
    assert [r["number"] for r in result.regions] == [number - 1, number, number + 1]
    assert result.diagnostics["repaired"] == [{"number": number, "head": head}]
    lines[0]["head"] = f"{number}. 已知"
    lines[2]["head"] = f"{number + 2}. 已知"
    assert _numbers(lines) == [number, number + 2]


@pytest.mark.parametrize(("head", "number"), [("7", 7), ("12", 12), ("1O.", 10), ("1l.", 11)])
def test_weak_number_requires_both_anchors_and_the_same_column(head, number):
    lines = [_line(.08, .10, f"{number - 1}. 已知", right=.42),
             _line(.08, .25, head, right=.42),
             _line(.08, .40, f"{number + 1}. 已知", right=.42)]
    assert _numbers(lines[:2]) == [number - 1]
    assert _numbers(lines[1:]) == [number + 1]
    lines[1] = _line(.55, .25, head)
    assert _numbers(lines) == [number - 1, number + 1]


def test_consecutive_ocr_letter_numbers_need_a_complete_unambiguous_gap():
    lines = [_line(.08, .10, "9. 已知"), _line(.08, .25, "1O."),
             _line(.08, .40, "1l."), _line(.08, .55, "12. 已知")]
    assert _numbers(lines) == [9, 10, 11, 12]
    assert _numbers(lines[:2] + lines[3:]) == [9, 12]
    lines.insert(2, _line(.08, .32, "10"))
    assert _numbers(lines) == [9, 12]


@pytest.mark.parametrize("head", ["10.2026", "10.5", "10.2026x", "10.2026年"])
def test_decimal_or_formula_cannot_enter_through_number_gap_repair(head):
    lines = [_line(.08, .10, "9. 已知"), _line(.08, .25, head), _line(.08, .40, "11. 已知")]

    assert _numbers(lines) == [9, 11]


@pytest.mark.parametrize(("head", "number"), [
    ("1O.5", 10), ("1O.x+1", 10), ("1O.+2", 10),
    ("1l.5", 11), ("1l.x", 11), ("7x+1", 7), ("12/3", 12),
])
def test_ocr_letter_formula_heads_are_not_repaired(head, number):
    lines = [_line(.08, .10, f"{number - 1}. 已知"), _line(.08, .25, head),
             _line(.08, .40, f"{number + 1}. 已知")]
    assert _numbers(lines) == [number - 1, number + 1]


def test_year_source_label_in_another_column_cannot_fill_gap():
    lines = [_line(.08, .10, "9. 已知", right=.42), _line(.55, .25, "10.2026上海"),
             _line(.08, .40, "11. 已知", right=.42)]

    assert _numbers(lines) == [9, 11]


def test_strong_numbers_from_different_columns_do_not_confirm_year_label():
    lines = [_line(.08, .10, "9. 已知", right=.42), _line(.08, .25, "10.2026上海", right=.42),
             _line(.55, .40, "11. 已知")]

    assert _numbers(lines) == [9, 11]


@pytest.mark.parametrize(("lines", "expected"), [
    ([_line(.08, .25, "10.2026上海"), _line(.08, .40, "11. 已知")], [11]),
    ([_line(.08, .10, "9. 已知"), _line(.08, .25, "10.2026上海")], [9]),
])
def test_year_source_label_requires_both_strong_neighbours(lines, expected):
    assert _numbers(lines) == expected


@pytest.mark.parametrize(("before", "after"), [(8, 11), (9, 12)])
def test_year_source_label_requires_immediately_adjacent_numbers(before, after):
    lines = [_line(.08, .10, f"{before}. 已知"), _line(.08, .25, "10.2026上海"),
             _line(.08, .40, f"{after}. 已知")]

    assert _numbers(lines) == [before, after]


def test_year_source_label_in_right_hand_formula_is_not_a_row_head():
    lines = [_line(.08, .10, "9. 已知"), _line(.08, .25, "由此可得", right=.48),
             _line(.50, .25, "10.2026上海"), _line(.08, .40, "11. 已知")]
    layout = [{"label": "text", "box": [.07, .08, .90, .45]}]

    assert _numbers(lines, layout) == [9, 11]


def test_consecutive_damaged_source_labels_need_the_complete_number_sequence():
    lines = [_line(.08, .10, "8. 已知"), _line(.08, .25, "9.2026广东"),
             _line(.08, .40, "10.2026上海"), _line(.08, .55, "11. 已知")]
    assert _numbers(lines) == [8, 9, 10, 11]
    lines[1]["head"] = "10.2026广东"
    assert _numbers(lines) == [8, 11]


def test_recorded_curved_book_page_recovers_all_four_questions():
    """Real OCR after quad head-cropping: left-page remnants and a lost bracket."""
    path = Path(__file__).parent / "fixtures/segment-book-page.ocr.json"
    ocr = json.loads(path.read_text())
    result = segment(ocr)
    assert [region["number"] for region in result.regions] == [8, 9, 10, 11]
    assert result.diagnostics["repaired"] == [{"number": 10, "head": "10.2026上海"}]
    wanted = page_head_candidates(ocr["lines"], ocr["layout"], ocr["width"], ocr["height"])
    for number in (8, 9, 11):
        index = next(i for i, line in enumerate(ocr["lines"]) if line["head"].startswith(f"{number}."))
        assert index in wanted, "must recognise this head before segmentation can use it"
    assert [r["number"] for r in segment({**ocr, "layout": []}).regions] == [11]
