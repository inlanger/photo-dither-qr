from pathlib import Path

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
