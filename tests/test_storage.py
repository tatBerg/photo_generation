from pathlib import Path

from photo_generation.config import Settings
from photo_generation.storage import MediaStorage


def test_local_storage_round_trip(tmp_path: Path):
    settings = Settings(media_dir=str(tmp_path / "media"), s3_bucket="")
    storage = MediaStorage(settings)
    source = tmp_path / "source.jpg"
    source.write_bytes(b"image-bytes")

    stored = storage.store(source, "uploads/job/main.jpg")

    assert Path(stored).read_bytes() == b"image-bytes"
    assert storage.materialize(stored, tmp_path / "unused.jpg") == Path(stored)
