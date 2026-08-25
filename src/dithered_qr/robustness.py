"""Paper-inspired scanner robustness helpers for rendered QR images.

The confidence proxy follows the scanner model described by ART-UP
(https://arxiv.org/abs/1803.02280): a Gaussian distribution for the sampling
position and a normally distributed local binarization threshold.  This
clean-room module is not a faithful implementation of ART-UP and is not an ISO
QR verifier.
"""

from __future__ import annotations

from collections.abc import Sequence
from math import erf, exp, sqrt

from PIL import Image
from segno import consts

from .core import generate_dithered_qr, _encode_payload, _module_types


DEFAULT_BORDER_MODULES = 4
_DATA_MODULE_TYPES = frozenset(
    (consts.TYPE_DATA_LIGHT, consts.TYPE_DATA_DARK)
)

__all__ = [
    "confidence_heatmap",
    "estimate_module_confidence",
    "generate_art_up_qr",
    "repair_low_confidence_modules",
]


def generate_art_up_qr(
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
    target_confidence: float = 0.65,
    max_passes: int | None = None,
) -> Image.Image:
    """Generate a dithered QR and apply ART-UP-inspired local repair.

    The default confidence floor is 0.65, below ART-UP's published 0.75--0.90
    range, because this binary 3x3 renderer otherwise loses most photo detail.
    Raise it when scan margin matters more than resemblance to the source.
    """
    result = generate_dithered_qr(
        payload,
        image,
        min_version=min_version,
        error=error,
        mask=mask,
        subpixels=subpixels,
        pixel_size=pixel_size,
        gamma=gamma,
        contrast=contrast,
        brightness=brightness,
        min_brightness=min_brightness,
        max_brightness=max_brightness,
    )
    qr = _encode_payload(payload, min_version, error.upper(), mask)
    return repair_low_confidence_modules(
        result,
        _module_types(qr),
        subpixels=subpixels,
        target_confidence=target_confidence,
        max_passes=max_passes,
    )


def estimate_module_confidence(
    image: Image.Image,
    module_types: Sequence[Sequence[int]],
    *,
    subpixels: int = 3,
    border_modules: int = DEFAULT_BORDER_MODULES,
    sampling_sigma: float | None = None,
    threshold_sigma: float = 1 / 3,
) -> tuple[tuple[float, ...], ...]:
    """Estimate the probability of correctly sampling every QR module.

    ``image`` must be an unwarped square ``L`` image whose size is an integer
    multiple of the conceptual subpixel grid.  ``sampling_sigma`` is measured
    in subpixels.  The expected threshold is the mean luminance in a square
    neighborhood three QR modules wide; ``threshold_sigma`` is expressed on
    the normalized 0..1 luminance scale.
    """
    matrix, logical_side, _ = _validate_layout(
        image, module_types, subpixels, border_modules
    )
    if sampling_sigma is None:
        sampling_sigma = subpixels / 3
    _validate_model_options(sampling_sigma, threshold_sigma)

    levels = _logical_levels(image, logical_side)
    return _confidence_from_levels(
        levels,
        matrix,
        subpixels,
        border_modules,
        sampling_sigma,
        threshold_sigma,
    )


def confidence_heatmap(
    confidences: Sequence[Sequence[float]], *, scale: int = 8
) -> Image.Image:
    """Render module confidences as a red-to-green nearest-neighbor heatmap."""
    rows = tuple(tuple(row) for row in confidences)
    if not rows or not rows[0] or any(len(row) != len(rows[0]) for row in rows):
        raise ValueError("confidences must be a non-empty rectangular grid")
    if scale < 1:
        raise ValueError("scale must be at least 1")

    pixels: list[tuple[int, int, int]] = []
    for row in rows:
        for value in row:
            if not 0 <= value <= 1:
                raise ValueError("confidence values must be between 0 and 1")
            red = round(255 * (1 - value))
            green = round(255 * value)
            pixels.append((red, green, 0))

    heatmap = Image.new("RGB", (len(rows[0]), len(rows)))
    heatmap.putdata(pixels)
    if scale != 1:
        heatmap = heatmap.resize(
            (heatmap.width * scale, heatmap.height * scale),
            Image.Resampling.NEAREST,
        )
    return heatmap


