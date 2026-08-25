from __future__ import annotations

import zxingcpp
from PIL import Image
from segno import consts

from dithered_qr import generate_dithered_qr
from dithered_qr.core import QUIET_ZONE_MODULES, _encode_payload, _module_types
from dithered_qr.robustness import (
    confidence_heatmap,
    estimate_module_confidence,
    generate_art_up_qr,
    repair_low_confidence_modules,
)


DATA_TYPES = {consts.TYPE_DATA_LIGHT, consts.TYPE_DATA_DARK}


def test_confidence_grid_and_heatmap_match_qr_geometry() -> None:
    payload = "https://example.com/art-up"
    qr = _encode_payload(payload, 6, "H", 0)
    module_types = _module_types(qr)
    image = generate_dithered_qr(
        payload,
        Image.new("L", (80, 80), 128),
        min_version=6,
        error="H",
        mask=0,
        subpixels=3,
        pixel_size=2,
    )

    confidences = estimate_module_confidence(image, module_types)
    heatmap = confidence_heatmap(confidences, scale=3)

    assert len(confidences) == len(module_types)
    assert all(len(row) == len(module_types) for row in confidences)
    assert all(0 <= value <= 1 for row in confidences for value in row)
    assert heatmap.mode == "RGB"
    assert heatmap.size == (len(module_types) * 3, len(module_types) * 3)


def test_local_threshold_changes_gray_sample_confidence() -> None:
    subpixels = 3
    border_modules = QUIET_ZONE_MODULES
    side = (1 + 2 * border_modules) * subpixels
    module_box = (
        border_modules * subpixels,
        border_modules * subpixels,
        (border_modules + 1) * subpixels,
        (border_modules + 1) * subpixels,
    )
    dark_surroundings = Image.new("L", (side, side), 0)
    light_surroundings = Image.new("L", (side, side), 255)
    dark_surroundings.paste(160, module_box)
    light_surroundings.paste(160, module_box)
    module_types = ((consts.TYPE_DATA_LIGHT,),)

    dark_score = estimate_module_confidence(
        dark_surroundings, module_types
    )[0][0]
    light_score = estimate_module_confidence(
        light_surroundings, module_types
    )[0][0]

    assert dark_score > light_score + 0.5


def test_gaussian_sampling_gives_the_module_center_more_weight() -> None:
    subpixels = 3
    border = QUIET_ZONE_MODULES * subpixels
    side = (1 + 2 * QUIET_ZONE_MODULES) * subpixels
    center_sample = Image.new("L", (side, side), 0)
    corner_sample = Image.new("L", (side, side), 0)
    center_sample.putpixel((border + 1, border + 1), 255)
    corner_sample.putpixel((border, border), 255)
    module_types = ((consts.TYPE_DATA_LIGHT,),)

    center_score = estimate_module_confidence(
        center_sample, module_types
    )[0][0]
    corner_score = estimate_module_confidence(
        corner_sample, module_types
    )[0][0]

    assert center_score > corner_score * 2


def test_repair_improves_confidence_preserves_function_modules_and_decodes() -> None:
    payload = "https://example.com/art-up-repair"
    subpixels = 3
    pixel_size = 2
    qr = _encode_payload(payload, 6, "H", 0)
    module_types = _module_types(qr)
    generated = generate_dithered_qr(
        payload,
        Image.new("L", (96, 64), 128),
        min_version=6,
        error="H",
        mask=0,
        subpixels=subpixels,
        pixel_size=pixel_size,
    )
    weakened = _weaken_free_subpixels(
        generated, module_types, subpixels, pixel_size
    )
    before = estimate_module_confidence(
        weakened, module_types, subpixels=subpixels
    )
    weakened_bytes = weakened.tobytes()

    repaired = repair_low_confidence_modules(
        weakened,
        module_types,
        subpixels=subpixels,
        target_confidence=0.9,
    )
    after = estimate_module_confidence(
        repaired, module_types, subpixels=subpixels
    )

    before_mean = _data_mean(before, module_types)
    after_mean = _data_mean(after, module_types)
    assert weakened.tobytes() == weakened_bytes
    assert after_mean > before_mean + 0.5
    assert min(
        after[y][x]
        for y, row in enumerate(module_types)
        for x, module_type in enumerate(row)
        if module_type in DATA_TYPES
    ) >= 0.9
    _assert_protected_pixels_unchanged(
        weakened, repaired, module_types, subpixels, pixel_size
    )

    decoded = zxingcpp.read_barcode(
        repaired,
        formats=zxingcpp.BarcodeFormat.QRCode,
        try_invert=False,
        is_pure=False,
    )
    assert decoded is not None
    assert decoded.valid
    assert decoded.text == payload


