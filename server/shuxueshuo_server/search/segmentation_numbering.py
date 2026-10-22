"""Conservative, weak question-number hints for damaged OCR heads.

This module does not decide whether a line starts a question. In particular,
an apparent decimal followed by Chinese text can still be a measurement; the
caller must confirm a proposed number against neighbouring strong question
numbers and the column's left margin before admitting it to the number chain.
"""

import re

# A source year is a bounded four-digit editorial label, not an arbitrary
# decimal suffix. Two Chinese characters avoid accepting a lone unit or 年.
# The fixed range keeps replay deterministic and is deliberately conservative.
_YEAR_PREFIX = re.compile(
    r"^[ \t]*([1-9][0-9]?)[ \t]*[.．][ \t]*(?:19|20)[0-9]{2}[ \t]*"
    r"[\u3400-\u4dbf\u4e00-\u9fff]{2,}"
)
_BARE_NUMBER = re.compile(r"[ \t]*([1-9][0-9]?)[ \t]*")
# Correct only the second character of a two-digit number, with punctuation
# and either no following text or a Chinese stem/source label. Never rewrite
# letters inside a formula, or accept a decimal suffix as question text.
_LETTER_NUMBER = re.compile(
    r"^[ \t]*([1-9][OoIl])[ \t]*[.．、。,，:：][ \t]*"
    r"(?=$|[\u3400-\u4dbf\u4e00-\u9fff【（\[])"
)
_OCR_DIGITS = str.maketrans({"O": "0", "o": "0", "I": "1", "l": "1"})


def gap_number_hint(head: str) -> int | None:
    """Propose a weak number that needs a complete, matching gap to confirm.

    Isolated numbers have no same-row text evidence. Letter-confused digits
    and source labels with missing brackets likewise cannot start a chain.
    """
    if not isinstance(head, str):
        return None
    match = _BARE_NUMBER.fullmatch(head) or _LETTER_NUMBER.match(head)
    if match:
        return int(match.group(1).translate(_OCR_DIGITS))
    return year_prefixed_number(head)


def year_prefixed_number(head: str) -> int | None:
    """Propose 1–99 from ``number.year Chinese-source``; never confirm it.

    Only years 1900–2099 and a following run of at least two Chinese
    characters are eligible. Bare decimals, extra digits, formula operators,
    variables and sub-question brackets are not repaired by this helper.
    A source label with its opening bracket intact belongs to the ordinary
    strong-number parser, not this missing-bracket recovery path.
    """
    if not isinstance(head, str):
        return None
    match = _YEAR_PREFIX.match(head)
    return int(match.group(1)) if match else None
