from pathlib import Path

from PIL import Image

from photo_generation.providers import MockProvider


def test_mock_provider_returns_jpeg(tmp_path: Path):
    source = tmp_path / "source.jpg"
    Image.new("RGB", (100, 100), "red").save(source)
    result = MockProvider().edit("test", source)
    output = tmp_path / "result.jpg"
    output.write_bytes(result)
    assert Image.open(output).format == "JPEG"