def test_art_up_generator_decodes() -> None:
    payload = "https://example.com/art-up-generator"
    source = Image.new("L", (120, 80), 128)
    qr = _encode_payload(payload, 6, "H", 2)
    module_types = _module_types(qr)
    baseline = generate_dithered_qr(
        payload,
        source,
        min_version=6,
        mask=2,
    )

    result = generate_art_up_qr(
        payload,
        source,
        min_version=6,
        mask=2,
    )

    assert source.getextrema() == (128, 128)
    assert result.tobytes() != baseline.tobytes()
    confidences = estimate_module_confidence(result, module_types)
    assert min(
        confidences[y][x]
        for y, row in enumerate(module_types)
        for x, module_type in enumerate(row)
        if module_type in DATA_TYPES
    ) >= 0.65
    decoded = zxingcpp.read_barcode(
        result,
        formats=zxingcpp.BarcodeFormat.QRCode,
        try_invert=False,
        is_pure=False,
    )
    assert decoded is not None
    assert decoded.valid
    assert decoded.text == payload


def _weaken_free_subpixels(
    image: Image.Image,
    module_types: tuple[tuple[int, ...], ...],
    subpixels: int,
    pixel_size: int,
) -> Image.Image:
    weakened = image.copy()
    center = subpixels // 2
    border = QUIET_ZONE_MODULES * subpixels

    for module_y, row in enumerate(module_types):
        for module_x, module_type in enumerate(row):
            if module_type not in DATA_TYPES:
                continue
            wrong = 255 if module_type >> 8 else 0
            for sub_y in range(subpixels):
                for sub_x in range(subpixels):
                    if sub_x == center and sub_y == center:
                        continue
                    logical_x = border + module_x * subpixels + sub_x
                    logical_y = border + module_y * subpixels + sub_y
                    left = logical_x * pixel_size
                    top = logical_y * pixel_size
                    weakened.paste(
                        wrong,
                        (
                            left,
                            top,
                            left + pixel_size,
                            top + pixel_size,
                        ),
                    )
    return weakened


def _data_mean(
    confidences: tuple[tuple[float, ...], ...],
    module_types: tuple[tuple[int, ...], ...],
) -> float:
    values = [
        confidences[y][x]
        for y, row in enumerate(module_types)
        for x, module_type in enumerate(row)
        if module_type in DATA_TYPES
    ]
    return sum(values) / len(values)


def _assert_protected_pixels_unchanged(
    before: Image.Image,
    after: Image.Image,
    module_types: tuple[tuple[int, ...], ...],
    subpixels: int,
    pixel_size: int,
) -> None:
    border = QUIET_ZONE_MODULES * subpixels * pixel_size
    tile_size = subpixels * pixel_size
    center = subpixels // 2
    quiet_zone_boxes = (
        (0, 0, before.width, border),
        (0, before.height - border, before.width, before.height),
        (0, border, border, before.height - border),
        (before.width - border, border, before.width, before.height - border),
    )
    for box in quiet_zone_boxes:
        assert before.crop(box).tobytes() == after.crop(box).tobytes()

    for module_y, row in enumerate(module_types):
        for module_x, module_type in enumerate(row):
            left = border + module_x * tile_size
            top = border + module_y * tile_size
            if module_type in DATA_TYPES:
                center_left = left + center * pixel_size
                center_top = top + center * pixel_size
                box = (
                    center_left,
                    center_top,
                    center_left + pixel_size,
                    center_top + pixel_size,
                )
            else:
                box = (left, top, left + tile_size, top + tile_size)
            assert before.crop(box).tobytes() == after.crop(box).tobytes()