def repair_low_confidence_modules(
    image: Image.Image,
    module_types: Sequence[Sequence[int]],
    *,
    subpixels: int = 3,
    border_modules: int = DEFAULT_BORDER_MODULES,
    target_confidence: float = 0.65,
    max_passes: int | None = None,
    sampling_sigma: float | None = None,
    threshold_sigma: float = 1 / 3,
) -> Image.Image:
    """Return a copy with weak data modules locally repaired.

    Each pass recomputes local thresholds, then moves at most one free
    subpixel per weak data module to the module's required luminance.  The
    highest Gaussian sampling weight is repaired first.  Center subpixels,
    function modules, and the quiet zone are never written.
    """
    matrix, logical_side, pixel_scale = _validate_layout(
        image, module_types, subpixels, border_modules
    )
    if not 0 <= target_confidence <= 1:
        raise ValueError("target_confidence must be between 0 and 1")
    if max_passes is None:
        max_passes = subpixels * subpixels - 1
    if max_passes < 0:
        raise ValueError("max_passes must not be negative")
    if sampling_sigma is None:
        sampling_sigma = subpixels / 3
    _validate_model_options(sampling_sigma, threshold_sigma)

    output = image.copy()
    levels = _logical_levels(output, logical_side)
    center = subpixels // 2
    offset = border_modules * subpixels

    for _ in range(max_passes):
        confidences = _confidence_from_levels(
            levels,
            matrix,
            subpixels,
            border_modules,
            sampling_sigma,
            threshold_sigma,
        )
        changed = False

        for module_y, row in enumerate(matrix):
            for module_x, module_type in enumerate(row):
                if (
                    module_type not in _DATA_MODULE_TYPES
                    or confidences[module_y][module_x] >= target_confidence
                ):
                    continue

                target = 0.0 if module_type >> 8 else 1.0
                candidate = _repair_candidate(
                    levels,
                    module_x,
                    module_y,
                    subpixels,
                    offset,
                    center,
                    target,
                )
                if candidate is None:
                    continue

                logical_x, logical_y = candidate
                levels[logical_y][logical_x] = target
                left = logical_x * pixel_scale
                top = logical_y * pixel_scale
                output.paste(
                    round(target * 255),
                    (
                        left,
                        top,
                        left + pixel_scale,
                        top + pixel_scale,
                    ),
                )
                changed = True

        if not changed:
            break

    return output


def _validate_layout(
    image: Image.Image,
    module_types: Sequence[Sequence[int]],
    subpixels: int,
    border_modules: int,
) -> tuple[tuple[tuple[int, ...], ...], int, int]:
    matrix = tuple(tuple(row) for row in module_types)
    if not matrix or any(len(row) != len(matrix) for row in matrix):
        raise ValueError("module_types must be a non-empty square matrix")
    if subpixels < 3 or subpixels % 2 == 0:
        raise ValueError("subpixels must be an odd integer of at least 3")
    if border_modules < 0:
        raise ValueError("border_modules must not be negative")
    if image.mode != "L":
        raise ValueError("image must use Pillow mode L")
    if image.width != image.height:
        raise ValueError("image must be square")

    logical_side = (len(matrix) + 2 * border_modules) * subpixels
    if image.width % logical_side:
        raise ValueError("image size must align with the subpixel grid")
    return matrix, logical_side, image.width // logical_side


def _validate_model_options(
    sampling_sigma: float, threshold_sigma: float
) -> None:
    if sampling_sigma <= 0:
        raise ValueError("sampling_sigma must be greater than 0")
    if threshold_sigma <= 0:
        raise ValueError("threshold_sigma must be greater than 0")


def _logical_levels(image: Image.Image, logical_side: int) -> list[list[float]]:
    sampled = image.resize(
        (logical_side, logical_side), Image.Resampling.BOX
    )
    flat = iter(sampled.get_flattened_data())
    return [
        [next(flat) / 255.0 for _ in range(logical_side)]
        for _ in range(logical_side)
    ]


