"""Bound phone photographs before OCR without retaining the original upload."""

import json
import struct
import zlib
from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import BmpImagePlugin, Image, ImageDraw, JpegImagePlugin, PngImagePlugin

from shuxueshuo_server.search import dev_api
from shuxueshuo_server.search.ocr_protocol import MAX_IMAGE_BYTES, MAX_IMAGE_PIXELS
from tests.search.test_private_api import login
from tests.search.test_private_api import private_app as private_app_fixture
from tests.search.test_repository import repository as repository_fixture


@pytest.fixture
def repository(tmp_path):
    yield from repository_fixture.__wrapped__(tmp_path)


@pytest.fixture
def upload_client(repository, monkeypatch):
    app, auth = private_app_fixture.__wrapped__(repository, monkeypatch)
    observations = []

    def observe(_client, path, *, auto_orient=True):
        with Image.open(path) as image:
            assert image.mode == "RGB" and image.format == "PNG"
            assert max(image.size) <= dev_api.PAGE_SIDE
            assert image.width * image.height <= MAX_IMAGE_PIXELS
            assert path.stat().st_size <= MAX_IMAGE_BYTES
            assert not image.getexif()
            observations.append((path, image.size, auto_orient))
            scale = min(1, 1600 / max(image.size))
            size = (round(image.width * scale), round(image.height * scale))
        return {"width": size[0], "height": size[1], "lines": [], "layout": [],
                "latency_ms": {"detect": 0}, "orientation": {
                    "status": "upright" if auto_orient else "manual", "rotation_degrees": 0,
                    "predicted_degrees": None, "confidence": None}}

    monkeypatch.setattr(dev_api.OcrClient, "observe", observe)
    with TestClient(app, base_url=auth.config.origin) as client:
        user, _token = login(client, auth)
        yield SimpleNamespace(client=client, user=user, observations=observations)


@pytest.mark.parametrize("size,orientation,expected", [((6000, 4000), 1, (4096, 2731)), ((8192, 3906), 6, (1953, 4096))])
def test_jpeg_is_bounded_before_ocr_and_manual_rotation(upload_client, repository, monkeypatch, size, orientation, expected):
    content = BytesIO()
    with Image.new("RGB", size, "white") as photograph:
        draw = ImageDraw.Draw(photograph)
        draw.rectangle((0, 0, 999, 999), fill=(240, 20, 20))
        draw.rectangle((0, size[1] - 1000, 999, size[1] - 1), fill=(20, 20, 240))
        exif = Image.Exif()
        exif[274] = orientation
        exif[315] = "synthetic private metadata"
        photograph.save(content, format="JPEG", quality=90, exif=exif)
    body = content.getvalue()
    assert len(body) < dev_api.MAX_UPLOAD
    assert size[0] * size[1] <= dev_api.MAX_UPLOAD_PIXELS == 32_000_000
    original = JpegImagePlugin.JpegImageFile.load
    decoded_sizes = []

    def load(image):
        if image.fp is not None:
            decoded_sizes.append(image.size)
        return original(image)

    monkeypatch.setattr(JpegImagePlugin.JpegImageFile, "load", load)
    response = upload_client.client.post("/api/search/pages", content=body, headers={"Content-Type": "image/png"})
    assert response.status_code == 200, response.text
    page = response.json()
    assert (page["width"], page["height"]) == expected
    assert decoded_sizes
    if size[0] == 8192:
        assert decoded_sizes[0] == (4096, 1953)
    directory = repository.page(upload_client.user, page["page_id"])["path"]
    assert upload_client.observations == [(directory / "source.png", expected, True)]
    assert not any(path.suffix.lower() in {".jpeg", ".jpg"} and path.name != "preview.jpg"
                   for path in directory.iterdir())
    with Image.open(directory / "source.png") as source:
        assert not source.info
        red, _green, blue = source.getpixel((100, 100))
        assert (red > 200 and blue < 60) if orientation == 1 else (blue > 200 and red < 60)
    rotated = upload_client.client.post(f"/api/search/pages/{page['page_id']}/rotate", json={"degrees": 90})
    assert rotated.status_code == 200, rotated.text
    assert (rotated.json()["width"], rotated.json()["height"]) == expected[::-1]
    assert upload_client.observations[-1][1:] == (expected[::-1], False)
    original_deadline = repository.page(upload_client.user, page["page_id"])["expires_at"]
    assert repository.page(upload_client.user, rotated.json()["page_id"])["expires_at"] == original_deadline


