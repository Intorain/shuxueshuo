import pytest
from shuxueshuo_server.search.segmentation_numbering import year_prefixed_number


@pytest.mark.parametrize(("head", "number"), [
    ("10.2026上海川", 10),
    ("8.2024浙江杭州模拟", 8),
    ("27．2019山东期中]若集合", 27),
    ("1.1900江苏", 1),
    ("99.2099广东", 99),
    ("  3 . 2007 北京期末", 3),
    ("\t42．\t1998\t重庆测试", 42),
    ("12.2025年全国模拟", 12),
])
def test_year_source_without_opening_bracket_proposes_a_weak_number(head, number):
    assert year_prefixed_number(head) == number


@pytest.mark.parametrize("head", [
    "", None, 10,
    "0.2026上海", "00.2026上海", "01.2026上海", "100.2026上海",
    "10.1899上海", "10.2100上海", "10.12026上海", "10.202上海", "10.20260上海",
    "10.2026", "10.2026 ", "10.2026x+1", "10.2026a", "10.2026e3", "10.2026E-3",
    "10.2026+1", "10.2026-2", "10.2026/3", "10.2026*3", "10.2026^2", "10.2026=0",
    "10.2026≤3", "10.2026(上海)", "10.2026元", "10.2026年", "10.2026,上海",
    "0.11", "2.7182818", "3.1415", "10.20265", "+10.2026上海", "-10.2026上海",
    "x=10.2026上海", "(10)2026上海", "（10）2026上海", "10、2026上海",
    "10.[2026上海]", "10.（2026上海）", "10.2026\n上海",
])
def test_decimal_formula_and_unsupported_head_are_not_repaired(head):
    assert year_prefixed_number(head) is None


def test_textual_ambiguity_is_left_for_layout_and_number_chain_confirmation():
    # A parser of a line head alone cannot distinguish these shapes. Even
    # this return value must never be treated as a strong question number.
    assert year_prefixed_number("10.2026万元") == 10
