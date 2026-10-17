import json
from pathlib import Path

import pytest

from shuxueshuo_server.search.segmentation import question_number, segment

PAGES = Path(__file__).parent / "fixtures/segment-pages"
TOLERANCE = 0.003


def _norm(box, w, h):
    return [box[0] / w, box[1] / h, box[2] / w, box[3] / h]


def _contains(outer, inner):
    return (outer[0] - TOLERANCE <= inner[0] and outer[1] - TOLERANCE <= inner[1]
            and inner[2] <= outer[2] + TOLERANCE and inner[3] <= outer[3] + TOLERANCE)


def _overlap_share(region, gold):
    x0, y0 = max(region[0], gold[0]), max(region[1], gold[1])
    x1, y1 = min(region[2], gold[2]), min(region[3], gold[3])
    if x1 <= x0 or y1 <= y0:
        return 0.0
    return (x1 - x0) * (y1 - y0) / ((gold[2] - gold[0]) * (gold[3] - gold[1]))


@pytest.mark.parametrize("page", sorted(p.name for p in PAGES.iterdir() if (p / "ocr.json").exists()))
def test_recorded_page_matches_gold(page):
    directory = PAGES / page
    gold = json.loads((directory / "gold.json").read_text(encoding="utf-8"))
    result = segment(json.loads((directory / "ocr.json").read_text(encoding="utf-8")))
    golds = [_norm(q["box"], gold["width"], gold["height"]) for q in gold["questions"]]
    regions = [r["box"] for r in result.regions]
    assert len(regions) == len(golds), result.diagnostics
    for question, box in zip(gold["questions"], golds, strict=True):
        owners = [r for r in result.regions if _contains(r["crop"], box)]
        assert len(owners) == 1, (question, result.regions)
        if question["number"] is not None:
            assert owners[0]["number"] == question["number"]
        for other in golds:
            if other is not box:
                assert _overlap_share(owners[0]["box"], other) < 0.1, (question, other)
                assert _overlap_share(owners[0]["crop"], other) < 0.5, (question, other)


@pytest.mark.parametrize(("head", "neighbour", "expected"), [
    ("10. 满足条件", True, 10),
    ("11、已知", True, 11),
    ("14．设集合", True, 14),
    ("15", True, 15),
    ("15", False, None),
    ("13. ", False, 13),
    ("0.11", True, None),
    ("2x+1+x", True, None),
    ("4<4a^2", True, None),
    ("(1) 若", True, None),
    ("100. 题", True, None),
])
def test_question_number(head, neighbour, expected):
    assert question_number(head, has_right_neighbour=neighbour) == expected


def _line(x0, y0, x1, y1, head=""):
    return {"box": [x0, y0, x1, y1], "head": head}


def test_misread_circled_number_fills_the_gap():
    lines = [_line(.05, .10, .9, .12, "10. 已知"), _line(.05, .20, .9, .22, "11. 已知"),
             _line(.05, .30, .9, .32, "42已知p"), _line(.05, .40, .9, .42, "13. 若")]
    result = segment({"width": 1000, "height": 2000, "lines": lines, "layout": []})
    assert [r["number"] for r in result.regions] == [10, 11, 12, 13]
    assert result.diagnostics["repaired"] == [{"number": 12, "head": "42已知p"}]


def test_whole_page_image_label_does_not_swallow_questions():
    lines = [_line(.05, .10, .9, .12, "1. 已知"), _line(.05, .50, .9, .52, "2. 已知")]
    layout = [{"label": "image", "confidence": .9, "box": [0, 0, 1, 1]}]
    result = segment({"width": 1000, "height": 2000, "lines": lines, "layout": layout})
    assert result.regions[0]["box"][3] < .5


def test_figure_below_text_joins_its_question():
    lines = [_line(.05, .10, .9, .12, "1. 如图"), _line(.05, .60, .9, .62, "2. 已知")]
    layout = [{"label": "image", "confidence": .9, "box": [.5, .14, .8, .40]}]
    result = segment({"width": 1000, "height": 2000, "lines": lines, "layout": layout})
    assert result.regions[0]["box"][3] >= .40
    assert result.regions[1]["box"][1] > .40


def _photo_page():
    """Layout of a real worksheet photo: notes on a sheet to the right, handwriting-inflated lines."""
    return [
        _line(.13, .070, .60, .115, "二、填空题（本大"),
        _line(.26, .096, .29, .115, "[a]"),
        _line(.13, .103, .59, .143, "10. 满足条件"),
        _line(.86, .109, .95, .145, "x+2y=b"),
        _line(.13, .130, .73, .174, "11. 已知集合"),
        _line(.17, .151, .36, .180, "取值范围是"),
        _line(.85, .160, .93, .190, "2x+1=a"),
        _line(.13, .181, .74, .215, "12. 已知 p"),
        _line(.17, .201, .58, .229, "是 q 的充分"),
        _line(.14, .227, .65, .259, "13. 若不等式"),
        _line(.13, .344, .76, .372, "三、解答题"),
        _line(.14, .379, .28, .399, "程或演算"),
        _line(.33, .389, .39, .410, ""),
        _line(.14, .407, .59, .435, "16. 已知集合"),
        _line(.15, .431, .42, .457, "(1)若A=0"),
    ]


def test_margin_notes_beside_the_sheet_stay_out_of_boxes():
    result = segment({"width": 767, "height": 1024, "lines": _photo_page(), "layout": []})
    assert [r["number"] for r in result.regions] == [10, 11, 12, 13, 16]
    for region in result.regions:
        assert region["box"][2] < .84, region


def test_boxes_do_not_overlap_each_other_or_headers():
    result = segment({"width": 767, "height": 1024, "lines": _photo_page(), "layout": []})
    boxes = [r["box"] for r in result.regions]
    for upper, lower in zip(boxes, boxes[1:]):
        assert upper[3] <= lower[1] + 1e-6
    q10, q11, _, q13, q16 = boxes
    assert q10[1] > .09 and q11[1] > .115
    assert q16[1] > .39, "handwriting left of the number line must not pull the box over the header"
    assert q13[3] < .344


def test_crops_keep_the_whole_last_line_even_when_tap_areas_split_it():
    result = segment({"width": 767, "height": 1024, "lines": _photo_page(), "layout": []})
    q10, q11, q12, q13, _ = result.regions
    assert q10["crop"][3] > .130 and q10["crop"][3] > q10["box"][3] - 1e-6
    assert q11["crop"][3] >= .180 and q12["crop"][3] >= .229 and q13["crop"][3] >= .256
    assert q10["crop"][3] <= .142, "only the top edge of the next number line may show"
    assert q10["crop"][1] >= .103 - 1e-6, "the header above stays out of the crop"
    assert q10["crop"][1] <= .103 + .25 * .040 + 1e-6, "but the own number line is kept"
    assert .133 < q11["crop"][1] < .143, "most of the previous question's last line stays out"


def test_unnumbered_page_is_one_region():
    lines = [_line(.05, .10, .9, .12, "已知函数"), _line(.08, .14, .9, .16, "(1) 若")]
    result = segment({"width": 1000, "height": 1000, "lines": lines, "layout": []})
    assert result.mode == "whole_content"
    assert len(result.regions) == 1 and result.regions[0]["number"] is None


def test_no_text_returns_no_regions():
    result = segment({"width": 1000, "height": 1000, "lines": [], "layout": []})
    assert result.mode == "empty" and result.regions == []
