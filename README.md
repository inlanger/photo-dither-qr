# Photo Dither QR

Turn a photo or illustration into a scannable monochrome QR code.

The image is woven into the QR module grid with two-pass error-diffusion dithering. The result is a crisp binary PNG: recognizably a picture, but still readable as a QR code.

Inspired by [Andrew Taylor's dithered QR code generator](https://www.andrewt.net/dithered-qr-codes/wtf/).

Repository: [github.com/inlanger/photo-dither-qr](https://github.com/inlanger/photo-dither-qr)

## Examples

| Encoded URL | Source image | Generated QR |
| --- | --- | --- |
| [example.com](https://example.com) | [![Mountain and lighthouse illustration](examples/demo-source.png)](examples/demo-source.png) | [![QR code containing the mountain and lighthouse illustration](examples/example-com-qr.png)](https://example.com) |
| [This repository](https://github.com/inlanger/photo-dither-qr) | [![Monochrome portrait](examples/portrait-source.png)](examples/portrait-source.png) | [![QR code containing the portrait](examples/repository-qr.png)](https://github.com/inlanger/photo-dither-qr) |

Both source images are included in `examples/` so you can reproduce the results immediately.

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

## Usage

```bash
dithered-qr photo.jpg "https://example.com" -o qr.png
```

You can also run the package as a Python module:

```bash
python -m dithered_qr photo.jpg "https://example.com" -o qr.png
```

Useful options:

```bash
dithered-qr photo.jpg "https://example.com" -o qr.png \
  --contrast 1.2 \
  --brightness 0.05 \
  --mask 3 \
  --min-version 6
```

Run `dithered-qr --help` for every option.

Reproduce the included examples:

```bash
dithered-qr examples/demo-source.png "https://example.com" \
  -o examples/example-com-qr.png

dithered-qr examples/portrait-source.png \
  "https://github.com/inlanger/photo-dither-qr" \
  -o examples/repository-qr.png
```

## Python API

```python
from PIL import Image
from dithered_qr import generate_dithered_qr

with Image.open("photo.jpg") as source:
    result = generate_dithered_qr("https://example.com", source)

result.save("qr.png")
```

## How it works

1. Each QR module is divided into a 3×3 subpixel grid.
2. The center subpixel keeps the required QR bit.
3. The brightness error introduced by that fixed center is distributed across the eight free subpixels.
4. Floyd–Steinberg dithering turns the free subpixels into black and white image detail.
5. Finder, timing, alignment, and other function modules remain intact.
6. A standard four-module white quiet zone is added around the result.

The binary grid is enlarged only by an integer scale factor with nearest-neighbor sampling, which keeps every edge sharp.

## Verification

```bash
python -m pip install -e '.[test]'
pytest
```

The test suite verifies geometry and protected QR regions, then decodes generated PNG files with the independent ZXing-C++ engine.

Decorative QR codes are less robust than plain QR codes. Before printing or publishing one, test the final PNG with several phones at the intended size, distance, lighting, and print material.
