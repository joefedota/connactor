from __future__ import annotations

import logging
from pathlib import Path

from google.cloud import storage

from utils.settings import settings

logger = logging.getLogger(__name__)

_client: storage.Client | None = None


def _get_client() -> storage.Client:
    global _client
    if _client is None:
        _client = storage.Client()
    return _client


def get_bucket() -> storage.Bucket:
    return _get_client().bucket(settings.gcs_bucket)


def download_to_file(blob_name: str, local_path: Path) -> bool:
    """Download blob to local_path. Returns False if blob doesn't exist."""
    bucket = get_bucket()
    blob = bucket.blob(blob_name)
    if not blob.exists():
        return False
    size_mb = (blob.size or 0) / 1024 / 1024
    logger.info("Downloading %s (%.1f MB) ...", blob_name, size_mb)
    blob.download_to_filename(str(local_path), timeout=600)
    return True


def upload_from_file(local_path: Path, blob_name: str) -> None:
    size_mb = local_path.stat().st_size / 1024 / 1024
    logger.info("Uploading %s (%.1f MB) ...", blob_name, size_mb)
    blob = get_bucket().blob(blob_name)
    blob.chunk_size = 8 * 1024 * 1024
    with open(local_path, "rb") as f:
        blob.upload_from_file(f, timeout=600)
    logger.info("Upload complete: %s", blob_name)


def blob_exists(blob_name: str) -> bool:
    return get_bucket().blob(blob_name).exists()
