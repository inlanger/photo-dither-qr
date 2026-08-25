import os
from pathlib import Path

import pytest
import zxingcpp
from PIL import Image

from dithered_qr.cli import main


def test_cli_writes_png(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    output = tmp_path / "result.png"
    Image.new("L", (80, 120), 128).save(source)

    assert main([str(source), "https://example.com", "-o", str(output)]) == 0
    assert output.exists()
    with Image.open(output) as result:
        assert result.format == "PNG"
        assert set(result.get_flattened_data()) == {0, 255}


def test_cli_art_up_writes_decodable_qr_and_heatmap(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    output = tmp_path / "result.png"
    heatmap = tmp_path / "heatmap.png"
    payload = "https://example.com/cli-art-up"
    Image.new("L", (80, 120), 128).save(source)

    assert main(
        [
            str(source),
            payload,
            "-o",
            str(output),
            "--method",
            "art-up",
            "--heatmap",
            str(heatmap),
        ]
    ) == 0
    assert heatmap.exists()
    with Image.open(output) as result:
        decoded = zxingcpp.read_barcode(
            result,
            formats=zxingcpp.BarcodeFormat.QRCode,
            try_invert=False,
            is_pure=False,
        )
    assert decoded is not None
    assert decoded.valid
    assert decoded.text == payload


def test_cli_blueprint_writes_decodable_qr(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    output = tmp_path / "result.png"
    payload = "https://example.com/cli-blueprint"
    Image.new("L", (80, 120), 128).save(source)

    assert main(
        [
            str(source),
            payload,
            "-o",
            str(output),
            "--method",
            "blueprint",
        ]
    ) == 0
    with Image.open(output) as result:
        decoded = zxingcpp.read_barcode(
            result,
            formats=zxingcpp.BarcodeFormat.QRCode,
            try_invert=False,
            is_pure=False,
        )
    assert decoded is not None
    assert decoded.valid
    assert decoded.text == payload


def test_cli_duel_writes_png(tmp_path: Path) -> None:
    output = tmp_path / "duel.png"

    assert main(
        [
            "duel",
            "https://example.com/first",
            "https://example.org/second",
            "-o",
            str(output),
        ]
    ) == 0
    with Image.open(output) as result:
        assert result.format == "PNG"
        assert set(result.get_flattened_data()) == {0, 255}


@pytest.mark.parametrize("heatmap_name", ["same.png", "SAME.png"])
def test_cli_rejects_same_output_and_heatmap_path(
    tmp_path: Path, heatmap_name: str
) -> None:
    source = tmp_path / "source.png"
    output = tmp_path / "same.png"
    heatmap = tmp_path / heatmap_name
    Image.new("L", (80, 120), 128).save(source)

    with pytest.raises(SystemExit):
        main(
            [
                str(source),
                "https://example.com",
                "-o",
                str(output),
                "--method",
                "art-up",
                "--heatmap",
                str(heatmap),
            ]
        )

    assert not output.exists()


def test_cli_rejects_hardlinked_output_paths(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    output = tmp_path / "output.png"
    heatmap = tmp_path / "heatmap.png"
    Image.new("L", (80, 120), 128).save(source)
    output.write_bytes(b"unchanged")
    os.link(output, heatmap)

    with pytest.raises(SystemExit):
        main(
            [
                str(source),
                "https://example.com",
                "-o",
                str(output),
                "--method",
                "art-up",
                "--heatmap",
                str(heatmap),
            ]
        )

    assert output.read_bytes() == b"unchanged"


@pytest.mark.parametrize(
    "option",
    [
        "--subpixels=5",
        "--pixel-size=5",
        "--gamma=1.8",
        "--contrast=1.2",
        "--brightness=0.1",
        "--min-brightness=0.1",
        "--max-brightness=0.9",
    ],
)
def test_cli_rejects_image_grid_options_in_blueprint(
    tmp_path: Path, option: str
) -> None:
    source = tmp_path / "source.png"
    output = tmp_path / "result.png"
    Image.new("L", (80, 120), 128).save(source)

    with pytest.raises(SystemExit):
        main(
            [
                str(source),
                "https://example.com",
                "-o",
                str(output),
                "--method",
                "blueprint",
                option,
            ]
        )


def test_cli_does_not_accept_abbreviated_options(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    output = tmp_path / "result.png"
    Image.new("L", (80, 120), 128).save(source)

    with pytest.raises(SystemExit):
        main(
            [
                str(source),
                "https://example.com",
                "-o",
                str(output),
                "--method",
                "blueprint",
                "--subp",
                "5",
            ]
        )


@pytest.mark.parametrize("method", ["dither", "art-up"])
def test_cli_rejects_module_size_outside_blueprint(
    tmp_path: Path, method: str
) -> None:
    source = tmp_path / "source.png"
    output = tmp_path / "result.png"
    Image.new("L", (80, 120), 128).save(source)

    with pytest.raises(SystemExit):
        main(
            [
                str(source),
                "https://example.com",
                "-o",
                str(output),
                "--method",
                method,
                "--module-size",
                "8",
            ]
        )