def _confidence_from_levels(
    levels: Sequence[Sequence[float]],
    module_types: Sequence[Sequence[int]],
    subpixels: int,
    border_modules: int,
    sampling_sigma: float,
    threshold_sigma: float,
) -> tuple[tuple[float, ...], ...]:
    thresholds = _local_thresholds(levels, subpixels)
    weights = _sampling_weights(subpixels, sampling_sigma)
    offset = border_modules * subpixels
    result: list[tuple[float, ...]] = []

    for module_y, row in enumerate(module_types):
        scores: list[float] = []
        for module_x, module_type in enumerate(row):
            target_is_light = not bool(module_type >> 8)
            origin_x = offset + module_x * subpixels
            origin_y = offset + module_y * subpixels
            confidence = 0.0
            for sub_y in range(subpixels):
                for sub_x in range(subpixels):
                    x = origin_x + sub_x
                    y = origin_y + sub_y
                    confidence += weights[sub_y][sub_x] * _correct_probability(
                        levels[y][x],
                        thresholds[y][x],
                        threshold_sigma,
                        target_is_light,
                    )
            scores.append(min(max(confidence, 0.0), 1.0))
        result.append(tuple(scores))
    return tuple(result)


def _sampling_weights(
    subpixels: int, sigma: float
) -> tuple[tuple[float, ...], ...]:
    center = (subpixels - 1) / 2
    unscaled = [
        [
            exp(-((x - center) ** 2 + (y - center) ** 2) / (2 * sigma**2))
            for x in range(subpixels)
        ]
        for y in range(subpixels)
    ]
    total = sum(sum(row) for row in unscaled)
    return tuple(tuple(value / total for value in row) for row in unscaled)


def _local_thresholds(
    levels: Sequence[Sequence[float]], subpixels: int
) -> list[list[float]]:
    side = len(levels)
    integral = [[0.0] * (side + 1) for _ in range(side + 1)]
    for y, row in enumerate(levels):
        running = 0.0
        for x, value in enumerate(row):
            running += value
            integral[y + 1][x + 1] = integral[y][x + 1] + running

    radius = (3 * subpixels) // 2
    thresholds = [[0.0] * side for _ in range(side)]
    for y in range(side):
        top = max(0, y - radius)
        bottom = min(side, y + radius + 1)
        for x in range(side):
            left = max(0, x - radius)
            right = min(side, x + radius + 1)
            total = (
                integral[bottom][right]
                - integral[top][right]
                - integral[bottom][left]
                + integral[top][left]
            )
            thresholds[y][x] = total / ((right - left) * (bottom - top))
    return thresholds


def _correct_probability(
    luminance: float,
    expected_threshold: float,
    sigma: float,
    target_is_light: bool,
) -> float:
    low = _normal_cdf(-expected_threshold / sigma)
    high = _normal_cdf((1 - expected_threshold) / sigma)
    if high == low:
        if luminance == expected_threshold:
            return 0.5
        sampled_as_light = luminance > expected_threshold
        return float(sampled_as_light == target_is_light)
    below_sample = (
        _normal_cdf((luminance - expected_threshold) / sigma) - low
    ) / (high - low)
    probability = below_sample if target_is_light else 1 - below_sample
    return min(max(probability, 0.0), 1.0)


def _normal_cdf(value: float) -> float:
    return 0.5 * (1 + erf(value / sqrt(2)))


def _repair_candidate(
    levels: Sequence[Sequence[float]],
    module_x: int,
    module_y: int,
    subpixels: int,
    offset: int,
    center: int,
    target: float,
) -> tuple[int, int] | None:
    origin_x = offset + module_x * subpixels
    origin_y = offset + module_y * subpixels
    candidates: list[tuple[float, float, int, int]] = []

    for sub_y in range(subpixels):
        for sub_x in range(subpixels):
            if sub_x == center and sub_y == center:
                continue
            logical_x = origin_x + sub_x
            logical_y = origin_y + sub_y
            adjustment = abs(target - levels[logical_y][logical_x])
            if adjustment == 0:
                continue
            distance = (sub_x - center) ** 2 + (sub_y - center) ** 2
            candidates.append(
                (distance, adjustment, logical_y, logical_x)
            )

    if not candidates:
        return None
    _, _, logical_y, logical_x = min(candidates)
    return logical_x, logical_y
