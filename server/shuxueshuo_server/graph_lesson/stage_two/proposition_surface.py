"""Locate explicit negation scopes, without deciding their mathematical meaning."""

import re
from dataclasses import dataclass

from .surface_math import formula_spans


@dataclass(frozen=True)
class NegatedProposition:
    start: int
    end: int
    body_start: int
    body_end: int
    asserted: bool = True


def _assertion_context(text, start, end):
    prefix = re.split(r'[，,。；;\n]', text[:start])[-1]
    if re.search(r'并非|并不|不是|是否|否定|¬|判断|求证|证明|未必', prefix):
        return False
    suffix = text[end:]
    # Only a completed assertion is supported; “为假或 …” / “是否正确”
    # requires reasoning about a larger proposition.
    boundary = re.match(r'[\s$]*(?:(?:为|是)真命题|成立|时)?[\s$]*(?:[，,。；;\n]|则|那么|$)', suffix)
    return bool(boundary) and not re.match(r'[\s$]*[，,]\s*(?:或|是否)', suffix)


def negated_propositions(text):
    """Keep even unsupported negative scopes out of ordinary positive matching.

    A false quoted proposition or an explicit ¬ has a local scope. A stray
    '假' elsewhere in the question never negates another formula.
    """
    regions = []
    for opening, closing in [('“', '”'), ('「', '」'), ('『', '』'), ('"', '"')]:
        pattern = re.compile(re.escape(opening) + r'([^' + opening + closing + r']+)' + re.escape(closing)
                             + r'\s*(?:为|是)\s*假命题')
        for match in pattern.finditer(text):
            asserted = _assertion_context(text, match.start(), match.end())
            regions.append(NegatedProposition(match.start(), match.end(), *match.span(1), asserted))

    for match in re.finditer('¬', text):
        start = match.start()
        if any(region.start <= start < region.end for region in regions):
            continue
        begin = match.end()
        while begin < len(text) and text[begin] in ' \t\r\n$':
            begin += 1
        stop = re.search(r'[。；;\n]|[，,](?=\s*(?:则|求))', text[begin:])
        end = begin + stop.start() if stop else len(text)
        body_start, body_end, asserted = begin, end, True
        if begin < len(text) and text[begin] in '([{':
            depth, closing = 0, None
            for i in range(begin, end):
                depth += (text[i] in '([{') - (text[i] in ')]}')
                if depth == 0:
                    closing = i
                    break
            if closing is None:
                asserted = False
            else:
                body_start, body_end, end = begin + 1, closing, closing + 1
                # Only the outer pair must match; domains inside may be valid
                # half-open intervals, e.g. (1, 4].
                asserted = text[closing] == {'(': ')', '[': ']', '{': '}'}[text[begin]]
        asserted = asserted and _assertion_context(text, start, end)
        regions.append(NegatedProposition(start, end, body_start, body_end, asserted))
    return sorted(regions, key=lambda region: region.start)


def proposition_parts(text, region):
    """Read one quantified domain followed by one atomic relation only.

    Mathematical validation belongs to the D1 matcher. The restricted prose
    grammar rejects conjunctions, nested quantifiers and ambiguous negations.
    """
    if not region.asserted:
        return None
    body = text[region.body_start:region.body_end]
    header = re.match(r'\s*\$?\s*(?:对)?(∀|∃|任意|所有|存在)\s*(实数\s*)?', body)
    if not header:
        return None
    offset = region.body_start + header.end()
    rest = text[offset:region.body_end]
    spans = list(formula_spans(rest))
    if len(spans) != 2:
        return None
    (da, db), (ra, rb) = spans
    if rest[:da].strip(' $\t\r\n'):
        return None
    if not re.fullmatch(r'[\s$，,:：]*(?:(?:不等式|使得|使|满足)[\s$]*)?', rest[db:ra]):
        return None
    if not re.fullmatch(r'[\s$]*(?:(?:恒成立|成立)[\s$]*)?', rest[rb:]):
        return None
    q = '∀' if header.group(1) in ('∀', '任意', '所有') else '∃'
    return q, bool(header.group(2)), (offset + da, offset + db), (offset + ra, offset + rb)
