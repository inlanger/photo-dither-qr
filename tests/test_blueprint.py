from __future__ import annotations

import random

import pytest
import segno
import zxingcpp
from PIL import Image
from segno import consts

from dithered_qr.blueprint import (
    QUIET_ZONE_MODULES,
    _histogram_polarize,
    _module_types,
    _thresholds,
    generate_blueprint_qr,
    render_blueprint,
)


DATA_TYPES = {consts.TYPE_DATA_LIGHT, consts.TYPE_DATA_DARK}


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


def test_histogram_polarization_matches_cdf_mapping() -> None:
    source = Image.new("L", (256, 1))
    source.putdata(range(256))

    result = _histogram_polarize(source, robustness=0.6)
    values = list(result.get_flattened_data())
    black_threshold, white_threshold = _thresholds(0.6)

    assert values[0] == 0
    assert values[126] == 50
    assert values[127] == 204
    assert values[255] == 255
    assert values == sorted(values)
    assert all(
        value < black_threshold or value >= white_threshold
        for value in values
    )


def test_existing_qr_function_modules_and_quiet_zone_are_preserved() -> None:
    module_size = 6
    qr = segno.make_qr(
        "https://example.com/blueprint",
        error="H",
        version=5,
        mask=3,
        boost_error=False,
    )
    result = render_blueprint(qr, gradient(), module_size=module_size)
    module_types = _module_types(qr)
    border = QUIET_ZONE_MODULES * module_size

    quiet_zone_strips = (
        result.crop((0, 0, result.width, border)),
        result.crop((0, result.height - border, result.width, result.height)),
        result.crop((0, 0, border, result.height)),
        result.crop((result.width - border, 0, result.width, result.height)),
    )
    assert all(strip.getextrema() == (255, 255) for strip in quiet_zone_strips)
    for module_y, row in enumerate(module_types):
        for module_x, module_type in enumerate(row):
            if module_type in DATA_TYPES:
                continue
            expected = 0 if module_type >> 8 else 255
            left = border + module_x * module_size
            top = border + module_y * module_size
            tile = result.crop(
                (left, top, left + module_size, top + module_size)
            )
            assert tile.getextrema() == (expected, expected)


def test_blueprint_is_deterministic() -> None:
    source = gradient()
    options = {"min_version": 5, "module_size": 8, "robustness": 0.6}

    first = generate_blueprint_qr("deterministic payload", source, **options)
    second = generate_blueprint_qr("deterministic payload", source, **options)

    assert first.mode == second.mode == "L"
    assert first.size == second.size
    assert first.tobytes() == second.tobytes()


def test_blueprint_decodes_with_zxing() -> None:
    payload = "https://example.com/text2qr-inspired-blueprint"
    result = generate_blueprint_qr(
        payload,
        gradient(),
        min_version=5,
        module_size=10,
    )

    decoded = zxingcpp.read_barcode(
        result,
        formats=zxingcpp.BarcodeFormat.QRCode,
        try_invert=False,
        is_pure=False,
    )

    assert decoded is not None
    assert decoded.valid
    assert decoded.text == payload


def test_auto_mask_decodes_adversarial_noise_at_minimum_settings() -> None:
    rng = random.Random(1)
    source = Image.new("L", (64, 64))
    source.putdata([rng.randrange(256) for _ in range(64 * 64)])

    result = generate_blueprint_qr(
        "x",
        source,
        min_version=5,
        module_size=4,
        robustness=0.5,
    )
    decoded = zxingcpp.read_barcode(
        result,
        formats=zxingcpp.BarcodeFormat.QRCode,
        try_invert=False,
        is_pure=False,
    )

    assert decoded is not None
    assert decoded.valid
    assert decoded.text == "x"


@pytest.mark.parametrize("module_size", [4, 5])
def test_every_data_module_reaches_the_safe_side_of_threshold(
    module_size: int,
) -> None:
    source = Image.new("L", (96, 96))
    source.putdata(
        [
            255 if (x + y) % 2 else 0
            for y in range(source.height)
            for x in range(source.width)
        ]
    )
    qr = segno.make_qr(
        "x",
        error="H",
        version=5,
        mask=6,
        boost_error=False,
    )
    result = render_blueprint(qr, source, module_size=module_size)
    module_types = _module_types(qr)
    border = QUIET_ZONE_MODULES * module_size
    black_threshold, white_threshold = _thresholds(0.6)

    for module_y, row in enumerate(module_types):
        for module_x, module_type in enumerate(row):
            if module_type not in DATA_TYPES:
                continue
            left = border + module_x * module_size
            top = border + module_y * module_size
            values = result.crop(
                (left, top, left + module_size, top + module_size)
            ).get_flattened_data()
            mean = sum(values) / (module_size * module_size)
            if module_type >> 8:
                assert mean <= black_threshold
            else:
                assert mean >= white_threshold


@pytest.mark.parametrize(
    ("option", "value", "message"),
    [
        ("module_size", 3, "at least 4"),
        ("robustness", 0.49, "between 0.5 and 1"),
        ("robustness", 1.0, "between 0.5 and 1"),
    ],
)
def test_invalid_blueprint_options(
    option: str, value: object, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        generate_blueprint_qr(
            "x",
            gradient(),
            **{option: value},
        )
