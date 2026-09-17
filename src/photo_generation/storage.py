"""Local and S3-compatible media storage."""

import shutil
from pathlib import Path

from .config import Settings


class MediaStorage:
    """Store durable media in S3/R2, with local storage kept for development."""

    def __init__(self, settings: Settings):
        self.media_dir = Path(settings.media_dir)
        self.media_dir.mkdir(parents=True, exist_ok=True)
        self.bucket = settings.s3_bucket
        self.prefix = settings.s3_prefix.strip("/")
        self.client = None
        if self.bucket:
            if not all((settings.s3_endpoint_url, settings.s3_access_key_id, settings.s3_secret_access_key)):
                raise RuntimeError("S3_BUCKET requires S3 endpoint and access credentials")
            import boto3

            self.client = boto3.client(
                "s3",
                endpoint_url=settings.s3_endpoint_url,
                aws_access_key_id=settings.s3_access_key_id,
                aws_secret_access_key=settings.s3_secret_access_key,
                region_name=settings.s3_region,
            )

    def store(self, source: Path, key: str) -> str:
        if self.client:
            object_key = self._object_key(key)
            self.client.upload_file(str(source), self.bucket, object_key)
            return object_key
        destination = self.media_dir / key
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        return str(destination)

    def materialize(self, stored: str, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if self.client:
            self.client.download_file(self.bucket, stored, str(destination))
            return destination
        return Path(stored)

    def _object_key(self, key: str) -> str:
        return f"{self.prefix}/{key.lstrip('/')}" if self.prefix else key.lstrip("/")
