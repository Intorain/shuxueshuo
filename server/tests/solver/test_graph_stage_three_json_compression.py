"""Bounded wire compression without spawning calculation processes."""

import json
import struct
import zlib

import pytest

from shuxueshuo_server.graph_lesson.stage_three import json_bounded


def compressed(data):
    return json_bounded._COMPRESSED_MAGIC + zlib.compress(data, level=1)


def test_large_json_wire_roundtrip_reduces_frames_but_preserves_plain_encoding():
    value = {"steps": [{"revisions": {"方法": "abc123" * 100}, "math": "∀x∈ℝ: x²≥0"}] * 300}
    plain = json_bounded._encode(value)
    wire = json_bounded._wire_bytes(plain)
    assert wire.startswith(json_bounded._COMPRESSED_MAGIC)
    assert len(wire) < len(plain) // 10
    assert len(list(json_bounded._frames(wire))) < len(list(json_bounded._frames(plain))) // 10
    assert json_bounded._decode(wire) == json.loads(plain) == value
    assert plain.startswith(b'{"steps":')


@pytest.mark.parametrize("size", [0, 1, json_bounded._COMPRESS_THRESHOLD])
def test_small_wire_stays_uncompressed(size, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("small wire messages must not invoke compression")

    monkeypatch.setattr(json_bounded.zlib, "compress", forbidden)
    plain = b" " * size
    assert json_bounded._wire_bytes(plain) is plain


def test_compression_that_grows_message_falls_back_to_original(monkeypatch):
    plain = b" " * (json_bounded._COMPRESS_THRESHOLD + 1)
    monkeypatch.setattr(json_bounded.zlib, "compress", lambda data, level: data)
    assert json_bounded._wire_bytes(plain) is plain


def test_original_oversize_is_rejected_before_compression(monkeypatch):
    monkeypatch.setattr(json_bounded, "MAX_JSON_BYTES", 64)

    def forbidden(*args, **kwargs):
        pytest.fail("compression must not hide an oversized original")

    monkeypatch.setattr(json_bounded.zlib, "compress", forbidden)
    with pytest.raises(ValueError, match="byte limit"):
        json_bounded._wire_bytes(b"x" * 65)


def test_oversized_wire_is_rejected_before_decompression(monkeypatch):
    monkeypatch.setattr(json_bounded, "MAX_JSON_BYTES", 64)

    def forbidden(*args, **kwargs):
        pytest.fail("oversized wire must not enter the decompressor")

    monkeypatch.setattr(json_bounded.zlib, "decompressobj", forbidden)
    with pytest.raises(ValueError, match="byte limit"):
        json_bounded._decode(json_bounded._COMPRESSED_MAGIC + b"x" * 65)


def test_decompression_bomb_expands_only_to_output_limit_plus_one(monkeypatch):
    wire = compressed(b'"' + b"x" * (2 * json_bounded.MAX_JSON_BYTES) + b'"')
    monkeypatch.setattr(json_bounded, "MAX_JSON_BYTES", 128 * 1024)
    original = zlib.decompressobj
    sizes = []

    class TrackedDecoder:
        def __init__(self):
            self.decoder = original()

        def decompress(self, data, max_length):
            result = self.decoder.decompress(data, max_length)
            sizes.append((max_length, len(result)))
            return result

        def __getattr__(self, name):
            return getattr(self.decoder, name)

    monkeypatch.setattr(json_bounded.zlib, "decompressobj", TrackedDecoder)
    assert len(wire) < json_bounded.MAX_JSON_BYTES
    with pytest.raises(ValueError, match="byte limit"):
        json_bounded._decode(wire)
    assert sizes == [(json_bounded.MAX_JSON_BYTES + 1, json_bounded.MAX_JSON_BYTES + 1)]


def test_exact_decompressed_byte_limit_is_accepted(monkeypatch):
    monkeypatch.setattr(json_bounded, "MAX_JSON_BYTES", 128)
    assert json_bounded._decode(compressed(b'"' + b"x" * 126 + b'"')) == "x" * 126


@pytest.mark.parametrize("alter", [
    lambda data: data[:-1],
    lambda data: data[:len(json_bounded._COMPRESSED_MAGIC) + 2],
    lambda data: data[:-1] + bytes([data[-1] ^ 1]),
    lambda data: data + b"trailing",
    lambda data: data + zlib.compress(b'"second stream"'),
    lambda data: json_bounded._COMPRESSED_MAGIC + b"not a zlib stream",
])
def test_truncated_corrupt_or_trailing_compressed_data_is_rejected(alter):
    with pytest.raises(ValueError, match="compressed JSON"):
        json_bounded._decode(alter(compressed(b'{"value":42}')))


@pytest.mark.parametrize("plain", [b"not JSON", b'{"v":NaN}', b'{"v":Infinity}', b"[" * 66 + b"]" * 66])
def test_compressed_payload_still_requires_valid_bounded_native_json(plain):
    with pytest.raises(ValueError):
        json_bounded._decode(compressed(plain))


def test_unknown_magic_version_is_not_accepted():
    with pytest.raises(ValueError):
        json_bounded._decode(b"\x00S3Z2\x00" + zlib.compress(b"{}"))


def test_send_frames_remain_atomic_and_reader_decodes_compressed_wire(monkeypatch):
    if json_bounded.os.name != "posix":
        pytest.skip("POSIX atomic frame path")
    packets = []
    monkeypatch.setattr(json_bounded.os, "set_blocking", lambda *args: None)

    def write(fd, packet):
        packets.append(packet)
        return len(packet)

    class Sender:
        def fileno(self):
            return 42

    monkeypatch.setattr(json_bounded.os, "write", write)
    value = {"text": "数学" * 100_000}
    json_bounded._send(Sender(), json_bounded._encode(value))
    frames = []
    for packet in packets:
        assert len(packet) <= 4 + 1 + 480
        assert struct.unpack("!i", packet[:4])[0] == len(packet) - 4
        frames.append(packet[4:])

    class Receiver:
        def recv_bytes(self, maximum):
            frame = frames.pop(0)
            assert len(frame) <= maximum
            return frame

    reader = json_bounded._Reader()
    result = None
    while frames:
        result = reader.read(Receiver())
    assert result.startswith(json_bounded._COMPRESSED_MAGIC)
    assert json_bounded._decode(result) == value


def test_expired_deadline_is_checked_before_compression(monkeypatch):
    monkeypatch.setattr(json_bounded.time, "monotonic", lambda: 10)

    def forbidden(*args, **kwargs):
        pytest.fail("expired sends must not start compression")

    monkeypatch.setattr(json_bounded, "_wire_bytes", forbidden)
    with pytest.raises(TimeoutError, match="deadline"):
        json_bounded._send(None, b"{}", deadline=9)


def test_durable_receipts_are_still_plain_json(tmp_path):
    path = tmp_path / "receipt.json"
    outcome = {"status": "returned", "result": {"value": "x" * 100_000}}
    expected = json_bounded._receipt({"receipt_path": str(path), "attempt_id": "test"}, outcome, 0.25)
    assert json.loads(path.read_bytes()) == expected
    assert path.read_bytes().startswith(b"{")