@pytest.mark.parametrize("file_format", ["JPEG", "PNG", "BMP"])
@pytest.mark.parametrize("content_type", ["image/jpeg", "application/octet-stream"])
@pytest.mark.parametrize("size,allowed", [((8000, 4000), True), ((8000, 4001), False), ((8000, 6000), False)])
def test_all_formats_share_thirty_two_megapixel_limit_before_decoding(
    upload_client, repository, monkeypatch, file_format, content_type, size, allowed,
):
    buffer = BytesIO()
    with Image.new("RGB", (16, 16)) as image:
        image.save(buffer, format=file_format)
    body = bytearray(buffer.getvalue())
    if file_format == "JPEG":
        frame = body.index(b"\xff\xc0")
        body[frame + 5:frame + 9] = struct.pack(">HH", size[1], size[0])
    elif file_format == "PNG":
        body[16:24] = struct.pack(">II", *size)
        body[29:33] = struct.pack(">I", zlib.crc32(body[12:29]))
    else:
        body[18:26] = struct.pack("<ii", *size)
    assert len(body) < 1024
    reached_draft = []

    class HeaderAccepted(Exception):
        pass

    def draft(image, *_args, **_kwargs):
        reached_draft.append((image.format, image.size))
        raise HeaderAccepted()

    def forbidden_decode(*_args, **_kwargs):
        pytest.fail("header fixture must never be decoded or resized")

    monkeypatch.setattr(Image.Image, "draft", draft)
    monkeypatch.setattr(JpegImagePlugin.JpegImageFile, "draft", draft)
    monkeypatch.setattr(Image.Image, "thumbnail", forbidden_decode)
    monkeypatch.setattr(PngImagePlugin.PngImageFile, "load", forbidden_decode)
    monkeypatch.setattr(BmpImagePlugin.BmpImageFile, "load", forbidden_decode)
    monkeypatch.setattr(JpegImagePlugin.JpegImageFile, "load", forbidden_decode)
    if allowed:
        with pytest.raises(HeaderAccepted):
            upload_client.client.post("/api/search/pages", content=bytes(body), headers={"Content-Type": content_type})
        assert reached_draft == [(file_format, size)]
    else:
        response = upload_client.client.post("/api/search/pages", content=bytes(body), headers={"Content-Type": content_type})
        assert response.status_code == 413
        assert response.json() == {"detail": "page.pixels"}
        assert reached_draft == []
    assert upload_client.observations == []
    assert not list((repository.root / "pages").iterdir())


@pytest.mark.parametrize("failure", ["input_limit", "pillow_warning", "pillow_error"])
def test_pixel_bombs_are_rejected_before_decode_or_ocr(upload_client, repository, monkeypatch, failure):
    buffer = BytesIO()
    with Image.new("RGB", (16, 16)) as image:
        image.save(buffer, format="PNG")
    body = bytearray(buffer.getvalue())
    if failure == "input_limit":
        body[16:24] = struct.pack(">II", 10000, 8001)
        body[29:33] = struct.pack(">I", zlib.crc32(body[12:29]))
    else:
        monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 200 if failure == "pillow_warning" else 100)

    def forbidden_decode(_image, *_args, **_kwargs):
        pytest.fail("oversized image was decoded")

    monkeypatch.setattr(PngImagePlugin.PngImageFile, "load", forbidden_decode)
    response = upload_client.client.post("/api/search/pages", content=bytes(body))
    assert response.status_code == 413
    assert response.json() == {"detail": "page.pixels"}
    assert upload_client.observations == []
    assert not list((repository.root / "pages").iterdir())


def test_manual_rotation_of_existing_large_page_uses_the_same_bound(upload_client, repository):
    page_id = "abcdef123456"
    directory = repository.storage.path(repository.storage.page_key(page_id))
    directory.mkdir()
    with Image.new("RGB", (5000, 100), "white") as page:
        page.save(directory / "page.png")
    metadata = {"width": 5000, "height": 100, "rotation_count": 0}
    (directory / "segments.json").write_text(json.dumps(metadata))
    repository.register_page(upload_client.user, page_id, metadata)
    response = upload_client.client.post(f"/api/search/pages/{page_id}/rotate", json={"degrees": 90})
    assert response.status_code == 200, response.text
    assert max(response.json()["width"], response.json()["height"]) == dev_api.PAGE_SIDE
    assert len(upload_client.observations) == 1
    assert upload_client.observations[0][2] is False
