"""Generate QR codes whose free subpixels form a dithered image."""

from __future__ import annotations

from collections.abc import Sequence

import segno
from PIL import Image, ImageOps
from segno import consts

QUIET_ZONE_MODULES = 4
_DATA_MODULE_TYPES = frozenset(
    (consts.TYPE_DATA_LIGHT, consts.TYPE_DATA_DARK)
)


def generate_dithered_qr(
    payload: str,
    image: Image.Image,
    *,
    min_version: int = 6,
    error: str = "H",
    mask: int | None = None,
    subpixels: int = 3,
    pixel_size: int = 4,
    gamma: float = 2.2,
    contrast: float = 1.0,
    brightness: float = 0.0,
    min_brightness: float = 0.05,
    max_brightness: float = 0.95,
) -> Image.Image:
    """Return a scannable monochrome QR code containing ``image``.

    ``subpixels`` is the odd number of image pixels placed along each QR
    module. The module's center pixel stores the original QR value.
    ``pixel_size`` enlarges each final binary pixel without interpolation.
    """
    _validate_options(
        payload=payload,
        min_version=min_version,
        error=error,
        mask=mask,
        subpixels=subpixels,
        pixel_size=pixel_size,
        gamma=gamma,
        contrast=contrast,
        min_brightness=min_brightness,
        max_brightness=max_brightness,
    )

    qr = _encode_payload(payload, min_version, error.upper(), mask)
    module_types = _module_types(qr)
    module_count = len(module_types)
    canvas_size = module_count * subpixels
    levels = _prepare_image(
        image,
        canvas_size,
        gamma=gamma,
        contrast=contrast,
        brightness=brightness,
        min_brightness=min_brightness,
        max_brightness=max_brightness,
    )

    _diffuse_forced_centers(levels, module_types, subpixels)
    _dither_free_pixels(levels, module_types, subpixels)
    result = _render(levels, module_types, subpixels)

    border = QUIET_ZONE_MODULES * subpixels
    result = ImageOps.expand(result, border=border, fill=255)
    if pixel_size != 1:
        result = result.resize(
            (result.width * pixel_size, result.height * pixel_size),
            Image.Resampling.NEAREST,
        )
    return result


def _validate_options(
    *,
    payload: str,
    min_version: int,
    error: str,
    mask: int | None,
    subpixels: int,
    pixel_size: int,
    gamma: float,
    contrast: float,
    min_brightness: float,
    max_brightness: float,
) -> None:
    if not payload:
        raise ValueError("payload must not be empty")
    if not 1 <= min_version <= 40:
        raise ValueError("min_version must be between 1 and 40")
    if error.upper() not in {"L", "M", "Q", "H"}:
        raise ValueError("error must be one of L, M, Q, or H")
    if mask is not None and not 0 <= mask <= 7:
        raise ValueError("mask must be between 0 and 7")
    if subpixels < 3 or subpixels % 2 == 0:
        raise ValueError("subpixels must be an odd integer of at least 3")
    if pixel_size < 1:
        raise ValueError("pixel_size must be at least 1")
    if gamma <= 0:
        raise ValueError("gamma must be greater than 0")
    if contrast <= 0:
        raise ValueError("contrast must be greater than 0")
    if not 0 <= min_brightness < max_brightness <= 1:
        raise ValueError(
            "brightness limits must satisfy 0 <= min < max <= 1"
        )


def _encode_payload(
    payload: str,
    min_version: int,
    error: str,
    mask: int | None,
):
    last_error: Exception | None = None
    for version in range(min_version, 41):
        try:
            return segno.make_qr(
                payload,
                error=error,
                version=version,
                mask=mask,
                encoding="utf-8",
                eci=True,
                boost_error=False,
            )
        except segno.DataOverflowError as exc:
            last_error = exc
    raise ValueError("payload does not fit into a version 40 QR code") from last_error


