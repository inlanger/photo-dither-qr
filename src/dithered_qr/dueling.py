"""Generate the angle-dependent dual-message QR construction.

The implementation follows the half-module construction described in
``Dueling QR Codes: The Hyding of Dr. Jeckyl`` (arXiv:2503.13458).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

import segno
from PIL import Image
from segno import consts

from .core import QUIET_ZONE_MODULES, _module_types

Split = Literal["vertical", "horizontal", "diagonal"]

_DATA_MODULE_TYPES = frozenset(
    (consts.TYPE_DATA_LIGHT, consts.TYPE_DATA_DARK)
)
_MODULE_KIND_NAMES = {
    consts.TYPE_DARKMODULE >> 8: "dark",
    consts.TYPE_FINDER_PATTERN_LIGHT: "finder",
    consts.TYPE_SEPARATOR: "separator",
    consts.TYPE_ALIGNMENT_PATTERN_LIGHT: "alignment",
    consts.TYPE_TIMING_LIGHT: "timing",
    consts.TYPE_FORMAT_LIGHT: "format",
    consts.TYPE_VERSION_LIGHT: "version",
}

__all__ = ["generate_dueling_qr"]


def generate_dueling_qr(
    payload1: str,
    payload2: str,
    *,
    version: int = 7,
    error: str = "H",
    mask: int | None = None,
    split: Split = "vertical",
    scale: int = 10,
    quiet_zone: int = QUIET_ZONE_MODULES,
) -> Image.Image:
    """Return one QR image containing two angle-selected payloads.

    Both payloads use the same QR version, error-correction level, and data
    mask. Every function module is copied intact; only data modules are split.
    A ``vertical`` split places ``payload1`` on the left and ``payload2`` on
    the right. A ``horizontal`` split places them at the top and bottom. A
    ``diagonal`` split places them toward the top-left and bottom-right.

    ``scale`` is the number of output pixels (subpixels) per QR module. It
    must be even so the two views occupy equal halves. The paper reports
    physical-camera results at 9--11 pixels per module; consequently the
    default of 10 is the only clean even split inside its tested range.

    A straight-on scan is intentionally ambiguous and can fail or return
    either payload. Camera, print, distance, and viewing angle reliability
    cannot be inferred from successful digital reconstruction of each view.
    """
    _validate_options(
        payload1=payload1,
        payload2=payload2,
        version=version,
        error=error,
        mask=mask,
        split=split,
        scale=scale,
        quiet_zone=quiet_zone,
    )

    normalized_error = error.upper()
    qr1, qr2 = _encode_pair(
        payload1,
        payload2,
        version=version,
        error=normalized_error,
        mask=mask,
    )
    module_types1 = _module_types(qr1)
    module_types2 = _module_types(qr2)
    _validate_compatible_function_modules(
        qr1, qr2, module_types1, module_types2
    )
    return _render_dueling(
        module_types1,
        module_types2,
        split=split,
        scale=scale,
        quiet_zone=quiet_zone,
    )


def _validate_options(
    *,
    payload1: str,
    payload2: str,
    version: int,
    error: str,
    mask: int | None,
    split: str,
    scale: int,
    quiet_zone: int,
) -> None:
    if not isinstance(payload1, str) or not payload1:
        raise ValueError("payload1 must be a non-empty string")
    if not isinstance(payload2, str) or not payload2:
        raise ValueError("payload2 must be a non-empty string")
    if isinstance(version, bool) or not isinstance(version, int):
        raise ValueError("version must be an integer between 1 and 40")
    if not 1 <= version <= 40:
        raise ValueError("version must be between 1 and 40")
    if not isinstance(error, str) or error.upper() not in {"L", "M", "Q", "H"}:
        raise ValueError("error must be one of L, M, Q, or H")
    if mask is not None and (
        isinstance(mask, bool) or not isinstance(mask, int) or not 0 <= mask <= 7
    ):
        raise ValueError("mask must be between 0 and 7")
    if split not in {"vertical", "horizontal", "diagonal"}:
        raise ValueError(
            "split must be vertical, horizontal, or diagonal"
        )
    if isinstance(scale, bool) or not isinstance(scale, int):
        raise ValueError("scale must be an even integer of at least 2")
    if scale < 2 or scale % 2:
        raise ValueError("scale must be an even integer of at least 2")
    if isinstance(quiet_zone, bool) or not isinstance(quiet_zone, int):
        raise ValueError("quiet_zone must be an integer of at least 4")
    if quiet_zone < QUIET_ZONE_MODULES:
        raise ValueError("quiet_zone must be at least 4 modules")


def _encode_pair(
    payload1: str,
    payload2: str,
    *,
    version: int,
    error: str,
    mask: int | None,
):
    qr1 = _encode_payload(
        payload1,
        label="payload1",
        version=version,
        error=error,
        mask=mask,
    )
    shared_mask = qr1.mask if mask is None else mask
    qr2 = _encode_payload(
        payload2,
        label="payload2",
        version=version,
        error=error,
        mask=shared_mask,
    )
    return qr1, qr2


def _encode_payload(
    payload: str,
    *,
    label: str,
    version: int,
    error: str,
    mask: int | None,
):
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
        raise ValueError(
            f"{label} does not fit QR version {version} at error level {error}"
        ) from exc


def _validate_compatible_function_modules(
    qr1,
    qr2,
    module_types1: Sequence[Sequence[int]],
    module_types2: Sequence[Sequence[int]],
) -> None:
    if qr1.version != qr2.version or len(module_types1) != len(module_types2):
        raise ValueError(
            "QR versions are incompatible; both views require the same module grid"
        )
    if qr1.error != qr2.error:
        raise ValueError(
            "QR error levels are incompatible; format modules would differ"
        )
    if qr1.mask != qr2.mask:
        raise ValueError(
            "QR masks are incompatible; format modules would describe the wrong data mask"
        )

    for y, (row1, row2) in enumerate(zip(module_types1, module_types2)):
        if len(row1) != len(row2):
            raise ValueError(
                "QR versions are incompatible; both views require the same module grid"
            )
        for x, (module_type1, module_type2) in enumerate(zip(row1, row2)):
            data1 = module_type1 in _DATA_MODULE_TYPES
            data2 = module_type2 in _DATA_MODULE_TYPES
            if data1 != data2:
                raise ValueError(
                    f"QR function-module layouts differ at ({x}, {y})"
                )
            if data1:
                continue
            kind1 = _module_kind(module_type1)
            kind2 = _module_kind(module_type2)
            if kind1 != kind2 or _is_dark(module_type1) != _is_dark(module_type2):
                kind = _MODULE_KIND_NAMES.get(kind1, "function")
                raise ValueError(
                    f"incompatible {kind} module at ({x}, {y}); "
                    "both QR views must have identical function modules"
                )


def _render_dueling(
    module_types1: Sequence[Sequence[int]],
    module_types2: Sequence[Sequence[int]],
    *,
    split: Split,
    scale: int,
    quiet_zone: int,
) -> Image.Image:
    module_count = len(module_types1)
    side = (module_count + 2 * quiet_zone) * scale
    result = Image.new("L", (side, side), 255)
    pixels = result.load()
    offset = quiet_zone * scale

    for module_y, (row1, row2) in enumerate(
        zip(module_types1, module_types2)
    ):
        top = offset + module_y * scale
        for module_x, (module_type1, module_type2) in enumerate(
            zip(row1, row2)
        ):
            left = offset + module_x * scale
            if module_type1 not in _DATA_MODULE_TYPES:
                value = 0 if _is_dark(module_type1) else 255
                for sub_y in range(scale):
                    for sub_x in range(scale):
                        pixels[left + sub_x, top + sub_y] = value
                continue

            value1 = 0 if _is_dark(module_type1) else 255
            value2 = 0 if _is_dark(module_type2) else 255
            for sub_y in range(scale):
                for sub_x in range(scale):
                    value = (
                        value1
                        if _belongs_to_first_half(
                            split, sub_x, sub_y, scale
                        )
                        else value2
                    )
                    pixels[left + sub_x, top + sub_y] = value

    return result


def _belongs_to_first_half(
    split: Split,
    sub_x: int,
    sub_y: int,
    scale: int,
) -> bool:
    half = scale // 2
    if split == "vertical":
        return sub_x < half
    if split == "horizontal":
        return sub_y < half

    diagonal_distance = sub_x + sub_y + 1 - scale
    if diagonal_distance:
        return diagonal_distance < 0
    # Pixel centers exactly on the diagonal are divided evenly between views.
    return sub_x % 2 == 0


def _module_kind(module_type: int) -> int:
    return module_type >> 8 if module_type >> 8 else module_type


def _is_dark(module_type: int) -> bool:
    return bool(module_type >> 8)
