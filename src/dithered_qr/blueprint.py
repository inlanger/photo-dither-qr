"""Render CPU-only, Text2QR-inspired QR aesthetic blueprints.

This module implements the published histogram-polarization and adaptive-
halftone stages of Text2QR's QR Aesthetic Blueprint (QAB). The paper does not
specify its module-reorganization algorithm. ``generate_blueprint_qr`` uses a
safe substitute instead: it searches the eight standard QR mask patterns and
keeps the matrix whose data modules best match the guidance image.
"""

from __future__ import annotations

from math import ceil, floor

import segno
from PIL import Image, ImageOps
from segno import consts

QUIET_ZONE_MODULES = 4
_MAX_LEVEL = 255.0
_DATA_MODULE_TYPES = frozenset(
    (consts.TYPE_DATA_LIGHT, consts.TYPE_DATA_DARK)
)

__all__ = ["generate_blueprint_qr", "render_blueprint"]


def generate_blueprint_qr(
    payload: str,
    image: Image.Image,
    *,
    min_version: int = 6,
    error: str = "H",
    mask: int | None = None,
    module_size: int = 16,
    robustness: float = 0.6,
) -> Image.Image:
    """Return a scannable grayscale QR aesthetic blueprint.

    If ``mask`` is ``None``, all eight standard QR mask patterns are scored
    against the polarized guidance image. This image-compatible mask search is
    a standards-preserving substitute for Text2QR's unpublished module
    reorganization; it is not a reproduction of that algorithm.

    ``module_size`` controls the number of output pixels per QR module.
    ``robustness`` is Text2QR's :math:`eta` and must be at least 0.5 and less
    than 1. Function modules are rendered as intact black or white squares,
    and a four-module quiet zone is always added.
    """
    _validate_generation_options(
        payload=payload,
        min_version=min_version,
        error=error,
        mask=mask,
        module_size=module_size,
        robustness=robustness,
    )
    error = error.upper()
    initial_mask = mask if mask is not None else 0
    initial_qr = _encode_payload(
        payload,
        min_version=min_version,
        error=error,
        mask=initial_mask,
    )
    module_count = len(initial_qr.matrix)
    polarized = _prepare_polarized_image(
        image,
        module_count * module_size,
        robustness,
    )

    qr = initial_qr
    if mask is None:
        qr = _select_image_compatible_mask(
            payload,
            polarized,
            version=initial_qr.version,
            error=error,
            module_size=module_size,
        )
    return _render_polarized_blueprint(
        qr,
        polarized,
        module_size=module_size,
        robustness=robustness,
    )


def render_blueprint(
    qr: segno.QRCode,
    image: Image.Image,
    *,
    module_size: int = 16,
    robustness: float = 0.6,
) -> Image.Image:
    """Blend ``image`` into an existing standard Segno QR matrix.

    The QR object's version, error correction level, and mask are preserved.
    Micro QR Codes are rejected because their quiet zone and function layout
    differ from the full QR symbols targeted by QAB.
    """
    _validate_render_options(
        qr=qr,
        module_size=module_size,
        robustness=robustness,
    )
    module_count = len(qr.matrix)
    polarized = _prepare_polarized_image(
        image,
        module_count * module_size,
        robustness,
    )
    return _render_polarized_blueprint(
        qr,
        polarized,
        module_size=module_size,
        robustness=robustness,
    )


def _validate_generation_options(
    *,
    payload: str,
    min_version: int,
    error: str,
    mask: int | None,
    module_size: int,
    robustness: float,
) -> None:
    if not payload:
        raise ValueError("payload must not be empty")
    if not 1 <= min_version <= 40:
        raise ValueError("min_version must be between 1 and 40")
    if error.upper() not in {"L", "M", "Q", "H"}:
        raise ValueError("error must be one of L, M, Q, or H")
    if mask is not None and not 0 <= mask <= 7:
        raise ValueError("mask must be between 0 and 7")
    _validate_common_options(
        module_size=module_size,
        robustness=robustness,
    )


def _validate_render_options(
    *,
    qr: segno.QRCode,
    module_size: int,
    robustness: float,
) -> None:
    if not isinstance(qr, segno.QRCode):
        raise TypeError("qr must be a Segno QRCode")
    if not isinstance(qr.version, int):
        raise ValueError("Micro QR Codes are not supported")
    _validate_common_options(
        module_size=module_size,
        robustness=robustness,
    )


def _validate_common_options(*, module_size: int, robustness: float) -> None:
    if module_size < 4:
        raise ValueError("module_size must be at least 4")
    if not 0.5 <= robustness < 1:
        raise ValueError("robustness must be between 0.5 and 1")


def _encode_payload(
    payload: str,
    *,
    min_version: int,
    error: str,
    mask: int,
) -> segno.QRCode:
    last_error: Exception | None = None
    for version in range(min_version, 41):
        try:
            return _make_qr(
                payload,
                version=version,
                error=error,
                mask=mask,
            )
        except segno.DataOverflowError as exc:
            last_error = exc
    raise ValueError("payload does not fit into a version 40 QR code") from last_error


def _make_qr(
    payload: str,
    *,
    version: int,
    error: str,
    mask: int,
) -> segno.QRCode:
    return segno.make_qr(
        payload,
        error=error,
        version=version,
        mask=mask,
        encoding="utf-8",
        eci=True,
        boost_error=False,
    )


