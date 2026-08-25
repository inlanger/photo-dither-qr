"""Command-line interface for dithered-qr."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from PIL import Image

from .blueprint import generate_blueprint_qr
from .core import generate_dithered_qr, _encode_payload, _module_types
from .dueling import generate_dueling_qr
from .robustness import (
    confidence_heatmap,
    estimate_module_confidence,
    generate_art_up_qr,
)

_IMAGE_GRID_OPTIONS = frozenset(
    {
        "--subpixels",
        "--pixel-size",
        "--gamma",
        "--contrast",
        "--brightness",
        "--min-brightness",
        "--max-brightness",
    }
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dithered-qr",
        description="Blend an image into a scannable QR code.",
        epilog=(
            "Dual-message mode:\n"
            "  dithered-qr duel FIRST_PAYLOAD SECOND_PAYLOAD -o dual.png"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        allow_abbrev=False,
    )
    parser.add_argument("image", type=Path, help="source image")
    parser.add_argument("payload", help="text or URL encoded in the QR code")
    parser.add_argument("-o", "--output", type=Path, required=True, help="output PNG")
    parser.add_argument("--min-version", type=int, default=6, help="minimum QR version (1-40)")
    parser.add_argument("--error", choices=("L", "M", "Q", "H"), default="H", help="error correction level")
    parser.add_argument("--mask", type=int, choices=range(8), help="QR mask (0-7); default: automatic")
    parser.add_argument("--subpixels", type=int, default=3, help="odd image grid size per QR module")
    parser.add_argument("--pixel-size", type=int, default=4, help="output pixels per dithered subpixel")
    parser.add_argument("--gamma", type=float, default=2.2)
    parser.add_argument("--contrast", type=float, default=1.0)
    parser.add_argument("--brightness", type=float, default=0.0)
    parser.add_argument("--min-brightness", type=float, default=0.05)
    parser.add_argument("--max-brightness", type=float, default=0.95)
    parser.add_argument(
        "--method",
        choices=("dither", "art-up", "blueprint"),
        default="dither",
        help="rendering method (default: dither)",
    )
    parser.add_argument(
        "--strength",
        type=float,
        help="confidence floor for art-up or robustness for blueprint",
    )
    parser.add_argument(
        "--module-size",
        type=int,
        default=16,
        help="pixels per module in blueprint mode (default: 16)",
    )
    parser.add_argument(
        "--heatmap",
        type=Path,
        help="write an ART-UP module-confidence heatmap",
    )
    return parser


def build_duel_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dithered-qr duel",
        description="Create an experimental angle-dependent two-payload QR.",
        allow_abbrev=False,
    )
    parser.add_argument("payload1", help="payload sampled from the first half")
    parser.add_argument("payload2", help="payload sampled from the second half")
    parser.add_argument("-o", "--output", type=Path, required=True, help="output PNG")
    parser.add_argument("--version", type=int, default=7, help="fixed QR version")
    parser.add_argument(
        "--error",
        choices=("L", "M", "Q", "H"),
        default="H",
        help="error correction level",
    )
    parser.add_argument("--mask", type=int, choices=range(8), help="shared QR mask")
    parser.add_argument(
        "--split",
        choices=("vertical", "horizontal", "diagonal"),
        default="vertical",
    )
    parser.add_argument(
        "--scale",
        type=int,
        default=10,
        help="even pixels per QR module (default: 10)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(argv) if argv is not None else sys.argv[1:]
    if arguments[:1] == ["duel"]:
        return _duel_main(arguments[1:])

    parser = build_parser()
    args = parser.parse_args(arguments)
    if args.output.suffix.lower() != ".png":
        parser.error("output must use the .png extension")
    if args.heatmap is not None and args.method != "art-up":
        parser.error("--heatmap requires --method art-up")
    if (
        args.heatmap is not None
        and _paths_overlap(args.output, args.heatmap)
    ):
        parser.error("--output and --heatmap must use different paths")
    if args.strength is not None and args.method == "dither":
        parser.error("--strength requires --method art-up or blueprint")
    incompatible = _first_supplied_option(arguments, _IMAGE_GRID_OPTIONS)
    if args.method == "blueprint" and incompatible is not None:
        parser.error(
            f"{incompatible} is not available with --method blueprint"
        )
    if args.method != "blueprint" and _first_supplied_option(
        arguments, {"--module-size"}
    ):
        parser.error("--module-size requires --method blueprint")

    try:
        with Image.open(args.image) as source:
            if args.method == "blueprint":
                result = generate_blueprint_qr(
                    args.payload,
                    source,
                    min_version=args.min_version,
                    error=args.error,
                    mask=args.mask,
                    module_size=args.module_size,
                    robustness=(
                        args.strength if args.strength is not None else 0.6
                    ),
                )
            else:
                generator = (
                    generate_art_up_qr
                    if args.method == "art-up"
                    else generate_dithered_qr
                )
                options = {
                    "min_version": args.min_version,
                    "error": args.error,
                    "mask": args.mask,
                    "subpixels": args.subpixels,
                    "pixel_size": args.pixel_size,
                    "gamma": args.gamma,
                    "contrast": args.contrast,
                    "brightness": args.brightness,
                    "min_brightness": args.min_brightness,
                    "max_brightness": args.max_brightness,
                }
                if args.method == "art-up":
                    options["target_confidence"] = (
                        args.strength if args.strength is not None else 0.65
                    )
                result = generator(args.payload, source, **options)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        result.save(args.output, format="PNG")

        if args.heatmap is not None:
            qr = _encode_payload(
                args.payload,
                args.min_version,
                args.error,
                args.mask,
            )
            confidences = estimate_module_confidence(
                result,
                _module_types(qr),
                subpixels=args.subpixels,
            )
            heatmap = confidence_heatmap(confidences)
            args.heatmap.parent.mkdir(parents=True, exist_ok=True)
            heatmap.save(args.heatmap, format="PNG")
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    print(f"Wrote {args.output} ({result.width}x{result.height})")
    if args.heatmap is not None:
        print(f"Wrote {args.heatmap} ({heatmap.width}x{heatmap.height})")
    return 0


def _duel_main(argv: Sequence[str]) -> int:
    parser = build_duel_parser()
    args = parser.parse_args(argv)
    if args.output.suffix.lower() != ".png":
        parser.error("output must use the .png extension")

    try:
        result = generate_dueling_qr(
            args.payload1,
            args.payload2,
            version=args.version,
            error=args.error,
            mask=args.mask,
            split=args.split,
            scale=args.scale,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        result.save(args.output, format="PNG")
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    print(f"Wrote {args.output} ({result.width}x{result.height})")
    return 0


def _first_supplied_option(
    arguments: Sequence[str], option_names: set[str] | frozenset[str]
) -> str | None:
    for argument in arguments:
        option = argument.partition("=")[0]
        if option in option_names:
            return option
    return None


def _paths_overlap(first: Path, second: Path) -> bool:
    resolved_first = first.resolve()
    resolved_second = second.resolve()
    if resolved_first == resolved_second:
        return True
    if str(resolved_first).casefold() == str(resolved_second).casefold():
        return True
    try:
        return resolved_first.samefile(resolved_second)
    except FileNotFoundError:
        return False
