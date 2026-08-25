"""Command-line interface for dithered-qr."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from PIL import Image

from .core import generate_dithered_qr


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dithered-qr",
        description="Blend a monochrome image into a scannable QR code.",
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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.output.suffix.lower() != ".png":
        parser.error("output must use the .png extension")

    try:
        with Image.open(args.image) as source:
            result = generate_dithered_qr(
                args.payload,
                source,
                min_version=args.min_version,
                error=args.error,
                mask=args.mask,
                subpixels=args.subpixels,
                pixel_size=args.pixel_size,
                gamma=args.gamma,
                contrast=args.contrast,
                brightness=args.brightness,
                min_brightness=args.min_brightness,
                max_brightness=args.max_brightness,
            )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        result.save(args.output, format="PNG")
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    print(f"Wrote {args.output} ({result.width}x{result.height})")
    return 0

