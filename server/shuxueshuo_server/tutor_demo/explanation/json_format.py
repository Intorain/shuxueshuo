"""Bounded syntax repairs at JSON parser error positions, never fill in content."""

import json
import re


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _constant(value):
    raise ValueError("non-finite JSON number")


def decode_model_json(raw):
    """Return an object and repair codes; ambiguous/truncated output is rejected.

    No global substitutions: commas, colons and backslashes inside formulas
    must survive unchanged. Only edit the position identified by json.loads.
    Missing values, unterminated strings/containers and extra payloads are not
    completed or discarded. Every repaired result still needs schema validation.
    """
    text, repairs = raw.strip(), []
    fence = re.fullmatch(r"```(?:json)?\s*\n(.*)\n\s*```", text, re.DOTALL | re.IGNORECASE)
    if fence:
        text = fence[1].strip()
        repairs.append("code_fence")
    for _ in range(65):
        try:
            value = json.loads(text, object_pairs_hook=_object, parse_constant=_constant)
            if not isinstance(value, dict):
                raise TypeError("expected a JSON object")
            return value, repairs
        except json.JSONDecodeError as exc:
            if len(repairs) >= 64:
                raise
            pos = exc.pos
            char = text[pos:pos + 1]
            before = text[:pos].rstrip()
            if exc.msg.startswith("Invalid \\escape") and char == "\\":
                # E.g. a literal TeX \cdot needs a doubled JSON backslash.
                text = text[:pos] + "\\" + text[pos:]
                repairs.append("invalid_escape")
            elif exc.msg.startswith("Invalid control character") and char:
                text = text[:pos] + json.dumps(char)[1:-1] + text[pos + 1:]
                repairs.append("literal_control")
            elif exc.msg == "Expecting ':' delimiter" and char == "：":
                text = text[:pos] + ":" + text[pos + 1:]
                repairs.append("fullwidth_colon")
            elif exc.msg == "Expecting ',' delimiter" and char == "，":
                text = text[:pos] + "," + text[pos + 1:]
                repairs.append("fullwidth_comma")
            elif exc.msg in {"Expecting ':' delimiter", "Expecting ',' delimiter"} and re.match(
                r'(?:["\[{]|-?\d|true\b|false\b|null\b)', text[pos:]
            ):
                delimiter = ":" if exc.msg == "Expecting ':' delimiter" else ","
                text = text[:pos] + delimiter + text[pos:]
                repairs.append("missing_colon" if delimiter == ":" else "missing_comma")
            elif before.endswith(",") and (
                (exc.msg == "Expecting property name enclosed in double quotes" and char == "}")
                or (exc.msg == "Expecting value" and char == "]")
            ):
                comma = len(before) - 1
                text = text[:comma] + text[comma + 1:]
                repairs.append("trailing_comma")
            else:
                raise
    raise ValueError("JSON repair limit exceeded")