def _select_image_compatible_mask(
    payload: str,
    polarized: Image.Image,
    *,
    version: int,
    error: str,
    module_size: int,
) -> segno.QRCode:
    """Return the closest of Segno's eight standards-compliant matrices."""
    module_means = _module_means(polarized, module_size)
    best_score = float("inf")
    best_qr: segno.QRCode | None = None

    for mask in range(8):
        qr = _make_qr(
            payload,
            version=version,
            error=error,
            mask=mask,
        )
        score = 0.0
        for y, row in enumerate(_module_types(qr)):
            for x, module_type in enumerate(row):
                if module_type not in _DATA_MODULE_TYPES:
                    continue
                target = _module_level(module_type)
                difference = module_means[y][x] - target
                score += difference * difference
        if score < best_score:
            best_score = score
            best_qr = qr

    if best_qr is None:  # pragma: no cover - every full QR has data modules
        raise RuntimeError("could not select a QR mask")
    return best_qr


def _prepare_polarized_image(
    image: Image.Image,
    size: int,
    robustness: float,
) -> Image.Image:
    source = ImageOps.exif_transpose(image).convert("L")
    source = ImageOps.fit(
        source,
        (size, size),
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.5),
    )
    return _histogram_polarize(source, robustness)


def _histogram_polarize(
    image: Image.Image,
    robustness: float,
) -> Image.Image:
    """Apply Text2QR equations 4--6 to an 8-bit luminance image."""
    black_threshold, white_threshold = _thresholds(robustness)
    compressed_range = _MAX_LEVEL - white_threshold + black_threshold
    shift = white_threshold - black_threshold
    pixel_count = image.width * image.height
    cumulative = 0
    lookup: list[int] = []

    for occurrences in image.histogram()[:256]:
        cumulative += occurrences
        equalized = compressed_range * cumulative / pixel_count
        if equalized < black_threshold:
            mapped = floor(equalized)
        else:
            mapped = ceil(equalized + shift)
        lookup.append(min(max(mapped, 0), 255))

    return image.point(lookup)


def _thresholds(robustness: float) -> tuple[float, float]:
    return (
        _MAX_LEVEL * (1.0 - robustness) / 2.0,
        _MAX_LEVEL * (1.0 + robustness) / 2.0,
    )


def _module_types(qr: segno.QRCode) -> tuple[tuple[int, ...], ...]:
    """Isolate Segno's experimental verbose matrix API in one adapter."""
    return tuple(
        tuple(row)
        for row in qr.matrix_iter(scale=1, border=0, verbose=True)
    )


def _module_means(
    image: Image.Image,
    module_size: int,
) -> tuple[tuple[float, ...], ...]:
    module_count = image.width // module_size
    pixels = image.tobytes()
    rows: list[tuple[float, ...]] = []
    module_area = module_size * module_size

    for module_y in range(module_count):
        means: list[float] = []
        top = module_y * module_size
        for module_x in range(module_count):
            left = module_x * module_size
            total = _box_sum(
                pixels,
                image.width,
                left,
                top,
                module_size,
            )
            means.append(total / module_area)
        rows.append(tuple(means))
    return tuple(rows)


def _render_polarized_blueprint(
    qr: segno.QRCode,
    polarized: Image.Image,
    *,
    module_size: int,
    robustness: float,
) -> Image.Image:
    module_types = _module_types(qr)
    pixels = bytearray(polarized.tobytes())
    width = polarized.width
    black_threshold, white_threshold = _thresholds(robustness)

    for module_y, row in enumerate(module_types):
        top = module_y * module_size
        for module_x, module_type in enumerate(row):
            left = module_x * module_size
            target = _module_level(module_type)
            if module_type in _DATA_MODULE_TYPES:
                threshold = (
                    black_threshold if target == 0 else white_threshold
                )
                side = _adaptive_square_size(
                    pixels,
                    width,
                    left,
                    top,
                    module_size,
                    target,
                    threshold,
                )
                offset = (module_size - side) // 2
                _fill_box(
                    pixels,
                    width,
                    left + offset,
                    top + offset,
                    side,
                    target,
                )
            else:
                _fill_box(
                    pixels,
                    width,
                    left,
                    top,
                    module_size,
                    target,
                )

    result = Image.frombytes("L", polarized.size, bytes(pixels))
    return ImageOps.expand(
        result,
        border=QUIET_ZONE_MODULES * module_size,
        fill=255,
    )


def _adaptive_square_size(
    pixels: bytes | bytearray,
    width: int,
    left: int,
    top: int,
    module_size: int,
    target: int,
    threshold: float,
) -> int:
    """Choose the centered square closest to the target module threshold."""
    module_sum = _box_sum(
        pixels,
        width,
        left,
        top,
        module_size,
    )
    module_area = module_size * module_size
    best_side = module_size
    best_distance = float("inf")

    first_side = 2 if module_size % 2 == 0 else 1
    for side in range(first_side, module_size + 1, 2):
        offset = (module_size - side) // 2
        center_sum = _box_sum(
            pixels,
            width,
            left + offset,
            top + offset,
            side,
        )
        candidate_mean = (
            module_sum - center_sum + target * side * side
        ) / module_area
        safe = (
            candidate_mean <= threshold
            if target == 0
            else candidate_mean >= threshold
        )
        if not safe:
            continue
        distance = abs(candidate_mean - threshold)
        if distance < best_distance:
            best_distance = distance
            best_side = side
    return best_side


def _box_sum(
    pixels: bytes | bytearray,
    width: int,
    left: int,
    top: int,
    size: int,
) -> int:
    return sum(
        sum(pixels[y * width + left : y * width + left + size])
        for y in range(top, top + size)
    )


def _fill_box(
    pixels: bytearray,
    width: int,
    left: int,
    top: int,
    size: int,
    value: int,
) -> None:
    row = bytes((value,)) * size
    for y in range(top, top + size):
        start = y * width + left
        pixels[start : start + size] = row


def _module_level(module_type: int) -> int:
    return 0 if module_type >> 8 else 255
