"""Pure encoding tests: no calculation worker or mathematical imports."""

import json
import math

import pytest

from shuxueshuo_server.graph_lesson.stage_three import json_bounded


def streamed_bytes(value):
    encoder = json.JSONEncoder(ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    return b"".join(part.encode("utf-8") for part in encoder.iterencode(value))


@pytest.mark.parametrize("value", [
    None, True, False, 0, -1, 2**4095, -(2**4095),
    0.0, -0.0, 1.7976931348623157e308, 5e-324,
    "中文 ∀𝑥 😀\n\t\r\b\f\x00\x1f\\\"",
    {"键\n\"": [None, True, False, 12, -4.25, {"嵌套": [[], {}, "😀"]}]},
])
def test_fast_encoding_is_byte_identical_to_original_stream(value, monkeypatch):
    expected = streamed_bytes(value)
    original = json.dumps
    calls = []

    def dumps(*args, **kwargs):
        calls.append(kwargs)
        return original(*args, **kwargs)

    monkeypatch.setattr(json_bounded.json, "dumps", dumps)
    assert json_bounded._encode(value) == expected
    assert calls == [{"ensure_ascii": False, "allow_nan": False, "separators": (",", ":")}]
    assert json_bounded._decode(expected) == value


@pytest.mark.parametrize("bits", [0, 1, 2, 9, 10, 53, 256, 4095, 4096])
def test_conservative_size_covers_integer_digits_and_json_structure(bits):
    number = (1 << bits) - 1
    value = {"a\x00": [number, -number, [], {}, None, False, True, -0.0, math.pi]}
    assert json_bounded._validate_json(value) >= len(streamed_bytes(value))


def test_overestimated_valid_payload_keeps_streaming_fallback(monkeypatch):
    monkeypatch.setattr(json_bounded, "MAX_JSON_BYTES", 128)

    def forbidden(*args, **kwargs):
        pytest.fail("an oversized estimate must not enter the allocating C encoder")

    monkeypatch.setattr(json_bounded.json, "dumps", forbidden)
    value = "x" * 126
    assert json_bounded._validate_json(value) > 128
    assert json_bounded._encode(value) == b'"' + b"x" * 126 + b'"'


@pytest.mark.parametrize("value", ["\x00" * 24, "😀" * 24, "x" * 64])
def test_streaming_fallback_preserves_actual_utf8_byte_limit(value, monkeypatch):
    monkeypatch.setattr(json_bounded, "MAX_JSON_BYTES", 64)

    def forbidden(*args, **kwargs):
        pytest.fail("oversized output must use the streaming guard")

    monkeypatch.setattr(json_bounded.json, "dumps", forbidden)
    with pytest.raises(ValueError, match="byte limit"):
        json_bounded._encode(value)


def test_many_large_integers_do_not_allocate_full_encoded_output(monkeypatch):
    value = [2**4095] * (json_bounded.MAX_JSON_NODES - 1)
    assert json_bounded._validate_json(value) > 200_000_000
    original = json.JSONEncoder.iterencode
    yielded = 0

    def tracked(self, *args, **kwargs):
        nonlocal yielded
        for part in original(self, *args, **kwargs):
            yielded += 1
            yield part

    def forbidden(*args, **kwargs):
        pytest.fail("large-integer input must not allocate hundreds of megabytes via dumps")

    monkeypatch.setattr(json_bounded.json, "dumps", forbidden)
    monkeypatch.setattr(json.JSONEncoder, "iterencode", tracked)
    with pytest.raises(ValueError, match="byte limit"):
        json_bounded._encode(value)
    assert 0 < yielded < 10_000


@pytest.mark.parametrize(("value", "error", "message"), [
    (float("nan"), ValueError, "finite"),
    (float("inf"), ValueError, "finite"),
    (float("-inf"), ValueError, "finite"),
    (2**4096, ValueError, "4096-bit"),
    (-(2**4096), ValueError, "4096-bit"),
    ({1: "value"}, TypeError, "keys must be exact strings"),
    ((1, 2), TypeError, "JSON-native"),
])
def test_invalid_values_never_reach_fast_encoder(value, error, message, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("validation must precede the allocating encoder")

    monkeypatch.setattr(json_bounded.json, "dumps", forbidden)
    with pytest.raises(error, match=message):
        json_bounded._encode(value)


def test_depth_node_and_text_limits_remain_enforced(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("invalid input must not enter the allocating encoder")

    monkeypatch.setattr(json_bounded.json, "dumps", forbidden)
    deep = None
    for _ in range(json_bounded.MAX_JSON_DEPTH + 1):
        deep = [deep]
    with pytest.raises(ValueError, match="depth/node"):
        json_bounded._encode(deep)
    with pytest.raises(ValueError, match="node limit"):
        json_bounded._encode([None] * json_bounded.MAX_JSON_NODES)
    with pytest.raises(ValueError, match="byte limit"):
        json_bounded._encode("x" * (json_bounded.MAX_JSON_BYTES + 1))


def test_unpaired_surrogate_keeps_existing_unicode_error():
    with pytest.raises(UnicodeEncodeError):
        json_bounded._encode({"value": "\ud800"})


def test_native_subclasses_remain_rejected():
    class Integer(int):
        pass

    with pytest.raises(TypeError, match="JSON-native"):
        json_bounded._encode(Integer(3))
