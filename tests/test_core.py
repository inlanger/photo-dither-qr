from __future__ import annotations

from pathlib import Path

import pytest
import segno
import zxingcpp
from PIL import Image
from segno import consts

from dithered_qr import generate_dithered_qr
from dithered_qr.core import QUIET_ZONE_MODULES, _encode_payload, _module_types


DATA_TYPES = {consts.TYPE_DATA_LIGHT, consts.TYPE_DATA_DARK}
PROJECT_ROOT = Path(__file__).parents[1]


def gradient(width: int = 180, height: int = 120) -> Image.Image:
    image = Image.new("L", (width, height))
    image.putdata(
        [
            int(255 * (0.7 * x / (width - 1) + 0.3 * y / (height - 1)))
            for y in range(height)
            for x in range(width)
        ]
    )
    return image


def test_geometry_palette_and_quiet_zone() -> None:
    subpixels = 3
    pixel_size = 2
    result = generate_dithered_qr(
        "https://example.com",
        gradient(),
        min_version=6,
        subpixels=subpixels,
        pixel_size=pixel_size,
    )

    modules = 17 + 4 * 6
    expected_side = (
        modules + 2 * QUIET_ZONE_MODULES
    ) * subpixels * pixel_size
    assert result.size == (expected_side, expected_side)
    assert set(result.get_flattened_data()) == {0, 255}
    assert result.crop((0, 0, result.width, QUIET_ZONE_MODULES * subpixels * pixel_size)).getextrema() == (255, 255)


def test_function_modules_and_data_centers_are_preserved() -> None:
    payload = "https://example.com"
    subpixels = 3
    border = QUIET_ZONE_MODULES * subpixels
    result = generate_dithered_qr(
        payload,
        gradient(),
        min_version=6,
        subpixels=subpixels,
        pixel_size=1,
    )
    qr = _encode_payload(payload, 6, "H", None)
    module_types = _module_types(qr)
    pixels = result.load()
    center = subpixels // 2

    for module_y, row in enumerate(module_types):
        for module_x, module_type in enumerate(row):
            expected = 0 if module_type >> 8 else 255
            left = border + module_x * subpixels
            top = border + module_y * subpixels
            if module_type in DATA_TYPES:
                assert pixels[left + center, top + center] == expected
            else:
                tile = result.crop(
                    (left, top, left + subpixels, top + subpixels)
                )
                assert tile.getextrema() == (expected, expected)


@pytest.mark.parametrize(
    ("payload", "source"),
    [
        ("https://example.com/photo-dither-qr", gradient()),
        ("Привет из QR", Image.new("L", (120, 180), 128)),
    ],
)
def test_generated_image_decodes(payload: str, source: Image.Image) -> None:
    result = generate_dithered_qr(payload, source)
    decoded = zxingcpp.read_barcode(
        result,
        formats=zxingcpp.BarcodeFormat.QRCode,
        try_invert=False,
        is_pure=False,
    )

    assert decoded is not None
    assert decoded.valid
    assert decoded.text == payload


@pytest.mark.parametrize(
    ("option", "value", "message"),
    [
        ("min_version", 0, "min_version"),
        ("subpixels", 2, "subpixels"),
        ("subpixels", 4, "subpixels"),
        ("pixel_size", 0, "pixel_size"),
        ("gamma", 0, "gamma"),
        ("mask", 8, "mask"),
    ],
)
def test_invalid_options(option: str, value: object, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        generate_dithered_qr("payload", gradient(), **{option: value})


def test_payload_grows_past_minimum_version() -> None:
    payload = "x" * 120
    qr = _encode_payload(payload, 1, "H", None)
    assert isinstance(qr.version, int)
    assert qr.version > 1


@pytest.mark.parametrize(
    ("filename", "payload"),
    [
        ("example-com-qr.png", "https://example.com"),
        (
            "repository-qr.png",
            "https://github.com/inlanger/photo-dither-qr",
        ),
    ],
)
def test_committed_examples_decode(filename: str, payload: str) -> None:
    with Image.open(PROJECT_ROOT / "examples" / filename) as image:
        decoded = zxingcpp.read_barcode(
            image,
            formats=zxingcpp.BarcodeFormat.QRCode,
            try_invert=False,
            is_pure=False,
        )

    assert decoded is not None
    assert decoded.valid
    assert decoded.text == payload