def _module_types(qr) -> tuple[tuple[int, ...], ...]:
    """Isolate Segno's experimental verbose matrix API in one adapter."""
    return tuple(
        tuple(row)
        for row in qr.matrix_iter(scale=1, border=0, verbose=True)
    )


def _prepare_image(
    image: Image.Image,
    size: int,
    *,
    gamma: float,
    contrast: float,
    brightness: float,
    min_brightness: float,
    max_brightness: float,
) -> list[list[float]]:
    source = ImageOps.exif_transpose(image).convert("L")
    source = ImageOps.fit(
        source,
        (size, size),
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.5),
    )

    values: list[list[float]] = []
    flat = iter(source.get_flattened_data())
    for _ in range(size):
        row: list[float] = []
        for _ in range(size):
            value = next(flat) / 255.0
            value = (value**gamma - 0.5) * contrast + brightness + 0.5
            row.append(min(max(value, min_brightness), max_brightness))
        values.append(row)
    return values


def _diffuse_forced_centers(
    levels: list[list[float]],
    module_types: Sequence[Sequence[int]],
    subpixels: int,
) -> None:
    center = subpixels // 2
    neighbors = (
        (-1, -1, 1 / 16),
        (0, -1, 3 / 16),
        (1, -1, 1 / 16),
        (-1, 0, 3 / 16),
        (1, 0, 3 / 16),
        (-1, 1, 1 / 16),
        (0, 1, 3 / 16),
        (1, 1, 1 / 16),
    )

    for module_y, row in enumerate(module_types):
        for module_x, module_type in enumerate(row):
            if module_type not in _DATA_MODULE_TYPES:
                continue
            x = module_x * subpixels + center
            y = module_y * subpixels + center
            target = _module_brightness(module_type)
            error = levels[y][x] - target
            levels[y][x] = target
            for dx, dy, weight in neighbors:
                levels[y + dy][x + dx] += error * weight


def _dither_free_pixels(
    levels: list[list[float]],
    module_types: Sequence[Sequence[int]],
    subpixels: int,
) -> None:
    size = len(levels)
    candidates = ((1, 0, 7), (-1, 1, 3), (0, 1, 5), (1, 1, 1))

    for y in range(size):
        for x in range(size):
            if not _is_free_pixel(x, y, module_types, subpixels):
                continue
            actual = 1.0 if levels[y][x] >= 0.5 else 0.0
            error = levels[y][x] - actual
            levels[y][x] = actual

            available = [
                (x + dx, y + dy, weight)
                for dx, dy, weight in candidates
                if _is_free_pixel(x + dx, y + dy, module_types, subpixels)
            ]
            total_weight = sum(weight for _, _, weight in available)
            if total_weight:
                for target_x, target_y, weight in available:
                    levels[target_y][target_x] += error * weight / total_weight


def _is_free_pixel(
    x: int,
    y: int,
    module_types: Sequence[Sequence[int]],
    subpixels: int,
) -> bool:
    size = len(module_types) * subpixels
    if x < 0 or y < 0 or x >= size or y >= size:
        return False
    module_type = module_types[y // subpixels][x // subpixels]
    if module_type not in _DATA_MODULE_TYPES:
        return False
    center = subpixels // 2
    return x % subpixels != center or y % subpixels != center


def _render(
    levels: Sequence[Sequence[float]],
    module_types: Sequence[Sequence[int]],
    subpixels: int,
) -> Image.Image:
    size = len(levels)
    center = subpixels // 2
    pixels: list[int] = []

    for y in range(size):
        for x in range(size):
            module_type = module_types[y // subpixels][x // subpixels]
            forced = (
                module_type not in _DATA_MODULE_TYPES
                or (x % subpixels == center and y % subpixels == center)
            )
            if forced:
                value = _module_brightness(module_type)
            else:
                value = levels[y][x]
            pixels.append(255 if value >= 0.5 else 0)

    result = Image.new("L", (size, size))
    result.putdata(pixels)
    return result


def _module_brightness(module_type: int) -> float:
    return 0.0 if module_type >> 8 else 1.0
