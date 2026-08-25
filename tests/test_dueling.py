from __future__ import annotations

from pathlib import Path

import pytest
import segno
import zxingcpp
from PIL import Image
from segno import consts

from dithered_qr.core import _module_types
from dithered_qr.dueling import (
    _validate_compatible_function_modules,
    generate_dueling_qr,
)


DATA_TYPES = {consts.TYPE_DATA_LIGHT, consts.TYPE_DATA_DARK}
PAYLOAD1 = "https://example.com/dueling/first"
PAYLOAD2 = "https://example.org/dueling/second"
VERSION = 7
SCALE = 10
QUIET_ZONE = 4
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _sample_view(image: Image.Image, split: str, view: int) -> Image.Image:
    module_count = 17 + 4 * VERSION
    grid_count = module_count + 2 * QUIET_ZONE
    quarter = SCALE // 4
    three_quarters = SCALE - quarter - 1
    sample_points = {
        "vertical": ((quarter, SCALE // 2), (three_quarters, SCALE // 2)),
        "horizontal": ((SCALE // 2, quarter), (SCALE // 2, three_quarters)),
        "diagonal": ((quarter, quarter), (three_quarters, three_quarters)),
    }
    sample_x, sample_y = sample_points[split][view]

    sampled = Image.new("L", (grid_count, grid_count), 255)
    sampled_pixels = sampled.load()
    source_pixels = image.load()
    for y in range(grid_count):
        for x in range(grid_count):
            sampled_pixels[x, y] = source_pixels[
                x * SCALE + sample_x,
                y * SCALE + sample_y,
            ]
    return sampled.resize(
        (grid_count * 8, grid_count * 8),
        Image.Resampling.NEAREST,
    )


@pytest.mark.parametrize("split", ["vertical", "horizontal", "diagonal"])
def test_both_sampled_views_decode(split: str) -> None:
    composite = generate_dueling_qr(
        PAYLOAD1,
        PAYLOAD2,
        version=VERSION,
        split=split,
        scale=SCALE,
    )

    for view, payload in enumerate((PAYLOAD1, PAYLOAD2)):
        reconstructed = _sample_view(composite, split, view)
        decoded = zxingcpp.read_barcode(
            reconstructed,
            formats=zxingcpp.BarcodeFormat.QRCode,
            try_invert=False,
            is_pure=True,
        )
        assert decoded is not None
        assert decoded.valid
        assert decoded.text == payload


def test_committed_example_contains_both_payloads() -> None:
    with Image.open(PROJECT_ROOT / "examples" / "dueling-qr.png") as image:
        for view, payload in enumerate(
            (
                "https://example.com",
                "https://github.com/inlanger/photo-dither-qr",
            )
        ):
            reconstructed = _sample_view(image, "vertical", view)
            decoded = zxingcpp.read_barcode(
                reconstructed,
                formats=zxingcpp.BarcodeFormat.QRCode,
                try_invert=False,
                is_pure=True,
            )
            assert decoded is not None
            assert decoded.valid
            assert decoded.text == payload


def test_composite_preserves_function_modules_and_quiet_zone() -> None:
    composite = generate_dueling_qr(
        PAYLOAD1,
        PAYLOAD2,
        version=VERSION,
        mask=3,
        scale=SCALE,
    )
    qr1 = segno.make_qr(
        PAYLOAD1,
        version=VERSION,
        error="H",
        mask=3,
        encoding="utf-8",
        eci=True,
        boost_error=False,
    )
    module_types = _module_types(qr1)
    border = QUIET_ZONE * SCALE
    expected_side = (len(module_types) + 2 * QUIET_ZONE) * SCALE

    assert composite.size == (expected_side, expected_side)
    assert set(composite.get_flattened_data()) == {0, 255}
    assert composite.crop((0, 0, expected_side, border)).getextrema() == (
        255,
        255,
    )
    assert composite.crop((0, 0, border, expected_side)).getextrema() == (
        255,
        255,
    )
    assert composite.crop(
        (0, expected_side - border, expected_side, expected_side)
    ).getextrema() == (255, 255)
    assert composite.crop(
        (expected_side - border, 0, expected_side, expected_side)
    ).getextrema() == (255, 255)

    for module_y, row in enumerate(module_types):
        for module_x, module_type in enumerate(row):
            if module_type in DATA_TYPES:
                continue
            expected = 0 if module_type >> 8 else 255
            left = border + module_x * SCALE
            top = border + module_y * SCALE
            tile = composite.crop(
                (left, top, left + SCALE, top + SCALE)
            )
            assert tile.getextrema() == (expected, expected)


def test_incompatible_masks_report_format_module_problem() -> None:
    qr1 = segno.make_qr(PAYLOAD1, version=VERSION, error="H", mask=0)
    qr2 = segno.make_qr(PAYLOAD2, version=VERSION, error="H", mask=1)

    with pytest.raises(ValueError, match="masks.*format modules"):
        _validate_compatible_function_modules(
            qr1,
            qr2,
            _module_types(qr1),
            _module_types(qr2),
        )


@pytest.mark.parametrize(
    ("option", "value", "message"),
    [
        ("scale", 9, "even"),
        ("scale", 1, "at least 2"),
        ("quiet_zone", 3, "at least 4"),
        ("split", "radial", "split"),
        ("version", 41, "version"),
        ("mask", 8, "mask"),
    ],
)
def test_invalid_options(option: str, value: object, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        generate_dueling_qr(
            PAYLOAD1,
            PAYLOAD2,
            **{option: value},
        )
